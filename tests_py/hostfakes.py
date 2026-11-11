"""宿主相关测试的公共替身：一律不建真实窗口，只桩掉 Win32 边界。

被 test_host_lifecycle.py / test_status_write.py / test_size_check.py 共用。
"""
from __future__ import annotations

import threading
from pathlib import Path

from cchud_next import host as host_mod
from cchud_next.host import Host

SETTINGS = {"alpha": 0.96, "topmost": True, "peek": True, "range": "1d",
            "layout": "card", "theme": "dark", "hollow": False}


class FakeHandle:
    def __init__(self, value: int = 4242):
        self._value = int(value)

    def ToInt64(self) -> int:
        return self._value


class FakeNative:
    def __init__(self, hwnd: int = 4242):
        self.Handle = FakeHandle(hwnd)


class StubWin:
    """有 HWND 的窗口替身：evaluate_js 只记账，hide/show 只记账。"""

    def __init__(self, hwnd: int = 4242):
        self.native = FakeNative(hwnd)
        self.js: list[str] = []
        self.visible = True

    def evaluate_js(self, script):
        self.js.append(script)
        return 1

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


class FlakyNativeWin:
    """native 先抛错、后可用：模拟宿主还没把 HWND 准备好。"""

    def __init__(self, hwnd: int = 4242):
        self.fail = True
        self.hwnd = hwnd
        self.js: list[str] = []

    @property
    def native(self):
        if self.fail:
            raise RuntimeError("native not ready")
        return FakeNative(self.hwnd)

    def evaluate_js(self, script):
        self.js.append(script)
        return 1


class OpsStub:
    """WindowOps 替身：place 结果可指定，set_topmost 可指定失败次数。"""

    def __init__(self, place_result: dict | None = None, topmost_fail_times: int = 0):
        self.hwnd = 4242
        self.place_calls: list[tuple] = []
        self.place_result = place_result
        self.topmost_fail_times = topmost_fail_times
        self.topmost_calls: list[bool] = []
        self._rect = (100, 50, 524, 380)

    def place(self, w=None, h=None, monitor=0, anchor="top-right", margin=16, keep_size=True):
        self.place_calls.append((w, h, monitor, anchor, margin, keep_size))
        if self.place_result is not None:
            res = dict(self.place_result)
            # 未显式给出 w/h 时按请求值回显，避免用例重复写死尺寸
            res.setdefault("w", w)
            res.setdefault("h", h)
            res.setdefault("x", 0)
            res.setdefault("y", 0)
            return res
        return {"x": 0, "y": 0, "w": w, "h": h, "monitor": "m", "ok": True, "read_ok": True}

    def set_topmost(self, on: bool) -> bool:
        self.topmost_calls.append(bool(on))
        if self.topmost_fail_times > 0:
            self.topmost_fail_times -= 1
            return False
        return True

    def set_alpha(self, alpha: float) -> bool:
        return True

    def set_colorkey(self, colorref: int, alpha: float = 1.0) -> bool:
        return True

    def set_round_region(self, width: int, height: int, radius: int) -> bool:
        return True

    def clear_region(self) -> bool:
        return True

    def rect(self) -> tuple[int, int, int, int]:
        return self._rect

    def move(self, x: int, y: int, w: int, h: int) -> dict:
        self._rect = (int(x), int(y), int(x) + int(w), int(y) + int(h))
        return {}

    def client_origin(self) -> tuple[int, int]:
        return (0, 0)

    def layered_state(self) -> dict:
        return {"layered": False, "alpha": 255, "colorkey": 0, "flags": 0, "read_ok": True}

    def is_topmost(self) -> bool:
        return True


def make_host(tmp_path, ops: OpsStub | None = None, window=None, **attrs) -> Host:
    """Host.__new__ 骨架：只补 _ensure_window_ready 及其步骤真正会碰的属性。

    没有 monkeypatch 也能用——所有 Win32 边界在调用方用 monkeypatch 桩掉。
    """
    h = Host.__new__(Host)
    h.root = Path(tmp_path)
    h.settings = dict(SETTINGS)
    h.status = {"layout": "card"}
    h.window = window if window is not None else StubWin()
    h.ops = ops
    h.tray = None
    h.hidden = False
    h._card_pos = None
    h._alive = True
    h._init_lock = threading.Lock()
    h._initialized = False
    h._init_started = False
    h._retry_threads = {}
    h._retry_delay = 0.0
    h.status_path = Path(tmp_path) / "artifacts" / "runtime.json"
    # GUI 线程边界与秒表都内联/免等，测试不碰真窗口、不等真时间
    h._schedule_on_gui = lambda fn: fn()
    h._pin_native_size = lambda w, h: None
    h._start_rect_guard = lambda target, ticks=40: None
    h._start_tray = lambda: h.status.__setitem__("tray_added", True)
    h._log = lambda msg: None
    for key, value in attrs.items():
        setattr(h, key, value)
    return h


def patch_win32(monkeypatch, ops: OpsStub) -> None:
    """把 host 模块用到的 Win32 边界钉成常量，避免测试依赖真实桌面。"""
    monkeypatch.setattr(host_mod, "WindowOps", lambda hwnd: ops)
    monkeypatch.setattr(host_mod, "dpi_for_window", lambda hwnd: 96)
    monkeypatch.setattr(host_mod, "monitors",
                        lambda: [{"work": (0, 0, 1920, 1080), "device": "M0"}])
    monkeypatch.setattr(host_mod, "work_area", lambda hwnd=0: (0, 0, 1920, 1040))


def join_retries(h, timeout: float = 3.0) -> None:
    for thread in list(getattr(h, "_retry_threads", {}).values()):
        thread.join(timeout)
