# -*- coding: utf-8 -*-
"""cc-hud 的 PIL 渲染原语: 面板/进度条/图标/折线/柱状。"""
import math

from .const import *
from .util import *

__all__ = [
    '_PAN', '_panel_img', '_mix', '_bake', '_rgba', '_BAR', '_bar_img', '_GLY', '_draw_glyph',
    '_glyph_img', '_spark_img', '_cr', '_bars_img', '_chart_img',
]


_PAN = {}


def _panel_img(w, h, r, fill, outline, lw, accent='', icon=None):
    """卡片底: 真·垂直渐变 + 顶部一层很淡的强调色辉光, 4x 超采样后缩回。
    用 Image.linear_gradient 做掩膜, 不是几条横带叠出来的台阶。"""
    k = (w, h, r, fill, outline, lw, accent, icon)
    img = _PAN.get(k)
    if img is not None:
        return img
    from PIL import Image, ImageDraw, ImageTk
    K = 4
    W, H = max(1, w * K), max(1, h * K)
    bot = Image.new('RGBA', (W, H), _rgba(fill, 255))
    top = Image.new('RGBA', (W, H), _rgba(_mix(fill, '#33405a', .55), 255))
    g = Image.linear_gradient('L').resize((W, H), Image.BILINEAR)
    im = Image.composite(top, bot, g.point(lambda v: int(v * .26)))
    if accent:
        a = g.point(lambda v: int(max(0, v * 3.2 - 255 * 2.2) * .055))
        im = Image.composite(Image.new('RGBA', (W, H), _rgba(accent, 255)), im, a)
    m = Image.new('L', (W, H), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, W - 1, H - 1], radius=r * K, fill=255)
    im.putalpha(m)
    ImageDraw.Draw(im).rounded_rectangle([lw // 2, lw // 2, W - 1 - lw // 2, H - 1 - lw // 2],
                                         radius=max(0, r * K - lw // 2), outline=_rgba(outline, 255),
                                         width=lw)
    if icon:
        _draw_glyph(ImageDraw.Draw(im), icon[0], icon[1], icon[2] * 4, icon[3] * 4, icon[4] * 4)
    _PAN[k] = _bake(im, w, h, BG, hard=True)
    return _PAN[k]


def _mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _spark_img(w, h, vals, s=1.0):
    """头卡的迷你曲线。以前用 Tk 的 create_line(smooth=True) —— 画布的 line 根本不做
    抗锯齿, smooth 还是不过数据点的 B 样条, 末端点另画一个 oval 会和线尾错位,
    这就是用户指着说「怎么还是那么粗糙」的那条线。改成 4x 超采样 + Catmull-Rom 过点,
    末端点画进同一张位图。底图 RGB 铺 CARD 而不是透明黑: RGBA 缩小时透明像素的黑会
    往线边渗, 留一圈暗边。"""
    from PIL import Image, ImageDraw, ImageTk
    K = 4
    W, H = max(1, w * K), max(1, h * K)
    im = Image.new('RGBA', (W, H), _rgba(CARD, 0))
    if len(vals) >= 2:
        mx = max(vals + [1]) or 1
        pad = max(2.0, 2.6 * s * K)
        span = (W - 1) - 2 * pad
        pts = [((pad + i * span / (len(vals) - 1)),
                (H - pad) - (v / mx) * (H - 2 * pad)) for i, v in enumerate(vals)]
        cr = _cr(pts, 10)
        # 贴曲线的真渐变面积(和大趋势图同一套做法): 多边形当掩膜 + 线性渐变当 alpha
        under = Image.new('L', (W, H), 0)
        ImageDraw.Draw(under).polygon(cr + [(W - 1, H - 1), (0, H - 1)], fill=255)
        ramp = Image.linear_gradient('L').resize((W, H), Image.BILINEAR)
        alpha = Image.composite(ramp.point(lambda v: int(v * .30 + 8)),
                                Image.new('L', (W, H), 0), under)
        lay = Image.new('RGBA', (W, H), _rgba(CY, 255))
        lay.putalpha(alpha)
        im = Image.alpha_composite(im, lay)
        d = ImageDraw.Draw(im)
        d.line(cr, fill=_rgba(CY, 255), width=max(1, int(round(1.15 * s * K))), joint='curve')
        r = max(2, int(round(1.5 * s * K)))
        x, y = pts[-1]
        d.ellipse([x - r, y - r, x + r, y + r], fill=_rgba(CY, 255))
    return ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS))


def _cr(pts, k=8):
    """Catmull-Rom 加密(模块级版本, 头卡迷你曲线与趋势图共用一套算法)。返回点列 [(x,y),...]
    —— Tk 的 smooth=True 是 B 样条, 曲线不经过真实数据点, 所以自己铺点: 既过点又平滑。"""
    if len(pts) < 3:
        return list(pts)
    out = []
    for i in range(len(pts) - 1):
        p0, p1 = pts[max(0, i - 1)], pts[i]
        p2, p3 = pts[i + 1], pts[min(len(pts) - 1, i + 2)]
        for j in range(k):
            t = j / float(k)
            t2, t3 = t * t, t * t * t
            out.append((0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0]
                          + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0]
                          + p3[0]) * t3),
                        0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1]
                          + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1]
                          + p3[1]) * t3)))
    out.append(pts[-1])
    return out


def _bars_img(w, h, rows, mt, mc, s=1.0):
    """按小时的用量条形: 柱高 = 该小时净 token(左轴), 叠一条成本折线(右轴)。
    今日档只有 1 个数据点, 画不出跨天曲线(以前直接写"画不出趋势"), 换成小时粒度。"""
    from PIL import Image, ImageDraw, ImageTk
    K = 3 if w * h >= 120_000 else 4
    W, H = max(1, w * K), max(1, h * K)
    im = Image.new('RGBA', (W, H), _rgba(CARD, 0))
    d = ImageDraw.Draw(im)
    n = max(1, len(rows))
    bw = (W - 1) / float(n)
    gap = max(1, int(round(bw * 0.22)))
    for i, r in enumerate(rows):
        tok, cost, reqs = r[2], r[1], r[3]
        x0 = i * bw + gap / 2.0
        x1 = (i + 1) * bw - gap / 2.0
        if tok <= 0:
            # 有请求但这一路不报 token(Qoder 系): 画一格极短的暗色提示, 不留纯空白,
            # 否则"柱子没有"会被读成"这段时间没用"。
            if reqs:
                d.rounded_rectangle([x0, H - max(2, int(round(2 * s * K))), x1, H - 1],
                                    radius=1, fill=_rgba(MUTED, 150))
            continue
        hh = (tok / float(mt)) * (H - 1)
        top = H - hh
        gr = Image.new('L', (max(1, int(x1 - x0)), max(1, int(hh))), 0)
        ImageDraw.Draw(gr).rectangle([0, 0, gr.size[0] - 1, gr.size[1] - 1], fill=255)
        ramp = Image.linear_gradient('L').resize(gr.size, Image.BILINEAR)
        alpha = Image.composite(ramp.point(lambda v: int(v * .34 + 26)),
                                Image.new('L', gr.size, 0), gr)
        lay = Image.new('RGBA', gr.size, _rgba(CY, 255))
        lay.putalpha(alpha)
        im.alpha_composite(lay, (int(x0), int(top)))
        d.line([x0, top, x1, top], fill=_rgba(CY, 235), width=max(1, int(round(1.1 * s * K))))
    pts = [((i + 0.5) * bw, H - 1 - (r[1] / mc) * (H - 1)) for i, r in enumerate(rows)]
    if len(pts) >= 2:
        d.line(pts, fill=_rgba(CH_COST, 240), width=max(1, int(round(1.3 * s * K))), joint='curve')
        for i, (px, py) in enumerate(pts):
            if rows[i][1] > 0:
                r = max(1, int(round(1.6 * s * K)))
                d.ellipse([px - r, py - r, px + r, py + r], fill=_rgba(CH_COST, 255))
    return ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS))


def _chart_img(w, h, area, lines, dots, sc=1.0):
    """趋势图整层用 PIL 画: 面积是从曲线往下衰减的真渐变(线性渐变当 alpha + 多边形掩膜),
    折线和数据点靠 4x 超采样拿到抗锯齿 —— Tk 的 line/polygon 两者都做不到。"""
    from PIL import Image, ImageDraw, ImageTk
    # 超采样倍数按面积自适应: 小图 4x; 宽版那种大图 4x 要画三百多万像素, 3x 仍然远超
    # 屏幕像素密度(线宽 2 物理px → 6px 采样), 但一次刷新的耗时几乎减半。
    K = 4 if w * h < 120_000 else 3
    W, H = max(1, w * K), max(1, h * K)
    im = Image.new('RGBA', (W, H), _rgba(CARD, 0))     # 见 _spark_img: 别用透明黑底

    if len(area) >= 2:
        under = Image.new('L', (W, H), 0)
        ImageDraw.Draw(under).polygon([(x * K, y * K) for x, y in area] + [(W - 1, H - 1), (0, H - 1)],
                                      fill=255)
        ramp = Image.linear_gradient('L').resize((W, H), Image.BILINEAR)
        alpha = Image.composite(ramp.point(lambda v: int(v * .42 + 16)),
                                Image.new('L', (W, H), 0), under)
        lay = Image.new('RGBA', (W, H), _rgba(CH_RD, 255))
        lay.putalpha(alpha)
        im = Image.alpha_composite(im, lay)
    d = ImageDraw.Draw(im)
    wl = lambda wd: max(1, int(round(wd * sc * K)))      # 线宽按逻辑px × DPI, 125% 屏上不再是 1 物理px
    for pts, col, dash, wd in lines:
        if len(pts) < 2:
            continue
        p = [(x * K, y * K) for x, y in pts]
        if dash:
            for i in range(0, len(p) - 1, 3):
                d.line([p[i], p[min(i + 3, len(p) - 1)]], fill=_rgba(col, 255), width=wl(wd))
        else:
            d.line(p, fill=_rgba(col, 255), width=wl(wd), joint='curve')
    r = max(2, int(round(1.9 * sc * K)))
    for x, y in dots:
        d.ellipse([x * K - r * 2, y * K - r * 2, x * K + r * 2, y * K + r * 2],
                  fill=_rgba(CH_RD, 255), outline=_rgba(CARD, 255), width=r)

    return ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS))


def _bake(im4, w, h, mat, hard=False):
    """4x 画好的图缩回 1x 并压在不透明材质上。
    hard=True 用于会接触键色镂空的剪影: 掩膜二值化, 边界不留中间色,
    因为键色只抠"恰好等于键色"的像素, 任何中间色都会被 DWM 抖成棋盘格影子。"""
    from PIL import Image, ImageTk
    soft = im4.resize((w, h), Image.LANCZOS)
    if hard:
        mk = im4.split()[3].resize((w, h), Image.NEAREST).point(lambda v: 255 if v > 127 else 0)
    else:
        mk = soft.split()[3]
    out = Image.new('RGBA', (w, h), _rgba(mat, 255))
    out.paste(soft, (0, 0), mk)
    return ImageTk.PhotoImage(out)


def _rgba(hx, a=255):
    return (int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16), a)


_BAR = {}


def _bar_img(w, h, col, mat):
    """进度条位图: **左端圆角 + 右端直角**, 4x 超采样后压 mat 底。

    为什么右端画直角: 条右端永远被 knob 盖住, 直角才不会在暗槽上戳出两个缺口;
    若两端都画圆角, 条右端的圆角会在槽中间啃掉两块。
    底材 mat 必须传"该处卡片的真实底色"(见 HUD._mat_at), 传死的 CARD 会露出一块平色矩形。
    """
    w = max(1, int(w))
    h = max(1, int(h))
    k = (w, h, col, mat)
    img = _BAR.get(k)
    if img is None:
        from PIL import Image, ImageDraw
        K = 4
        im = Image.new('RGBA', (w * K, h * K), (0, 0, 0, 0))
        r = h * K / 2.0
        # 右边界多画 r 再靠 _bake 的缩回裁掉 -> 右端自然成直角
        ImageDraw.Draw(im).rounded_rectangle([0, 0, w * K - 1 + r, h * K - 1], radius=r,
                                             fill=_rgba(col, 255))
        img = _bake(im, w, h, mat, hard=False)
        if len(_BAR) > 128:                 # 上限保护: 命中率只在小数点后一位变, 键数很有限
            _BAR.clear()
        _BAR[k] = img
    return img


_GLY = {}


def _draw_glyph(d, kind, color, ox, oy, u, chip=True):
    """在 4x 画布的 (ox,oy) 处画一个 u×u 图标(含芯片底)。
    单独用 `_glyph_img`, 卡片则把它直接烘进卡片图 —— Tk 的 image 项透明处会露出画布底色,
    叠在卡片上就是一圈方块, 所以图标不能和卡片分开画。"""
    acc = _rgba(color)
    if chip:
        m = u * .04
        d.rounded_rectangle([ox + m, oy + m, ox + u - m, oy + u - m], radius=u * .28,
                            fill=_rgba(_mix(CARD, color, .15)),
                            outline=_rgba(_mix(CARD, color, .42)), width=max(2, int(u * .045)))
    lw = max(2, int(u * .075))
    cx, cy, r = ox + u / 2.0, oy + u / 2.0, u * .245
    P = lambda fx, fy: (ox + u * fx, oy + u * fy)

    if kind == 'ring':
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=acc, width=lw)
        q = u * .075
        d.ellipse([cx - q, cy - q, cx + q, cy + q], fill=acc)
    elif kind == 'bars':
        for i, hh in enumerate((.30, .55, .80)):
            x0 = ox + u * (.24 + .19 * i)
            d.rounded_rectangle([x0, oy + u * (.78 - hh * .52), x0 + u * .115, oy + u * .78],
                                radius=u * .055, fill=acc)
    elif kind == 'grid':
        for i in (0, 1):
            for j in (0, 1):
                p0, p1 = P(.26 + .28 * i, .26 + .28 * j), P(.44 + .28 * i, .44 + .28 * j)
                d.rounded_rectangle([p0[0], p0[1], p1[0], p1[1]], radius=u * .05, fill=acc)
    elif kind == 'clock':
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=acc, width=lw)
        d.line([cx, cy, cx, cy - r * .62], fill=acc, width=lw, joint='curve')
        d.line([cx, cy, cx + r * .55, cy], fill=acc, width=lw, joint='curve')
    elif kind == 'wave':
        d.line([P(.20, .70), P(.42, .30), P(.55, .58), P(.80, .26)], fill=acc, width=lw,
               joint='curve')
    elif kind == 'coin':
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=acc, width=lw)
        d.line([cx, cy - r * .52, cx, cy + r * .52], fill=acc, width=lw)
        t = max(2, lw - 3)
        d.line([cx - r * .30, cy - r * .22, cx + r * .30, cy - r * .22], fill=acc, width=t)
        d.line([cx - r * .30, cy + r * .22, cx + r * .30, cy + r * .22], fill=acc, width=t)
    elif kind == 'dot':
        for i in range(3):
            yy = oy + u * (.29 + .21 * i)
            q = u * .045
            d.ellipse([ox + u * .25 - q, yy - q, ox + u * .25 + q, yy + q], fill=acc)
            d.line([ox + u * .40, yy, ox + u * (.84 - .09 * i), yy], fill=acc,
                   width=max(2, lw - 2))
    elif kind == 'gear':
        q = r * .52
        d.ellipse([cx - q, cy - q, cx + q, cy + q], outline=acc, width=max(2, lw - 2))
        for ang in range(0, 360, 45):
            dx, dy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            d.line([cx + dx * r * .68, cy + dy * r * .68, cx + dx * r * 1.02, cy + dy * r * 1.02],
                   fill=acc, width=lw)
    elif kind == 'minus':
        t = u * .30
        d.rounded_rectangle([cx - t, cy - u * .045, cx + t, cy + u * .045], radius=u * .045, fill=acc)
    elif kind == 'peek':
        q = u * .30
        d.ellipse([cx - q, cy - q, cx + q, cy + q], outline=acc, width=max(2, int(u * .06)))
        q = u * .115
        d.ellipse([cx - q, cy - q, cx + q, cy + q], fill=acc)
    elif kind == 'knob':
        q = u * .33
        d.ellipse([cx - q, cy - q, cx + q, cy + q], fill=_rgba('#f4f9ff'), outline=acc,
                  width=max(2, int(u * .075)))
    elif kind == 'cdot':
        q = u * .30
        d.ellipse([cx - q, cy - q, cx + q, cy + q], fill=acc, outline=_rgba(CARD),
                  width=max(2, int(u * .10)))
    elif kind == 'fill':
        q = u * .40
        d.ellipse([cx - q, cy - q, cx + q, cy + q], fill=acc)
    elif kind in ('boxon', 'boxoff'):
        q = u * .30
        d.rounded_rectangle([cx - q, cy - q, cx + q, cy + q], radius=u * .10,
                            fill=_rgba(_mix(CARD, color, .22 if kind == 'boxon' else 0)),
                            outline=acc, width=max(2, int(u * .075)))
        if kind == 'boxon':
            d.line([ox + u * .33, oy + u * .52, ox + u * .45, oy + u * .66,
                    ox + u * .68, oy + u * .34], fill=acc, width=max(2, int(u * .09)),
                   joint='curve')


def _glyph_img(px, kind, color, chip=True, mat=CARD, hard=False):
    """独立小图标(滑块头/曲线点/图例点/角落圆点): 同样 4x 超采样。"""
    k = (px, kind, color, chip, mat, hard)
    img = _GLY.get(k)
    if img is None:
        from PIL import Image, ImageDraw
        u = px * 4
        im = Image.new('RGBA', (u, u), (0, 0, 0, 0))
        _draw_glyph(ImageDraw.Draw(im), kind, color, 0, 0, u, chip)
        img = _bake(im, px, px, mat, hard=hard)
        _GLY[k] = img
    return img
