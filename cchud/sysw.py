# -*- coding: utf-8 -*-
"""cc-hud Win32 互操作: 托盘图标/进程探测/窗口结构。"""
import ctypes
from ctypes import wintypes as wt

from .const import *
from .util import *
from .render import *

__all__ = [
    '_PE', 'ccswitch_pid', 'already_running', 'WM_TRAY', 'TRAY_EVT', '_hicon', '_NID', '_WCX',
    'Tray',
]


class _PE(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wt.DWORD),
                ('cntThreads', wt.DWORD), ('th32ParentProcessID', wt.DWORD),
                ('pcPriClassBase', wt.LONG), ('dwFlags', wt.DWORD),
                ('szExeFile', wt.WCHAR * 260)]


def ccswitch_pid():
    """CC Switch 主进程 PID, 不在则 None。一次快照拿全部进程名, 不派生 tasklist。"""
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p     # 不写这句: 返回值按 c_int 截断,
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)       # TH32CS_SNAPPROCESS   大句柄会变负数
    if not snap or ctypes.c_ssize_t(snap).value == -1:
        return None
    pe = _PE()
    pe.dwSize = ctypes.sizeof(_PE)
    pid = None
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            if pe.szExeFile.lower().startswith('cc-switch'):
                pid = int(pe.th32ProcessID)
                break
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return pid


def already_running():
    """命名互斥体做单实例闸门: 开机自启 + 手动再双击只会留一个卡片。"""
    ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\cc-hud-single')
    return ctypes.windll.kernel32.GetLastError() == 183   # ERROR_ALREADY_EXISTS


# ── 系统托盘: 隐藏之后唯一的找回入口(纯 ctypes, 不引第三方) ────────────────
WM_TRAY = 0x800 + 1


TRAY_EVT = {0x202: 'toggle', 0x203: 'toggle', 0x400: 'toggle', 0x401: 'toggle',
            0x204: 'menu', 0x7B: 'menu'}      # 左键/双击/NIN_SELECT/右键/WM_CONTEXTMENU


def _hicon(size, on):
    """画一枚托盘图标并转成 HICON: 32bpp 颜色位图 + 全零 AND 掩码, alpha 交给外壳读。"""
    from PIL import Image, ImageDraw
    s = size * 4
    im = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    acc = (52, 211, 153, 255) if on else (96, 108, 124, 255)
    lw = max(1, int(s * 0.055))
    d.rounded_rectangle([s * .05, s * .05, s * .95, s * .95], radius=s * .24,
                        fill=(16, 19, 29, 255), outline=acc, width=lw)
    r = s * .24
    d.ellipse([s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r], outline=acc,
              width=max(1, int(s * .085)))
    k = s * .06
    d.ellipse([s / 2 - k, s / 2 - k, s / 2 + k, s / 2 + k], fill=acc)
    im = im.transpose(Image.FLIP_TOP_BOTTOM).resize((size, size), Image.LANCZOS)
    g, u = ctypes.windll.gdi32, ctypes.windll.user32
    gdi32_CreateBitmap = g.CreateBitmap
    gdi32_CreateBitmap.restype = ctypes.c_void_p
    gdi32_CreateBitmap.argtypes = [ctypes.c_int] * 4 + [ctypes.c_void_p]
    col = gdi32_CreateBitmap(size, size, 1, 32, im.tobytes('raw', 'BGRA'))
    mask = gdi32_CreateBitmap(size, size, 1, 1, b'\x00' * (((size + 31) // 32) * 4 * size))

    class _II(ctypes.Structure):
        # winuser.h 的 ICONINFO 真布局是 fIcon / xHotspot / yHotspot / hbmMask / hbmColor。
        # 以前写成 fIcon/fMask/两个句柄(24 字节): CreateIconIndirect 把 mask 指针当成
        # yHotspot、把 color 当成 hbmMask、hbmColor 读到未初始化内存 -> 直接返回 NULL,
        # 于是 nid.hIcon=0。NIM_ADD 对 hIcon=0 照样返回"成功", 外壳就摆了一个透明空槽。
        _fields_ = [('fIcon', wt.BOOL), ('xHotspot', wt.DWORD), ('yHotspot', wt.DWORD),
                    ('hbmMask', ctypes.c_void_p), ('hbmColor', ctypes.c_void_p)]

    u.CreateIconIndirect.restype = ctypes.c_void_p
    u.CreateIconIndirect.argtypes = [ctypes.c_void_p]
    g.DeleteObject.argtypes = [ctypes.c_void_p]
    h = u.CreateIconIndirect(ctypes.byref(_II(1, 0, 0, mask, col)))
    g.DeleteObject(col)
    g.DeleteObject(mask)
    if not h:
        raise ctypes.WinError()          # 宁可托盘挂不上并写明原因, 也不要留一个看不见的图标
    return h


class _NID(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('hWnd', wt.HWND), ('uID', wt.UINT), ('uFlags', wt.UINT),
                ('uCallbackMessage', wt.UINT), ('hIcon', ctypes.c_void_p), ('uX', wt.WORD),
                ('uY', wt.WORD), ('szTip', wt.WCHAR * 64), ('dwState', wt.DWORD),
                ('dwStateMask', wt.DWORD), ('szInfo', wt.WCHAR * 256),
                ('uVersion', wt.UINT), ('szInfoTitle', wt.WCHAR * 64), ('dwInfoFlags', wt.DWORD),
                ('guidItem', ctypes.c_char * 16), ('hBalloonIcon', ctypes.c_void_p)]


class _WCX(ctypes.Structure):
    _fields_ = [('cbSize', wt.UINT), ('style', wt.UINT),
                ('lpfnWndProc', ctypes.c_void_p), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', ctypes.c_void_p),
                ('hIcon', ctypes.c_void_p), ('hCursor', ctypes.c_void_p),
                ('hbrBackground', ctypes.c_void_p), ('lpszMenuName', ctypes.c_wchar_p),
                ('lpszClassName', ctypes.c_wchar_p), ('hIconSm', ctypes.c_void_p)]


class Tray:
    """通知区域图标。Tcl 在 Windows 上由独立的通知线程派发窗口消息, 所以 WndProc
    绝不碰 Tk, 只往队列里丢事件, 由界面线程的 _tick 消费。"""

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    def __init__(self, q):
        self.q = q
        u = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        k32.GetModuleHandleW.restype = ctypes.c_void_p
        u.CreateWindowExW.restype = wt.HWND
        u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND,
                                      wt.HMENU, ctypes.c_void_p, ctypes.c_void_p]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        self._proc = Tray.WNDPROC(self._wnd)
        hinst = k32.GetModuleHandleW(None)
        wc = _WCX()
        wc.cbSize = ctypes.sizeof(wc)
        wc.lpfnWndProc = ctypes.cast(self._proc, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = 'ccHudTrayWnd'
        if not u.RegisterClassExW(ctypes.byref(wc)):
            raise ctypes.WinError()
        self.hwnd = u.CreateWindowExW(0, 'ccHudTrayWnd', 'cc-hud-tray', 0, 0, 0, 0, 0,
                                      ctypes.c_void_p(-3), 0, hinst, 0)   # HWND_MESSAGE
        if not self.hwnd:
            raise ctypes.WinError()
        self.nid = _NID()
        self.nid.cbSize = ctypes.sizeof(_NID)
        self.nid.hWnd = self.hwnd
        self.nid.uFlags = 0x1 | 0x2 | 0x4          # MESSAGE | ICON | TIP
        self.nid.uCallbackMessage = WM_TRAY
        self._icons = {}
        self._tip = None
        self.added = False
        self.set(True, '启动中')
        if not ctypes.windll.shell32.Shell_NotifyIconW(0, ctypes.byref(self.nid)):
            raise RuntimeError('Shell_NotifyIcon NIM_ADD 失败')
        self.added = True

    def _wnd(self, h, msg, wp, lp):
        try:
            if msg == WM_TRAY:
                ev = TRAY_EVT.get(lp & 0xFFFF)
                if ev:
                    self.q.put(ev)          # 只丢事件, 不在这里碰 Tk
                return 1
        except Exception:
            return 0                        # Python 异常逃回原生窗口过程会直接带走进程
        return ctypes.windll.user32.DefWindowProcW(h, msg, wp, lp)

    def set(self, on, tip):
        """切换图标明暗 + 更新悬停提示(显示中/已隐藏)。"""
        if on not in self._icons:
            self._icons[on] = _hicon(16, on)
        self.nid.hIcon = self._icons[on]
        if tip != self._tip:
            self.nid.szTip = tip[:63]
            self._tip = tip
        if self.added:
            ctypes.windll.shell32.Shell_NotifyIconW(1, ctypes.byref(self.nid))   # NIM_MODIFY

    def quit(self):
        if getattr(self, 'added', False):
            ctypes.windll.shell32.Shell_NotifyIconW(2, ctypes.byref(self.nid))   # NIM_DELETE
            self.added = False
        for k in list(getattr(self, '_icons', {})):        # HICON 是我们 CreateIconIndirect 造的
            ctypes.windll.user32.DestroyIcon(self._icons.pop(k))
