# -*- coding: utf-8 -*-
"""Probe: register the same tray icon from a hidden top-level tool window.

Message-only windows (HWND_MESSAGE) are excluded from broadcasts such as
TaskbarCreated; if the Shell refuses those icons on this box, a top-level window
should get a valid rect. Adds an icon, checks GetRect, then removes it.
"""
import ctypes
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cchud_next.tray import _hicon, _NID, _NII, _WCX, WM_TRAY  # noqa: E402


def main() -> int:
    u = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    u.CreateWindowExW.restype = wt.HWND
    u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND,
                                  wt.HMENU, ctypes.c_void_p, ctypes.c_void_p]
    u.DefWindowProcW.restype = ctypes.c_ssize_t
    u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    PROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    proc = PROC(lambda h, m, w, l: u.DefWindowProcW(h, m, w, l))

    hinst = k32.GetModuleHandleW(None)
    wc = _WCX()
    wc.cbSize = ctypes.sizeof(wc)
    wc.lpfnWndProc = ctypes.cast(proc, ctypes.c_void_p)
    wc.hInstance = hinst
    wc.lpszClassName = "ccHudTrayProbe"
    u.RegisterClassExW(ctypes.byref(wc))

    # WS_EX_TOOLWINDOW (0x80) keeps it out of Alt+Tab; parent=None => top-level (not message-only)
    hwnd = u.CreateWindowExW(0x80, "ccHudTrayProbe", "cc-hud-tray-probe",
                             0, 0, 0, 0, 0, None, None, hinst, None)
    out = {"hwnd": int(hwnd) if hwnd else 0}
    if not hwnd:
        out["error"] = "CreateWindowExW failed"
        print(out)
        return 1

    nid = _NID()
    nid.cbSize = ctypes.sizeof(_NID)
    nid.hWnd = hwnd
    nid.uID = 1
    nid.uFlags = 0x1 | 0x2 | 0x4
    nid.uCallbackMessage = WM_TRAY
    nid.hIcon = _hicon(16, True)
    nid.szTip = "cc-hud-tray-probe"
    out["add"] = bool(ctypes.windll.shell32.Shell_NotifyIconW(0, ctypes.byref(nid)))
    nid.uVersion = 4
    out["setver"] = bool(ctypes.windll.shell32.Shell_NotifyIconW(4, ctypes.byref(nid)))
    time.sleep(0.6)
    rect = wt.RECT()
    ident = _NII(ctypes.sizeof(_NII), hwnd, 1, b"\x00" * 16)
    rc = ctypes.windll.shell32.Shell_NotifyIconGetRect(ctypes.byref(ident), ctypes.byref(rect))
    out["getrect_rc"] = int(rc)
    out["getrect"] = [rect.left, rect.top, rect.right, rect.bottom]
    ctypes.windll.shell32.Shell_NotifyIconW(2, ctypes.byref(nid))
    u.DestroyWindow(hwnd)
    out["ok"] = rc == 0
    print(out)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
