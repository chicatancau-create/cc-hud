"""托盘取证（读-only）：跨进程枚举任务栏通知区 Toolbar 的按钮文本，找 cc-hud tooltip。

不点击、不改变任务栏设置；仅 OpenProcess + ReadProcessMemory + SendMessage。
用法：先启动 cc-hud.pyw，再 `python tools/tray_toolbar.py`
"""
from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

TB_BUTTONCOUNT = 0x0418
TB_GETBUTTON = 0x0417
TB_GETBUTTONTEXTW = 0x044B
TB_GETITEMRECT = 0x041D
WM_USER = 0x0400
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04


class TBBUTTON(ctypes.Structure):
    _fields_ = [
        ("iBitmap", ctypes.c_int),
        ("idCommand", ctypes.c_int),
        ("fsState", ctypes.c_ubyte),
        ("fsStyle", ctypes.c_ubyte),
        ("bReserved", ctypes.c_ubyte * 6),
        ("dwData", ctypes.c_size_t),
        ("iString", ctypes.c_ssize_t),
    ]


def _hwnd(parent, cls):
    user32.FindWindowExW.restype = wt.HWND
    return user32.FindWindowExW(wt.HWND(parent), None, cls, None)


def main() -> int:
    out = Path(__file__).resolve().parents[1] / "artifacts" / "tray-toolbar.json"
    user32.FindWindowW.restype = wt.HWND
    tray = user32.FindWindowW("Shell_TrayWnd", None)
    result = {"tray": int(tray or 0), "ok": False, "buttons": 0, "names": []}
    if not tray:
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 1

    notify = _hwnd(tray, "TrayNotifyWnd")
    pager = _hwnd(notify, "SysPager") if notify else 0
    toolbar = _hwnd(pager, "ToolbarWindow32") if pager else _hwnd(notify, "ToolbarWindow32")
    result["toolbar"] = int(toolbar or 0)
    if not toolbar:
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 1

    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(wt.HWND(toolbar), ctypes.byref(pid))
    result["explorer_pid"] = int(pid.value)
    access = PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_INFORMATION
    hproc = k32.OpenProcess(access, False, pid.value)
    result["open_process"] = bool(hproc)
    if not hproc:
        result["error"] = f"OpenProcess failed: {ctypes.get_last_error()}"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 1

    k32.VirtualAllocEx.restype = ctypes.c_void_p
    k32.VirtualAllocEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
    remote = k32.VirtualAllocEx(hproc, None, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    try:
        user32.SendMessageW.restype = ctypes.c_ssize_t
        count = int(user32.SendMessageW(wt.HWND(toolbar), TB_BUTTONCOUNT, 0, 0))
        result["buttons"] = count
        buf = ctypes.create_string_buffer(4096)
        read = ctypes.c_size_t()
        k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        for i in range(min(count, 64)):
            user32.SendMessageW(wt.HWND(toolbar), TB_GETBUTTON, i, ctypes.c_void_p(remote))
            if not k32.ReadProcessMemory(hproc, ctypes.c_void_p(remote), buf, ctypes.sizeof(TBBUTTON),
                                         ctypes.byref(read)):
                continue
            btn = TBBUTTON.from_buffer_copy(buf.raw[:ctypes.sizeof(TBBUTTON)])
            k32.ReadProcessMemory(hproc, ctypes.c_void_p(remote), buf, 4096, ctypes.byref(read))
            n = int(user32.SendMessageW(wt.HWND(toolbar), TB_GETBUTTONTEXTW, btn.idCommand,
                                        ctypes.c_void_p(remote)))
            name = ""
            if n > 0:
                k32.ReadProcessMemory(hproc, ctypes.c_void_p(remote), buf, 4096, ctypes.byref(read))
                name = buf.raw[: min(n * 2, 4096)].decode("utf-16-le", "replace").rstrip("\x00")
            if name:
                result["names"].append(name)
            if "cc-hud" in name:
                result["ok"] = True
                result["hit"] = {"index": i, "id": btn.idCommand, "name": name}
    finally:
        k32.VirtualFreeEx(hproc, ctypes.c_void_p(remote), 0, 0x8000)
        k32.CloseHandle(hproc)

    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
