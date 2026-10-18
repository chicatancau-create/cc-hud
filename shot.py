# -*- coding: utf-8 -*-
"""三条版式的实拍取证(一次跑完): 收起 / 展开竖版 / 展开宽版, 外加一张关掉镂空的对照、
一张"全部"档宽版(用来拍到只在早期记过账的那几路)、一张今日档小时条形。
用 7 天范围拍 —— 今日只有 1 个点, 趋势卡画不出曲线, 拍出来看不出曲线有没有画坏。

取证走 PrintWindow 而不是桌面 BitBlt(PIL 的 ImageGrab):
  ① 桌面抓取在锁屏/安全桌面上会直接抛 "screen grab failed", 甚至挂住不返回;
  ② 桌面抓取会把**屏幕上另一个 HUD 实例**一起拍进来(上一轮就拍出过串影的"证据图")。
PrintWindow 只渲染本窗口, 键色镂空处回来的是键色本身 —— 所以另存一张 -hollow 关闭的对照。
跑之前先备份 hud-state.json: 这个脚本会改 range/版式并触发写盘。"""
import ctypes, ctypes.wintypes as wt, json, os, shutil, sys, tempfile
from importlib.machinery import SourceFileLoader
sys.path.insert(0, os.getcwd())
BAK = os.path.join(tempfile.gettempdir(), 'hud-state-before-shot.json')
STATE = os.path.join(os.getcwd(), 'hud-state.json')
shutil.copyfile(STATE, BAK)
m = SourceFileLoader('hud', 'cc-hud.pyw').load_module()
u32, gdi = ctypes.windll.user32, ctypes.windll.gdi32
m._dpi_aware()
h = m.HUD()
h.range_i = 1


class BI(ctypes.Structure):
    _fields_ = [('biSize', wt.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
                ('biPlanes', wt.WORD), ('biBitCount', wt.WORD), ('biCompression', wt.DWORD),
                ('biSizeImage', wt.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wt.DWORD),
                ('biClrImportant', wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BI), ('bmiColors', ctypes.c_ubyte * 12)]


def grab(name):
    from PIL import Image
    h.root.attributes('-topmost', True)
    h.root.update()
    hwnd = u32.GetAncestor(h.root.winfo_id(), 3)          # GA_ROOT
    rr = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(rr))
    w, hh = rr.right - rr.left, rr.bottom - rr.top
    hdc = u32.GetWindowDC(hwnd)
    mem = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, w, hh)
    old = gdi.SelectObject(mem, bmp)
    if not u32.PrintWindow(hwnd, mem, 2):                # 2 = PW_RENDERFULLCONTENT
        u32.PrintWindow(hwnd, mem, 0)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BI)
    bi.bmiHeader.biWidth, bi.bmiHeader.biHeight = w, -hh
    bi.bmiHeader.biPlanes, bi.bmiHeader.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * hh * 4)
    if not gdi.GetDIBits(mem, bmp, 0, hh, buf, ctypes.byref(bi), 0):
        raise SystemExit('GetDIBits 失败: %s' % ctypes.GetLastError())
    gdi.SelectObject(mem, old)
    for fn, arg in ((gdi.DeleteObject, bmp), (gdi.DeleteDC, mem), (u32.ReleaseDC, hdc)):
        fn(arg)
    Image.frombytes('RGBA', (w, hh), buf, 'raw', 'BGRA', 0, 1).save(name)
    print('%-20s %dx%d 于 (%d,%d) 镂空=%s' % (name, w, hh, rr.left, rr.top, bool(h._hollowed)))


def restore():
    """只回写本次测试改掉的键。以前是拿备份整份覆写, 会把这几秒里用户自己改的偏好
    (拖过的圆点位置、改过的透明度)一起抹掉 —— 现在按键位还原。
    peek 必须在列: 拍图时面板会跟着测试用的版式重算落位并写回状态文件, 漏还原就等于
    **把用户手拖过的圆点位置改掉了**(实测 2026-10-18 拍完从 2437,74 变成 2363,11)。
    hollow 同理: 拍"关掉镂空"那张对照时会切一次, 切回去靠的是配对调用, 不能赌它配平了。"""
    load = lambda p: (json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {})
    cur, orig = load(STATE), load(BAK)
    keys = ('range', 'exp', 'wide', 'peek', 'hollow')
    cur.update({k: orig[k] for k in keys if k in orig})
    with open(STATE, 'w', encoding='utf-8') as fh:
        json.dump(cur, fh, ensure_ascii=False)
    print('还原 %s · 其余键保持现状: %s' % ('/'.join(keys), sorted(cur)))


def cap():
    h.expanded = False
    h.refresh()
    h.root.update()
    grab('shot-collapsed.png')
    h._hollow()
    grab('shot-solid.png')                       # 关掉镂空: 对照圆角与阴影
    h._hollow()
    h.expanded = True
    h.wide = False
    h.refresh()
    h.root.update()
    grab('shot-expanded.png')
    h.wide = True
    h.refresh()
    h.root.update()
    grab('shot-wide.png')
    # 再拍一张"全部"档: WorkBuddy 国内版最后一笔账在 09-19, 7 天档里它是空的,
    # 用 7 天档那张图证明不了"两版横幅真的画出了值"(国外版 09-17~10-14 才落在 7 天内)。
    h.range_i = len(m.RANGES) - 1
    h.refresh()
    h.root.update()
    grab('shot-wide-all.png')
    # 今日档(只有 1 天 -> 画 24 根小时条形)也一起拍, 否则这张图会停在旧配色那一版
    h.range_i = 0
    h.refresh()
    h.root.update()
    grab('shot-today-bars.png')
    h.root.destroy()
    restore()


h.root.after(2500, cap)
h.run()
