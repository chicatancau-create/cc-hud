"""Windows 实机验收：WebView2 起窗、DPI、alpha、置顶、托盘、圆点、多屏、截图。

只报告实测；任何一项失败都以退出码 1 结束，不伪造。
用法：python tools/verify_windows.py [--layout card|insights] [--shot NAME]
"""
from __future__ import annotations

import argparse
import ctypes
import faulthandler
import json
import os
import subprocess
import tempfile
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cchud_next.win32 import WindowOps, dpi_aware, monitors  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]


def process_dpi_awareness(pid: int) -> int | None:
    shcore = ctypes.windll.shcore
    val = ctypes.c_int()
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    try:
        return val.value if shcore.GetProcessDpiAwareness(h, ctypes.byref(val)) == 0 else None
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def owner_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def find_owned(title: str, pid: int) -> int:
    for h, t, _cls in windows():
        if t == title and owner_pid(h) == pid:
            return h
    return 0


def windows() -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HWND, wt.LPARAM)

    def cb(hwnd, _lp):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        out.append((int(hwnd), buf.value, cls.value))
        return 1

    user32.EnumWindows(PROC(cb), 0)
    return out


def find(title: str) -> int | None:
    for hwnd, text, _cls in windows():
        if text == title:
            return hwnd
    return None


def main() -> int:
    dpi_aware()          # GetWindowRect/抓图必须是物理像素，否则 125% 下会被虚拟化成 0.8 倍
    if os.environ.get("CC_HUD_STACK"):
        faulthandler.dump_traceback_later(40, repeat=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", default="card")
    ap.add_argument("--shot", default="windows-card")
    ap.add_argument("--timeout", type=int, default=45)
    ap.add_argument("--hidden", action="store_true", help="启动后隐藏，验证呼出圆点")
    ap.add_argument("--wait", type=float, default=6.0, help="首次快照等待秒数")
    ap.add_argument("--screen", action="store_true", help="改用整屏抓取后裁窗（交叉核对）")
    ap.add_argument("--scroll", type=int, default=0, help="抓图前滚动 .page 的像素")
    ap.add_argument("--selftest", default="", help="前端自测：hide|export")
    ap.add_argument("--scale", default="", help="强制 WebView2 device scale（1 或 1.25）")
    ap.add_argument("--hollow", action="store_true", help="背景镂空（LWA_COLORKEY）取证")
    args = ap.parse_args()

    runtime = ROOT / "artifacts" / "runtime.json"
    shot = ROOT / "artifacts" / "windows" / f"{args.shot}.png"
    if runtime.exists():
        runtime.unlink()

    # 不设 CC_HUD_SIZE：抓图必须走生产布局尺寸（尺寸由宿主按 DPI 换算）
    env = dict(os.environ, CC_HUD_LAYOUT=args.layout,
               CC_HUD_PROFILE=tempfile.mkdtemp(prefix="cchud-webview-"),
               CC_HUD_MUTEX=rf"Local\cc-hud-verify-{os.getpid()}-{args.layout}")
    if args.scroll:
        env["CC_HUD_SCROLL"] = str(args.scroll)
    if args.selftest:
        env["CC_HUD_SELFTEST"] = args.selftest
    if args.scale:
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--force-device-scale-factor={args.scale}"
    if args.hollow:
        env["CC_HUD_HOLLOW"] = "1"
    if args.selftest == "power":
        env["CC_HUD_FAKE_POWER"] = "1"
    if args.hidden:
        env["CC_HUD_START_HIDDEN"] = "1"
    proc = subprocess.Popen([sys.executable, str(ROOT / "cc-hud.pyw")], cwd=str(ROOT), env=env)

    deadline = time.time() + args.timeout
    data: dict = {}
    while time.time() < deadline:
        if runtime.exists():
            try:
                data = json.loads(runtime.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if data.get("ready"):
                break
        if proc.poll() is not None:
            break
        time.sleep(0.4)
    # 托盘在 GUI 线程里异步建立：等它落账再判定，否则会把「还没建」误判成「建不成」
    deadline2 = time.time() + 12
    while time.time() < deadline2:
        if data.get("tray_added") is not None:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.3)
        try:
            data = json.loads(runtime.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    checks: dict[str, dict] = {}

    def check(name: str, ok: bool, detail) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    own_pid = int(data.get("pid") or 0)
    cand = int(data.get("hwnd") or 0)
    if not cand or owner_pid(cand) != own_pid:
        cand = find_owned("cc-hud", own_pid)
    hwnd = cand if cand and own_pid and owner_pid(cand) == own_pid else 0
    if hwnd:
        deadline2 = time.time() + args.wait
        while time.time() < deadline2:
            try:
                data = json.loads(runtime.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            if not args.selftest or data.get("selftest_result"):
                break
            time.sleep(0.5)
        try:
            data = json.loads(runtime.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    check("process_alive", proc.poll() is None, proc.poll())
    check("runtime_json", bool(data), str(runtime))
    check("window_created", bool(hwnd), hwnd)
    check("main_title", find("cc-hud") is not None, find("cc-hud"))
    # 第二窗口已删除：任何时刻都不允许存在 cc-hud-dot
    dot_hwnd0 = find_owned("cc-hud-dot", own_pid)
    check("no_dot_window", dot_hwnd0 == 0 and not data.get("dot_created"), {
        "hwnd": dot_hwnd0 or None, "dot_created": data.get("dot_created")})
    check("single_window_only", bool(data.get("main_created")) and not data.get("dot_created"),
          {"main_created": data.get("main_created"), "dot_created": data.get("dot_created")})
    check("file_url", str(data.get("dist", "")).startswith("file://"), data.get("dist"))
    check("tray_added", bool(data.get("tray_added")), data.get("tray_added"))
    if args.selftest:
        try:
            data = json.loads(runtime.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if args.selftest == "power":
        raw = data.get("selftest_result") or {}
        if isinstance(raw, dict):
            info = raw
        else:
            try:
                info = json.loads(raw)
            except (TypeError, ValueError):
                info = {}
        check("selftest_power",
              info.get("unconfirmed", {}).get("ok") is False and info.get("confirmed", {}).get("ok") is True,
              info or {"raw": raw, "type": type(raw).__name__})
    if args.selftest == "export":
        raw = data.get("selftest_result") or {}
        if isinstance(raw, dict):
            info = raw
        else:
            try:
                info = json.loads(raw)
            except (TypeError, ValueError):
                info = {}
        path = info.get("path")
        check("selftest_export", bool(info.get("revision")) and bool(path) and os.path.exists(path), info)
    check("dpi", int(data.get("dpi") or 0) >= 96, data.get("dpi"))
    pid = int(data.get("pid") or 0)
    aw = process_dpi_awareness(pid) if pid else None
    check("dpi_aware_per_monitor", aw == 2, {"pid": pid, "awareness": aw})
    mons = monitors()
    check("multi_monitor", len(mons) >= 1, [m["device"] for m in mons])
    check("work_area", len(data.get("work_area") or []) == 4, data.get("work_area"))

    if hwnd:
        time.sleep(args.wait)
        ops = WindowOps(hwnd)
        state = ops.layered_state()
        check("layered", state["layered"], state)
        check("alpha", state["alpha"] > 0 and (state["flags"] & 2) != 0, state)
        check("topmost", ops.is_topmost(), ops.is_topmost())
        if args.hidden:
            for _ in range(40):
                try:
                    data = json.loads(runtime.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = data
                if data.get("hidden"):
                    break
                time.sleep(0.25)
        else:
            time.sleep(1.0)
        vis = bool(user32.IsWindowVisible(wt.HWND(hwnd)))
        check("visible", (not vis) if args.hidden else vis, vis)
        if args.hidden:
            # 隐藏后唯一找回入口是托盘：必须注册成功且仍存在，且没有任何圆点窗口
            check("tray_available_when_hidden", bool(data.get("tray_added")), {
                "tray_added": data.get("tray_added"),
                "tray_hwnd": data.get("tray_hwnd"),
                "tray_getrect_rc": data.get("tray_getrect_rc")})
            check("no_dot_when_hidden", find_owned("cc-hud-dot", own_pid) == 0,
                  find_owned("cc-hud-dot", own_pid) or None)
        if not args.hollow:
            ops.set_alpha(1.0)
        time.sleep(0.35)
        if args.screen or args.hollow:
            from PIL import ImageGrab
            rect = wt.RECT()
            user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect))
            time.sleep(0.4)  # 镂空态不要再用 alpha 覆盖，保持区域/颜色键
            img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
            img.save(shot)
            cap = {"ok": True, "method": "ImageGrab", "w": img.width, "h": img.height,
                   "max_luma": img.convert("L").getextrema()[1], "path": str(shot)}
            if args.hollow:
                px = list(img.convert("RGB").getdata())
                bg = sum(1 for q in px if abs(q[0] - 11) <= 2 and abs(q[1] - 14) <= 2 and abs(q[2] - 20) <= 2)
                inv = sum(1 for q in px if abs(q[0] - 255) <= 2 and abs(q[1] - 255) <= 2 and abs(q[2] - 255) <= 2)
                cap["bg_pixels"] = bg
                cap["area"] = len(px)
                state = ops.layered_state()
                rgn = ops.region_state()
                # 颜色键会让 WebView2 子窗整窗穿透（按钮点不到），改用圆角窗口区域 + alpha
                check("hollow_transparent", (state["flags"] & 1) != 0 or rgn in (2, 3),
                      {"layered": state, "region_type": rgn})
                # 圆角外四角必须是“窗口后面的画面”，不能是窗口自身的背景色；
                # 不能用全图同色像素占比——UI 自身的深色（如 10,13,22）会落进容差带造成假阳性。
                corners = [(2, 2), (img.width - 3, 2), (2, img.height - 3),
                           (img.width - 3, img.height - 3)]
                corner_px = [img.getpixel(c) for c in corners]
                native = [c for c in corner_px
                          if abs(c[0] - 11) <= 2 and abs(c[1] - 14) <= 2 and abs(c[2] - 20) <= 2]
                check("hollow_corners_transparent", not native,
                      {"corners": corner_px, "native_bg_hits": len(native),
                       "bg_pixels": bg, "inv_pixels": inv})
            if not args.hollow:
                ops.set_alpha(float(data.get("alpha_setting") or 0.96))
        else:
            cap = ops.capture(shot)
        check("capture", cap.get("ok") and cap.get("max_luma", 0) > 10, cap)
    else:
        for name in ("layered", "alpha", "topmost", "visible", "capture"):
            check(name, False, "no hwnd")

    if hwnd:
        user32.PostMessageW(wt.HWND(hwnd), 0x0010, 0, 0)  # WM_CLOSE
    for _ in range(20):
        if proc.poll() is not None:
            break
        time.sleep(0.3)
    if own_pid:
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, own_pid)  # SYNCHRONIZE
        if h:
            ctypes.windll.kernel32.WaitForSingleObject(h, 5000)
            ctypes.windll.kernel32.CloseHandle(h)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()

    ok = all(c["ok"] for c in checks.values())
    evidence = {
        "layout": args.layout,
        "ok": ok,
        "checks": checks,
        "runtime": data,
        "monitors": mons,
        "timestamp": time.time(),
        "shot": str(shot),
    }
    out = ROOT / "artifacts" / f"windows-verify-{args.shot}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, c in checks.items():
        print(f"[{'PASS' if c['ok'] else 'FAIL'}] {name}: {json.dumps(c['detail'], ensure_ascii=False)[:180]}")
    print(f"evidence: {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
