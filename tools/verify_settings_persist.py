"""设置在进程重启后生效：预写状态文件，核对 alpha/置顶/布局。"""
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
OUT = ROOT / "artifacts" / "windows-verify-settings-persist.json"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cchud-state-"))
    state = tmp / "state.json"
    state.write_text(json.dumps({
        "alpha": 0.78, "topmost": False, "peek": True, "range": "7d",
        "layout": "card", "theme": "dark", "hollow": False,
    }), encoding="utf-8")
    env = dict(os.environ, CC_HUD_LAYOUT="", CC_HUD_STATE=str(state),
               CC_HUD_PROFILE=str(tmp / "profile"))
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
        if data.get("ready") and data.get("pid"):
            break
        time.sleep(0.4)
    time.sleep(1.0)

    lay = (data.get("layered") or {})
    checks = {
        "ready": bool(data.get("ready")),
        "alpha_applied": lay.get("alpha") in (198, 199),   # 0.78*255 截断/四舍五入
        "topmost_off": data.get("topmost") is False,
        "layout_card": data.get("layout") == "card",
        # 旧配置里带 peek 也必须能正常起来；同时不得因此建出第二窗口
        "legacy_peek_file_read": state.exists(),
        "no_dot_window": not data.get("dot_created"),
        "tray_added": bool(data.get("tray_added")),
    }
    hwnd = int(data.get("hwnd") or 0)
    if hwnd:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
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

    ok = all(checks.values())
    OUT.write_text(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
