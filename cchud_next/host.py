"""pywebview 宿主：file:// + http_server=False；整窗效果走 Win32。"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import traceback
from pathlib import Path

import webview

from . import __version__
from .bridge import Bridge
from .settings import LAYOUT_SIZES, SettingsStore, use_colorkey
from .win32 import WindowOps, dpi_aware, dpi_for_window, monitors, system_scale, work_area

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist" / "index.html"
PEEK = ROOT / "web" / "peek.html"
STATUS_PATH = ROOT / "artifacts" / "runtime.json"

# #0b0e14 -> COLORREF 0x00BBGGRR
BG_COLORREF = 0x00140E0B  # COLORREF(0x00BBGGRR) <- #0b0e14


def safe_capture_path(root: Path, value: object) -> Path:
    """截图只能落在 <root>/artifacts 下，页面传绝对路径也不能越界。"""
    base = (Path(root) / "artifacts").resolve()
    try:
        if value:
            raw = Path(str(value))
            target = (raw if raw.is_absolute() else base / raw).resolve()
        else:
            target = base / "capture.png"
    except (OSError, ValueError):
        target = base / "capture.png"
    return target if target.is_relative_to(base) else base / "capture.png"


class _FakePower:
    """实机取证用：记录调用，绝不执行真实电源动作。"""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    def run(self, action: str, delay: int = 15) -> dict:
        self.calls.append((action, delay))
        return {"ok": True, "fake": True, "action": action, "scheduled": delay > 0}

    def cancel(self) -> dict:
        return {"ok": True, "fake": True, "action": "cancel"}


class Host:
    def __init__(self, root: Path | None = None, settings: SettingsStore | None = None):
        self.root = Path(root) if root else ROOT
        state_override = os.environ.get("CC_HUD_STATE")
        self.store = settings or SettingsStore(
            Path(state_override) if state_override else self.root / "hud-next-state.json")
        self.settings = self.store.load()
        if os.environ.get("CC_HUD_LAYOUT"):  # 实机取证用：不写盘覆盖用户设置
            self.settings = dict(self.settings, layout=os.environ["CC_HUD_LAYOUT"])
        if os.environ.get("CC_HUD_ALPHA"):
            try:
                self.settings = dict(self.settings, alpha=float(os.environ["CC_HUD_ALPHA"]))
            except ValueError:
                pass
        if os.environ.get("CC_HUD_RANGE"):
            self.settings = dict(self.settings, range=os.environ["CC_HUD_RANGE"])
        if os.environ.get("CC_HUD_HOLLOW"):
            self.settings = dict(self.settings, hollow=True)
        self.window = None
        self.dot = None
        self.ops: WindowOps | None = None
        self.tray = None
        self.events: queue.Queue[str] = queue.Queue()
        self.hidden = False
        self._alive = True
        self._card_pos: tuple[int, int, int, int] | None = None
        self.fake_power = _FakePower() if os.environ.get("CC_HUD_FAKE_POWER") else None
        self.bridge = Bridge(root=self.root, settings=self.store, window=self,
                             settings_provider=lambda: self.settings, power=self.fake_power)
        self.status: dict = {"version": __version__, "started_at": time.time(),
                             "layout": self.settings.get("layout"),
                             "alpha_setting": self.settings.get("alpha")}
        self._init_lock = threading.Lock()
        self._initialized = False
        self._init_started = False

    # ---- WindowPort（供 bridge 调用） ----
    def _run_on_gui(self, fn, *args, timeout: float = 10.0):
        """WinForms 窗口属性必须在 GUI 线程改；跨线程 SetWindowPos 会被框架事后改写尺寸。"""
        native = getattr(self.window, "native", None)
        if native is None:
            return fn(*args)
        try:
            needs_marshal = bool(native.InvokeRequired)
        except Exception:
            needs_marshal = False
        if not needs_marshal:
            return fn(*args)
        from System import Action

        done = threading.Event()
        box: dict = {}

        def runner() -> None:
            try:
                box["value"] = fn(*args)
            except BaseException as exc:
                box["error"] = exc
            finally:
                done.set()

        native.BeginInvoke(Action(runner))
        if not done.wait(timeout):
            raise RuntimeError("等待 GUI 线程应用窗口设置超时")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def apply_settings(self, settings: dict) -> None:
        """先应用原生效果，成功才提交内存/状态；失败回滚并向上抛。"""
        if not self.ops:
            self.settings = dict(settings)
            return
        self._run_on_gui(self._apply_settings_sync, dict(settings))
        self._refresh_targets()          # 需要 WebView2 求值，只能留在调用线程
        self._write_status()

    def _apply_settings_sync(self, settings: dict) -> None:
        old = dict(self.settings)
        cand = dict(settings)
        changed = old.get("layout") != cand.get("layout")
        if changed and old.get("layout") == "card":
            try:
                self._card_pos = self.ops.rect()
            except Exception:
                self._card_pos = None
        try:
            if changed:
                self._apply_layout_size(cand)
            self._apply_effects(cand)
            if changed and cand.get("layout") == "card" and self._card_pos:
                x, y, _r, _b = self._card_pos
                w, h = self._layout_px(cand)
                self.ops.move(x, y, w, h)
        except Exception as exc:
            self.status["apply_trace"] = traceback.format_exc()[-1500:]
            try:
                self._apply_effects(old)
            except Exception:
                pass
            try:
                if changed:
                    self._apply_layout_size(old)
                    if old.get("layout") == "card" and self._card_pos:
                        x, y, _r, _b = self._card_pos
                        w, h = self._layout_px(old)
                        self.ops.move(x, y, w, h)
            except Exception:
                pass
            raise RuntimeError(f"窗口应用失败：{exc}") from exc
        self.settings = cand
        self.status["layout"] = cand.get("layout")
        try:
            self.status["rect"] = list(self.ops.rect())
        except Exception:
            pass
        self.status["colorkey"] = False   # 不再使用颜色键（见 hollow_mode）

    def _apply_effects(self, settings: dict) -> None:
        if not self.ops:
            return
        alpha = float(settings.get("alpha", 0.96))
        if not self.ops.set_topmost(bool(settings.get("topmost", True))):
            raise RuntimeError("置顶设置失败")
        if use_colorkey(settings):
            # 颜色键对 WebView2 子窗会整窗穿透（按钮也点不到）；改用圆角区域镂空 + alpha。
            # 区域必须跟真实窗口一致，CC_HUD_SIZE 覆盖尺寸时也不能按布局名义值裁。
            l, t, r, b = self.ops.rect()
            w, h = max(1, r - l), max(1, b - t)
            radius = max(6, int(14 * (w / 424)))
            if not self.ops.set_round_region(w, h, radius):
                raise RuntimeError("圆角区域镂空失败")
            if not self.ops.set_alpha(alpha):
                raise RuntimeError("整窗透明度设置失败")
            self.status["hollow_mode"] = "region"
        else:
            self.ops.clear_region()
            self.status["hollow_mode"] = "alpha"
            if not self.ops.set_alpha(alpha):
                raise RuntimeError("整窗透明度设置失败")

    def _layout_px(self, settings: dict) -> tuple[int, int]:
        logical = LAYOUT_SIZES.get(settings.get("layout"), LAYOUT_SIZES["card"])
        force = os.environ.get("CC_HUD_FORCE_DPI")
        try:
            dpi = float(force) if force else float(dpi_for_window(self.ops.hwnd) or 0)
        except Exception:
            dpi = 0.0
        scale = dpi / 96.0 if dpi > 0 else system_scale()
        w, h = int(logical[0] * scale), int(logical[1] * scale)
        mons = monitors()
        if mons:
            l, t, r, b = mons[0]["work"]
            w = min(w, max(200, r - l - 16))
            h = min(h, max(150, b - t - 16))
        return w, h

    def _pin_native_size(self, w: int, h: int) -> None:
        """把 WinForms 的 Min/Max 钉到当前布局尺寸。

        pywebview 建窗后框架会在 WebView2 首次渲染完成时再走一遍布局，
        把窗口改成另一个尺寸；Min=Max 后这次改写会被夹回目标值。"""
        native = getattr(self.window, "native", None)
        if native is None:
            return
        from System.Drawing import Size
        from System.Windows.Forms import FormStartPosition
        native.StartPosition = FormStartPosition.Manual   # 否则框架重排时会按 CenterScreen 再居中
        native.MinimumSize = Size(1, 1)
        native.MaximumSize = Size(int(w), int(h))
        native.MinimumSize = Size(int(w), int(h))

    def _apply_layout_size(self, settings: dict) -> None:
        if not self.ops:
            return
        if os.environ.get("CC_HUD_SIZE"):
            return
        w, h = self._layout_px(settings)
        self._run_on_gui(self._pin_native_size, w, h)
        anchor = "top-right" if settings.get("layout") == "card" else "center"
        res = self.ops.place(w, h, 0, anchor, 0 if anchor == "center" else 16, keep_size=False)
        if res.get("w") != w or res.get("h") != h:
            raise RuntimeError(f"窗口尺寸未生效：期望 {w}x{h}，实际 {res.get('w')}x{res.get('h')}")
        self._run_on_gui(self._start_rect_guard,
                         (int(res["x"]), int(res["y"]), int(w), int(h)))

    def _start_rect_guard(self, target: tuple[int, int, int, int], ticks: int = 40) -> None:
        """布局切换后短暂守住目标矩形。

        WinForms/WebView2 在首次渲染完成后会再走一遍重排，偶发把窗口改成另一个尺寸
        并按旧尺寸重新居中；这里在 GUI 线程上把漂移立刻纠回。"""
        if self.ops is None or getattr(self.window, "native", None) is None:
            return
        try:
            prev = getattr(self, "_rect_guard", None)
            if prev is not None:
                prev.Stop()
                prev.Dispose()
        except Exception:
            pass
        try:
            from System.Windows.Forms import Timer
        except Exception:
            return

        tx, ty, tw, th = target
        state = {"left": ticks}

        def tick(sender, args):
            try:
                cur = self.ops.rect()
                if cur != (tx, ty, tx + tw, ty + th):
                    self.ops.move(tx, ty, tw, th)
                    self.status["rect_guard_fixes"] = int(self.status.get("rect_guard_fixes", 0)) + 1
                state["left"] -= 1
                if state["left"] <= 0:
                    sender.Stop()
                    sender.Dispose()
            except Exception:
                try:
                    sender.Stop()
                except Exception:
                    pass

        timer = Timer()
        timer.Interval = 40
        timer.Tick += tick
        self._rect_guard = timer
        timer.Start()
        # 不做 CSS zoom：整页按设备像素比自然铺满，避免缩小后留下可穿透的透明带


    TARGET_SELECTORS = {
        "expand": '[data-testid="expand-insights"]',
        "range7": '[data-testid="range-7d"]',
        "collapse": '[data-testid="collapse-card"]',
        "diagnostics": '[data-testid="nav-diagnostics"]',
        "settings": '[data-testid="nav-settings"]',
        "insights": '[data-testid="nav-insights"]',
        "card": '[data-testid="nav-card"]',
    }

    def _refresh_targets(self) -> None:
        if os.environ.get("CC_HUD_SELFTEST") != "layout" or not self.window or not self.ops:
            return
        out = {}
        try:
            ox, oy = self.ops.client_origin()
        except Exception as exc:
            self.status["targets_error"] = repr(exc)
            return
        for name, sel in self.TARGET_SELECTORS.items():
            js = ("(function(){var e=document.querySelector(%r);if(!e)return null;"
                  "var r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2];})()" % sel)
            try:
                v = self.window.evaluate_js(js)
            except Exception as exc:
                self.status["targets_error"] = repr(exc)
                v = None
            if v:
                out[name] = [int(ox + v[0]), int(oy + v[1])]
        if out:
            self.status["targets"] = out

    def command(self, action: str, value=None) -> dict:
        if action == "show":
            self.show()
            return {"ok": True}
        if action == "hide":
            self.hide()
            return {"ok": True}
        if action == "toggle":
            self.hide() if not self.hidden else self.show()
            return {"ok": True, "hidden": self.hidden}
        if action == "alpha":
            ok = bool(self.ops and self.ops.set_alpha(float(value)))
            return {"ok": ok, "value": value}
        if action == "topmost":
            ok = bool(self.ops and self.ops.set_topmost(bool(value)))
            return {"ok": ok, "value": value}
        if action == "hollow":
            if not self.ops:
                return {"ok": False, "reason": "无窗口"}
            cand = dict(self.settings, hollow=bool(value))
            self._run_on_gui(self._apply_effects, cand)
            self.settings = cand
            self.status["colorkey"] = False
            self._write_status()
            return {"ok": True, "value": bool(value), "colorkey": use_colorkey(cand)}
        if action == "place":
            if not self.ops:
                return {"ok": False, "reason": "无窗口"}
            return {"ok": True, **self.ops.place(None, None, int(value or 0))}
        if action == "capture":
            if not self.ops:
                return {"ok": False, "reason": "无窗口"}
            return self.ops.capture(safe_capture_path(self.root, value))
        if action == "dpi":
            return {"ok": True, "dpi": dpi_for_window(self.ops.hwnd if self.ops else 0)}
        if action == "selftest_result":
            self.status["selftest_result"] = value
            self._log(f"selftest_result {value}")
            self._write_status()
            return {"ok": True}
        if action == "layout_targets":
            if os.environ.get("CC_HUD_SELFTEST") != "layout":
                return {"ok": False, "reason": "selftest 未开"}
            try:
                payload = json.loads(value) if isinstance(value, str) else dict(value or {})
                ox, oy = self.ops.client_origin() if self.ops else (0, 0)
                dpr = float(self.status.get("dpr") or 1.0)   # CSS px -> 物理像素
                self.status["targets"] = {
                    k: [int(ox + v[0] * dpr), int(oy + v[1] * dpr)]
                    for k, v in payload.items() if isinstance(v, (list, tuple)) and len(v) == 2
                }
                self._write_status()
                return {"ok": True, "count": len(self.status["targets"])}
            except Exception as exc:
                return {"ok": False, "reason": repr(exc)}
        if action == "frontend_ready":
            self._log(f"frontend_ready {value}")
            return {"ok": True}
        if action == "status":
            return {"ok": True, "status": self.status}
        return {"ok": False, "reason": f"未知窗口动作: {action}"}

    def _selftest_hide(self) -> None:
        self._log("selftest hide fire")
        self.hide()

    def show(self) -> None:
        try:
            if self.dot:
                self.dot.hide()
            if self.window:
                self.window.show()
            self.hidden = False
            if self.tray:
                self.tray.set(True, "cc-hud · 显示中")
            self.status["hidden"] = False
            self.status["peek_visible"] = False
            self._write_status()
        except Exception as exc:
            self.status["last_error"] = f"show: {exc!r}"

    def hide(self) -> None:
        self._log("hide() called")
        try:
            if self.window:
                self.window.hide()
            if self.dot:
                self.dot.show()
            self.hidden = True
            if self.tray:
                self.tray.set(False, "cc-hud · 已隐藏")
            self.status["hidden"] = True
            self.status["peek_visible"] = True
            self._write_status()
        except Exception as exc:
            self.status["last_error"] = f"hide: {exc!r}"

    # ---- 生命周期 ----
    def _on_loaded(self) -> None:
        self._log("loaded event fired")
        self._ensure_window_ready()

    def _schedule_on_gui(self, fn) -> None:
        """托盘窗口必须由 GUI 线程创建并派发消息；其余线程建的窗收不到点击。"""
        try:
            from System import Action
            self.window.native.BeginInvoke(Action(fn))
        except Exception as exc:
            self.status["gui_invoke_error"] = repr(exc)
            self.status["tray_skipped"] = "gui invoke failed"   # 宁可不建，也不建一个收不到点击的托盘

    def _ensure_window_ready(self) -> None:
        with self._init_lock:
            if self._initialized:
                return
            if self._init_started:
                return
            self._init_started = True
        try:
            native = self.window.native
            self._log(f"native={type(native)!r} attrs={[a for a in dir(native) if 'andle' in a or 'Handle' in a][:6]}")
            hwnd = int(native.Handle.ToInt64())
            self.ops = WindowOps(hwnd)
            self.status.update({
                "hwnd": hwnd,
                "pid": os.getpid(),
                "dpi": dpi_for_window(hwnd),
                "monitors": monitors(),
                "work_area": list(work_area(hwnd)),
            })
            # pywebview 按物理像素建窗、WebView2 又按系统缩放渲染 -> 右侧被裁。
            # 用 CSS zoom 反比补偿，使布局视口与窗口一致。
            try:
                self.status["dpr"] = self.window.evaluate_js("window.devicePixelRatio")
                self.status["inner_width"] = self.window.evaluate_js("window.innerWidth")
                self.window.evaluate_js(
                    "document.documentElement.style.zoom = String(1 / (window.devicePixelRatio || 1))")
            except Exception as exc:
                self.status["zoom_error"] = repr(exc)
            self._apply_layout_size(self.settings)
            self.apply_settings(self.settings)


            def _late_reapply():
                time.sleep(1.0)
                if not self._alive or not self.ops:
                    return
                self._schedule_on_gui(lambda: self._apply_layout_size(self.settings))

            threading.Thread(target=_late_reapply, daemon=True).start()
            self.status["layered"] = self.ops.layered_state()
            self.status["topmost"] = self.ops.is_topmost()
            self._schedule_on_gui(self._start_tray)
            self._place_dot()
            self.status["ready"] = True
            self._initialized = True
            self._write_status()
            if os.environ.get("CC_HUD_START_HIDDEN"):
                self._log("selftest hide armed (JS-triggered)")
        except Exception as exc:
            self._initialized = False   # 让 HWND 轮询线程还能重试
            self._init_started = False
            self.status["last_error"] = f"on_loaded: {exc!r}"
            self._log(f"on_loaded error: {exc!r}")
            self._write_status()

    def _place_dot(self) -> None:
        try:
            hwnd = int(self.dot.native.Handle.ToInt64())
            self.status["dot_hwnd"] = hwnd
            ops = WindowOps(hwnd)
            # WinForms/WebView2 最小窗约 200x100；用颜色键把除圆点外的同色背景镂空
            ops.set_colorkey(BG_COLORREF, 1.0)
            self.status["dot_placed"] = ops.place(None, None, 0, "bottom-right", 12)["x"] >= 0
        except Exception as exc:
            self.status["dot_placed"] = False
            self.status["dot_error"] = repr(exc)

    def _start_tray(self) -> None:
        if self.tray is not None:
            return
        host = self
        try:
            import ctypes as _ct
            from . import tray as _sysw

            class _SyncTray(_sysw.Tray):
                """托盘事件在 WndProc（GUI 线程）里同步处理。

                实测：pywebview/WinForms 循环起来约 1~2 秒后，Python 后台线程会被饿死，
                用 queue+轮询线程的旧做法会静默失效。"""

                def _wnd(self, h, msg, wp, lp):
                    try:
                        if msg == _sysw.WM_TRAY:
                            ev = _sysw.TRAY_EVT.get(lp & 0xFFFF)
                            if ev:
                                host._on_tray(ev)
                            return 1
                    except Exception as exc:
                        host.status["tray_error"] = repr(exc)
                        return 0
                    return _ct.windll.user32.DefWindowProcW(h, msg, wp, lp)

            self.tray = _SyncTray(self.events)
            self.tray.set(True, "cc-hud · 显示中")
            self.status["tray_added"] = bool(self.tray.added)
            self.status["tray_hwnd"] = int(self.tray.hwnd) if self.tray.hwnd else None
            self.status["tray_uid"] = int(self.tray.nid.uID)
            self.status["tray_getrect_rc"] = getattr(self.tray, "getrect_rc", None)
            self.status["tray_rect"] = getattr(self.tray, "getrect", None)
        except Exception as exc:
            self.status["tray_added"] = False
            self.status["tray_error"] = repr(exc)

    def _on_tray(self, ev: str) -> None:
        if ev in ("toggle", "menu"):
            self.hide() if not self.hidden else self.show()

    def _tray_loop(self) -> None:
        while self._alive:
            try:
                ev = self.events.get(timeout=0.25)
            except queue.Empty:
                continue
            if ev in ("toggle", "menu"):
                self.hide() if not self.hidden else self.show()

    def _log(self, msg: str) -> None:
        try:
            p = self.root / "artifacts" / "host.log"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%H:%M:%S ") + msg + "\n")
        except OSError:
            pass

    def _write_status(self) -> None:
        try:
            STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATUS_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.status, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, STATUS_PATH)
        except OSError:
            pass

    def run(self) -> None:
        if os.environ.get("CC_HUD_LOG"):
            logging.basicConfig(filename=str(self.root / "artifacts" / "pywebview.log"),
                                level=logging.DEBUG,
                                format="%(asctime)s %(levelname)s %(name)s %(message)s")
        self._log("run() start")
        if not DIST.exists():
            raise SystemExit(f"缺少前端构建产物: {DIST}（先运行 cd web && npm run build）")
        dpi_aware()
        url = DIST.as_uri()
        if os.environ.get("CC_HUD_START_HIDDEN"):
            url += "#selftest=hide"
        if os.environ.get("CC_HUD_SELFTEST"):
            url += ("&" if "#" in url else "#") + "selftest=" + os.environ["CC_HUD_SELFTEST"]
        if os.environ.get("CC_HUD_SCROLL"):
            url += ("&" if "#" in url else "#") + "scroll=" + os.environ["CC_HUD_SCROLL"]
        scale = system_scale()
        w0, h0 = int(424 * scale), int(330 * scale)
        env_size = os.environ.get("CC_HUD_SIZE", "")
        if "x" in env_size:
            try:
                w0, h0 = (int(v) for v in env_size.lower().split("x", 1))
            except ValueError:
                pass
        self.window = webview.create_window(
            "cc-hud", url, width=w0, height=h0,
            frameless=True, easy_drag=False, resizable=True, min_size=(360, 300),
            on_top=bool(self.settings.get("topmost", True)),
            background_color="#0b0e14", js_api=self.bridge,
            text_select=True, confirm_close=False,
        )
        self.dot = webview.create_window(
            "cc-hud-dot", PEEK.as_uri(), width=int(34 * scale), height=int(34 * scale),
            frameless=True, easy_drag=False, resizable=False, hidden=True, min_size=(34, 34),
            on_top=True, background_color="#0b0e14", js_api=self.bridge,
        )
        def _dot_loaded() -> None:
            try:
                self.status["dot_api"] = bool(self.dot.evaluate_js(
                    "!!(window.pywebview && window.pywebview.api)"))
            except Exception as exc:
                self.status["dot_api_error"] = repr(exc)
        try:
            self.dot.events.loaded += _dot_loaded
        except Exception as exc:
            self.status["dot_hook_error"] = repr(exc)
        try:
            from webview.platforms import edgechromium as _ec
            _orig = _ec.inject_pywebview
            def _wrap(platform, window):
                self._log(f"inject begin {platform} {getattr(window,'title','?')}")
                try:
                    r = _orig(platform, window)
                    self._log("inject ok")
                    return r
                except Exception as exc:
                    self._log(f"inject error {exc!r}")
                    raise
            _ec.inject_pywebview = _wrap
        except Exception as exc:
            self._log(f"inject wrap failed {exc!r}")
        self.window.events.loaded += self._on_loaded
        self.window.events.closed += self._on_closed
        self._log("handlers attached")
        webview.start(self._after_start, http_server=False, private_mode=False,
                      storage_path=os.environ.get("CC_HUD_PROFILE") or str(self.root / ".webview"))

    def _after_start(self) -> None:
        self._log("after_start")
        # loaded 事件在不同 pywebview/WebView2 组合下可能漏发；HWND 轮询是幂等兜底。
        threading.Thread(target=self._wait_hwnd, daemon=True).start()
        if os.environ.get("CC_HUD_HEARTBEAT"):
            def beat():
                for i in range(6):
                    self._log(f"heartbeat {i}")
                    time.sleep(1.0)
            threading.Thread(target=beat, daemon=True).start()
        self.status["started"] = True
        self.status["dist"] = DIST.as_uri()
        self.status["dot_created"] = self.dot is not None
        self.status["main_created"] = self.window is not None
        self._write_status()
        threading.Thread(target=self._watch_ccswitch, daemon=True).start()

    def _watch_ccswitch(self) -> None:
        """CC Switch 退出 -> HUD 跟随退出（启动时没见到 CC Switch 则不自杀）。"""
        from .tray import ccswitch_pid

        seen = False
        misses = 0
        while self._alive:
            time.sleep(5.0)
            if not self._alive:
                return
            if ccswitch_pid():
                seen = True
                misses = 0
                continue
            if not seen:
                continue
            misses += 1
            if misses >= 2:          # 10 秒宽限，避免 CC Switch 重启瞬间误杀
                self._log("ccswitch gone -> quit")
                self.status["quit_reason"] = "ccswitch_gone"
                self._write_status()
                self._schedule_on_gui(self._quit_quiet)
                return

    def _quit_quiet(self) -> None:
        try:
            if self.window:
                self.window.destroy()
        except Exception as exc:
            self.status["last_error"] = f"quit: {exc!r}"

    def _wait_hwnd(self) -> None:
        for _ in range(150):
            if not self._alive:
                return
            try:
                native = self.window.native if self.window else None
                if native is not None and hasattr(native, "Handle"):
                    hwnd = int(native.Handle.ToInt64())
                    if hwnd:
                        self._log(f"hwnd ready {hwnd}")
                        self._ensure_window_ready()
                        return
            except Exception:
                pass
            time.sleep(0.1)
        self._log("hwnd wait timeout")
        self.status["last_error"] = "hwnd wait timeout"
        self._write_status()

    def _on_closed(self) -> None:
        self._alive = False
        try:
            if self.tray:
                self.tray.quit()
        except Exception:
            pass
        for w in (self.dot, self.window):
            try:
                if w:
                    w.destroy()
            except Exception:
                pass


def main() -> None:
    from .tray import already_running

    if already_running():
        return
    Host().run()


if __name__ == "__main__":
    main()
