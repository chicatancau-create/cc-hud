# -*- coding: utf-8 -*-
"""视觉迭代截图器：隔离 profile 启动真实 HUD，按布局/主题/滚动位置截图。

用法（在 G:\\cc-hud 下）：
  .venv\\Scripts\\python.exe tools\\shoot_ui.py --layout insights --out insights-top
  .venv\\Scripts\\python.exe tools\\shoot_ui.py --layout insights --out insights-scroll --scroll 3,6,9

产物：
  artifacts/visual/<out>.png            PrintWindow 抓取（窗口自身像素，透明区为黑）
  artifacts/visual/<out>-desk.png       桌面区域真实像素（含透明混合、圆角、阴影、背后壁纸）
  artifacts/visual/<out>.json           本次运行的实测矩形/尺寸/hollow_mode 等

隔离手段（都来自宿主已有的环境变量，不改用户状态）：
  CC_HUD_STATE       指向临时 state.json（不碰 hud-next-state.json）
  CC_HUD_PROFILE     独立 WebView2 storage（不碰 .webview）
  CC_HUD_MUTEX       独立单实例互斥体（不与真实实例冲突）
  CC_HUD_ALPHA=1     截图时强制不透明，颜色不受桌面混合干扰
  CC_HUD_FAKE_POWER=1  禁止真实电源动作
"""
from __future__ import annotations

import argparse
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

from cchud_next.win32 import WindowOps, dpi_aware  # noqa: E402

STATUS = ROOT / "artifacts" / "runtime.json"
OUTDIR = ROOT / "artifacts" / "visual"

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]

MOUSEEVENTF_WHEEL = 0x0800


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", MOUSEINPUT)]


def read_status() -> dict:
    try:
        return json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_for(pred, seconds: float, interval: float = 0.15):
    end = time.time() + seconds
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    return None


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def send_wheel(x: int, y: int, notches: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    for _ in range(abs(notches)):
        inp = INPUT(type=0, mi=MOUSEINPUT(0, 0, -120 if notches > 0 else 120, MOUSEEVENTF_WHEEL, 0, 0))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.04)


def grab_desktop(rect: tuple[int, int, int, int], path: Path) -> dict:
    try:
        from PIL import ImageGrab
    except Exception as exc:  # pragma: no cover - 环境缺 pillow 时如实记录
        return {"ok": False, "err": f"PIL 不可用: {exc!r}"}
    l, t, r, b = rect
    try:
        img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "err": repr(exc)}
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return {"ok": True, "path": str(path), "w": img.width, "h": img.height}


def launch(layout: str, theme: str, rng: str, size: str = "") -> tuple[subprocess.Popen, dict, Path]:
    env = dict(os.environ)
    for key in ("CC_HUD_SIZE", "CC_HUD_LAYOUT", "CC_HUD_ALPHA", "CC_HUD_RANGE",
                "CC_HUD_HOLLOW", "CC_HUD_FORCE_DPI", "CC_HUD_SELFTEST"):
        env.pop(key, None)
    env["CC_HUD_FAKE_POWER"] = "1"
    env["CC_HUD_PROFILE"] = tempfile.mkdtemp(prefix="cchud-shot-profile-")
    env["CC_HUD_MUTEX"] = rf"Local\cc-hud-shot-{os.getpid()}-{layout}"
    env["CC_HUD_ALPHA"] = "1"                     # 截图时固定不透明
    state_dir = Path(tempfile.mkdtemp(prefix="cchud-shot-state-"))
    state = state_dir / "state.json"
    state.write_text(json.dumps({"alpha": 1, "topmost": True, "peek": True, "range": rng,
                                 "layout": layout, "theme": theme, "hollow": True},
                                ensure_ascii=False), encoding="utf-8")
    env["CC_HUD_STATE"] = str(state)
    if size:                                      # 验证容器查询/窄窗兜底
        env["CC_HUD_SIZE"] = size
    try:
        STATUS.unlink()
    except OSError:
        pass
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    proc = subprocess.Popen([str(pyw), str(ROOT / "cc-hud.pyw")], cwd=str(ROOT), env=env)
    def ready_status():
        d = read_status()
        return d if d.get("ready") and d.get("hwnd") else None

    data = wait_for(ready_status, 90)
    if not data:
        proc.kill()
        raise RuntimeError("宿主未就绪（90s 内 runtime.json 未出现 ready+hwnd）")
    return proc, data, state


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", required=True, choices=["card", "insights", "diagnostics", "settings"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--range", default="7d", choices=["1d", "7d", "30d", "all"])
    ap.add_argument("--scroll", default="", help="逗号分隔的滚轮档数，如 3,6,9（正=向下）")
    ap.add_argument("--settle", type=float, default=2.2, help="就绪后等待渲染的秒数")
    ap.add_argument("--size", default="", help="覆盖窗口尺寸，如 900x760（默认走生产布局尺寸）")
    args = ap.parse_args()

    dpi_aware()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    proc, data, state = launch(args.layout, args.theme, args.range, args.size)
    hwnd = int(data["hwnd"])
    shots: list[dict] = []
    try:
        user32.SetForegroundWindow(wt.HWND(hwnd))
        time.sleep(args.settle)
        rect = window_rect(hwnd)
        notches_list = [0] + [int(x) for x in args.scroll.split(",") if x.strip()]
        for idx, notches in enumerate(notches_list):
            if notches:
                cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
                send_wheel(cx, cy, notches)
                time.sleep(0.7)
            suffix = "" if idx == 0 else f"-s{notches}"
            name = f"{args.out}{suffix}"
            cap = WindowOps(hwnd).capture(OUTDIR / f"{name}.png")
            desk = grab_desktop(window_rect(hwnd), OUTDIR / f"{name}-desk.png")
            shots.append({"name": name, "scroll": notches, "printwindow": cap, "desktop": desk,
                          "rect": list(window_rect(hwnd))})
        doc = {"layout": args.layout, "theme": args.theme, "range": args.range,
               "status": {k: data.get(k) for k in
                          ("layout", "rect", "dpi", "dpr", "inner_width", "hollow_mode",
                           "colorkey", "layered", "ready", "step_errors", "size_mismatch")},
               "shots": shots, "state_file": str(state),
               "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        (OUTDIR / f"{args.out}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
        print(json.dumps({"ok": all(s["printwindow"].get("ok") for s in shots),
                          "layout": args.layout, "shots": [s["name"] for s in shots],
                          "rect": doc["status"]["rect"], "hollow_mode": doc["status"]["hollow_mode"]},
                         ensure_ascii=False))
        return 0
    finally:
        stop(proc, read_status())


if __name__ == "__main__":
    raise SystemExit(main())
