"""托盘行为验收：向托盘窗口发 WM_TRAY 左键消息，验证隐藏/恢复链路。

图标是否被本机 Shell 显示是另一道门禁；这里验证的是应用侧消息泵与隐藏/恢复行为。
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
OUT = ROOT / "artifacts" / "windows-verify-tray-click.json"
WM_TRAY = 0x801
WM_LBUTTONDOWN = 0x0202


def visible(hwnd: int) -> bool:
    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))


def main() -> int:
    env = dict(os.environ, CC_HUD_LAYOUT="card",
               CC_HUD_PROFILE=tempfile.mkdtemp(prefix="cchud-trayclick-"))
    proc = subprocess.Popen([sys.executable, str(ROOT / "cc-hud.pyw")],
                            cwd=str(ROOT), env=env)
    runtime = ROOT / "artifacts" / "runtime.json"
    try:
        runtime.unlink()
    except OSError:
        pass
    data: dict = {}
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            data = json.loads(runtime.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data.get("ready") and data.get("tray_added") and data.get("pid"):
            break
        time.sleep(0.4)
    time.sleep(1.2)

    hwnd = int(data.get("hwnd") or 0)
    tray = int(data.get("tray_hwnd") or 0)
    api = ctypes.windll.user32
    deadline = time.time() + 12
    while hwnd and not visible(hwnd) and time.time() < deadline:
        time.sleep(0.3)
    checks = {
        "ready": bool(data.get("ready")),
        "tray_added": bool(data.get("tray_added")),
        "tray_hwnd": tray > 0,
        "initial_visible": visible(hwnd) if hwnd else False,
    }

    def click() -> None:
        api.PostMessageW(tray, WM_TRAY, 0, WM_LBUTTONDOWN)

    def wait_for(target: bool, seconds: float = 3.0) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if visible(hwnd) is target:
                return True
            time.sleep(0.2)
        return visible(hwnd) is target

    if tray and hwnd and checks["initial_visible"]:
        click()
        checks["hidden_after_click"] = wait_for(False)
        dot = api.FindWindowW(None, "cc-hud-dot")
        end = time.time() + 2.0
        while time.time() < end and not (dot and visible(dot)):
            time.sleep(0.2)
        checks["dot_visible_when_hidden"] = bool(dot) and visible(dot)
        if checks["dot_visible_when_hidden"]:
            end = time.time() + 3.0
            while time.time() < end:
                try:
                    data = json.loads(runtime.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = {}
                if data.get("dot_api"):
                    break
                time.sleep(0.2)
            checks["dot_api"] = bool(data.get("dot_api"))
            pt = wt.POINT()
            api.GetCursorPos(ctypes.byref(pt))
            saved = (pt.x, pt.y)
            rect = wt.RECT()
            api.GetWindowRect(dot, ctypes.byref(rect))
            cx, cy = (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
            api.SetCursorPos(cx, cy)
            time.sleep(0.4)
            under = api.WindowFromPoint(wt.POINT(cx, cy))
            checks["cursor_on_dot"] = int(under or 0) == int(dot)
            shown = False
            for _ in range(3):
                api.mouse_event(0x0002, 0, 0, 0, 0)
                api.mouse_event(0x0004, 0, 0, 0, 0)
                if wait_for(True, 1.5):
                    shown = True
                    break
            checks["shown_after_dot_click"] = shown
            api.SetCursorPos(saved[0], saved[1])
        click()
        checks["shown_after_second_click"] = wait_for(True)

    if proc.poll() is None:
        api.PostMessageW(hwnd, 0x0010, 0, 0)  # 只关本进程自己的窗口
    for _ in range(15):
        if proc.poll() is not None:
            break
        time.sleep(0.3)
    if data.get("pid"):
        subprocess.run(["taskkill", "/PID", str(data["pid"]), "/F"], capture_output=True)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()

    ok = all(bool(checks.get(k)) for k in (
        "ready", "tray_added", "tray_hwnd", "initial_visible",
        "hidden_after_click", "dot_visible_when_hidden", "shown_after_second_click"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "ok": ok, "checks": checks,
        "informational": ["cursor_on_dot", "shown_after_dot_click"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
