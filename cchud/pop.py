# -*- coding: utf-8 -*-
"""cc-hud 自绘右键菜单。"""
import ctypes
import tkinter as tk
from ctypes import wintypes as wt

from .const import *
from .util import *
from .render import *

__all__ = [
    'Pop',
]


class Pop:
    """自绘右键菜单。tk.Menu 在 Windows 上永远带原生描边和勾选栏, 调不到面板那套样式,
    所以浮层自己画: 同一个圆角渐变壳、同一套字色, 勾选/单选用面板自己的 ✓ / ● 指示符。
    items 可以给列表, 也可以给「返回列表的函数」—— 后者才能就地刷新到最新状态。"""

    ROW, HDR, SEP, GAP, PAD, IND = 25, 20, 9, 8, 7, 21

    def _hh(self, kind):
        """行高: sep = 一条横线带 9px, gap = 纯留白 8px(不画线, 也不进 rows)。"""
        return (self.SEP if kind == 'sep' else self.GAP if kind == 'gap'
                else self.HDR if kind in ('hdr', 'info') else self.ROW)
    STAY = ('radio', 'check', 'scmd')     # 点完不关菜单: 设定值类 + 定时武装/取消

    def __init__(self, hud, items, x, y, root_pop=None, parent=None):
        self.hud, self.parent = hud, parent
        self.spec = items if callable(items) else (lambda it=items: it)
        self.root_pop = root_pop or self
        self.kids, self.imgs, self.rows = [], [], []
        self.active, self.press, self.closed = -1, -1, False
        self.sub_i, self._job, self._btn_last = -1, None, False
        win = self.win = tk.Toplevel(hud.root)
        win.overrideredirect(True)
        win.configure(bg=BG)
        win.attributes('-topmost', True)
        try:
            win.attributes('-transparentcolor', BG)
        except tk.TclError:
            pass
        cv = self.cv = tk.Canvas(win, bg=BG, highlightthickness=0, bd=0)
        cv.pack()
        self._draw(x, y)
        cv.bind('<Motion>', self._move)
        cv.bind('<ButtonPress-1>', self._down)
        cv.bind('<ButtonRelease-1>', self._up)
        cv.bind('<Leave>', self._leave)
        if self is self.root_pop:
            win.bind('<Button-1>', self._outside)
            # 不用 grab_set: 实测( TEMP/pop_grab_probe2.py )证明 grab 挂在根浮层时,
            # 同进程的子弹出窗口一个事件都收不到 —— 子菜单点了没反应, 而且点击坐标会被
            # 算到根浮层外面从而把整菜单关掉。改成 50ms 轮询左/右键沿 + 游标矩形判定。
            self._job = self.hud.root.after(50, self._watch)

    def _draw(self, x, y):
        """画(或就地重画)这一层: 尺寸按当前条目重算, 位置沿用请求坐标。
        子层和 kids 不动 —— 重画父层不能把自己弹出去的那层弄丢。"""
        hud = self.hud
        s = hud.s
        R = lambda v: int(round(v * s))
        items = self.spec()
        lw = R(self.IND) + max([hud.f_micro.measure(it[1])
                                for it in items if it[0] not in ('sep', 'gap')]
                               + [R(56)])
        # 量化到 24px 一档再往下用: 「延迟时长 · 当前 N 分钟」这类会变的文字如果按像素建精灵,
        # _SPR 每种尺寸存一张、永不释放(pmin 有上百种取值)。
        lw = ((lw + 23) // 24) * 24
        pw = R(self.PAD * 2) + lw
        ph = R(self.PAD * 2) + sum(R(self._hh(it[0])) for it in items)
        x, y = _clamp_xy(x, y, pw, ph)
        self.gx, self.gy = x, y        # 子菜单定位用请求值: winfo_x() 要等 WM 映射后才有数
        self.w, self.h = pw, ph
        self.cv.configure(width=pw, height=ph)
        self.win.geometry('%dx%d+%d+%d' % (pw, ph, x, y))
        self.cv.delete('all')
        self.imgs, self.rows = [], []
        self.active = self.press = -1
        shell = hud._sprite(pw, ph, R(11), CARD, EDGE, BG)
        self.imgs.append(shell)
        self.cv.create_image(pw // 2, ph // 2, image=shell)
        hover = hud._sprite(lw, R(self.ROW) - R(4), R(6), _mix(CARD, CY, .17), _mix(EDGE, CY, .55))
        self.imgs.append(hover)
        yy = R(self.PAD)
        for it in items:
            kind = it[0]
            hh = R(self._hh(kind))
            if kind == 'gap':
                pass
            elif kind == 'sep':
                self.cv.create_line(R(10), yy + hh // 2, pw - R(10), yy + hh // 2, fill=EDGE)
            else:
                mid = yy + hh // 2
                hov = self.cv.create_image(R(self.PAD) + lw // 2, mid, image=hover, state='hidden')
                tx = R(self.PAD) + R(self.IND)
                col = {'hdr': FAINT, 'info': MUTED}.get(kind, FG)
                txt = self.cv.create_text(tx, mid, anchor='w', text=it[1], fill=col,
                                          font=hud.f_tiny if kind in ('hdr', 'info')
                                          else hud.f_micro)
                ind = None
                if kind == 'radio':
                    ind = self.cv.create_image(R(self.PAD) + R(self.IND / 2.0), mid,
                                               state='hidden',
                                               image=_glyph_img(R(9), 'fill', IN, chip=False))
                    if it[2]:
                        self.cv.itemconfig(ind, state='normal')
                elif kind == 'check':
                    ind = self.cv.create_image(R(self.PAD) + R(self.IND / 2.0), mid,
                                               image=_glyph_img(R(13), 'boxon' if it[2] else 'boxoff',
                                                                GR if it[2] else MUTED, chip=False))
                elif kind == 'sub':
                    ind = self.cv.create_text(pw - R(11), mid, anchor='e', text='▸', fill=DIM,
                                              font=hud.f_micro)
                self.rows.append([yy, yy + hh, it, hov, txt, ind])
            yy += hh

    def redraw(self):
        if not self.closed:
            self._draw(self.gx, self.gy)

    def _row(self, ev):
        if not (0 <= ev.x <= self.w):        # 以前只看 y, 横向出界也会算命中一行
            return -1
        for i, r in enumerate(self.rows):
            if r[0] <= ev.y <= r[1]:
                return i
        return -1

    def _hover(self, i):
        if i == self.active:
            return
        for j, r in enumerate(self.rows):
            self.cv.itemconfig(r[3], state='normal' if j == i else 'hidden')
        self.active = i
        if i >= 0 and self.rows[i][2][0] == 'sub':
            self._open_sub(i)
        # 滑过别的条目不收起子菜单: 斜着移进子菜单的途中必然扫过父层其他行,
        # 一收就变成「手一抖菜单没了」。只有换到另一个子菜单/选中条目/点外面才收。

    def _leave(self, ev=None):
        """指针离开父浮层, 十有八九只是横移进了子弹出窗口 —— 高亮和子菜单都得留着。"""
        if not self.kids:
            self._hover(-1)

    def _move(self, ev):
        self._hover(self._row(ev))

    def _down(self, ev):
        self.press = self._row(ev)

    def _outside(self, ev):
        if not (0 <= ev.x <= self.w and 0 <= ev.y <= self.h):
            self.root_pop.close()

    def _watch(self):
        """没有 grab 就得自己盯着「点在外面」: 50ms 轮询鼠标键按下沿 + 游标是否落在
        本层和所有子弹出层的矩形之外。子菜单存活期间也算进去, 不然点它就等于点外面。"""
        if self.closed:
            return
        try:
            u = ctypes.windll.user32
            u.GetAsyncKeyState.restype = ctypes.c_short
            down = (u.GetAsyncKeyState(0x01) | u.GetAsyncKeyState(0x02)) & 0x8000
            if down and not self._btn_last and not self._cursor_in():
                self.close()
                return
            self._btn_last = bool(down)
        except Exception as e:
            self.hud.note = '菜单轮询异常: ' + str(e)[:26]      # 别静默, 也别断链
        finally:
            # 重挂必须放 finally: 写在最后一行的话, _cursor_in 里一次 winfo 竞态就能让
            # 这条链永久停摆 -> 菜单再也点不关, 而 .pyw 没有 stderr, 没人知道出过事
            if not self.closed:
                self._job = self.hud.root.after(50, self._watch)

    def _rects(self):
        out = []
        for p in [self] + list(self.kids):
            if p.closed or not p.win.winfo_exists():
                continue
            if p.win.winfo_ismapped():
                out.append((p.win.winfo_rootx(), p.win.winfo_rooty(),
                            p.win.winfo_width(), p.win.winfo_height()))
            else:
                out.append((p.gx, p.gy, p.w, p.h))
        return out

    def _cursor_in(self):
        pt = wt.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        for x, y, w, h in self._rects():
            if x <= pt.x < x + w and y <= pt.y < y + h:
                return True
        return False

    def _up(self, ev):
        i = self._row(ev)
        if i < 0 or i != self.press:
            return
        it = self.rows[i][2]
        if it[0] in ('hdr', 'info'):        # sep/gap 不进 rows, 这里不需要判它们
            return
        if it[0] == 'sub':
            if self.sub_i == i and self.kids:      # 再点一次 = 把自己弹出去的那层收掉
                self._close_subs()
            else:
                self._open_sub(i)
            return
        cmd = it[-1]
        if it[0] in self.STAY:
            cmd()                                  # 先执行, 再按最新状态就地重画, 菜单留着连着点
            p = self
            while p is not None:
                p.redraw()
                p = p.parent
            self._hover(i)
            return
        self.root_pop.close()
        cmd()

    def _open_sub(self, i):
        if self.sub_i == i and self.kids:
            return
        self._close_subs()
        self.sub_i = i
        r = self.rows[i]
        sub = Pop(self.hud, r[2][2], self.gx + self.w - 4, self.gy + r[0], self.root_pop, self)
        if sub.gx < self.gx + self.w - 4:
            # 右边放不下被挤回来了 —— 挤回来会盖住父层自己的条目(点不到)。翻到左侧,
            # 放不下再退回挤回来的位置(垂直相接, 至少不挡字)。
            alt = _clamp_xy(self.gx - sub.w + 4, self.gy + r[0], sub.w, sub.h)
            if alt[0] + sub.w <= self.gx + 4:
                sub.place_at(alt[0], alt[1])
        self.kids.append(sub)
        if self is not self.root_pop:
            self.root_pop.kids.append(sub)

    def place_at(self, x, y):
        self.gx, self.gy = x, y
        if self.win.winfo_exists():
            self.win.geometry('+%d+%d' % (x, y))

    def _close_subs(self):
        for k in list(self.kids):        # close() 会回头改 self.kids, 必须先固化
            k.close()
        self.kids = []
        self.sub_i = -1

    def labels(self):
        return [(r[2][0], r[2][1]) for r in self.rows]

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self is self.root_pop:
            self.hud.pop = None
        if self._job:
            try:
                self.hud.root.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
            self._job = None
        self._close_subs()
        if self.parent and self in self.parent.kids:
            self.parent.kids.remove(self)
        if self.win.winfo_exists():
            self.win.destroy()
