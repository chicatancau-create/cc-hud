# -*- coding: utf-8 -*-
"""Win32 托盘与进程探测（原 cchud.sysw 迁入，纯 ctypes + Pillow）。"""
import ctypes
import time
from ctypes import wintypes as wt


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

# 一次物理单击会被 Shell 发成好几条消息（DOWN / UP / NIN_SELECT / DBLCLK），
# 不去抖就会「点一下、切换两次」。同一类事件在 DEBOUNCE 秒内只认第一条。
LEFT_CODES = (0x202, 0x203, 0x400, 0x401)   # LBUTTONDOWN/DBLCLK/NIN_SELECT/NIN_KEYSELECT
RIGHT_CODES = (0x204, 0x7B)                 # RBUTTONUP/WM_CONTEXTMENU
TRAY_EVT = {**{c: 'toggle' for c in LEFT_CODES}, **{c: 'menu' for c in RIGHT_CODES}}
DEBOUNCE = 0.30


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
                ('uY', wt.WORD), ('szTip', wt.WCHAR * 128), ('dwState', wt.DWORD),
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


class _NII(ctypes.Structure):
    """Shell_NotifyIconGetRect 要的是 NOTIFYICONIDENTIFIER（32 字节）。"""
    _fields_ = [('cbSize', wt.DWORD), ('hWnd', wt.HWND), ('uID', wt.UINT),
                ('guidItem', ctypes.c_char * 16)]


class Tray:
    """通知区域图标。WndProc 只处理托盘消息；host 的子类在 GUI 线程里同步处理事件。"""

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    def __init__(self, q):
        self.q = q
        # WndProc 在建窗过程中就会同步收到 WM_NCCREATE/WM_CREATE。
        # 这些字段必须先就位，否则回调抛 AttributeError → 返回 0 → CreateWindowExW 静默失败。
        self._taskbar_created = 0
        self._last: dict[str, float] = {}
        self.suppressed = 0
        self.added = False
        self._icons: dict[bool, int] = {}
        self._tip = None
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
        # 必须声明 argtypes/restype：64 位下 hInstance 会按 c_int 截断，
        # 类和 CreateWindowEx 用的就不是同一个模块句柄，建窗静默返回 NULL（err=0）。
        u.RegisterClassExW.restype = wt.ATOM
        u.RegisterClassExW.argtypes = [ctypes.POINTER(_WCX)]
        u.RegisterClassExW(ctypes.byref(wc))   # 类已存在（重试）也不算错
        # 必须是隐藏的顶层窗（WS_EX_TOOLWINDOW），不能用 HWND_MESSAGE：
        # message-only 窗口收不到 TaskbarCreated 等广播，Win11 Shell 会静默丢弃图标
        # （NIM_ADD=1、GetRect=E_FAIL、溢出面板无条目）。2026-11-08 实测顶层窗 GetRect=0。
        # 父窗口/菜单传 None；hInstance 显式包成 c_void_p：
        # 64 位句柄按裸 int 传入会被 ctypes 在个别版本上按 32 位校验/截断，
        # CreateWindowExW 于是静默返回 NULL（err=0），表现为「托盘建不出来」。
        self.hwnd = u.CreateWindowExW(0x80, 'ccHudTrayWnd', 'cc-hud-tray', 0, 0, 0, 0, 0,
                                      None, None, ctypes.c_void_p(hinst), None)
        if not self.hwnd:
            raise ctypes.WinError()
        u.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
        u.RegisterWindowMessageW.restype = wt.UINT
        self._taskbar_created = u.RegisterWindowMessageW("TaskbarCreated")
        self.nid = _NID()
        self.nid.cbSize = ctypes.sizeof(_NID)
        self.nid.hWnd = self.hwnd
        self.nid.uID = 1                            # 未赋值时是 0：Shell 不显示该图标，GetRect 也查不到
        self.nid.uFlags = 0x1 | 0x2 | 0x4          # MESSAGE | ICON | TIP
        self.nid.uCallbackMessage = WM_TRAY
        self.set(True, '启动中')
        if not ctypes.windll.shell32.Shell_NotifyIconW(0, ctypes.byref(self.nid)):
            u.DestroyWindow(self.hwnd)      # 失败不留半初始化窗口，否则重试会撞类名
            raise RuntimeError('Shell_NotifyIcon NIM_ADD 失败')
        self.added = True
        self.nid.uVersion = 4
        ctypes.windll.shell32.Shell_NotifyIconW(4, ctypes.byref(self.nid))  # NIM_SETVERSION
        rect = wt.RECT()
        ident = _NII(ctypes.sizeof(_NII), self.hwnd, 1, b"\x00" * 16)
        self.getrect_rc = ctypes.windll.shell32.Shell_NotifyIconGetRect(
            ctypes.byref(ident), ctypes.byref(rect))
        self.getrect = [rect.left, rect.top, rect.right, rect.bottom]

    def _wnd(self, h, msg, wp, lp):
        try:
            if msg == self._taskbar_created:
                # explorer 重启后 Shell 会丢图标；顶层窗能收到广播，重新 NIM_ADD
                if getattr(self, "added", False):
                    ctypes.windll.shell32.Shell_NotifyIconW(0, ctypes.byref(self.nid))
                return 0
            if msg == WM_TRAY:
                ev = TRAY_EVT.get(lp & 0xFFFF)
                if ev and self._accept(ev):
                    self.q.put(ev)          # 只丢事件, 不在这里碰 Tk
                return 1
        except Exception:
            return 0                        # Python 异常逃回原生窗口过程会直接带走进程
        return ctypes.windll.user32.DefWindowProcW(h, msg, wp, lp)

    def _accept(self, ev: str) -> bool:
        """同一种事件在 DEBOUNCE 内只放行一次，挡掉 Shell 的多消息叠加。"""
        now = time.monotonic()
        if now - self._last.get(ev, 0.0) < DEBOUNCE:
            self.suppressed += 1
            return False
        self._last[ev] = now
        return True

    # ── 右键原生菜单：和主面板共用 cchud_next.menu 生成的同一棵树 ──
    def popup(self, items: list[dict]) -> str | None:
        """按菜单树弹原生菜单，返回被选中的命令 id。

        TrackPopupMenu 会阻塞到菜单关闭；菜单句柄用完立刻 DestroyMenu，
        重复右键不会累积 GDI 对象。调用前必须 SetForegroundWindow，
        否则点菜单外部不会消失（Win32 的经典坑）。
        """
        u = ctypes.windll.user32
        u.CreatePopupMenu.restype = ctypes.c_void_p
        u.AppendMenuW.argtypes = [ctypes.c_void_p, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
        u.AppendMenuW.restype = wt.BOOL
        u.DestroyMenu.argtypes = [ctypes.c_void_p]
        u.TrackPopupMenu.argtypes = [ctypes.c_void_p, wt.UINT, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, wt.HWND, ctypes.c_void_p]
        u.TrackPopupMenu.restype = ctypes.c_int
        u.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]

        ids: dict[int, str] = {}
        next_id = [1000]

        MF_STRING, MF_POPUP, MF_SEPARATOR = 0x0, 0x10, 0x800
        MF_GRAYED, MF_CHECKED, MF_DISABLED = 0x1, 0x8, 0x2
        TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x100, 0x2

        def build(nodes: list[dict]) -> int:
            hmenu = u.CreatePopupMenu()
            for node in nodes:
                if node.get("kind") == "separator":
                    u.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                    continue
                flags = MF_STRING
                if node.get("kind") == "submenu":
                    sub = build(node.get("children") or [])
                    flags |= MF_POPUP
                    if not node.get("enabled", True):
                        flags |= MF_GRAYED
                    u.AppendMenuW(hmenu, flags, sub, node.get("title", ""))
                    continue
                mid = next_id[0]
                next_id[0] += 1
                ids[mid] = str(node.get("id"))
                if not node.get("enabled", True):
                    flags |= MF_GRAYED | MF_DISABLED
                if node.get("checked"):
                    flags |= MF_CHECKED
                title = node.get("title", "")
                if node.get("danger"):
                    title = "⚠ " + title
                u.AppendMenuW(hmenu, flags, mid, title)
            return hmenu

        menu = build(items)
        pt = wt.POINT()
        u.GetCursorPos(ctypes.byref(pt))
        try:
            u.SetForegroundWindow(self.hwnd)
            picked = u.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                      pt.x, pt.y, 0, self.hwnd, None)
        finally:
            u.DestroyMenu(menu)
            u.PostMessageW(self.hwnd, 0, 0, 0)   # 让菜单真正收起
        return ids.get(int(picked or 0))

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
        if getattr(self, 'hwnd', None):
            ctypes.windll.user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        for k in list(getattr(self, '_icons', {})):        # HICON 是我们 CreateIconIndirect 造的
            ctypes.windll.user32.DestroyIcon(self._icons.pop(k))
