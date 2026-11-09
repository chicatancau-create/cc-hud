"""Win32 窗口能力：DPI、整窗 alpha、颜色键镂空、置顶、多屏定位、取证截图。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
LWA_COLORKEY = 0x00000001
LWA_ALPHA = 0x00000002
PW_RENDERFULLCONTENT = 0x00000002
MONITOR_DEFAULTTONEAREST = 2


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
        ("szDevice", wt.WCHAR * 32),
    ]


def dpi_aware() -> bool:
    """PER_MONITOR_AWARE_V2；失败逐级回退。必须在建窗前调用。"""
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        try:
            user32.SetProcessDPIAware()
            return True
        except Exception:
            return False


def system_scale() -> float:
    """当前系统 DPI 缩放（1.25 = 125%）。"""
    try:
        user32.GetDpiForSystem.restype = ctypes.c_uint
        return max(1.0, user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


def dpi_for_window(hwnd: int) -> int:
    try:
        user32.GetDpiForWindow.restype = ctypes.c_uint
        return int(user32.GetDpiForWindow(wt.HWND(hwnd)))
    except Exception:
        return 96


def work_area(hwnd: int | None = None, point: tuple[int, int] | None = None):
    try:
        if hwnd:
            mon = user32.MonitorFromWindow(wt.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
        elif point is not None:
            mon = user32.MonitorFromPoint(wt.POINT(int(point[0]), int(point[1])), MONITOR_DEFAULTTONEAREST)
        else:
            mon = user32.MonitorFromPoint(wt.POINT(0, 0), MONITOR_DEFAULTTONEAREST)
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if mon and user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            r = info.rcWork
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    r = wt.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
    return (r.left, r.top, r.right, r.bottom)


def monitors() -> list[dict]:
    out: list[dict] = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(wt.RECT), ctypes.c_double)

    def cb(hmon, hdc, rect, data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            out.append({
                "device": info.szDevice,
                "primary": bool(info.dwFlags & 1),
                "rect": [info.rcMonitor.left, info.rcMonitor.top,
                         info.rcMonitor.right, info.rcMonitor.bottom],
                "work": [info.rcWork.left, info.rcWork.top,
                         info.rcWork.right, info.rcWork.bottom],
                "dpi": dpi_for_window(0),
            })
        return 1

    user32.EnumDisplayMonitors(None, None, PROC(cb), 0)
    return out


def _get_exstyle(hwnd: int) -> int:
    user32.GetWindowLongW.restype = ctypes.c_ssize_t
    user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    return int(user32.GetWindowLongW(wt.HWND(hwnd), GWL_EXSTYLE))


def _set_exstyle(hwnd: int, style: int) -> None:
    user32.SetWindowLongW.restype = ctypes.c_ssize_t
    user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongW(wt.HWND(hwnd), GWL_EXSTYLE, style)


def compute_placement(work_areas: list[tuple[int, int, int, int]], width: int, height: int,
                      monitor: int = 0, anchor: str = "top-right", margin: int = 16) -> tuple[int, int]:
    """纯函数：在给定工作区列表里定位，越界夹取。便于在没有第二块屏时单测多屏分支。"""
    if not work_areas:
        raise ValueError("no work areas")
    l, t, r, b = work_areas[min(max(0, monitor), len(work_areas) - 1)]
    x = r - width - margin if "right" in anchor else l + margin
    y = t + margin if "top" in anchor else b - height - margin
    x = max(l, min(x, r - width - 4))
    y = max(t, min(y, b - height - 4))
    return int(x), int(y)


class WindowOps:
    """一个 HWND 的整窗效果。Windows 下绝不使用 pywebview transparent=True。"""

    def __init__(self, hwnd: int):
        self.hwnd = int(hwnd)

    def set_alpha(self, alpha: float) -> bool:
        a = max(0.0, min(1.0, float(alpha)))
        ex = _get_exstyle(self.hwnd) | WS_EX_LAYERED
        _set_exstyle(self.hwnd, ex)
        return bool(user32.SetLayeredWindowAttributes(wt.HWND(self.hwnd), 0, int(a * 255), LWA_ALPHA))

    def set_colorkey(self, colorref: int, alpha: float = 1.0) -> bool:
        """颜色键镂空；与 alpha 同时生效（两标志位可并）。"""
        ex = _get_exstyle(self.hwnd) | WS_EX_LAYERED
        _set_exstyle(self.hwnd, ex)
        return bool(user32.SetLayeredWindowAttributes(
            wt.HWND(self.hwnd), wt.DWORD(colorref), int(max(0.0, min(1.0, alpha)) * 255),
            LWA_COLORKEY | LWA_ALPHA))

    def set_round_region(self, width: int, height: int, radius: int) -> bool:
        """圆角窗口区域：区域外不参与命中测试（可点、无颜色键穿透）。"""
        rgn = gdi32.CreateRoundRectRgn(0, 0, int(width) + 1, int(height) + 1,
                                       int(radius), int(radius))
        if not rgn:
            return False
        ok = bool(user32.SetWindowRgn(wt.HWND(self.hwnd), rgn, True))
        if not ok:
            gdi32.DeleteObject(rgn)
        return ok

    def clear_region(self) -> bool:
        return bool(user32.SetWindowRgn(wt.HWND(self.hwnd), None, True))

    def region_state(self) -> int:
        """GetWindowRgn：0=无区域/失败，1=NULL，2=SIMPLE，3=COMPLEX。"""
        rgn = gdi32.CreateRectRgn(0, 0, 0, 0)
        try:
            return int(user32.GetWindowRgn(wt.HWND(self.hwnd), rgn))
        finally:
            gdi32.DeleteObject(rgn)

    def clear_layered(self) -> bool:
        ex = _get_exstyle(self.hwnd) & ~WS_EX_LAYERED
        _set_exstyle(self.hwnd, ex)
        return True

    def layered_state(self) -> dict:
        ex = _get_exstyle(self.hwnd)
        key = wt.DWORD(0)
        alpha = wt.BYTE(0)
        flags = wt.DWORD(0)
        ok = user32.GetLayeredWindowAttributes(wt.HWND(self.hwnd), ctypes.byref(key),
                                               ctypes.byref(alpha), ctypes.byref(flags))
        return {"layered": bool(ex & WS_EX_LAYERED), "alpha": alpha.value,
                "colorkey": key.value, "flags": flags.value, "read_ok": bool(ok)}

    def set_topmost(self, on: bool) -> bool:
        user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wt.UINT]
        return bool(user32.SetWindowPos(wt.HWND(self.hwnd), HWND_TOPMOST if on else HWND_NOTOPMOST,
                                        0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))

    def is_topmost(self) -> bool:
        return bool(_get_exstyle(self.hwnd) & WS_EX_TOPMOST)

    def place(self, width: int | None = None, height: int | None = None, monitor: int = 0,
              anchor: str = "top-right", margin: int = 16, keep_size: bool = True) -> dict:
        """搬位置 / 改尺寸，并回读真实矩形。

        SetWindowPos 的返回值必须检查：WinForms 会按 Min/Max 夹取、WebView2 还会在
        首帧后异步重排，结果和请求值并不总是相等。旧实现直接回显请求值，导致宿主侧
        「尺寸是否生效」的校验恒真（熔断永不触发）。这里返回 GetWindowRect 的实际
        w/h 与 ok，让调用方拿真实值比对。
        """
        mons = monitors()
        mi = mons[min(monitor, max(0, len(mons) - 1))] if mons else None
        if mi:
            l, t, r, b = mi["work"]
        else:
            l, t, r, b = work_area()
        rect = wt.RECT()
        user32.GetWindowRect(wt.HWND(self.hwnd), ctypes.byref(rect))
        cw = width if width is not None else rect.right - rect.left
        ch = height if height is not None else rect.bottom - rect.top
        if "center" in anchor:
            x = l + max(0, (r - l - cw) // 2)
            y = t + max(0, (b - t - ch) // 2)
        else:
            x = r - cw - margin if "right" in anchor else l + margin
            y = t + margin if "top" in anchor else b - ch - margin
        x = max(l, min(x, r - cw - 4))
        y = max(t, min(y, b - ch - 4))
        flags = SWP_NOACTIVATE | (SWP_NOSIZE if keep_size else 0)
        ok = bool(user32.SetWindowPos(wt.HWND(self.hwnd), 0, int(x), int(y),
                                      int(cw), int(ch), flags))
        err = 0 if ok else ctypes.get_last_error()
        after = wt.RECT()
        read_ok = bool(user32.GetWindowRect(wt.HWND(self.hwnd), ctypes.byref(after)))
        out = {
            "x": int(after.left) if read_ok else int(x),
            "y": int(after.top) if read_ok else int(y),
            "w": int(after.right - after.left) if read_ok else int(cw),
            "h": int(after.bottom - after.top) if read_ok else int(ch),
            "ok": ok,
            "read_ok": read_ok,
            "requested": [int(cw), int(ch)],
            "monitor": mi["device"] if mi else None,
        }
        if not ok:
            out["err"] = err
        return out

    def rect(self) -> tuple[int, int, int, int]:
        r = wt.RECT()
        user32.GetWindowRect(wt.HWND(self.hwnd), ctypes.byref(r))
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))

    def move(self, x: int, y: int, width: int, height: int) -> dict:
        user32.SetWindowPos(wt.HWND(self.hwnd), 0, int(x), int(y), int(width), int(height),
                            SWP_NOACTIVATE)
        return {"x": int(x), "y": int(y), "w": int(width), "h": int(height)}

    def client_origin(self) -> tuple[int, int]:
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(wt.HWND(self.hwnd), ctypes.byref(pt))
        return int(pt.x), int(pt.y)

    def capture(self, path: Path) -> dict:
        """PrintWindow 优先；WebView2 常返回黑图，失败则回退屏幕 BitBlt。"""
        from PIL import Image

        rect = wt.RECT()
        user32.GetWindowRect(wt.HWND(self.hwnd), ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return {"ok": False, "reason": "窗口矩形为空", "w": w, "h": h}

        def grab(printwindow: bool):
            hdc = user32.GetDC(0)
            mdc = gdi32.CreateCompatibleDC(hdc)
            bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
            gdi32.SelectObject(mdc, bmp)
            if printwindow:
                ok = user32.PrintWindow(wt.HWND(self.hwnd), mdc, PW_RENDERFULLCONTENT)
            else:
                ok = gdi32.BitBlt(mdc, 0, 0, w, h, hdc, rect.left, rect.top, 0x00CC0020)
            class BIH(ctypes.Structure):
                _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                            ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                            ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                            ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                            ("biClrImportant", wt.DWORD)]
            bi = BIH()
            bi.biSize = ctypes.sizeof(BIH)
            bi.biWidth, bi.biHeight = w, -h
            bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
            buf = ctypes.create_string_buffer(w * h * 4)
            gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
            img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mdc)
            user32.ReleaseDC(0, hdc)
            return bool(ok), img

        # 分层窗口（整窗 alpha）用屏幕 BitBlt 会把后面的桌面一起拍进来；
        # 取证时先把 alpha 临时设 100%，PrintWindow 出图干净。BitBlt 仅兜底。
        ok, img = grab(True)
        method = "PrintWindow"
        extrema = img.convert("L").getextrema()
        if not ok or extrema[1] <= 4:
            ok2, img2 = grab(False)
            if ok2 and img2.convert("L").getextrema()[1] > 4:
                img, ok, method = img2, True, "BitBlt"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
        return {"ok": bool(ok), "method": method, "w": w, "h": h,
                "max_luma": img.convert("L").getextrema()[1], "path": str(path)}
