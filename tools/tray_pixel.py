"""托盘像素取证：启动应用 -> 截屏通知区域 -> 统计 cc-hud 绿色图标像素 -> 关窗。

图标用 (52,211,153) 画环；Windows 隐藏区会整体调暗，因此按色相+饱和度判定而不是 RGB 距离。
Shell 的图标布局有延迟，采样最多重试 12 次（每次 1.5s），任一帧达标即通过。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

from verify_windows import user32, wt  # noqa: E402
from cchud_next.win32 import dpi_aware  # noqa: E402

OUT = ROOT / "artifacts" / "windows" / "tray-crop.png"


def green_pixels(img) -> int:
    """隐藏区图标会被系统整体调暗，按色相+饱和度统计绿色像素。"""
    import colorsys

    n = 0
    for (r, g, b) in img.convert("RGB").getdata():
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if 0.30 < h < 0.55 and s > 0.35 and v > 0.12:
            n += 1
    return n


def main() -> int:
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.OpenMutexW.restype = ctypes.c_void_p

    def hud_running() -> bool:
        h = k32.OpenMutexW(0x00100000, False, r"Local\cc-hud-single")
        if h:
            k32.CloseHandle(ctypes.c_void_p(h))
            return True
        return False

    # 上一轮取证实例可能还在退出；等互斥体释放再起，避免新实例静默自杀
    wait_until = time.time() + 20
    while hud_running() and time.time() < wait_until:
        time.sleep(0.5)
    if hud_running():
        ev = {"ok": False, "reason": "hud_running", "crop": str(OUT)}
        print(json.dumps(ev, ensure_ascii=False))
        return 2

    env = dict(os.environ, CC_HUD_LAYOUT="card",
               CC_HUD_PROFILE=tempfile.mkdtemp(prefix="cchud-tray-"))
    runtime = ROOT / "artifacts" / "runtime.json"
    try:
        runtime.unlink()
    except OSError:
        pass
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    proc = subprocess.Popen([str(pyw if pyw.exists() else sys.executable), str(ROOT / "cc-hud.pyw")],
                            cwd=str(ROOT), env=env)
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            data = json.loads(runtime.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data.get("ready"):
            break
        time.sleep(0.4)
    time.sleep(2.0)

    from PIL import ImageGrab
    import colorsys
    import ctypes
    from ctypes import wintypes as wt2

    class NII(ctypes.Structure):
        _fields_ = [("cbSize", wt2.DWORD), ("hWnd", wt2.HWND), ("uID", wt2.UINT),
                    ("guidItem", ctypes.c_byte * 16)]

    dpi_aware()
    sw = ctypes.windll.user32.GetSystemMetrics(0)
    sh = ctypes.windll.user32.GetSystemMetrics(1)

    def sample() -> tuple[dict, object, tuple, object, int]:
        try:
            fresh = json.loads(runtime.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            fresh = {}
        rc, rect = None, wt2.RECT()
        if fresh.get("tray_hwnd"):
            nii = NII(ctypes.sizeof(NII), wt2.HWND(int(fresh["tray_hwnd"])),
                      int(fresh.get("tray_uid") or 1))
            rc = ctypes.windll.shell32.Shell_NotifyIconGetRect(ctypes.byref(nii), ctypes.byref(rect))
        if rc == 0 and rect.right > rect.left:
            box = (rect.left - 2, rect.top - 2, rect.right + 2, rect.bottom + 2)
        else:
            box = (max(0, sw - 800), max(0, sh - 64), sw, sh)
        img = ImageGrab.grab(bbox=box, all_screens=True)
        return fresh, rc, box, img, green_pixels(img)

    best = None
    for _ in range(12):
        cur = sample()
        if best is None or cur[4] >= 20:
            best = cur
        if cur[4] >= 20:
            break
        time.sleep(1.5)
    data, api_rc, box, img, count = best
    img.save(OUT)

    if data.get("pid"):
        subprocess.run(["taskkill", "/PID", str(data["pid"]), "/F"], capture_output=True)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()

    ev = {"box": list(box), "accent_pixels": count, "tray_added": data.get("tray_added"),
          "shell_getrect": api_rc, "crop": str(OUT), "ok": bool(data.get("tray_added")) and count >= 20}
    out = ROOT / "artifacts" / "tray-pixel.json"
    out.write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(ev, ensure_ascii=False))
    return 0 if ev["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
