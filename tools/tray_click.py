"""托盘行为验收：左键切换一次、右键只弹菜单、隐藏后靠托盘找回、且没有桌面小圆点。

图标是否被本机 Shell 显示是另一道门禁（tray_pixel）；这里验证应用侧消息泵与显隐语义。
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "windows-verify-tray-click.json"
WM_TRAY = 0x801
WM_LBUTTONDOWN = 0x0202
WM_RBUTTONUP = 0x0204


def visible(hwnd: int) -> bool:
    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))


def runtime_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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
        data = runtime_json(runtime)
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
        # 第二窗口已删除：进程里不允许再出现 cc-hud-dot
        "no_dot_window": not any(
            (lambda h: (api.GetWindowTextW(h, buf := ctypes.create_unicode_buffer(64), 64),
                        buf.value == "cc-hud-dot")[1])(h)
            for h in _enum_windows(api)),
        "dot_created_false": data.get("dot_created") is False,
    }

    def click(msg: int = WM_LBUTTONDOWN) -> None:
        api.PostMessageW(tray, WM_TRAY, 0, msg)

    def wait_for(target: bool, seconds: float = 3.0) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if visible(hwnd) is target:
                return True
            time.sleep(0.2)
        return visible(hwnd) is target

    if tray and hwnd and checks["initial_visible"]:
        # 1) 左键：显示 -> 隐藏。同一物理单击常伴随多条 Shell 消息，必须只切一次。
        click()
        checks["hidden_after_click"] = wait_for(False)
        # 连发一次重复消息：仍要保持隐藏（去抖生效），不能来回翻转
        api.PostMessageW(tray, WM_TRAY, 0, WM_LBUTTONDOWN)
        time.sleep(0.8)
        checks["stays_hidden_on_duplicate_message"] = not visible(hwnd)

        # 2) 右键：只弹菜单，不改显隐。菜单是模态循环，按 ESC 收起后再断言。
        click(WM_RBUTTONUP)
        time.sleep(1.2)
        opened = runtime_json(runtime)
        checks["right_click_opened_menu"] = int(opened.get("tray_menu_shown") or 0) >= 1
        _send_escape()
        time.sleep(0.8)
        checks["right_click_keeps_hidden"] = not visible(hwnd)
        checks["menu_closed_after_escape"] = runtime_json(runtime).get("tray_menu_phase") in (
            "closed", "opening")

        # 3) 再左键：隐藏 -> 显示（托盘是唯一找回入口）
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
        "no_dot_window", "dot_created_false",
        "hidden_after_click", "stays_hidden_on_duplicate_message",
        "right_click_keeps_hidden", "shown_after_second_click"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"ok": ok, "checks": checks,
                               "informational": ["right_click_opened_menu"],
                               "runtime": data},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False))
    return 0 if ok else 1


def _send_escape() -> None:
    """右键菜单是模态循环：用真实 ESC 键收起，模拟用户点外面。"""
    u = ctypes.windll.user32
    u.keybd_event(0x1B, 0, 0, 0)
    time.sleep(0.05)
    u.keybd_event(0x1B, 0, 2, 0)


def _enum_windows(api) -> list[int]:
    out: list[int] = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _lp):
        out.append(int(hwnd))
        return 1

    api.EnumWindows(PROC(cb), 0)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
