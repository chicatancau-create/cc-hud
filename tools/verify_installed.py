# -*- coding: utf-8 -*-
"""Attach to the already-running installed HUD and capture it (no second launch)."""
import ctypes
import json
import sys
from ctypes import wintypes as wt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import verify_windows as vw  # noqa: E402
from cchud_next.win32 import WindowOps  # noqa: E402

user32 = ctypes.windll.user32
user32.IsWindowVisible.argtypes = [wt.HWND]


def main() -> int:
    rt = json.loads((ROOT / "artifacts" / "runtime.json").read_text(encoding="utf-8"))
    pid = int(rt.get("pid") or 0)
    hwnd = int(rt.get("hwnd") or 0)
    owned = [(h, t, c) for h, t, c in vw.windows() if vw.owner_pid(h) == pid and t]
    if owned and not hwnd:
        hwnd = owned[0][0]
    out = {"pid": pid, "hwnd": hwnd, "owned": owned, "runtime_ready": bool(rt.get("ready"))}
    if not hwnd:
        out["ok"] = False
        out["error"] = "no window owned by host pid"
        print(json.dumps(out, ensure_ascii=False))
        return 1
    out["visible"] = bool(user32.IsWindowVisible(hwnd))
    rect = wt.RECT()
    user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect))
    out["rect"] = [rect.left, rect.top, rect.right, rect.bottom]
    out["capture"] = WindowOps(hwnd).capture(ROOT / "artifacts" / "windows" / "REPLACED-card.png")
    out["ok"] = bool(out["visible"] and out["capture"].get("ok"))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
