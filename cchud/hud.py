# -*- coding: utf-8 -*-
"""cc-hud 主面板: 布局、绘制、刷新、交互。"""
import ctypes
import datetime as dt
import json
import os
import queue
import sqlite3
import threading
import time
from ctypes import wintypes as wt

import tkinter as tk
from tkinter import font as tkfont

from .const import *
from .util import *
from .render import *
from .power import *
from .data import *
from .sysw import *
from .pop import *

__all__ = [
    'HUD',
]


# ── 界面 ────────────────────────────────────────────────────────────────────
class HUD:
    def __init__(self):
        self.s = _scale()
        self.state = self._load()
        self.W = int(round(CARD_W * self.s))
        self._H = 1
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        # 置顶与透明度都先给默认值, 下面读回偏好后再覆盖 —— 以前这里是硬写 True/0.96,
        # 于是 pin:false 与 alpha:0.78 只存在于菜单的高亮里, 窗口其实没变过。
        self._pinned = True
        self.alpha = 0.96
        self.root.attributes('-topmost', self._pinned)
        self.root.attributes('-alpha', self.alpha)
        self.root.configure(bg=BG)
        self.expanded = bool(self.state.get('exp', False))
        self.wide = bool(self.state.get('wide', False))   # 展开态版式: False=竖版长条, True=宽版
        # 冷启动就要按"恢复出来的版式"算宽度: __init__ 早期 self.W 还是收起态的 530,
        # 直接拿它去 _corner() 会把右上角算到屏外, 随后 _clamp 只能把它钉在屏幕右沿
        # —— 于是"面板锚在圆点右上角"在开机自启这一条路上是破的(实测差 49px)。
        self.W = int(round((WIDE_W if (self.expanded and self.wide) else CARD_W) * self.s))
        self._built = None
        # 状态文件是用户可以手改的: 一个 range:9 会让 RANGES[9] 在第一次绘制时 IndexError,
        # 而这发生在装 _crash 之前 -> pythonw 没有 stderr, 表现为"双击没反应"。
        try:
            self.range_i = min(max(0, int(self.state.get('range', 1))), len(RANGES) - 1)
        except (TypeError, ValueError):
            self.range_i = 1
        self._drag = None
        self._pinned = bool(self.state.get('pin', True))
        self.root.attributes('-topmost', self._pinned)
        self._hollowed = False
        self.note = getattr(self, '_load_err', None)   # 状态文件读不了要在底栏说, 别静默回默认
        self._job = None
        self.follow = bool(self.state.get('follow', True))     # 跟随 CC Switch 显示/隐藏
        a = self.state.get('alpha', 0.96)
        self.alpha = a if a in ALPHAS else 0.96
        self.root.attributes('-alpha', self.alpha)
        self._cc_up = None
        self._shown = True
        self._last = 0.0
        self._n = 0
        self._data = None
        self._data_err = None
        self._read_lock = threading.Lock()
        self._read_busy = False
        self._read_result = None
        self._read_generation = 0
        self._read_stop = threading.Event()
        self.q = queue.Queue()
        self.tray = None
        self._pk = None
        self.pop = None
        self._tipw = None
        self._plot = None
        self.deadline = None
        self.power_kind = None
        self.fired = False
        self._pk_drag = None              # 圆点没收到 Press 就来了 Release 时, 这里先兜住
        try:                              # 武装过的定时要能跨重启活下来(见 _resume_power)
            self._pw = [self.state.get('dl'), self.state.get('pk'), bool(self.state.get('pf'))]
        except Exception:
            self._pw = None
        self._resume_power()
        self._plast = None
        s = self.s
        self.root.geometry('+%d+%d' % self._corner())
        self._req_w = self.W          # 这一版尺寸就是刚按 self.W 定位的, 后面改尺寸要拿它算右上角
        self._place_next = None       # 'center' = 这一次切换要把大面板放到屏幕正中 / 'corner' = 回到圆球那个角

        def F(px, fam='Microsoft YaHei UI', bold=False):
            return tkfont.Font(family=fam, size=-int(round(px * s)),
                               weight='bold' if bold else 'normal')
        # 参考图通篇一种无衬线, 标题和数值靠字重分层, 不是靠换字体
        self.f_hero = F(25, bold=True)
        self.f_num = F(13.5, bold=True)
        self.f_title = F(11.5, bold=True)
        self.f_micro = F(9)
        self.f_tiny = F(8.5)
        self.f_sm = F(11, 'Consolas')          # 表格里数字要按位对齐, 只有这里留等宽

        self.cv = tk.Canvas(self.root, width=self.W, height=int(round(300 * s)), bg=BG,
                            highlightthickness=0, bd=0)
        self.cv.pack(fill='both', expand=True)
        self.ids = {}
        self.imgs = {}
        self.pair = {}
        self.barh = {}
        self.barfill = {}
        self.barmat = {}
        self.zones = []
        self._missing = set()
        try:                                 # 状态文件里一个坏 pmin 会让 HUD 启动即崩
            self.pmin = max(PMIN_LO, min(PMIN_HI, int(self.state.get('pmin', 30))))
        except (TypeError, ValueError):
            self.pmin = 30

        self._bind()
        if self.state.get('hollow', True):     # 镂空: 卡片之间透出桌面, 卡片本身实心
            try:
                self.root.attributes('-transparentcolor', BG)
                self._hollowed = True
            except tk.TclError:
                pass
        try:                                   # 托盘: 卡片隐藏后唯一的找回入口
            self.tray = Tray(self.q)
        except Exception as e:
            self.note = '托盘挂不上: ' + str(e)[:22]
        self._cc_up = ccswitch_pid() is not None
        if not self._cc_up:                    # CC Switch 没在跑 -> 先藏着等它
            self._set_visible(False)
        if self.tray:
            self.tray.set(self._shown, self._tip())
        self.refresh()

    # ── 交互 ──
    def _bind(self):
        cv = self.cv
        cv.bind('<Button-1>', self._down)
        cv.bind('<B1-Motion>', self._move)
        cv.bind('<ButtonRelease-1>', self._up_pos)
        cv.bind('<Double-Button-1>', self._dbl)

        cv.bind('<Button-3>', lambda e: self.open_menu(e.x_root, e.y_root))
        cv.bind('<Motion>', self._hover)
        cv.bind('<Leave>', lambda e: self._tip_hide())
        # 刚映射上就把底栏抬回任务栏之上, 不等下一次 30s 刷新
        self.root.bind('<Map>', lambda e: self.root.after(80, self._clamp))
        # .pyw 没有 stderr, Tk 默认处理器等于把回调异常扔进黑洞(菜单/绘制里任何一次意外
        # 都会变成"它怎么不动了"却查不到)。挂上之后异常直接上底栏。
        self.root.report_callback_exception = self._crash

    def _crash(self, exc, val, tb):
        """Tk 回调里的异常出口: 默认处理器往 stderr 打印, 而 .pyw 的 stderr 没人看得见。"""
        try:
            self.note = '回调异常 %s: %s' % (exc.__name__, str(val)[:40])
            self.refresh(True)
        except Exception:
            pass

    def menu_spec(self):
        """菜单项在弹出这一刻现建, 状态天然就是当前值 —— 不需要事后同步条目文字。"""
        pid = ccswitch_pid()
        spec = [('hdr', '时间范围')]
        spec += [('radio', RANGES[i][0], i == self.range_i, lambda i=i: self.set_range(i))
                 for i in range(len(RANGES))]
        spec += [('sep',),
                 ('check', '展开明细  (或双击卡片)', self.expanded, self.toggle),
                 ('check', '宽版布局  (拉成横长条)', self.wide, self.set_wide),
                 ('cmd', '立即刷新', lambda: self.refresh(True)),
                 ('sep',), ('hdr', '不透明度')]
        spec += [('radio', '%d%%' % round(a * 100), abs(self.alpha - a) < .004,
                  lambda a=a: self.set_alpha(a)) for a in ALPHAS]
        spec += [('check', '背景镂空  (只透底色, 文字不淡)', self._hollowed, self._hollow),
                 ('cmd', '取消置顶' if self._pinned else '保持置顶', self._topmost),
                 ('sep',),
                 ('check', '跟随 CC Switch 启停', self.follow, self.set_follow),
                 ('info', ('CC Switch 运行中 · PID %d' % pid) if pid
                  else 'CC Switch 未运行 · 自动刷新已停(手动刷新仍会读库)')]
        spec += [('cmd', '立即隐藏  (圆点/托盘可再叫出)', self.hide_now)
                 if (self.follow and self._shown) else ('info', '立即隐藏  (已经是隐藏态)')]
        spec += [('sub', '定时操作', self.power_spec), ('sep',),
                 ('cmd', '复制对账数据 (JSON → 剪贴板)', self.copy_json),
                 ('cmd', '导出对账数据 (JSON → 文件)', self.export), ('sep',),
                 ('cmd', '退出  (不再跟随, 下次 CC Switch 启动才恢复)',
                  self.mark_quit_and_exit)]
        return spec

    def power_spec(self):
        """这一层全部是「连着点」的条目: 选延迟 → 选到点干什么 → 想反悔就地取消,
        所以武装/取消用 scmd(点完不关菜单), 只有点菜单外面才收。
        布局: 时长组和动作组之间不画分隔线(点完时间紧接着点动作, 本来就是同一件事);
        取消块前单独留一段空, 免得被当成一组误点。"""
        armed = bool(self.deadline or self.fired)
        spec = [('hdr', '延迟时长 · 当前 %d 分钟' % self.pmin)]
        spec += [('radio', lab, self.pmin == mins, lambda mins=mins: self.set_pmin(mins))
                 for mins, lab in PMINS]
        spec += [('scmd', '－ 5 分钟', lambda: self.set_pmin(self.pmin - 5)),
                 ('scmd', '＋ 5 分钟', lambda: self.set_pmin(self.pmin + 5))]
        spec += [('scmd', '到点' + lab, lambda k=kind: self.arm(k)) for kind, lab in POWERS]
        spec += [('sep',), ('gap',), ('info', self._power_line() if armed else '未设定时'),
                 ('scmd', '取消定时', self.cancel_power) if armed else ('info', '取消定时')]
        return spec

    def set_pmin(self, mins):
        self.pmin = max(PMIN_LO, min(PMIN_HI, int(mins)))
        self.state['pmin'] = self.pmin
        self._save()

    def open_menu(self, x, y):
        self._close_menu()
        self.pop = Pop(self, self.menu_spec, x, y)
        return self.pop

    def _close_menu(self):
        if getattr(self, 'pop', None) is not None:
            self.pop.close()
        self.pop = None

    def _down(self, e):
        self._zhit = False
        self._drag = None          # 命中可点区就不进入拖动; 残留的旧偏移会让 _up_pos 写错 peek
        for zx0, zy0, zx1, zy1, cb in self.zones:
            if zx0 <= e.x <= zx1 and zy0 <= e.y <= zy1:
                self._zhit = True
                cb()
                return
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _dbl(self, e):
        """双击卡片任意空白处 = 大小面板互切。落在可点区域(范围胶囊/展开按钮/关闭键)时,
        按下那一次已经执行过动作了, 这里不能再切一次 —— 否则双击「展开大面板」等于切两下,
        看着就是没反应。无论如何都 return 'break', 免得 Tk 把这次按下又交给 <Button-1>。"""
        if not getattr(self, '_zhit', False):
            self.toggle()
        return 'break'

    def _move(self, e):
        if self._drag:
            self.root.geometry('+%d+%d' % (e.x_root - self._drag[0], e.y_root - self._drag[1]))

    def _up_pos(self, e):
        """面板拖动结束: 把「圆点」挪到面板右上角, 两者共用同一个锚。
        圆点本来就是面板收起后留在屏上的那个角 —— 不同步的话收起后小卡会跑到别处去。
        位置按 _move 同一套算式从事件坐标推, 不读 winfo_x(): 刚 geometry() 完 winfo 还是旧值。"""
        dr = self._drag
        self._drag = None
        if dr is None or not self.root.winfo_ismapped():
            return
        l, t, r, b = _work_area(point=(e.x_root, e.y_root))
        d = int(round(PEEK * self.s))
        x = max(l, min(r - d, e.x_root - dr[0] + self.W - d))
        y = max(t, min(b - d, e.y_root - dr[1]))
        if list(self.state.get('peek') or []) != [x, y]:
            self.state['peek'] = [x, y]
            self._save()

    def _corner(self):
        """面板落点 = 圆点那个**右上角**(不是左上角 —— 那儿什么都没有)。
        圆点记的是它自己的左上角, 所以面板右上角 = 圆点左上角 + 圆点边长。"""
        s, d = self.s, int(round(PEEK * self.s))
        pv = self.state.get('peek')
        if isinstance(pv, (list, tuple)) and len(pv) == 2:
            l, t, r, b = _work_area(point=pv)
            ex, ey = int(pv[0]) + d, int(pv[1])
        else:                                   # 没记过 -> 默认右上角(与 _peek 的默认位同一套算式)
            l, t, r, b = _work_area(hwnd=self.root.winfo_id())
            ex, ey = r - int(round(28 * s)), t + int(round(36 * s))
        return max(l + 4, min(r - 4, ex) - self.W), max(t + 4, ey)

    def _topmost(self):
        self._pinned = not self._pinned
        self.root.attributes('-topmost', self._pinned)
        self.state['pin'] = self._pinned
        self._save()

    # ── 跟随 CC Switch ──
    def _peek(self, show):
        """隐藏后留在屏幕上的呼出点: 可拖动、位置记进 hud-state.json。
        不依赖托盘图标是否被 Windows 收进溢出菜单, 所以一定点得到。"""
        if not show:
            if self._pk is not None:
                self._pk.withdraw()
            return
        if self._pk is None:
            d = self._pk_d = int(round(PEEK * self.s))
            pk = self._pk = tk.Toplevel(self.root)
            pk.overrideredirect(True)
            pk.configure(bg=BG)
            pk.attributes('-topmost', True)
            pk.attributes('-alpha', 0.66)
            try:
                pk.attributes('-transparentcolor', BG)
            except tk.TclError:
                pass
            c = tk.Canvas(pk, width=d, height=d, bg=BG, highlightthickness=0, bd=0)
            c.pack()
            self._pk_c = c
            self._pk_item = c.create_image(d / 2.0, d / 2.0, tags='p',
                                           image=_glyph_img(d, 'peek', GR, chip=False, mat=BG, hard=True))
            c.bind('<ButtonPress-1>', self._pk_down)
            c.bind('<B1-Motion>', self._pk_move)
            c.bind('<ButtonRelease-1>', self._pk_up)
            c.bind('<Button-3>', lambda e: self.open_menu(e.x_root, e.y_root))
            c.bind('<Enter>', lambda e: pk.attributes('-alpha', 0.95))
            c.bind('<Leave>', lambda e: pk.attributes('-alpha', 0.66))
            pv = self.state.get('peek')           # (0,0) 也是合法坐标, 只能按"有没有这个键"判
            l, t, r, b = _work_area(point=pv if isinstance(pv, (list, tuple)) and len(pv) == 2 else None)
            if (isinstance(pv, (list, tuple)) and len(pv) == 2
                    and l <= pv[0] <= r - d and t <= pv[1] <= b - d):
                x, y = int(pv[0]), int(pv[1])
            else:                                 # 没记过/记的位置已不在屏内 -> 面板自己那个右上角
                x, y = r - d - int(round(28 * self.s)), int(round(36 * self.s))
            pk.geometry('+%d+%d' % (x, y))
        self._pk_color()
        self._pk.deiconify()

    def _pk_color(self):
        """绿 = CC Switch 在跑; 灰 = 它没跑(这时点出来也是空的, 得先启 CC Switch)。"""
        if self._pk is None:
            return
        col = GR if (self._cc_up or not self.follow) else FAINT
        img = _glyph_img(self._pk_d, 'peek', col, chip=False, mat=BG, hard=True)
        # 圆点是另一个 Toplevel, 位图却曾存在画布共用的 imgs 里 —— _layout() 每次
        # imgs.clear() 就把这张还挂在圆点上的图引用丢掉, ImageTk 一回收圆点就变空白
        # (bbox 也空, 点不到)。所以它单独持有, 不进 imgs。
        if getattr(self, '_pk_img', None) is not img:
            self._pk_c.itemconfig(self._pk_item, image=img)
            self._pk_img = img

    def _pk_down(self, e):
        self._pk_drag = (e.x_root - self._pk.winfo_x(), e.y_root - self._pk.winfo_y(),
                         e.x_root, e.y_root)

    def _pk_move(self, e):
        self._pk.geometry('+%d+%d' % (e.x_root - self._pk_drag[0], e.y_root - self._pk_drag[1]))

    def _pk_up(self, e):
        if not self._pk_drag:
            return
        ox, oy, sx, sy = self._pk_drag
        self._pk_drag = None
        if abs(e.x_root - sx) + abs(e.y_root - sy) > 5:      # 拖过 = 挪位置, 不当点击
            l, t, r, b = _work_area(hwnd=self._pk.winfo_id())
            x = max(l, min(r - self._pk_d, self._pk.winfo_x()))
            y = max(t, min(b - self._pk_d, self._pk.winfo_y()))
            self._pk.geometry('+%d+%d' % (x, y))
            self.state['peek'] = [x, y]
            self._save()
        else:
            self._set_visible(True)

    def _load(self):
        try:
            with open(STATE, encoding='utf-8-sig') as f:     # utf-8-sig: 带 BOM 也能读
                d = json.load(f)
            d = d if isinstance(d, dict) else {}
        except Exception as e:
            self._load_err = '状态文件读不了: ' + str(e)[:26]
            return {}
        # 状态文件是用户可以手改的。凡是会被 int()/索引/几何用上的键都在这里先验一遍 ——
        # pythonw 没有 stderr, 一个 peek:['a','b'] 会让 _corner() 抛 ValueError 崩在
        # __init__ 里, 表现就是"双击没反应"(verify T3 段实测)。
        pv = d.get('peek')
        ok2 = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
        if not (isinstance(pv, (list, tuple)) and len(pv) == 2 and all(ok2(v) for v in pv)):
            d.pop('peek', None)
        for k in ('dl',):
            if k in d and not ok2(d[k]):
                d.pop(k)
        if 'pk' in d and d['pk'] not in dict(POWERS):
            d.pop('pk', None)
        return d

    def _save(self):
        """先写 .tmp 再 os.replace: 同名覆盖在 Windows 上是原子的, 断电/被杀也不会留下半截
        JSON(以前直接 'w' 打开就已经把旧文件截断了)。"""
        try:
            tmp = '%s.%d.tmp' % (STATE, os.getpid())   # 固定名会被第二个写者咬掉一半
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())                   # 只 flush 的话断电能留下 0 字节
            os.replace(tmp, STATE)
        except OSError as e:
            self.note = '偏好没写进去: ' + str(e)[:22]  # 静默失败=每次重启都回到默认值

    def _tip(self):
        return 'CC Switch HUD · %s · %s' % ('显示中' if self._shown else '已隐藏',
                                            'CC Switch 运行中' if self._cc_up else 'CC Switch 未运行')

    def _set_visible(self, on):
        self._shown = on
        if on:
            self.root.geometry('+%d+%d' % self._corner())   # 从圆点那个角长出来, 不是回左上角
            self.root.deiconify()
            self.root.attributes('-topmost', self._pinned)
            self.root.lift()     # 取消置顶后 deiconify 可能落在别的窗口后面 = "点了圆球没显示"
            self.refresh(True)
        else:
            self.root.withdraw()
            self._tip_hide()
        self._peek(not on)
        if self.tray:
            self.tray.set(on, self._tip())

    def set_follow(self):
        self.follow = not self.follow
        self.state['follow'] = self.follow
        self._save()
        if self.follow:
            up = ccswitch_pid() is not None
            self._cc_up = up
            self._set_visible(up)
        else:
            self._set_visible(True)

    def hide_now(self):
        self._set_visible(False)

    def mark_quit_and_exit(self):
        self.mark_quit()
        self.quit()

    def mark_quit(self):
        """写下"当前这个 CC Switch 的 PID"。CC Switch 下次重启会换 PID, 标记自然失效。"""
        try:
            with open(QUIT_MARK, 'w', encoding='utf-8') as fh:
                fh.write(str(ccswitch_pid() or 0))
        except OSError:
            pass

    def quit(self):
        for j in (getattr(self, '_job', None),):
            try:
                if j:
                    self.root.after_cancel(j)
            except Exception:
                pass
        for p in list(getattr(self, 'pops', ())):        # 浮层(含子弹出层)一起收
            try:
                p.close()
            except Exception:
                pass
        try:
            if self.tray:
                self.tray.quit()                         # NIM_DELETE + DestroyIcon
        except Exception:
            pass
        self._read_stop.set()
        self.root.destroy()

    def _tray_event(self, ev):
        if ev == 'menu':
            pt = wt.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            self.open_menu(pt.x, pt.y)     # 托盘右键与卡片右键同一个菜单
        else:
            self._set_visible(not self._shown)

    def _hover(self, e):
        """鼠标停在趋势图上: 竖十字线钉到那一天 + 浮出当日读数。"""
        p = self._plot if (self.expanded and not self._drag) else None
        if not p:
            self._tip_hide()
            return
        days, x0, yt, step, H, pad, mt, mc = p
        # 条形是带状布局: 落在哪一格就是哪一小时, 不能四舍五入到柱心
        i = int((e.x - x0) / step) if step else 0
        if not getattr(self, '_barm', False):
            i = int(round((e.x - x0) / step)) if step else 0
        if not (0 <= i < len(days)) or not (yt - 6 <= e.y <= yt + H + 6):
            self._tip_hide()
            return
        r = days[i]
        px = x0 + (i + 0.5) * step if getattr(self, '_barm', False) else x0 + i * step
        py = yt + H - (r[8] / mt) * (H - pad)
        self.cv.coords(self.xhair, px, yt, px, yt + H)
        self.cv.itemconfig(self.xhair, state='normal')
        self.cv.coords(self.ids['chart.dot'], px, py)
        self.cv.itemconfig(self.ids['chart.dot'], state='normal')
        self._tip_show(e.x_root + 14, e.y_root + 18, chr(10).join((
            ('%s 这一小时 · 今日' % r[0]) if getattr(self, '_barm', False)
            else '%s · %s' % (r[0], RANGES[self.range_i][0]),
            '请求 %s · 成本 %s' % (f'{int(r[3]):,}', money(r[1])),
            '缓存命中 %s · 输入 %s' % (big(r[8]), big(r[5])),
            '输出 %s · 创建 %s' % (big(r[6]), big(r[7])))))

    def _tip_show(self, x, y, txt):
        if self._tipw is None:
            tw = self._tipw = tk.Toplevel(self.root)
            tw.overrideredirect(True)
            tw.attributes('-topmost', True)
            tw.attributes('-alpha', 0.97)
            tw.configure(bg=CARD, highlightthickness=1, highlightbackground=EDGE,
                         highlightcolor=EDGE)
            self._tip_lab = tk.Label(tw, bg=CARD, fg=FG, font=self.f_tiny, justify='left',
                                     padx=8, pady=6)
            self._tip_lab.pack()
        if self._tip_lab.cget('text') != txt:
            self._tip_lab.configure(text=txt)
        self._tipw.update_idletasks()
        l, t, r, b = _work_area(point=(x, y))
        w, hh = self._tipw.winfo_reqwidth(), self._tipw.winfo_reqheight()
        self._tipw.geometry('+%d+%d' % (max(l, min(x, r - w - 4)), max(t, min(y, b - hh - 4))))
        if not self._tipw.winfo_ismapped():
            self._tipw.deiconify()

    def _tip_hide(self):
        if self._tipw is not None and self._tipw.winfo_ismapped():
            self._tipw.withdraw()
        dot = self.ids.get('chart.dot')
        if dot is not None:                 # 收起态没有趋势图: 图元早被 delete('fg') 删掉了,
            self.cv.itemconfig(self.xhair, state='hidden')   # 再去 itemconfig 就是 KeyError
            self.cv.itemconfig(dot, state='hidden')

    def _persist_power(self):
        """把定时写进状态文件。以前 deadline/power_kind/fired 一个都不落盘, 于是
        武装完只要 HUD 重启(崩、注销、开机自启换实例), 定时就静默消失 —— 而系统那边
        可能已经挂着 shutdown /t 的倒计时, 菜单显示「未设定时」, 用户取消不了。"""
        self.state['dl'] = self.deadline
        self.state['pk'] = self.power_kind
        self.state['pf'] = bool(self.fired)
        self._save()

    def _resume_power(self):
        if not self._pw:
            return
        dl, pk, fired = self._pw
        self._pw = None
        if not pk:
            return
        if fired:
            if pk in ('off', 'reboot'):
                self.power_kind, self.fired = pk, True     # 系统倒计时还在跑, 撤销口留着
                self.note = '重启前已交给系统 · 菜单里可取消'
            return
        try:
            dl = float(dl)
        except (TypeError, ValueError):
            return
        if dl > time.time():
            self.deadline, self.power_kind = dl, pk
            self.note = '定时%s 已接着上次' % dict(POWERS)[pk]
        else:
            self.note = '定时%s 到点时 HUD 不在运行, 未执行' % dict(POWERS)[pk]

    def arm(self, kind):
        self.power_kind = kind
        self.deadline = time.time() + self.pmin * 60
        self.fired = False
        self._plast = None
        self.note = '已设定时' + dict(POWERS)[kind]
        self._persist_power()
        self.refresh(True)

    def cancel_power(self):
        if self.fired:                                      # 已经交给系统的 15s 倒计时也能撤
            if self.power_kind in ('off', 'reboot'):
                abort_power()
                self.note = '已撤销系统关机倒计时'
            else:
                self.note = '动作已执行, 无法撤销'
        elif self.deadline:
            self.note = '已取消定时'
        else:
            return
        self.deadline, self.power_kind, self.fired = None, None, False
        self._plast = None
        self._persist_power()
        self.refresh(True)

    def _power_line(self):
        if not self.deadline:
            return '定时%s 已交给系统 · 可取消' % dict(POWERS).get(self.power_kind, '')
        left = max(0, int(self.deadline - time.time()))
        return '定时%s 剩%02d:%02d · 右键取消' % (dict(POWERS)[self.power_kind], left // 60, left % 60)

    def _fire(self):
        kind = self.power_kind
        self.deadline = None
        if not run_power(kind):                     # 没权限/被策略禁用时别装作已经下发了
            self.power_kind, self.fired = None, False
            self.note = '电源动作下发失败: ' + str(POWERSD.get(kind, kind))
        else:
            self.fired = True
            if kind in ('off', 'reboot'):
                self.note = '%ds内可在菜单里取消' % GRACE
        self._persist_power()

    def _tick(self):
        try:
            # 后台线程只写结果；所有 Tk 访问在这个主线程心跳里完成。
            self._poll_read_result()
            tgl = menu = False
            while True:
                try:
                    ev = self.q.get_nowait()
                except queue.Empty:
                    break
                tgl |= ev == 'toggle'
                menu |= ev == 'menu'
            # 一次"点击"外壳会派发多个通知(左键 up + NIN_SELECT, 双击再来一层),
            # 逐个翻转会翻 3 次 = 看起来点了没反应, 右键还会把菜单弹两遍。
            if menu:
                self._tray_event('menu')
            elif tgl:
                self._tray_event('toggle')
            self._n += 1
            if self.follow and self._n % CC_TICKS == 0:
                up = ccswitch_pid() is not None
                if up != self._cc_up:
                    self._cc_up = up
                    if up:
                        self._set_visible(True)
                        if self.tray:
                            self.tray.set(self._shown, self._tip())
                    elif self.deadline or self.fired:
                        # 唯一不能跟着退的情形: 定时电源已武装或已交给系统。
                        # 退了就没有撤销口, 用户取消不了自己设的关机。
                        self._set_visible(False)
                        self.note = 'CC Switch 已退出 · 定时未清, 暂不跟随退出'
                        if self.tray:
                            self.tray.set(False, self._tip())
                    else:
                        self.quit()
                        return
            if self.deadline and time.time() >= self.deadline:
                self._fire()
            if self.deadline:
                ln = self._power_line()
                if ln != self._plast:                   # 秒数变了才写一次, 不每拍刷
                    self._plast = ln
                    self._put('foot.m', ln, PK if time.time() + 60 < self.deadline + 1 else '#ff6b6b')
            else:
                self._plast = None
            if self._shown and time.time() - self._last >= REFRESH_MS / 1000.0:
                self.refresh(background=True)
        except Exception as e:
            # 重挂必须无条件执行: 这条链一断, CC Switch 再怎么启停都没人接
            self.note = '心跳异常 ' + str(e)[:30]
        finally:
            self._job = self.root.after(POLL_MS, self._tick)

    def _hollow(self):
        """键色镂空: 只让 BG 底色的像素透明, 卡片与文字保持实心。"""
        want = BG if not self._hollowed else ''
        try:
            self.root.attributes('-transparentcolor', want)
        except tk.TclError:
            try:
                self.root.attributes('-transparentcolor', want or 'systemTransparent')
            except tk.TclError as e:
                self.note = '镂空不可用 ' + str(e)[:18]
                self.refresh()
                return
        self._hollowed = bool(want)
        self.state['hollow'] = self._hollowed
        self._save()
        self.refresh()

    def set_alpha(self, a):
        self.alpha = a
        self.root.attributes('-alpha', a)
        self.state['alpha'] = a
        self._save()

    def set_range(self, i):
        self.range_i = i
        self.state['range'] = i
        self._save()
        self.refresh(True)

    def toggle(self):
        self.expanded = not self.expanded
        # 小→大: 第一次展开必须落在屏幕正中(用户点名)。大→小: 回到圆球那个角, 沿左下扩展。
        # 只管"这一次切换" —— 之后用户怎么拖都不动它(拖动只靠 _clamp 保证不出屏)。
        self._place_next = 'center' if self.expanded else 'corner'
        self.state['exp'] = self.expanded
        self._save()
        self.refresh(True)

    def set_wide(self):
        """宽版(横长条)开关: 只影响展开态版式, 收起态那张小卡不动。"""
        self.wide = not self.wide
        self.state['wide'] = self.wide
        self._save()
        self.refresh(True)

    def export(self):
        try:
            p = os.path.join(ROOTDIR, 'ccswitch-对账数据.json')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(self._json())
            self.note = '已写出 ccswitch-对账数据.json'
        except Exception as e:
            self.note = '导出失败 ' + str(e)[:28]
        self.refresh(True)

    def _json(self):
        d = self._read(self._start())
        return json.dumps(_redact_export(d), ensure_ascii=False, indent=1, default=str)

    def copy_json(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._json())
            self.note = '对账 JSON 已进剪贴板'
        except Exception as e:
            self.note = '复制失败 ' + str(e)[:28]
        self.refresh(True)

    # ── 数据 ──
    def _start(self):
        days = RANGES[self.range_i][1]
        if not days:
            return 0
        return int(dt.datetime.combine(dt.date.today() - dt.timedelta(days=days - 1),
                                       dt.time.min).timestamp())

    def _read(self, start):
        db = sqlite3.connect('file:' + DB.replace(os.sep, '/') + '?mode=ro', uri=True)
        db.execute('pragma busy_timeout=1500')
        try:
            d = fetch(db, start)
        finally:
            db.close()
        merge_haha(d, fetch_haha(start))   # 第二路: 读不到就只是少并一路, 不影响原有口径
        merge_qoder(d, fetch_qoder(start))  # 第三路 Qoder: 只并请求数与 credits
        qcn = fetch_qoder(start, QDIR_CN, 'qoder-cn', 'Qoder CN')
        if qcn:                       # CN 版与国际版同一套壳: 也只有 credits, 走通用并入器
            for v in qcn['by_day'].values():
                v.update({'in': 0, 'out': 0, 'rd': 0, 'cc': 0})
            qcn.update({'app': 'qoder-cn', 'models': {}, 'note': '只有 credits 与响应数',
                        'in': 0, 'out': 0, 'rd': 0, 'cc': 0})
            merge_extra(d, qcn)
        for f in (lambda: fetch_zcode(start),
                  lambda: fetch_herdsman(start),
                  lambda: fetch_codex_gap(start, d.get('codex_sids') or set()),
                  # 第七、八路: WorkBuddy 国内版与国外版各自一本账
                  lambda: fetch_workbuddy(start, WB_SOURCES[0][0], WB_SOURCES[0][1],
                                          WB_SOURCES[0][2]),
                  lambda: fetch_workbuddy(start, WB_SOURCES[1][0], WB_SOURCES[1][1],
                                          WB_SOURCES[1][2])):
            try:
                merge_extra(d, f() or {})
            except Exception as e:
                d['extra_err'] = str(e)[:40]
        return d

    def _read_worker(self, start, generation):
        """后台读取只产生普通 Python 数据；Tk 对象只能由主线程绘制。"""
        try:
            result = (self._read(start), None)
        except Exception as e:
            result = (None, str(e))
        with self._read_lock:
            if generation == self._read_generation:
                self._read_result = result

    def _poll_read_result(self):
        with self._read_lock:
            result = self._read_result
            self._read_result = None
            if result is None:
                return
            self._read_busy = False
        self._data, self._data_err = result
        if self._shown:
            try:
                self.paint(self._data, self._data_err)
            except Exception as e:
                self.cv.delete('fatal')
                self.cv.create_text(int(round(8 * self.s)), int(round(8 * self.s)), anchor='nw', fill='#ff6b6b',
                                    font=self.f_tiny, text='绘制异常 ' + str(e)[:48], tags='fatal')

    def _start_background_read(self):
        with self._read_lock:
            if self._read_busy:
                return False
            self._read_busy = True
            self._read_generation += 1
            generation = self._read_generation
        t = threading.Thread(target=self._read_worker, args=(self._start(), generation),
                             name='cc-hud-data-read', daemon=True)
        t.start()
        return True

    def refresh(self, force=False, background=False):
        if not (self._shown or force):           # 隐藏期间不读库
            return
        self._last = time.time()
        # 首次绘制和用户明确要求的立即刷新保持同步，保证启动/菜单动作有即时结果。
        if self._data is None or force:
            with self._read_lock:
                self._read_generation += 1
                self._read_busy = False
                self._read_result = None
            try:
                self._data, self._data_err = self._read(self._start()), None
            except Exception as e:
                self._data, self._data_err = None, str(e)
            try:
                self.paint(self._data, self._data_err)
            except Exception as e:
                self.cv.delete('fatal')
                self.cv.create_text(int(round(8 * self.s)), int(round(8 * self.s)), anchor='nw', fill='#ff6b6b',
                                    font=self.f_tiny, text='绘制异常 ' + str(e)[:48], tags='fatal')
            return
        if background:
            self._start_background_read()
        else:
            with self._read_lock:
                self._read_generation += 1
                self._read_busy = False
                self._read_result = None
            try:
                self._data, self._data_err = self._read(self._start()), None
            except Exception as e:
                self._data, self._data_err = None, str(e)
        try:
            self.paint(self._data, self._data_err)
        except Exception as e:
            self.cv.delete('fatal')
            self.cv.create_text(int(round(8 * self.s)), int(round(8 * self.s)), anchor='nw', fill='#ff6b6b',
                                font=self.f_tiny, text='绘制异常 ' + str(e)[:48], tags='fatal')

    # ── 画布原语(全部就地更新) ──
    # Tk 的 polygon 不做抗锯齿, 圆角直接画就是锯齿 -> 静态壳一律 4x 超采样成图元再缩回。
    _SPR = {}

    def _sprite(self, w, h, r, fill, outline='', mat=CARD, hard=False):
        """圆角壳精灵。mat = 它**实际压在什么材质上**: 卡片内的压 CARD, 直接画在镂空区
        (键色 BG)上的必须传 mat=BG + hard=True —— 否则抗锯齿那一圈会被拍平成 CARD 那种
        深色, 既不等于键色也透不掉, 看着就像一圈投影(用户点名「就这一个东西像阴影」)。"""
        w, h = max(1, int(round(w))), max(1, int(round(h)))
        r = max(0, int(round(r)))
        k = (w, h, r, fill, outline, mat, hard)
        img = HUD._SPR.get(k)
        if img is None:
            from PIL import Image, ImageDraw, ImageTk
            K, lw = 4, max(1, int(round(self.s)))
            im = Image.new('RGBA', (w * K, h * K), (0, 0, 0, 0))
            ImageDraw.Draw(im).rounded_rectangle(
                [lw * K / 2.0, lw * K / 2.0, w * K - 1 - lw * K / 2.0, h * K - 1 - lw * K / 2.0],
                radius=r * K, fill=fill, outline=outline or None, width=lw * K)
            img = _bake(im, w, h, mat, hard=hard)
            HUD._SPR[k] = img
        return img

    def _panel(self, key, x, y, w, h, r, accent='', icon=None):
        """卡片底: 渐变 + 顶部淡辉光 + 图标烘在同一张图里。"""
        img = _panel_img(w, h, r, CARD, EDGE, max(2, int(round(1.1 * self.s * 4))), accent, icon)
        i = self.cv.create_image(int(round(x + w / 2.0)), int(round(y + h / 2.0)),
                                 image=img, tags='fg')
        self.ids[key] = i
        self.imgs[key] = img
        return i

    def _mat_at(self, y):
        """卡片内某个高度处的**真实底色** —— 与 _panel_img 的渐变(含强调色辉光)同源。

        精灵烘图时必须拿它当底材。原因: `_bake` 会把整张精灵矩形填成**不透明的 mat 色**,
        而卡面是"上深下亮"的渐变 —— 传死的 CARD, 就会在卡片下半部露出一块平色矩形,
        看上去像"一块灰影"。用户 2026-10-14 放大截图点名了「展开大面板」胶囊背后那块
        (该处卡面实测 (21,31,44), 而 CARD 只有 (16,19,29))。
        """
        cy, ch, acc = getattr(self, '_cur_card', (0.0, 0.0, ''))
        t = 0.0 if ch <= 1 else min(1.0, max(0.0, (y - cy) / float(ch - 1)))
        base = _mix(CARD, _mix(CARD, '#33405a', .55), .26 * t)      # 与 _panel_img 同一条渐变
        if acc:
            v = t * 255.0
            a = max(0.0, v * 3.2 - 255 * 2.2) * .055 / 255.0        # 与 _panel_img 同一道辉光
            if a > 0:
                base = _mix(base, acc, a)
        return base

    def _rr(self, key, x, y, w, h, r, fill, outline=''):
        img = self._sprite(w, h, r, fill, outline, self._mat_at(y + h / 2.0))
        i = self.cv.create_image(int(round(x + w / 2.0)), int(round(y + h / 2.0)),
                                 image=img, tags='fg')
        if key:
            self.ids[key] = i
            self.imgs[key] = img                    # 断引用 Tk 会回收图片, 必须自己持有
        return i

    def _rr2(self, key, x, y, w, h, r, off, on, mat=None, hard=False):
        """两态圆角壳(选中/未选中): 两张图预先烘好, 刷新只换图不新建图元。

        mat=None(默认) = 自动取该处卡片的真实底色; 直接画在镂空带上的必须显式传
        mat=BG + hard=True, 否则抗锯齿那一圈会被拍平成 CARD 深色, 看着像一圈投影。
        """
        if mat is None:
            mat = self._mat_at(y + h / 2.0)
        a = self._sprite(w, h, r, off[0], off[1], mat, hard)
        b = self._sprite(w, h, r, on[0], on[1], mat, hard)
        i = self.cv.create_image(int(round(x + w / 2.0)), int(round(y + h / 2.0)),
                                 image=a, tags='fg')
        if key:
            self.ids[key] = i
            self.imgs[key] = a
            self.pair[key] = (a, b)
        return i

    def _put_img(self, key, on):
        i = self.ids.get(key)
        if i is None:
            self._missing.add(key)
            return
        img = self.pair[key][1 if on else 0]
        if self.imgs.get(key) is not img:
            self.cv.itemconfig(i, image=img)
            self.imgs[key] = img

    def _t(self, key, x, y, text, fill, font, anchor='w'):
        i = self.cv.create_text(int(round(x)), int(round(y)), anchor=anchor, text=text,
                                fill=fill, font=font, tags='fg')
        if key:
            self.ids[key] = i
        return i

    def _put(self, key, text=None, fill=None, outline=None):
        i = self.ids.get(key)
        if i is None:
            # 槽位没登记时 Tk 不报错, 数值会静默不更新 -> 记下来给自检用
            self._missing.add(key)
            return
        if text is not None and self.cv.itemcget(i, 'text') != text:
            self.cv.itemconfig(i, text=text)
        if fill is not None and self.cv.itemcget(i, 'fill') != fill:
            self.cv.itemconfig(i, fill=fill)
        if outline is not None and self.cv.itemcget(i, 'outline') != outline:
            self.cv.itemconfig(i, outline=outline)

    _set = _put

    def _rect(self, key, x, y, w, h, fill=None):
        i = self.ids.get(key)
        if i is None:
            return
        self.cv.coords(i, int(round(x)), int(round(y)), int(round(x + w)), int(round(y + h)))
        if fill is not None:
            self._put(key, fill=fill)

    def _bar(self, key, x, y, w, h, fill=None):
        """圆角进度条 —— 4x 超采样位图, 与曲线/卡片同一套做法。

        以前是 Tk 的 rectangle + 两端 oval 拼的: **oval 不做抗锯齿**, 填充条左端圆头是
        一排锯齿台阶(用户 2026-10-14 放大截图点名)。现在整条交给 PIL:
          · 左端圆角与暗槽同半径 -> 边界平滑;
          · 右端直角 -> 被 knob 盖住, 不会在槽上戳缺口;
          · 底材 = 该处卡片的真实底色 -> 条外与卡面严丝合缝。
        """
        h = max(1, int(round(h)))
        w = max(0, int(round(w)))
        if fill is not None:
            self.barfill[key] = fill
        col = self.barfill.get(key, GR)
        self.barh[key] = h
        # 底材只在**布局期**算一次并缓存: paint 里每次刷新都会调 _bar, 那时 _cur_card 已经
        # 是最后建的那张卡了, 现算会取错底色。
        mat = self.barmat.get(key)
        if mat is None:
            mat = self.barmat[key] = self._mat_at(y + h / 2.0)
        img = _bar_img(w, h, col, mat)
        i = self.ids.get(key)
        if i is None:
            i = self.cv.create_image(0, 0, image=img, tags='fg')
            self.ids[key] = i
        elif self.imgs.get(key) is not img:
            self.cv.itemconfig(i, image=img)
        self.imgs[key] = img                 # 断引用 Tk 会回收图片, 必须自己持有
        self.cv.coords(i, int(round(x + w / 2.0)), int(round(y + h / 2.0)))

    def _cardw(self, key):
        """某张卡的内容宽; 收起态/竖版没登记时退回当前 self.cw(那时它就是整宽卡, 正确)。"""
        return getattr(self, 'cardw', {}).get(key, self.cw)

    def _fit(self, text, font, px):
        if font.measure(text) <= px:
            return text
        while text and font.measure(text + '…') > px:
            text = text[:-1]
        return (text[:-1] + '…') if text else ''

    def _fitkv(self, label, pairs, font, px):
        """整行超宽时改成「每个值各自截断」。整行交给 _fit 会把行尾那几个应用整个吃掉
        —— 竖版「当前 …」那行就是这么把 gemini 变没的, 而"少显示一个应用"用户点过名。"""
        if not pairs:
            return label
        sep = ' · '
        per = (px - font.measure(label + sep * (len(pairs) - 1))) // len(pairs)
        out = []
        for k, v in pairs:
            t = '%s=%s' % (k, v)
            if font.measure(t) > per:
                t = self._fit(t, font, per) or (t[:6] + '…')
            out.append(t)
        return label + sep.join(out)

    def _zone(self, x, y, w, h, cb):
        self.zones.append((x, y, x + w, y + h, cb))

    # ── 卡片骨架 ──
    def _card(self, key, y, h, color, icon, title, vkey=None, vcol=None, vfont=None,
              x=None, w=None):
        """x/w 不传 = 整宽(竖版)。宽版按列摆放时传进来, 卡内一切坐标都跟着 self.cx/cw 走。"""
        s = self.s
        # 登记"当前卡片"的几何与强调色: 卡内精灵烘图时要按这个算真实底色(见 _mat_at)
        self._cur_card = (float(y), float(h), color)
        if x is None:
            x = int(round(PAD * s))
        if w is None:
            w = self.W - 2 * int(round(PAD * s))
        self.cx = x + int(round(11 * s))
        self.cw = w - 2 * int(round(11 * s))
        # 宽版按列建卡, 建完最后一张(全宽横幅)后 self.cw 就是 1890 —— paint 里所有 _fit 预算
        # 若直接用 self.cw 会放大 4 倍, 长供应商名/模型名会压过右列(实测越界 157px)。
        # 所以建卡时把每张卡自己的内容宽记下来, 截断按卡取。
        self.cardw[key] = self.cw
        ib = int(round(18 * s))
        # 图标烘在卡片自己的位图上, 必须给局部坐标; 之前传的是画布绝对坐标,
        # 结果图标全画到卡片位图外面去了 —— 这就是"左边图标不见了"的原因
        lx, ly = int(round(11 * s)), int(round(10 * s))
        ix, iy = x + lx, y + ly
        self._panel(key + '.bg', x, y, w, h, int(round(11 * s)), accent=color,
                    icon=(icon, color, lx, ly, ib))
        tx = ix + ib + int(round(8 * s))
        self._t(key + '.ti', tx, y + int(round(10 * s)) + int(round(9 * s)), title, FG, self.f_title)
        if vkey:
            self._t(vkey, tx + self.f_title.measure(title) + int(round(10 * s)),
                    y + int(round(10 * s)) + int(round(9 * s)), '', vcol, vfont or self.f_num,
                    'w')
        self._t(key + '.rt', x + w - int(round(11 * s)), y + int(round(10 * s)) + int(round(9 * s)), '', DIM, self.f_tiny, 'e')
        # 标题行与数据区之间一条发丝线: 之前标题飘在上、数字飘在下, 没有结构关系
        self.cv.create_line(self.cx, y + int(round(33 * s)),
                            self.cx + self.cw, y + int(round(33 * s)),
                            fill=EDGE, tags='fg')
        return x, y, w

    # ── 布局: 只在展开/收起切换时重建一次 ──
    ROWS = (('c1', 'c2', 'prov', 'c3'),      # 第一排 = 最常看的: 命中率 / 请求与成本 / 应用与供应商 / Token构成
            ('model', 'c4', 'c7', 'c8'))     # 第二排 = 次要的: 模型 / 延迟 / 24小时 / 代理与配置

    def _layout_cols(self, y):
        """宽版 = 趋势图一整行 + 两排卡片 + cc-haha 横幅一整行, 两条硬规则:
        ① 间隙统一: 除「曲线图与下面那排」之间用极小间隙(2 逻辑px)外, 所有模块间隙一律 8 逻辑px;
        ② 每排卡片等高: 行高取该排最高的那张, 短的把**外壳拉长、内容垂直居中** —— 于是每一排
           都是齐的整块, 整个面板是一个矩形, 不会再出现"空隙留给谁看"的那种洞。
        排序权重: 趋势图(体积最大) → 第一排(核心数) → 第二排(明细/配置) → 第三排(第二数据源)。"""
        s = self.s
        G = int(round(8 * s))
        Gt = int(round(2 * s))
        pw = self.W - 2 * int(round(PAD * s))
        x0 = int(round(PAD * s))
        fn = {'c1': self._c1, 'c2': self._c2, 'c3': self._c3, 'c4': self._c4, 'c6': self._c6,
              'c7': self._c7, 'c8': self._c8, 'prov': self._prov, 'model': self._model,
              'haha': self._haha, 'qoder': self._qoder, 'wb': self._wb}
        self._gap = 0                             # 纵向推进由本函数负责, 卡片不再各自加间隙
        y = fn['c6'](y, x0, pw) + Gt              # 趋势图: 全宽一整行
        n = len(self.ROWS[0])
        colw = (pw - (n - 1) * G) // n
        for row in self.ROWS:
            minh = max(int(round(self._hgt(k) * s)) for k in row)
            for i, k in enumerate(row):
                fn[k](y, x0 + i * (colw + G), colw, minh)
            y += minh + G
        y = fn['haha'](y, x0, pw) + G             # 倒数第三行: 全宽横幅(cc-haha 直连会话)
        y = fn['qoder'](y, x0, pw) + G            # 倒数第二行: 全宽横幅(Qoder, 不走代理)
        y = fn['wb'](y, x0, pw) + G               # 最后一行: 全宽横幅(WorkBuddy 国内+国外)
        return y

    def _c1(self, y, x=None, w=None, minh=None):
        """1 缓存命中率 —— 竖版大面板保持原样(用户明确说大面板不要动); x/w 供宽版按列复用。
        minh = 行高: 宽版一行里卡片必须等高, 外壳拉长到 minh, 内容整体垂直居中
        (否则就是在卡片里挖一个大洞, 用户点名过「这么大个空隙留给谁看」)。"""
        s = self.s
        hh = int(round(66 * s))
        H = max(hh, minh or 0)
        self._card('c1', y, H, GR, 'ring', '缓存命中率',
                   vkey='c1.val', vcol=GR, vfont=self.f_hero, x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        self.track_x = self.cx
        self.track_w = self.cw
        self.track_h = int(round(7 * s))
        self.track_y = y + int(round(48 * s))
        self._rr('c1.track', self.track_x, self.track_y, self.track_w, self.track_h,
                 int(round(3.5 * s)), EDGE)          # 暗槽必须用 EDGE: TRACK 压在 CARD 上看不见
        self._bar('c1.fill', self.track_x, self.track_y, self.track_h,
                  self.track_h, GR)
        self.knob_px = int(round(15 * s))
        self.imgs['c1.knob'] = _glyph_img(self.knob_px, 'knob', GR)
        self.ids['c1.knob'] = self.cv.create_image(0, 0, image=self.imgs['c1.knob'], tags='fg')
        return yb + self._gap

    def _c2(self, y, x=None, w=None, minh=None):
        """2 请求与成本 —— 整宽四数。"""
        s = self.s
        hh = int(round(84 * s))
        H = max(hh, minh or 0)
        self._card('c2', y, H, CY, 'coin', '请求与成本', x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        for i, (k, lab, c) in enumerate((('a', '总请求数', FG), ('b', '总成本', VI),
                                         ('c', '今日', TE), ('d', '近1小时', AM))):
            xx = self.cx + int(self.cw / 4 * i)
            self._t('c2.%sl' % k, xx, y + int(round(CARD_LBL_DY * s)), lab, FAINT, self.f_micro)
            self._t('c2.%s' % k, xx, y + int(round(CARD_VAL_DY * s)), '', c, self.f_num)
        return yb + self._gap

    def _layout(self):
        # 宽版只在展开时生效; 收起态永远是那一整张小卡
        self._widem = bool(self.expanded and self.wide)   # 宽版只在展开时生效; 收起态那张小卡不动
        self.W = int(round((WIDE_W if self._widem else CARD_W) * self.s))
        self._gap = int(round(8 * self.s))            # 卡间隙: 宽版会临时改成"摊过余量"的值
        self._c6h = 208 if self._widem else 164       # 趋势卡高度(逻辑px)
        cv, W, s = self.cv, self.W, self.s
        cv.delete('fg')
        self.ids.clear()
        self.cardw = {}               # 每张卡的内容宽(宽版按列, 见 _card)
        self._plot = None                   # 版式一变旧的绘图矩形就作废, 否则悬停会算到不存在的图上
        self.imgs.clear()
        self.pair.clear()
        self.barh.clear()
        self.barfill = {}             # 进度条当前颜色(按槽位记), 换色才重建位图
        self.barmat = {}              # 进度条底材(布局期按所在卡片算一次)
        self.zones.clear()
        px, pw = int(round(PAD * s)), W - 2 * int(round(PAD * s))
        y = int(round(12 * s))
        # 标题卡片: 标题行 + 范围胶囊行包进实心卡(镂空时不会被一起透掉)。展开态就这两行的头;
        # 收起态整张面板只有这一张卡, 所以它要按 _head_h 长到能装下正文。
        self._head_h = 62 if self.expanded else 224
        self._panel('head.bg', px, y, pw, int(round(self._head_h * s)),
                    int(round(11 * s)), accent=CY)
        # 头卡也是一个"卡片": 卡内精灵(logo/范围胶囊/进度槽/底栏胶囊)按它的渐变算真实底色
        self._cur_card = (float(y), float(int(round(self._head_h * s))), CY)
        hy = y + int(round(9 * s))

        self._rr('logo', px + int(round(11 * s)), hy, int(round(20 * s)), int(round(20 * s)),
                 int(round(6 * s)), _mix(CARD, CY, .16), _mix(CARD, CY, .42))
        self._t('logo.t', px + int(round(21 * s)), hy + int(round(10 * s)), 'CC', CY, self.f_tiny,
                'center')
        self._t('title', px + int(round(37 * s)), hy + int(round(10 * s)), 'CC Switch', FG,
                self.f_title)
        self._t('cur', px + int(round(37 * s)) + self.f_title.measure('CC Switch') + int(round(7 * s)),
                hy + int(round(10 * s)), '', DIM, self.f_micro)
        # 右上角只留一个按钮: 隐藏(等 CC Switch 下次启动)。展开/收起归底栏那一枚胶囊, 不重复
        bw = int(round(22 * s))
        self._rr2('btn.bg', px + pw - int(round(11 * s)) - bw, hy - int(round(1 * s)), bw,
                  int(round(22 * s)), int(round(6 * s)),
                  (_mix(CARD, TE, .1), EDGE), (_mix(CARD, PK, .2), _mix(EDGE, PK, .55)))
        gi = _glyph_img(int(round(16 * s)), 'minus', TE, chip=False)
        self.imgs['btn'] = gi
        self.ids['btn'] = cv.create_image(px + pw - int(round(11 * s)) - bw / 2.0,
                                         hy + int(round(10 * s)), image=gi, tags='fg')
        self._zone(px + pw - int(round(11 * s)) - bw, hy - int(round(1 * s)), bw,
                   int(round(22 * s)), self.hide_now)
        self._t('clock', px + pw - int(round(40 * s)), hy + int(round(10 * s)), '', FAINT,
                self.f_tiny, 'e')
        self.sk_x1 = px + pw - int(round(84 * s))
        self.sk_w = int(round(66 * s))
        self.sk_h = int(round(18 * s))
        self.sk_y = hy + int(round(10 * s))
        si = _spark_img(self.sk_w, self.sk_h, [], s)
        self.imgs['spark'] = si
        self.ids['spark'] = cv.create_image(self.sk_x1 - self.sk_w / 2.0, self.sk_y,
                                            image=si, tags='fg')
        self._spark_sig = None

        chw = ((pw if not self._widem else min(pw, int(round(CHIP_BLOCK_W * s))))
               - int(round(22 * s)) - int(round(6 * s)) * 3) / 4

        for i, (name, _) in enumerate(RANGES):
            x = px + int(round(11 * s)) + int(round(i * (chw + 6 * s)))
            self._rr2('chip%d' % i, x, y + int(round(34 * s)), chw, int(round(21 * s)),
                      int(round(6 * s)), (CARD, EDGE), (_mix(CARD, IN, .22), _mix(EDGE, IN, .8)))
            self._t('chipt%d' % i, x + chw / 2, y + int(round(44.5 * s)), name, DIM, self.f_micro,
                    'center')
            self._zone(x, y + int(round(34 * s)), chw, int(round(21 * s)),
                       lambda i=i: self.set_range(i))
        if self.expanded:
            if self.wide:
                y += int(round(62 * s)) + int(round(8 * s))   # c1/c2 交给 _layout_cols 按列画
            else:
                y = self._c1(y + int(round(62 * s)) + int(round(8 * s)))
                y = self._c2(y)
        else:
            # 收起态 = 字面意义的一个模块: 标题行/范围胶囊/命中率+进度条/成本三数/
            # Token成本构成条/按应用/底栏 全在同一张卡里(head.bg 按 _head_h 画好)。
            # 槽位名与大面板共用 c1.*/c2.*/c3.*/cin... 所以 paint 不用分状态。
            # 用户 2026-10-08 晚点名三件事: ① 进度条只看得见亮的填充, 暗槽 TRACK 压在 CARD
            # 上等于没有 -> 换 EDGE; ② 「总请求次数」在小卡上没必要 -> 拿掉(展开态保留);
            # ③ 东西太少太素 -> 把大面板那条四色成本构成条连同分项搬进来。
            y += int(round(62 * s))
            self.cx = px + int(round(11 * s))
            self.cw = pw - 2 * int(round(11 * s))
            bh = self.track_h = int(round(7 * s))
            self._t('c1.val', self.cx, y + int(round(20 * s)), '', GR, self.f_hero)
            # 预留宽度按**实际量出来的大数字**算, 不是拍脑袋的 82: 命中率到 100.0% 时
            # f_hero 要 114px, 写死 82 会让数字直接压在进度条上
            self.track_x = self.cx + max(int(round(82 * s)),
                                         int(self.f_hero.measure('100.0%')) + int(round(10 * s)))
            self.track_w = int(round(104 * s))
            self.track_y = y + int(round(16 * s))
            self._rr('c1.track', self.track_x, self.track_y, self.track_w, bh,
                     int(round(3.5 * s)), EDGE)
            self._bar('c1.fill', self.track_x, self.track_y, bh, bh, GR)
            self.knob_px = int(round(15 * s))
            self.imgs['c1.knob'] = _glyph_img(self.knob_px, 'knob', GR)
            self.ids['c1.knob'] = cv.create_image(0, 0, image=self.imgs['c1.knob'], tags='fg')
            self._t('c1.rt', self.cx + self.cw, y + int(round(20 * s)), '', DIM,
                    self.f_tiny, 'e')
            for i, (k, lab, c) in enumerate((('b', '总成本', VI), ('c', '今日', TE),
                                             ('d', '近1小时', AM))):
                xx = self.cx + int(self.cw / 3 * i)
                self._t('c2.%sl' % k, xx, y + int(round(44 * s)), lab, FAINT, self.f_micro)
                self._t('c2.%s' % k, xx, y + int(round(62 * s)), '', c, self.f_num)
            self._t('c3.lb', self.cx, y + int(round(82 * s)), 'Token 成本构成', FAINT,
                    self.f_micro)
            self._t('c3.rt', self.cx + self.cw, y + int(round(82 * s)), '', DIM,
                    self.f_micro, 'e')
            self._rr('c5.bg', self.cx, y + int(round(90 * s)), self.cw, bh,
                     int(round(3.5 * s)), EDGE)
            self.cbar = (self.cx, y + int(round(90 * s)), self.cw, bh)
            for k, c in (('cin', CH_IN), ('cout', CH_OUT), ('crd', CH_RD), ('cwr', CH_CW)):
                self.ids[k] = cv.create_rectangle(self.cx, y + int(round(90 * s)), self.cx + 2,
                                                  y + int(round(90 * s)) + bh, fill=c,
                                                  outline='', tags='fg')
            for i, (k, lab, c) in enumerate((('cin', '输入', CH_IN), ('cout', '输出', CH_OUT),
                                             ('crd', '命中', CH_RD), ('cwr', '创建', CH_CW))):
                self._t(k + '.lt', self.cx + int(self.cw / 4 * i), y + int(round(106 * s)),
                        lab, c, self.f_tiny)
            self._t('c2.rt', self.cx, y + int(round(124 * s)), '', DIM, self.f_tiny)
            y += int(round(136 * s))          # 到本卡内的底栏起点(foot.pbg 用 y+4)

        if self.expanded:
            y = self._layout_cols(y) if self.wide else self._layout_detail(y)
        else:
            self.cells = None

        # 底栏: 左=数据新鲜度/定时倒计时, 右=唯一的展开胶囊。跟随开关只在右键菜单里, 不重复
        pbw, pbh = int(round(64 * s)), int(round(18 * s))
        pbx = px + pw - int(round(9 * s)) - pbw
        # 展开态胶囊在卡片之间的镂空带上 -> 必须 mat=BG + 二值剪影, 否则露出一圈"投影";
        # 收起态胶囊在 head.bg **里面** -> 用普通 CARD 底材, 否则会烘出一圈 BG 接缝
        self._rr2('foot.pbg', pbx, y + int(round(4 * s)), pbw, pbh, int(round(6 * s)),
                  (_mix(CARD, CY, .13), _mix(EDGE, CY, .5)),
                  (_mix(CARD, VI, .16), _mix(EDGE, VI, .55)),
                  BG if self.expanded else None, self.expanded)
        self._t('foot.r', pbx + pbw / 2.0, y + int(round(13 * s)), '展开大面板', CY, self.f_tiny,
                'center')
        self._zone(pbx, y + int(round(4 * s)), pbw, pbh, self.toggle)
        self.mid_x = px + int(round(9 * s))
        self.mid_w = pbx - int(round(10 * s)) - self.mid_x
        self._t('foot.m', self.mid_x, y + int(round(13 * s)), '', GR, self.f_tiny)
        self._H = y + int(round(26 * s)) + int(round(9 * s))
        self._built = (self.expanded, self.wide)   # 版式指纹: 展开/收起 + 宽窄, 任一变了都要重建
                                                     # (不能用 self.W: 它是在 _layout 里才更新的)

    def _cr(self, pts, k=8):
        return _cr(pts, k)

    def _layout_detail(self, y, x=None, w=None):
        """明细区: 每张卡一个 _cX 方法, 画完往下走 self._gap(默认 8 逻辑px)。
        竖版按固定顺序整宽画; 宽版由 _layout_cols 按行调, 等高靠 minh 拉伸外壳实现
        (早先靠改 self._gap 摊余量的做法已废弃 —— 那会在带子里挖出大洞)。"""
        for fn in (self._c3, self._c4, self._c6, self._c7, self._prov, self._model, self._c8):
            y = fn(y, x, w)
        return y

    def _c3(self, y, x=None, w=None, minh=None):
        s, cv = self.s, self.cv
        # 3 Token 明细 + 成本构成条 —— 小面板放不下, 归大面板
        hh = int(round(103 * s))
        H = max(hh, minh or 0)
        self._card('c3', y, H, VI, 'grid', 'Token与成本构成', x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        tw = self.cw / 5
        for i, (k, lab, c) in enumerate((('real', '真实消耗', MA), ('fin', '新增输入', CY),
                                         ('out', '输出', TE), ('cre', '缓存创建', AM),
                                         ('rd', '缓存命中', GR))):
            xx = self.cx + int(tw * i)
            self._t(k + '.l', xx, y + int(round(CARD_LBL_DY * s)), lab, FAINT, self.f_micro)
            self._t(k + '.v', xx, y + int(round(CARD_VAL_DY * s)), '', c, self.f_num)
        self._rr('c5.bg', self.cx, y + int(round(71 * s)), self.cw, int(round(7 * s)),
                 int(round(3.5 * s)), EDGE)
        self.cbar = (self.cx, y + int(round(71 * s)), self.cw, int(round(7 * s)))
        for k, c in (('cin', CH_IN), ('cout', CH_OUT), ('crd', CH_RD), ('cwr', CH_CW)):
            self.ids[k] = cv.create_rectangle(self.cx, y + int(round(71 * s)), self.cx + 2,
                                              y + int(round(78 * s)), fill=c, outline='', tags='fg')
        for i, (k, lab) in enumerate((('cin', '输入'), ('cout', '输出'), ('crd', '命中'),
                                      ('cwr', '创建'))):
            self._t(k + '.lt', self.cx + int(self.cw / 4 * i), y + int(round(86 * s)), lab,
                    MUTED, self.f_tiny)
        return yb + self._gap

    def _c4(self, y, x=None, w=None, minh=None):
        s = self.s
        # 4 延迟实测
        hh = int(round(95 * s))
        H = max(hh, minh or 0)
        self._card('c4', y, H, AM, 'clock', '延迟实测', x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        for i, (k, lab, c) in enumerate((('ftt', '首TOKEN', TE), ('sp', '生成TOK/S', CY),
                                         ('lat', '请求耗时', VI))):
            xx = self.cx + int(self.cw / 3 * i)
            self._t(k + '.l', xx, y + int(round(CARD_LBL_DY * s)), lab, FAINT, self.f_micro)
            self._t(k + '.v', xx, y + int(round(CARD_VAL_DY * s)), '—', c, self.f_num)
        self._t('c4.note', self.cx, y + int(round(77 * s)), '', MUTED, self.f_tiny)
        return yb + self._gap

    def _c6(self, y, x=None, w=None, minh=None):
        s, cv = self.s, self.cv
        h = self._c6h                                   # 宽版整宽放大, 竖版保持 164 不变
        hh = int(round(h * s))
        H = max(hh, minh or 0)
        # 5 使用趋势 —— 照 CC Switch 原版画法: 过点平滑曲线 + 贴曲线的渐变面积 +
        #   虚线成本走右轴 + 横向网格 + 双轴刻度 + 底部图例
        self._card('c6', y, H, CH_RD, 'wave', '使用趋势', x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        self.plot_x0, self.plot_x1 = self.cx, self.cx + self.cw
        self.plot_top = y + int(round(46 * s))
        self.plot_h = int(round((h - 86) * s))
        self.plot_yb = self.plot_top + self.plot_h
        self.grid, self.axl, self.axr = [], [], []
        for i in range(4):
            gy = self.plot_top + int(self.plot_h * i / 3.0)
            self.grid.append(cv.create_line(self.plot_x0, gy, self.plot_x1, gy,
                                            fill=_mix(CARD, EDGE, .55), dash=(2, 3), tags='fg'))
            # 刻度写在网格线下方, 才不会压住卡片标题行
            self.axl.append(self._t(None, self.plot_x0, gy + int(round(6 * s)), '', MUTED,
                                    self.f_tiny))
            self.axr.append(self._t(None, self.plot_x1, gy + int(round(6 * s)), '', MUTED,
                                    self.f_tiny, 'e'))
        # 数据层整块交给 PIL: 真渐变面积 + 抗锯齿折线, Tk 的 line/polygon 都不做 AA
        self.plot_w, self.plot_h2 = self.plot_x1 - self.plot_x0, self.plot_h
        ci = _chart_img(self.plot_w, self.plot_h2, [], [], [], s)
        self.imgs['chart'] = ci
        self.ids['chart'] = cv.create_image((self.plot_x0 + self.plot_x1) / 2.0,
                                            (self.plot_top + self.plot_yb) / 2.0,
                                            image=ci, tags='fg')
        self.xhair = cv.create_line(0, self.plot_top, 0, self.plot_yb, fill=DIM, dash=(2, 2),
                                    width=max(1, int(round(self.s))), tags='fg', state='hidden')
        self.imgs['chart.dot'] = _glyph_img(int(round(8 * s)), 'cdot', CH_RD)
        self.ids['chart.dot'] = cv.create_image(0, 0, image=self.imgs['chart.dot'],
                                                tags='fg', state='hidden')
        # 峰值标注: 总量最高的那天钉一条竖虚线 + 一行字(宽版绘图区大了, 光靠眼看峰在哪天很累)
        self.peakline = cv.create_line(0, self.plot_top, 0, self.plot_yb,
                                       fill=_mix(CARD, AM, .62), dash=(1, 3), tags='fg',
                                       state='hidden')
        self.ids['c6.peak'] = self._t(None, self.plot_x0, self.plot_top + int(round(11 * s)),
                                      '', FAINT, self.f_tiny)
        self._t('c6.d0', self.plot_x0, y + int(round((h - 32) * s)), '', FAINT, self.f_tiny)
        self._t('c6.dm', (self.plot_x0 + self.plot_x1) / 2.0, y + int(round((h - 32) * s)), '',
                FAINT, self.f_tiny, 'center')
        self._t('c6.d1', self.plot_x1, y + int(round((h - 32) * s)), '', FAINT, self.f_tiny, 'e')
        for i, (lab, c) in enumerate((('成本', CH_COST), ('缓存创建', CH_CW), ('缓存命中', CH_RD),
                                      ('输入', CH_IN), ('输出', CH_OUT))):
            li = _glyph_img(int(round(5.5 * s)), 'fill', c, chip=False)
            self.imgs['lg.dot%d' % i] = li
            self.ids['lg.dot%d' % i] = cv.create_image(0, 0, image=li, tags='fg')
            self._t('lg%d' % i, 0, y + int(round((h - 16) * s)), lab, DIM, self.f_tiny)
        return yb + self._gap

    def _c7(self, y, x=None, w=None, minh=None):
        s, cv = self.s, self.cv
        # 6 24 小时活跃 —— 格条与卡片内容左右对齐, 下方标时刻, 颜色含义写在标题行右侧。
        # 空槽底色必须用 EDGE: TRACK 压在 CARD 上等于没有, 整条就变成"只看得见有数的那几格"
        # (用户 2026-10-08 晚对小面板进度条的同一句抱怨: 只看见亮的部分, 看不见暗的部分)。
        hh = int(round(82 * s))
        H = max(hh, minh or 0)
        self._card('c7', y, H, TE, 'bars', '24小时活跃', x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        gap = int(round(2 * s))
        cw2 = (self.cw - gap * 23) / 24.0
        self.cells = [cv.create_rectangle(int(round(self.cx + i * (cw2 + gap))), y + int(round(42 * s)),
                                         int(round(self.cx + i * (cw2 + gap) + cw2)),
                                         y + int(round(54 * s)), fill=EDGE, outline='', tags='fg')
                      for i in range(24)]
        for i, hh in enumerate(('00', '06', '12', '18', '23')):
            px = (self.cx if i == 0 else self.cx + int(round((i * 6 if i < 4 else 23) * (cw2 + gap)))
                  + (0 if i == 0 else (int(round(cw2 / 2.0)) if i < 4 else int(round(self.cw - (23 * (cw2 + gap)) - cw2 / 2.0)))))
            self._t('c7.h%d' % i, px, y + int(round(64 * s)), hh + '时', MUTED, self.f_tiny,
                    'w' if i == 0 else ('e' if i == 4 else 'center'))
        return yb + self._gap

    def _table(self, key, y, color, title, cols, nrow, x=None, w=None, minh=None):
        s = self.s
        hh = int(round((62 + 12 * (nrow - 1) + 17) * s))     # 行距 13→12: 多塞几行也还看得清
        H = max(hh, minh or 0)
        self._card(key, y, H, color, 'dot', title, x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        for j, (letter, head, ax, col, small) in enumerate(cols):
            self._t('%s.hd%s' % (key, letter), self.cx + int(self.cw * ax),
                    y + int(round(CARD_LBL_DY * s)), head, FAINT, self.f_tiny, 'w' if ax == 0 else 'e')
            for i in range(nrow):
                self._t('%s.%s%d' % (key, letter, i), self.cx + int(self.cw * ax),
                        y + int(round(CARD_VAL_DY * s)) + int(round(12 * s)) * i, '', col,
                        self.f_tiny if small else self.f_sm, 'w' if ax == 0 else 'e')
        return yb

    def _prov(self, y, x=None, w=None, minh=None):
        # 7 应用与供应商(整宽/整列各一张, 避免列挤在一起)
        return self._table('prov', y, TE, '应用与供应商', (
            ('n', '名称', 0, FG, False), ('q', '请求', .62, DIM, True),
            ('h', '命中率', .80, MUTED, True), ('b', '成本', 1.0, TE, False)),
            PROV_ROWS, x, w, minh) + self._gap

    def _model(self, y, x=None, w=None, minh=None):
        return self._table('model', y, VI, '模型TOP4', (
            ('n', '名称', 0, FG, False), ('q', '请求', .46, DIM, True),
            ('a', 'TOKEN', .64, MUTED, True), ('b', '成本', .82, VI, False),
            ('p', '单价', 1.0, DIM, True)), 4, x, w, minh) + self._gap

    def _c8(self, y, x=None, w=None, minh=None):
        s = self.s
        # 8 代理与配置 —— 8 行(原来是 10 行): 「Codex 上下文」与「优化器」并成一行,
        # 单价那行删掉(模型表里本来就有「单价」列, 是重复信息)。省出来的高度给上面的应用行。
        # 宽版一列只有 386 逻辑px, 「当前 claude=… · desktop=… · codex=…」整行会被省略号吃掉一半,
        # 所以宽版把它拆成一行一个应用(多 2 个槽位), 竖版维持原样。
        n = 10 if self._widem else 8
        hh = int(round((147 + 12 * (n - 8)) * s))
        H = max(hh, minh or 0)
        self._card('c8', y, H, DIM, 'gear', '代理与配置', x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        for i in range(n):
            self._t('c8.l%d' % i, self.cx, y + int(round(CARD_LBL_DY * s)) + int(round(12 * s)) * i, '',
                    FAINT, self.f_tiny)
        return yb + self._gap

    HEI = {'c1': 66, 'c2': 84, 'c3': 103, 'c4': 95, 'c7': 82, 'c8': 147, 'haha': 84,
           'qoder': 84}

    def _haha(self, y, x=None, w=None, minh=None):
        """cc-haha 这一路的明细 —— 宽版最后一行的全宽横幅。它的钱和 token 已经并进上面的总量了,
        这张卡说明"并进来多少" + 只有它才有的维度(会话/消息/工具调用/时长)。
        竖版**不画**: 展开态 1510 物理px 已经贴着工作区底 1540, 再加一张卡会被任务栏吃掉。"""
        s = self.s
        hh = int(round(84 * s))
        H = max(hh, minh or 0)
        self._card('haha', y, H, CY, 'wave', 'cc-haha 直连(已并入总量)', vkey='haha.v', vcol=CY,
                   vfont=self.f_tiny, x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        for i, (k, lab, c) in enumerate((('add', '并入成本', GR), ('addt', '并入 token', CY),
                                         ('sess', '会话', FG), ('msgs', '消息', TE),
                                         ('calls', '工具调用', VI), ('days', '活跃天数', AM))):
            xx = self.cx + int(self.cw / 6 * i)
            self._t('haha.%sl' % k, xx, y + int(round(CARD_LBL_DY * s)), lab, FAINT, self.f_micro)
            self._t('haha.%s' % k, xx, y + int(round(CARD_VAL_DY * s)), '', c, self.f_num)
        return yb + self._gap

    def _qoder(self, y, x=None, w=None, minh=None):
        """Qoder(本机 IDE 的 agent 会话)横幅 —— 宽版最后一行。
        它只贡献「请求数 + credits」, token/成本这一路是拿不到的, 所以说明行必须写清楚。
        竖版不画(同 _haha: 展开态已经贴着工作区底了)。"""
        s = self.s
        hh = int(round(84 * s))
        H = max(hh, minh or 0)
        self._card('qoder', y, H, VI, 'grid', 'Qoder(已并入请求数)', vkey='qoder.v',
                   vcol=VI, vfont=self.f_tiny, x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        for i, (k, lab, c) in enumerate((('add', '并入 credits', AM), ('reqs', '并入请求数', VI),
                                         ('sess', '会话', FG), ('days', '活跃天数', TE),
                                         ('streak', '连续', CY), ('avg', '平均 credits/请求', FAINT))):
            xx = self.cx + int(self.cw / 6 * i)
            self._t('qoder.%sl' % k, xx, y + int(round(CARD_LBL_DY * s)), lab, FAINT, self.f_micro)
            self._t('qoder.%s' % k, xx, y + int(round(CARD_VAL_DY * s)), '', c, self.f_num)
        return yb + self._gap

    def _wb(self, y, x=None, w=None, minh=None):
        """WorkBuddy 两版横幅 —— 宽版最后一行。
        「并入积分」这一格**只有国内版给得起**(逐调用覆盖 96.2%), 国外版 1182 条里只有 20 条带值、
        且与它自己的 workbuddy.db 差 5 倍, 所以不给它一个看起来像真值的格子, 只在说明行写清"不并"。
        竖版不画(同 _haha/_qoder: 展开态已经贴着工作区底了)。"""
        s = self.s
        hh = int(round(84 * s))
        H = max(hh, minh or 0)
        self._card('wb', y, H, MA, 'grid', 'WorkBuddy(两版已并入)', vkey='wb.v',
                   vcol=MA, vfont=self.f_tiny, x=x, w=w)
        yb = y + H
        y += (H - hh) // 2
        for i, (k, lab, c) in enumerate((('cred', '并入积分(仅国内)', AM),
                                         ('reqs', '并入请求数', MA),
                                         ('tok', '并入真实消耗', FG),
                                         ('sess', '会话', TE),
                                         ('days', '有账天数', CY),
                                         ('avg', '平均 积分/请求', FAINT))):
            xx = self.cx + int(self.cw / 6 * i)
            self._t('wb.%sl' % k, xx, y + int(round(CARD_LBL_DY * s)), lab, FAINT, self.f_micro)
            self._t('wb.%s' % k, xx, y + int(round(CARD_VAL_DY * s)), '', c, self.f_num)
        return yb + self._gap

    def _hgt(self, key):
        """卡片高度(逻辑px) —— 必须与各 _cX 里写死的值一致, verify P 段逐张核对实测值。"""
        if key == 'c6':
            return self._c6h
        if key == 'c8':
            return 147 + (24 if getattr(self, '_widem', False) else 0)
        if key in ('prov', 'model'):
            return 62 + 12 * ((PROV_ROWS if key == 'prov' else 4) - 1) + 17
        return self.HEI[key]

    def _chrome(self):
        """与数据无关的底栏状态: 跟随方框 + 展开胶囊(两态图在布局时就烘好了)。"""
        self._put_img('foot.pbg', self.expanded)
        self._put('foot.r', '收起面板' if self.expanded else '展开大面板',
                  VI if self.expanded else CY)

    # ── 上色(每次刷新只改文字/坐标/颜色) ──
    def paint(self, d, err):
        s = self.s
        if getattr(self, '_built', None) != (self.expanded, self.wide) or not self.ids:
            self._layout()
        if self.cv.find_withtag('fatal'):       # 上一轮的红字成功了就要清掉, 但空删也算一次删除
            self.cv.delete('fatal')
        self._chrome()
        if err is not None:
            self._put('foot.m', self._fit('● 读不到 CC Switch 库: ' + err[:30]
                                          + ' · 下面数字是上次成功读取的', self.f_tiny, self.mid_w),
                      '#ff6b6b')
            return
        px, pw = int(round(PAD * s)), self.W - 2 * int(round(PAD * s))

        # 头卡这行以前只写 is_current=1 的那一个服务商 —— 用户范围内实际用过的第二个 API
        # 接口看不见, 等于没报。现在列本范围实际用过的(按成本倒序), 前 2 个 + 剩余个数。
        pv = [PROV_ALIAS.get(n) or (n or '?') for n, _a, _r, _c, _t, _h in d['providers']]
        ctxt = ('· 本范围无Provider用量' if not pv else
                '· ' + ' · '.join(pv[:2]) + (' +%d' % (len(pv) - 2) if len(pv) > 2 else ''))
        self._set('cur', self._fit(
            ctxt, self.f_micro, self.sk_x1 - self.sk_w - int(round(10 * s)) - px
            - int(round(37 * s)) - self.f_title.measure('CC Switch') - int(round(7 * s))))

        self._set('clock', time.strftime('%H:%M'))
        for i in range(len(RANGES)):
            on = i == self.range_i
            self._put_img('chip%d' % i, on)
            self._set('chipt%d' % i, RANGES[i][0], FG if on else DIM)

        hc = GR if d['hit'] >= 80 else (AM if d['hit'] >= 50 else '#ff6b6b')
        self._set('c1.val', '%.1f%%' % d['hit'], hc)
        self._set('c1.rt', '命中%s · 真实%s' % (big(d['read']), big(d['real'])))
        bh = self.track_h
        fl = max(bh, int(self.track_w * min(1.0, d['hit'] / 100.0)))
        self._bar('c1.fill', self.track_x, self.track_y, fl, bh, hc)
        kx, ky = self.track_x + fl, self.track_y + bh / 2.0
        self.cv.coords(self.ids['c1.knob'], kx, ky)
        kimg = _glyph_img(self.knob_px, 'knob', hc)
        if self.imgs.get('c1.knob') is not kimg:
            self.cv.itemconfig(self.ids['c1.knob'], image=kimg)
            self.imgs['c1.knob'] = kimg

        vals = [r[1] for r in d['daily']][-14:]
        sig = (tuple(vals), self.sk_w, self.sk_h)
        if sig != self._spark_sig:
            self._spark_sig = sig
            img = _spark_img(self.sk_w, self.sk_h, vals, s)
            self.cv.itemconfig(self.ids['spark'], image=img)
            self.imgs['spark'] = img
        self.cv.itemconfig(self.ids['spark'], state='normal' if len(vals) >= 2 else 'hidden')

        if self.expanded:                       # 小卡不放总请求次数(用户点名没必要), 槽位也就不建
            self._set('c2.a', f"{d['reqs']:,}")
        self._set('c2.b', money(d['cost']))
        self._set('c2.c', f"{d['today'][0]:,}")
        self._set('c2.d', f"{d['h1'][0]:,}", AM if d['h1'][0] else FAINT)
        ap = d['apps']
        self._set('c2.rt', self._fit('按应用 ' + ' · '.join(
            '%s %s' % (APP_ALIAS.get(a) or a, f'{n:,}') for a, n, _c, _t, _h in ap[:2])
            + (' +%d' % (len(ap) - 2) if len(ap) > 2 else ''), self.f_tiny,
            self._cardw('c2') - int(round(66 * s))))
        self._costbar(d)


        if self.expanded:
            self._detail(d, pw)

        fresh = d['last'] and (time.time() - d['last']) < 3600
        note, self.note = self.note, None
        pl = self._power_line() if (self.deadline or self.fired) else None
        # 倒计时优先于一次性提示: 刚点完「到点关机」会带一句 note, 但那 30 分钟里
        # 用户要看的是还剩多久(而且 note 已被消费, 不会延后弹出来捣乱)。
        self._put('foot.m', self._fit(pl or note or '%s · 末次 %s · 库%.1fMB'
                                      % ('● LIVE' if fresh else '○ 数据较旧',
                                         stamp(d['last']), d['dsize']), self.f_tiny, self.mid_w),
                  PK if pl else (GR if fresh else DIM))

        if self.root.winfo_height() != self._H or self.root.winfo_width() != self.W:
            # 改尺寸必须钉住**右上角**(= 圆点那个角), 不能用 Tk 默认的左上角锚: 宽版 1950 收起成
            # 530 时只发 '%dx%d' 会让整张卡留在屏幕左边, 而左上角什么锚都没有(用户点名)。
            if getattr(self, '_req_w', 0) and self.root.winfo_ismapped():
                self.root.geometry('%dx%d+%d+%d' % (self.W, self._H,
                                                     self.root.winfo_x() + self._req_w - self.W,
                                                     self.root.winfo_y()))
                # geometry 只是"请求", winfo_x() 要等 configure 事件回来才更新; 不刷一次的话
                # 紧接着的 _clamp() 会拿旧坐标判定"伸出屏幕右侧", 把右上角锚点又推走 31px。
                self.root.update_idletasks()
            else:
                self.root.geometry('%dx%d' % (self.W, self._H))   # 未映射时带坐标会被 WM 打回原位
            self._req_w = self.W
        if self._place_next and self.root.winfo_ismapped():
            # 尺寸已经落定(上面刚改完并 update_idletasks 过), 这时才谈得上"居中"。
            # 放在 _clamp 之前: 居中本来就不会出屏, 万一工作区很小, 让 _clamp 兜住。
            mode, self._place_next = self._place_next, None
            if mode == 'center':
                cl, ct, cr, cb = _work_area(hwnd=self.root.winfo_id())
                self.root.geometry('+%d+%d' % (cl + max(0, (cr - cl - self.W)) // 2,
                                               ct + max(0, (cb - ct - self._H)) // 2))
            else:
                self.root.geometry('+%d+%d' % self._corner())
            self.root.update_idletasks()
        self._clamp()

    def _clamp(self):
        """把卡片整体抬回任务栏之上。两个坑: ① 要按**工作区**下沿算, 按屏幕高度算等于
        允许它钻到任务栏底下; ② 开机那次绘制时窗口还没映射, 所以除了每轮绘制, 还得在
        <Map> 上再挂一次, 否则要等到下一次刷新才回位(中间那 30 秒底栏被遮着)。"""
        if not self.root.winfo_ismapped() or not getattr(self, '_H', 0):
            return
        s = self.s
        wl, wa_t, wr, wa_b = _work_area(hwnd=self.root.winfo_id())
        x0 = self.root.winfo_x()
        if x0 + self.W > wr - 4:            # 宽版 1550px 摆在右上角会伸出屏幕: 先按宽度回位
            x0 = max(wl + 4, wr - 4 - self.W)
        lim = wa_b - self._H - int(round(6 * s))
        y0 = min(self.root.winfo_y(), lim)
        if (x0, y0) != (self.root.winfo_x(), self.root.winfo_y()):
            self.root.geometry('+%d+%d' % (x0, max(wa_t + int(round(6 * s)), y0)))

    def _costbar(self, d):
        """Token 成本构成条 —— 展开态画在 c3 卡里, 收起态画在那张小卡里, 用的是同一批槽位
        (cin/cout/crd/cwr + .lt + c3.rt), 所以两条版式共用这一份代码。"""
        tot = max(1e-9, d['cin'] + d['cout'] + d['crd'] + d['cwr'])
        bx, by, bw, bh = self.cbar
        acc = bx
        for k, v in (('cin', d['cin']), ('cout', d['cout']), ('crd', d['crd']),
                     ('cwr', d['cwr'])):
            w = bw * v / tot
            self._rect(k, acc, by, max(0, w), bh)
            acc += w
            self._set(k + '.lt', '%s%s·%.0f%%' % ({'cin': '输入', 'cout': '输出', 'crd': '命中',
                                                  'cwr': '创建'}[k], money(v), v / tot * 100))
        self._set('c3.rt', '四项合计%s' % money(tot))

    def _detail(self, d, pw):
        s, cv = self.s, self.cv
        # 3 Token 明细
        for k, v in (('real', d['real']), ('fin', d['fresh_in']), ('out', d['out']),
                     ('cre', d['creat']), ('rd', d['read'])):
            self._set(k + '.v', big(v))

        # 4 延迟实测
        L = d['lat']
        self._set('ftt.v', secs(L['ftt']) if L['ftt'] else '—', TE if L['ftt'] else FAINT)
        self._set('sp.v', ('%.0f' % L['sp_g']) if L['sp_g'] else '—', CY if L['sp_g'] else FAINT)
        self._set('lat.v', secs(L['p50']) if L['p50'] else '—', VI if L['p50'] else FAINT)
        if L['n']:
            self._set('c4.rt', '实测%d条(首token %d条)' % (L['n'], L['ftt_n']))
            self._set('c4.note', 'P95首token=%s · 耗时=%s · 整请求=%.0ftok/s · 纯生成p50=%.0ftok/s'
                      % (secs(L['ftt95']), secs(L['p95']), L['sp_w'] or 0, L['sp_g'] or 0))
        else:
            self._set('c4.rt', '本范围无实测')
            self._set('c4.note', '代理实测全库%d条·截至%s·会话回填不记计时'
                      % (L['total'], stamp(L['last'])))

        # 5 使用趋势 —— 数据层整块交给 PIL(真渐变面积 + 抗锯齿折线)
        # 范围内只有一天(今日档, 或空档)时画不出跨天曲线 —— 改成 24 根小时条形。
        # 行元组与 daily 完全同形状, 所以悬停读数、峰值、左右轴都不用再写第二套。
        bar = len(d['daily']) <= 1
        days = hourly_rows(d['htok']) if bar else d['daily'][-14:]
        n = len(days)
        x0, x1, yt = self.plot_x0, self.plot_x1, self.plot_top
        yb = self.plot_yb
        H = yb - yt
        # 条形用"带状"布局(每根柱占一格, 柱心在格中), 折线用"过点"布局(首尾钉在两端):
        # 带状才不会让 00 时和 23 时的柱子各有一半被裁到绘图区外。
        step = (x1 - x0) / n if bar else ((x1 - x0) / (n - 1) if n > 1 else 0)
        pad = int(round(4 * s))
        # 空范围(例如今天还没有请求)时 max([]) 会直接抛异常, 每个 max 都要带兜底初值
        mt = max([max([r[i] for r in days] + [0]) for i in (5, 6, 7, 8)] + [1])
        mc = max([r[1] for r in days] + [1])

        def series(idx, m):
            return [(i * step, H - (r[idx] / m) * (H - pad)) for i, r in enumerate(days)]

        kk = max(8, int(round(self.plot_w / 55.0)))     # 绘图区越宽铺点越密, 否则陡坡看得出折角
        def cr(pts):
            return self._cr(pts, kk)

        ok = n >= 1
        # 这张位图每重建一次就是 10MB 级中间图 + 一次 resize, 而曲线一天才动一次: 照
        # _spark_img 的做法加签名跳过重建。**只能跳过建图, 不能 return 整段 _detail** ——
        # 图例/网格/日期标签的坐标都是这里往后摆的, 提前返回会把它们全留在 (0,0) 叠成一坨
        # (新加的 B3 卡内越界门禁当场把它抓出来了)。
        sig = (self.plot_w, self.plot_h2, bar, tuple(tuple(r) for r in days))
        if sig != getattr(self, '_chart_sig', None):        # 只有这里可以跳过重建
            self._chart_sig = sig
            if bar and ok:
                img = _bars_img(self.plot_w, self.plot_h2, days, mt, mc, s)
            elif ok:
                p_rd, p_in, p_out = series(8, mt), series(5, mt), series(6, mt)
                p_cw, p_ct = series(7, mt), series(1, mc)
                img = _chart_img(self.plot_w, self.plot_h2, cr(p_rd),
                                 [(cr(p_cw), CH_CW, False, 1.2), (cr(p_in), CH_IN, False, 1.2),
                                  (cr(p_out), CH_OUT, False, 1.2), (cr(p_ct), CH_COST, True, 1.2),
                                  (cr(p_rd), CH_RD, False, 1.9)], p_rd, s)
            else:
                img = _chart_img(self.plot_w, self.plot_h2, [], [], [], s)
            if self.imgs.get('chart') is not img:
                cv.itemconfig(self.ids['chart'], image=img)
                self.imgs['chart'] = img
        self._barm = bool(bar and ok)
        self._plot = (days, x0, yt, step, H, pad, mt, mc) if ok else None
        if not ok:
            cv.itemconfig(self.xhair, state='hidden')
            cv.itemconfig(self.ids['chart.dot'], state='hidden')
            self._tip_hide()
        pk = max(range(n), key=lambda i: days[i][2]) if (n >= 2 and not bar) else None
        if pk is None:
            cv.itemconfig(self.peakline, state='hidden')
            self._set('c6.peak', '')
        else:
            pxk = x0 + pk * step
            cv.coords(self.peakline, pxk, yt, pxk, yb)
            cv.itemconfig(self.peakline, state='normal')
            # 标的是"当日四项净 token 合计", 左轴画的是四条分线各自的刻度 —— 两者不同量纲,
            # 以前都叫"峰值"会让人以为这根线顶到了轴外。
            lab = '最大一天 %s tok · %s' % (big(days[pk][2]), days[pk][0][5:])
            self._set('c6.peak', lab, AM)
            lw = self.f_tiny.measure(lab)
            self.cv.coords(self.ids['c6.peak'], min(max(pxk + int(round(6 * s)), x0),
                                                    max(x0, x1 - lw)),
                           yt + int(round(11 * s)))

        for i, (g, al, ar) in enumerate(zip(self.grid, self.axl, self.axr)):
            cv.coords(g, x0, yt + int(H * i / 3.0), x1, yt + int(H * i / 3.0))
            if i == 3:                                  # 基线那格不写 0, 免得压住日期行
                cv.itemconfig(al, text='')
                cv.itemconfig(ar, text='')
                continue
            cv.itemconfig(al, text=big(mt * (1 - i / 3.0)))
            cv.itemconfig(ar, text='$%.0f' % (mc * (1 - i / 3.0)))

        if bar:                                         # X 轴 = 时间: 0/6/12/18/23 时
            self._set('c6.d0', '00时')
            self._set('c6.dm', '12时')
            self._set('c6.d1', '23时')
        else:
            self._set('c6.d0', days[0][0][5:] if days else '样本不足')
            self._set('c6.dm', days[n // 2][0][5:] if n >= 3 else '')
            self._set('c6.d1', days[-1][0][5:] if n >= 2 else '')
        lx = self.cx
        # 今日档只有两种量(柱=净token, 线=成本), 图例跟着换, 不然会写着看不见的东西
        lg = ((('净token(柱)', CY), ('成本(线)', CH_COST)) if bar else
              (('成本', CH_COST), ('缓存创建', CH_CW), ('缓存命中', CH_RD),
               ('输入', CH_IN), ('输出', CH_OUT)))
        for i, (lab, c) in enumerate(lg):
            d0 = int(round(5.5 * s))
            cy = yb + int(round(24 * s))
            cv.coords(self.ids['lg.dot%d' % i], lx + d0 / 2.0, cy)
            self._set('lg%d' % i, lab, DIM)
            cv.coords(self.ids['lg%d' % i], lx + d0 + int(round(4 * s)), cy)
            lx += d0 + int(round(4 * s)) + self.f_tiny.measure(lab) + int(round(11 * s))
        # 条模式只有 2 项图例: 剩下 3 个槽位要清空并挪走, 不然它们留着上一档的
        # "缓存命中/输入/输出"文字与圆点停在自己的旧坐标上(切版式残留图元抓过一次)。
        for i in range(2, 5):
            if bar:
                self._set('lg%d' % i, '')
                cv.coords(self.ids['lg.dot%d' % i], -60, -60)
        self._set('c6.rt', '本范围无请求' if sum(r[3] for r in days) == 0 else (
            '按小时·柱=净token·线=成本·悬停看该时' if bar else
            '左轴token·右轴成本·悬停看当日') if n else '')

        # 6 24 小时活跃
        h = d['hourly']
        mh = max(h) or 1
        for i, o in enumerate(self.cells):
            cv.itemconfig(o, fill=_mix(EDGE, TE, (h[i] / mh) ** 1.5) if h[i] else EDGE)
        # 这一格是"本范围内该钟点的**累计**次数"(跨天求和), 不是每小时速率: 7 天档实测
        # 峰值 730 次全落在同一个钟点, 写"次/时"就是假的。
        self._set('c7.rt', '颜色越深请求越多 · 峰值%d次(钟点%d累计)' % (mh, h.index(mh)))

        cw = self._cardw('prov')
        # 前 3 行 = 按应用(与 CC Switch 顶部那排应用过滤同一口径), 后面才是供应商/会话回填
        prow = [('▸ ' + (APP_ALIAS.get(a) or a), '', n, cs, tk, hit)
                for a, n, cs, tk, hit in d['apps'][:3]]
        provs = (d['providers'] + d['backfill'])[:PROV_ROWS - 3]
        nhide = len(d['providers']) + len(d['backfill']) - len(provs)   # 行位不够时别静默丢
        prow += provs
        for i in range(PROV_ROWS):
            if i < len(prow):
                n2, app, rc, cs, tkn, hit = prow[i]
                self._set('prov.n%d' % i, self._fit(
                    PROV_ALIAS.get(n2) or (n2 if not app
                                           else '%s·%s' % (n2, APP_ALIAS.get(app) or app)),
                    self.f_sm, int(cw * .62) - int(round(46 * s))))
                self._set('prov.q%d' % i, f'{rc:,}')
                self._set('prov.h%d' % i, ('%.0f%%' % hit) if tkn else '—')
                self._set('prov.b%d' % i, money(cs))
            else:
                for c in 'nqhb':
                    self._set('prov.%s%d' % (c, i), '')
        for i in range(4):
            if i < len(d['models']):
                mn, rc, cs, tkn = d['models'][i]
                pr = d['prices'].get(mn)
                self._set('model.n%d' % i, self._fit(mn, self.f_sm, int(self._cardw('model') * .46) - int(round(40 * s))))
                self._set('model.q%d' % i, f'{rc:,}')
                self._set('model.a%d' % i, big(tkn))
                self._set('model.b%d' % i, money(cs))
                self._set('model.p%d' % i, ('%s/%s' % pr) if pr else '-')
            else:
                for c in 'nqabp':
                    self._set('model.%s%d' % (c, i), '')

        p = d['proxy']
        num = lambda v: format(int(v), ',') if (v and str(v).isdigit()) else '-'
        on = lambda v: '开' if v else '关'
        opt = '/'.join(k for k, o2 in (('改写', d['opt'].get('enabled')),
                                       ('思考', d['opt'].get('thinkingOptimizer')),
                                       ('缓存注入', d['opt'].get('cacheInjection'))) if o2) or '关'
        shortk = {'claude-desktop': 'desktop'}
        kvp = sorted((shortk.get(k, k), str(v)) for k, v in d['cur'].items())
        cur = ['%s=%s' % kv for kv in kvp]
        one = '当前 ' + ' · '.join(cur)
        curline = one if (self._widem or self.f_tiny.measure(one) <= self.cw) else \
            self._fitkv('当前 ', kvp, self.f_tiny, self.cw)
        lines = [
            '代理 %s:%d · 日志 %s · 自动切换 %s · 重试 %d'
            % (p[0], p[1], on(p[10]), on(p[6]), p[5]),
            '超时 首字节 %ds / 空闲 %ds / 非流 %ds' % (p[2], p[3], p[4]),
            '熔断 连续失败 %d 次 或 错误率 %.0f%% (最少 %d 次)' % (p[7], p[8] * 100, p[9]),
            curline,
            '端点 %s' % (', '.join(sorted({host(e[2]) for e in d['eps']})) or '库里没有配端点'),
            '库内 Provider %d 个 · 连通性 %s' % (
                d['ptotal'],
                ('%s(%s) %sms HTTP %s · %s' % (d['chk'][0], shortk.get(d['chk'][1], d['chk'][1]),
                                               d['chk'][2], d['chk'][3], stamp(d['chk'][4])))
                if d['chk'] else '无检查记录'),
            'Codex 上下文 %s · 自动压缩 %s · 推理 %s · 优化器 %s'
            % (num(d['ctx_window']), num(d['compact']), d['effort'] or '-', opt),
            '状态码 %s%s' % (' · '.join('%s×%s' % (c, f'{n:,}') for c, n in d['status'][:4])
                             or '本范围无请求',
                          (' · 错误 ' + ' | '.join('%s×%d' % (str(m)[:16], n)
                                                   for m, n in d['errors'][:1])) if d['errors'] else ''),
        ]
        if self._widem and len(cur) > 1:          # 一行一个应用, 免得整行被省略号截掉
            cl = ['当前 ' + cur[0], '\u3000' + cur[1]]
            if len(cur) > 2:
                cl.append('\u3000' + ' · '.join(cur[2:]))
            lines[3:4] = cl
        n8 = 10 if self._widem else 8
        lines += [''] * (n8 - len(lines))
        for i in range(n8):
            self._set('c8.l%d' % i, self._fit(lines[i], self.f_tiny, self._cardw('c8')))
        # 这一卡所有配置都只取自 proxy_config 里 app_type='codex' 的那一行(超时/重试/熔断/
        # 监听端口都是代理进程的), claude 侧的同名配置不在这张卡上 —— 不写出来就像在报全局。
        self._set('c8.rt', '取自 codex 的 proxy_config')
        # 状态码只有 CC Switch 记, 并进来 cc-haha 的响应后「成功+失败」必然小于总请求数,
        # 不写分母就是数字对不上。
        self._set('prov.rt', self._fit(
            '状态(仅CC Switch %s次) 成功%s·失败%s%s'
            % (f"{int(d['ok']) + int(d['fail']):,}", f"{int(d['ok']):,}", f"{int(d['fail']):,}",
               ('' if not nhide else ' · +%d接口未列' % nhide)
               + ('' if not [x for x in (d.get('extra') or {}).values() if x.get('in')]
                  else ' · 额外源无本机定价')),
            self.f_micro, self._cardw('prov') - int(round(74 * s))))
        self._set('model.rt', '本范围%d个模型·展示成本前4' % d['nmodel'])

        hb = d.get('haha')
        if self._widem:
            if hb:
                # 报**真的并进去的那个数**(本地日口径), 不是索引全量(UTC 日口径) ——
                # 两个数不一样时, 卡片与总量对不上就等于报错数。
                self._set('haha.add', money(hb.get('mcost', hb['cost'])))
                self._set('haha.addt', big(hb.get('mtok', hb['tok'])))
                self._set('haha.sess', f"{hb['sess']:,}")
                self._set('haha.msgs', f"{hb['msgs']:,}")
                self._set('haha.calls', f"{hb['calls']:,}")
                self._set('haha.days', '%d天' % hb['days']
                          + ('·连%d' % hb['streak'] if hb['streak'] > 1 else ''))
                self._set('haha.v', '最长活跃 %s · 子代理 %d 个' % (dur(hb['act']), hb['sub']))
                self._set('haha.rt', self._fit(
                    ('检测到 %d 个会话 id 重叠 · 已拒绝并入(见 R 段双计保险)' % hb['clash'])
                    if hb.get('clash') else
                    '末次 %s · 会话 id 与 CC Switch 不相交(R 段断言)·状态码/延迟仍是 CC Switch 口径'
                    % stamp(hb['last']), self.f_tiny, self._cardw('haha')))
            else:
                for k in ('add', 'addt', 'sess', 'msgs', 'calls', 'days'):
                    self._set('haha.' + k, '—')
                self._set('haha.v', '没读到索引库')
                self._set('haha.rt', '没找到 cc-haha 索引库(找过 CLAUDE_CONFIG_DIR / .claude / 各分区 cc-haha)')

        qb = d.get('qoder')
        if self._widem:
            if qb and not qb.get('clash'):
                self._set('qoder.add', '%.0f' % qb['credits'])
                self._set('qoder.reqs', f"{qb['reqs']:,}")
                self._set('qoder.sess', f"{qb['sessions']:,}")
                # 活跃天数与连续天数各占一格(横幅里已有专门的"连续"格, 这里不再带后缀)
                self._set('qoder.days', '%d天' % qb['days'])
                self._set('qoder.streak', '连%d' % qb['streak'] if qb['streak'] > 1 else '—')
                self._set('qoder.avg', '%.3f' % (qb['credits'] / qb['reqs']) if qb['reqs'] else '—')
                # 额外源按成本排序时全被挤到应用表 3 个槽位之外(它们不记钱), 所以在这行点名,
                # 否则就是"并进来了但看不见" —— 与用户要的"全部统计"不是一回事。
                self._set('qoder.v', self._fit(
                    '末次 %s · %s' % (stamp(qb['last']), ' · '.join(
                        '%s %s' % (v['name'], f"{v['reqs']:,}")
                        for k, v in sorted((d.get('extra') or {}).items())
                        if v and v.get('reqs')))
                    if [v for v in (d.get('extra') or {}).values() if v and v.get('reqs')]
                    else '末次 %s' % stamp(qb['last']), self.f_tiny,
                    int(self._cardw('qoder') * .42)))
                self._set('qoder.rt', self._fit(
                    '不走代理的 IDE 会话 · 本机只落 credits 与响应数, token 四项实测恒为 0'
                    ' -> 不并入 token/成本/命中率 · 会话 id 与 CC Switch 不相交(U 段断言)',
                    self.f_tiny, self._cardw('qoder')))
            elif qb and qb.get('clash'):
                for k in ('add', 'reqs', 'sess', 'days', 'streak', 'avg'):
                    self._set('qoder.' + k, '—')
                self._set('qoder.v', '已拒绝并入')
                self._set('qoder.rt', '检测到 %d 个会话 id 已在 CC Switch 里 · 整路不并'
                          % qb['clash'])
            else:
                for k in ('add', 'reqs', 'sess', 'days', 'streak', 'avg'):
                    self._set('qoder.' + k, '—')
                self._set('qoder.v', '没读到会话目录')
                self._set('qoder.rt', '没找到 %s' % QDIR)

        # WorkBuddy 两版: 并入器把每一路都留在 d['extra'][key] 里, 这里按 WB_SOURCES 的次序取
        ex = d.get('extra') or {}
        wbs = [ex[t[1]] for t in WB_SOURCES if ex.get(t[1])]
        if self._widem:
            live = [v for v in wbs if v.get('reqs')]
            for k in ('cred', 'reqs', 'tok', 'sess', 'days', 'avg'):
                self._set('wb.' + k, '—')
            if live:
                cn = next((v for v in live if v['key'] == 'workbuddy'), None)
                self._set('wb.cred', '%.0f' % sum(v['credits'] for v in live))
                self._set('wb.reqs', f"{sum(v['reqs'] for v in live):,}")
                self._set('wb.tok', big(sum(v['in'] + v['out'] + v['rd'] + v['cc']
                                            for v in live)))
                self._set('wb.sess', f"{sum(v['sessions'] for v in live):,}")
                self._set('wb.days', '%d天' % len({dte for v in live for dte in v['by_day']}))
                self._set('wb.avg', '%.3f' % (cn['credits'] / cn['reqs'])
                          if cn and cn['reqs'] else '—')
                self._set('wb.v', self._fit(
                    ' · '.join('%s %s 次' % (v['name'], f"{v['reqs']:,}") for v in live)
                    + ' · 末次 %s' % stamp(max(v['last'] for v in live)),
                    self.f_tiny, int(self._cardw('wb') * .42)))
                self._set('wb.rt', self._fit(
                    '两版都不走 CC Switch 代理 · prompt_tokens 含缓存读与写(已拆, 四桶相加=='
                    '应用自记 total_tokens) · 国外版积分与它自己的 workbuddy.db 差 5 倍, 不并'
                    ' · 会话 id 与 CC Switch 不相交(Y 段断言)', self.f_tiny, self._cardw('wb')))
            elif wbs:
                self._set('wb.v', '已拒绝并入')
                self._set('wb.rt', '检测到 %d 个会话 id 已在 CC Switch 里 · 整路不并'
                          % sum(v.get('clash', 0) for v in wbs))
            else:
                self._set('wb.v', '没读到会话目录')
                self._set('wb.rt', '没找到 %s / %s' % (WB_SOURCES[0][0], WB_SOURCES[1][0]))

    def run(self):
        self._tick()                                 # 刷新与跟随判定共用这一条 after 链
        self.root.mainloop()
