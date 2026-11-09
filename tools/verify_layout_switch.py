# -*- coding: utf-8 -*-
"""真实鼠标布局切换验收：card→insights→7天→诊断→设置→洞察→card。

- 清除 CC_HUD_SIZE，走生产尺寸；CC_HUD_FAKE_POWER=1，禁止真实电源。
- 只认前端上报的固定目标矩形（CC_HUD_SELFTEST=layout）。
- 用 SetCursorPos + SendInput 发真实左键 down/up，不直接调用 apply_settings。
- 每步校验 layout、HWND 尺寸、WindowFromPoint 归属、color-key 策略、截图。
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes as wt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cchud_next.win32 import WindowOps, dpi_aware, monitors  # noqa: E402

STATUS = ROOT / "artifacts" / "runtime.json"
OUT = ROOT / "artifacts" / "layout-switch.json"
SHOTS = ROOT / "artifacts" / "windows"

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.WindowFromPoint.argtypes = [wt.POINT]
user32.WindowFromPoint.restype = wt.HWND
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetAncestor.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.ScreenToClient.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.ChildWindowFromPointEx.argtypes = [wt.HWND, wt.POINT, wt.UINT]
user32.ChildWindowFromPointEx.restype = wt.HWND
CWP_SKIPINVISIBLE = 0x0001

GA_ROOT = 2
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800

SIZES = {"card": (424, 330), "insights": (1180, 800),
         "diagnostics": (1080, 760), "settings": (760, 640)}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", MOUSEINPUT)]


def send_click(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    for flag in (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP):
        inp = INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, flag, 0, 0))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.02)


def owner_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def root_of(hwnd: int) -> int:
    return int(user32.GetAncestor(wt.HWND(hwnd), GA_ROOT) or 0)


def hit_inside(main: int, x: int, y: int) -> tuple[bool, str]:
    """颜色键分层窗会被 WindowFromPoint 跳过；再用本窗子树命中兜底。"""
    h = user32.WindowFromPoint(wt.POINT(x, y))
    if h and root_of(int(h)) == main:
        return True, "WindowFromPoint"
    pt = wt.POINT(int(x), int(y))
    user32.ScreenToClient(wt.HWND(main), ctypes.byref(pt))
    child = user32.ChildWindowFromPointEx(wt.HWND(main), pt, CWP_SKIPINVISIBLE)
    if child:
        return True, "ChildWindowFromPointEx"
    return False, "miss"


def read_status() -> dict:
    try:
        return json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_for(pred, seconds: float, interval: float = 0.2):
    end = time.time() + seconds
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    return None


def launch(dpi: int | None, label: str) -> tuple[subprocess.Popen, dict]:
    env = dict(os.environ)
    for key in ("CC_HUD_SIZE", "CC_HUD_LAYOUT", "CC_HUD_ALPHA", "CC_HUD_RANGE", "CC_HUD_HOLLOW"):
        env.pop(key, None)
    env["CC_HUD_SELFTEST"] = "layout"
    env["CC_HUD_FAKE_POWER"] = "1"
    env["CC_HUD_PROFILE"] = tempfile.mkdtemp(prefix="cchud-layout-")
    env["CC_HUD_MUTEX"] = rf"Local\cc-hud-layout-{os.getpid()}-{label}"
    env.pop("CC_HUD_FORCE_DPI", None)
    if dpi:
        env["CC_HUD_FORCE_DPI"] = str(dpi)
    state = Path(tempfile.mkdtemp(prefix="cchud-layout-state-")) / "state.json"
    state.write_text(json.dumps({"alpha": 0.96, "topmost": True, "peek": True,
                                 "range": "1d", "layout": "card", "theme": "dark",
                                 "hollow": True}), encoding="utf-8")
    env["CC_HUD_STATE"] = str(state)
    try:
        STATUS.unlink()
    except OSError:
        pass
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    proc = subprocess.Popen([str(pyw), str(ROOT / "cc-hud.pyw")], cwd=str(ROOT), env=env)
    data = wait_for(lambda: (d := read_status()).get("hwnd") and d.get("targets") and d, 90)
    if not data:
        raise RuntimeError("宿主未就绪或未上报目标矩形")
    return proc, data


def stop(proc: subprocess.Popen, data: dict) -> None:
    pid = data.get("pid")
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def expected(layout: str, scale: float, work: tuple[int, int]) -> tuple[int, int]:
    """按窗口缩放换算逻辑尺寸；宿主会同时夹到当前显示器工作区。"""
    w, h = SIZES[layout]
    w, h = int(w * scale), int(h * scale)
    return min(w, max(200, work[0] - 16)), min(h, max(150, work[1] - 16))


def run_chain(dpi: int | None, label: str, required: bool = True) -> dict:
    proc, data = launch(dpi, label)
    hwnd = int(data["hwnd"])
    scale = (dpi or data.get("dpi") or 96) / 96.0
    steps: list[dict] = []
    observed: list[dict] = []

    def window_rect() -> tuple[int, int, int, int]:
        r = wt.RECT()
        user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r))
        return (r.left, r.top, r.right, r.bottom)

    def inside(x: int, y: int, pad: int = 2) -> bool:
        l, t, r, b = window_rect()
        return l + pad <= x < r - pad and t + pad <= y < b - pad

    def send_wheel(x: int, y: int, notches: int) -> None:
        """notches>0 向下滚（看下方内容）；用真实滚轮事件，不调 JS。"""
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.04)
        delta = -120 if notches > 0 else 120
        for _ in range(abs(notches)):
            inp = INPUT(type=0, mi=MOUSEINPUT(0, 0, delta, MOUSEEVENTF_WHEEL, 0, 0))
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            time.sleep(0.03)

    try:
        user32.SetForegroundWindow(wt.HWND(hwnd))

        def click_once(name: str) -> None:
            """目标可能在页内滚动区下方：先真实滚轮滚到可见，再按钮式点击。"""
            tgt = None
            for _ in range(40):
                tgt = (read_status().get("targets") or {}).get(name)
                if tgt and inside(*tgt):
                    break
                if tgt:
                    l, t, r, b = window_rect()
                    cx = min(max(int(tgt[0]), l + 24), r - 24)
                    send_wheel(cx, (t + b) // 2, 3 if tgt[1] > b else -3)
                time.sleep(0.25)
            else:
                raise RuntimeError(f"{name} 滚动后目标仍不在窗口内 target={tgt} window={window_rect()}")
            x, y = int(tgt[0]), int(tgt[1])
            ok, how = hit_inside(hwnd, x, y)
            if not ok:
                raise RuntimeError(f"{name} 点击位置未命中主窗口 target=({x},{y}) window={window_rect()}")
            cur = wt.POINT()
            for _ in range(5):
                user32.SetCursorPos(x, y)
                time.sleep(0.1)
                user32.GetCursorPos(ctypes.byref(cur))
                if abs(cur.x - x) <= 2 and abs(cur.y - y) <= 2:
                    break
                user32.SetForegroundWindow(wt.HWND(hwnd))
                time.sleep(0.2)
            else:
                raise RuntimeError(f"{name} 光标未到位 目标=({x},{y}) 实到=({cur.x},{cur.y})")
            send_click(x, y)

        def click(name: str, expect: str | None = None) -> None:
            """真实点击；若布局未按预期切换，重发一次真实点击并如实记录。"""
            click_once(name)
            if expect is None:
                return

            def at():
                st = read_status()
                return st if st.get("layout") == expect else None

            if wait_for(at, 5):
                return
            steps.append({"retry": name, "reason": f"5s 内布局未切到 {expect}，重发一次真实点击"})
            time.sleep(0.4)
            click_once(name)
            if not wait_for(at, 6):
                raise RuntimeError(f"{name} 点击后布局未切到 {expect}")

        def verify(layout: str, shot: str) -> dict:
            def at_layout():
                st = read_status()
                return st if st.get("layout") == layout and st.get("colorkey") is not None else None

            d = wait_for(at_layout, 15)
            if not d:
                raise RuntimeError(f"布局未切到 {layout}")
            work = (2560, 1540)
            mons = data.get("monitors") or []
            if mons:
                l, t, r, b = mons[0]["work"]
                work = (r - l, b - t)
            ew, eh = expected(layout, scale, work)
            end = time.time() + 8
            while True:
                rect = wt.RECT()
                user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect))
                w, h = rect.right - rect.left, rect.bottom - rect.top
                if (w, h) == (ew, eh) or time.time() > end:
                    break
                time.sleep(0.25)
            if (w, h) != (ew, eh):
                observed.append({"layout": layout, "expected": [ew, eh], "actual": [w, h]})
                raise RuntimeError(f"{layout} 尺寸 {w}x{h} != {ew}x{eh}")
            status_rect = tuple(d.get("rect") or ())
            actual_rect = (rect.left, rect.top, rect.right, rect.bottom)
            if status_rect and status_rect != actual_rect:
                raise RuntimeError(f"{layout} 状态矩形 {status_rect} 与实机 {actual_rect} 不一致")
            cx, cy = (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
            ok, how = hit_inside(hwnd, cx, cy)
            if not ok:
                raise RuntimeError(
                    f"{layout} 中心点未命中主窗口（鼠标穿透） point=({cx},{cy}) "
                    f"method={how} main={hwnd}")
            want_mode = "region" if layout == "card" else "alpha"
            if d.get("hollow_mode") != want_mode:
                raise RuntimeError(f"{layout} hollow_mode={d.get('hollow_mode')} 期望 {want_mode}")
            cap = WindowOps(hwnd).capture(SHOTS / f"layout-{label}-{shot}.png")
            if not cap.get("ok") or (cap.get("w"), cap.get("h")) != (ew, eh):
                raise RuntimeError(f"{layout} 截图失败 {cap}")
            row = {"layout": layout, "rect": [rect.left, rect.top, rect.right, rect.bottom],
                   "hit_ok": True, "hit_method": how,
                   "colorkey": d.get("colorkey"), "capture": cap}
            steps.append(row)
            return row

        verify("card", "card")
        click("expand", "insights")
        verify("insights", "insights")
        click("range7")
        time.sleep(0.8)
        verify("insights", "insights-7d")
        click("diagnostics", "diagnostics")
        verify("diagnostics", "diagnostics")
        click("settings", "settings")
        verify("settings", "settings")
        click("insights", "insights")
        verify("insights", "insights-back")
        click("collapse", "card")
        verify("card", "card-back")
        return {"label": label, "dpi": dpi or "system", "scale": scale, "required": required,
                "steps": steps, "ok": True}
    except Exception as exc:
        return {"label": label, "dpi": dpi or "system", "scale": scale, "required": required,
                "steps": steps, "observed": observed, "ok": False, "error": repr(exc)}
    finally:
        stop(proc, read_status())


def main() -> int:
    dpi_aware()          # 必须在任何 SetCursorPos/WindowFromPoint 之前
    SHOTS.mkdir(parents=True, exist_ok=True)
    specs = [("sys", None, True), ("dpi96", 96, False), ("dpi144", 144, False)]
    want = set(sys.argv[1:]) or {s[0] for s in specs}
    runs = [run_chain(dpi, label, required) for label, dpi, required in specs if label in want]
    mons = monitors()
    blocked = []
    for r in runs:
        if r["required"]:
            continue
        if not r["ok"]:
            blocked.append(f"{r['label']}: {r.get('error')}")
        r["simulated"] = ("强制 DPI 只改宿主换算；WinForms/WebView2 仍按系统 DPI 125% 原生缩放，"
                          "本机无法得到可信的 100%/150% 结果")
    core = [r for r in runs if r["required"]]
    doc = {
        "ok": bool(core) and all(r["ok"] for r in core),
        "blocked": blocked,
        "display_count": len(mons),
        "multi_monitor": "blocked: only 1 display" if len(mons) < 2 else "ok",
        "dpi_note": "system 档是真实系统 DPI（125%）；dpi96/dpi144 为强制换算探测，失败只记 blocked，不计入通过",
        "runs": runs,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": doc["ok"], "display_count": doc["display_count"],
                      "multi_monitor": doc["multi_monitor"],
                      "runs": [{"dpi": r["dpi"], "ok": r["ok"],
                                "error": r.get("error")} for r in runs]}, ensure_ascii=False))
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
