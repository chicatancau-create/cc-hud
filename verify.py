import ctypes
import ctypes.wintypes as wt
import datetime as dt
import re
import glob, json, os, subprocess, sys, tempfile, time
from importlib.machinery import SourceFileLoader
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.getcwd())
m = SourceFileLoader('hud', 'cc-hud.pyw').load_module()
m._dpi_aware()
REAL_RUN_POWER = m.run_power        # J 段会把 m.run_power 打桩, T1 要拿真函数验参数
import tkinter as tk


# DSH 是**活数据源**: 正在跑的这个会话自己就在往 sessions/*.json 的 tokenUsage 累计值里加数
# (实测 6s 涨 13.3 万 token)。N 段与 V8 都要"拿 HUD 的数"与"独立基线自己再读一遍"比对,
# 两次读之间只要有别的会话落盘, 同一次运行就会随机红 —— 那是测试竞态, 不是代码错。
# 所以整轮验证先把会话 json 复制成一份冻结快照, 再把 m.DSH_DIR 指过去(与 U 段换 QDIR 同一套
# 打桩手法, 转发器会让 cchud.const/cchud.data 读到同一个值)。
# 这样做**不是放宽判据**: 两条路径读的是同一份字节, 断言反而从"容差"收紧成精确相等。
_REAL_DSH_DIR = m.DSH_DIR
_DSH_SNAP = os.path.join(tempfile.gettempdir(), 'cc-hud-verify-dsh-snapshot')
try:
    if os.path.isdir(_DSH_SNAP):
        import shutil
        shutil.rmtree(_DSH_SNAP, ignore_errors=True)
    if os.path.isdir(_REAL_DSH_DIR):
        os.makedirs(_DSH_SNAP)
        import shutil
        for _p in glob.glob(os.path.join(_REAL_DSH_DIR, '*.json')):
            shutil.copy2(_p, _DSH_SNAP)
        m.DSH_DIR = _DSH_SNAP
except OSError:
    pass                    # 快照建不出来就照旧读真目录(可能偶发竞态, 但不至于跑不了)

# 真机安全闸: 把 subprocess 的两个出口包起来, 全程记录有没有人碰过 shutdown。
# (J 段的电源打桩只证明"桩被叫了几次", 证不了没有别的路径真调用 —— 这条才是外部证据)
POWERCALLS = []
_op, _orun = m.subprocess.Popen, m.subprocess.run


def _spyP(*a, **k):
    POWERCALLS.append(' '.join(str(x) for x in (a[0] if a else k.get('args', []))))
    raise AssertionError('测试里不许真的执行电源命令: ' + str(a))


def _spyR(*a, **k):
    POWERCALLS.append(' '.join(str(x) for x in (a[0] if a else k.get('args', []))))
    return type('R', (), {'returncode': 0, 'stdout': b'', 'stderr': b''})()


m.subprocess.Popen = _spyP
m.subprocess.run = _spyR
ORIG_STATE = None
h = m.HUD()
ORIG_STATE = dict(h.state)            # 用户此刻的偏好; 收尾要还原成这个, 不是还原成旧备份
h.root.update()
cv = h.cv

# 直接数 delete/create 调用, 不靠图元 id(Tk 会复用 id)
cnt = {'del': 0, 'cre': 0}
_od = tk.Canvas.delete


def _nd(self, *a, **k):
    if a and a[0] not in ('all', 'fg'):
        cnt['del'] += 1
    elif a and a[0] == 'fg':
        cnt['del'] += 999
    return _od(self, *a, **k)


tk.Canvas.delete = _nd
NAMES = ('create_text', 'create_rectangle', 'create_line', 'create_oval', 'create_polygon',
         'create_arc')
saved = {}
for nm in NAMES:
    orig = getattr(tk.Canvas, nm)
    saved[nm] = orig

    def mk(orig=orig):
        def patched(self, *a, **k):
            cnt['cre'] += 1
            return orig(self, *a, **k)
        return patched
    setattr(tk.Canvas, nm, mk())

print('=== A. 无闪烁判据: 一次刷新里到底删/建了多少图元 ===')
for lab in ('收起', '展开'):
    if lab == '展开':
        h.expanded = True
        h.refresh()
    cnt['del'] = cnt['cre'] = 0
    h.refresh()
    print('  %s: 本次刷新 新建 %d 个图元, 单个删除 %d 个, 整组删除 %s  '
          '(画布现有 %d 个图元)'
          % (lab, cnt['cre'], cnt['del'], '有' if cnt['del'] >= 999 else '无', len(cv.find_all())))

tk.Canvas.delete = _od
for nm in NAMES:
    setattr(tk.Canvas, nm, saved[nm])

print('=== B. 越界/裁切 ===')


def overflow(tag):
    W, H = h.W, h._H
    bad = []
    for i in cv.find_all():
        try:
            bb = cv.bbox(i)
        except tk.TclError:
            continue
        if bb is None:                      # state=hidden 的图元没有 bbox
            continue
        x0, y0, x1, y1 = bb
        if x0 < -1 or y0 < -1 or x1 > W + 1 or y1 > H + 1:
            bad.append((cv.type(i), (cv.itemcget(i, 'text') if cv.type(i) == 'text' else '')[:26],
                        (x0, y0, x1, y1)))
    print('  %s: 窗口 %dx%d, 越界图元 %d 个' % (tag, W, H, len(bad)))
    for b in bad[:6]:
        print('     ', b)
    return bad


h.expanded = False
h.refresh()
overflow('收起')
h.expanded = True
h.refresh()
h.root.update()
overflow('展开')

print('=== B2. 文字互撞检查(同一行两个 text 图元的 bbox 重叠) ===')


def collisions():
    txt = []
    for i in cv.find_all():
        if cv.type(i) != 'text':
            continue
        try:
            bb = cv.bbox(i)
        except tk.TclError:
            continue
        if bb and cv.itemcget(i, 'text').strip():
            txt.append((bb, cv.itemcget(i, 'text')[:20]))
    bad = []
    for a in range(len(txt)):
        for b in range(a + 1, len(txt)):
            (ax0, ay0, ax1, ay1), at = txt[a]
            (bx0, by0, bx1, by1), bt = txt[b]
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if ox > 0 and oy > 3:
                bad.append(('重叠', at, bt, int(ox), int(oy)))
            elif -4 < ox <= 0 and oy > 3:
                bad.append(('贴太近', at, bt, int(ox), int(oy)))
    print('  冲突/过近文字对 %d' % len(bad))
    for x in bad[:8]:
        print('    ', x)
    return bad


def trunc():
    t = [cv.itemcget(i, 'text') for i in cv.find_all()
         if cv.type(i) == 'text' and str(cv.itemcget(i, 'text')).endswith('…')]
    print('  被截断的文字 %d 条' % len(t))
    for x in t:
        print('    …', x)
    return t


h.expanded = False
h.refresh()
collisions()
trunc()
h.expanded = True
h.refresh()
h.root.update()
collisions()
trunc()
h.expanded = False

def card_over(tag):
    """逐条文字量它是否越出**所属卡片**的右内边界。窗口越界(B 段)抓不到这个:
    宽版列卡只有 482px, 文字溢出后仍在窗口内, 却会压到隔壁列上。"""
    bad = []
    for k, i in h.ids.items():
        if cv.type(i) != 'text':
            continue
        pre = k.split('.')[0]
        cb = pre + '.bg'
        if cb not in h.ids:
            continue
        try:
            x1 = cv.bbox(i)[2]
            cx1 = cv.bbox(h.ids[cb])[2]
        except Exception:
            continue
        lim = cx1 - int(round(11 * h.s))
        if x1 - lim > 1:
            bad.append((k, int(x1 - lim), str(cv.itemcget(i, 'text'))[:36]))
    print('  %s: 越出所属卡片右内边界的文字 %d 处 %s (期望 0)'
          % (tag, len(bad), bad[:3] or ''))
    return bad


print('=== B3. 卡内越界(窗口越界抓不到: 宽版列卡只有 482px, 溢出会压到隔壁列) ===')
_ov = []
for _tag, _e, _w in (('收起', False, False), ('竖版', True, False), ('宽版', True, True)):
    h.expanded, h.wide = _e, _w
    h.refresh()
    h.root.update()
    _ov += card_over(_tag)
h.expanded, h.wide = True, True
h.refresh()
h.root.update()
print('  三态合计越界 %d 处 (期望 0 —— 曾经因为 paint 用了"最后一张卡的 cw"而溢出 157px)' % len(_ov))

print('=== C. 键色镂空 ===')
try:
    h.root.attributes('-transparentcolor', m.BG)
    on = h.root.attributes('-transparentcolor')
    h.root.attributes('-transparentcolor', '')
    off = h.root.attributes('-transparentcolor')
    print('  设置 ->', on, ' 清除 ->', off)
    # 必须还原成镂空: 之前留了个空值就走人, 后面所有段量的都是"非镂空"窗口,
    # 与用户实机看到的不是同一个东西(圆角边缘、接缝那些问题就是这样被漏掉的)
    h.root.attributes('-transparentcolor', m.BG)
    back = h.root.attributes('-transparentcolor')
    print('  已还原镂空 %r · _hollowed=%s (期望 %r / True)'
          % (str(back), h._hollowed, m.BG))
    assert str(back) == m.BG and h._hollowed, 'C 段没把镂空还原回去'
except Exception as e:
    print('  失败:', repr(e)[:120])
    raise

print('=== D. 数值 ===')
d = h._read(h._start())
print('  %s: 请求 %d 成本 %.4f 命中率 %.2f%% 四项和差 %.8f'
      % (m.RANGES[h.range_i][0], d['reqs'], d['cost'], d['hit'],
         d['cin'] + d['cout'] + d['crd'] + d['cwr'] - d['cost']))
print('  近5h %s 近1h %s 今日 %s 昨日 %s' % (d['h5'], d['h1'], d['today'], d['yday']))
print('  延迟样本 %d/%d 首token %s 生成 %s 耗时 %s'
      % (d['lat']['n'], d['reqs'], d['lat']['ftt'], d['lat']['sp_g'], d['lat']['p50']))
print('=== E. 跑遍 4 个范围 × 2 个状态, 找静默失效的槽位 ===')
print('  前置: CC Switch PID %s · 窗口可见 %s (隐藏时 refresh 不读库, 上面各项会全是空)'
      % (m.ccswitch_pid(), h._shown))
# 前置只打印不断言 = 面板被哪一步藏起来之后, B/E 整段在空画布上跑完还全绿(历史上真发生过)
h._set_visible(True)
h.root.update()
assert h._shown and h.root.winfo_ismapped() and len(h.cv.find_all()) > 30,     'E 段前置不成立: 面板没在显示/画布是空的, 越界与撞字检查等于没跑'
h._missing.clear()
sizes = {}
for exp in (False, True):
    h.expanded = exp
    for i in range(len(m.RANGES)):
        h.range_i = i
        h.refresh()
        h.root.update()
    sizes[exp] = (h.W, h._H)
print('  未登记槽位 %d 个: %s' % (len(h._missing), sorted(h._missing) or '无'))
print('  收起 %dx%d / 展开 %dx%d' % (sizes[False][0], sizes[False][1],
                                     sizes[True][0], sizes[True][1]))
print('  面板底边不许越过工作区(任务栏):')
for exp in (False, True):
    h.expanded = exp
    h.root.geometry('+1995+45')          # 故意摆在用户那个位置: 展开态会顶到任务栏
    h.refresh()
    for _ in range(25):
        h.root.update()
        time.sleep(0.02)
    wb = m._work_area()[3]
    y0, hh = h.root.winfo_y(), h.root.winfo_height()
    print('    %s y=%d h=%d 底=%d ≤ 工作区底 %d → %s (期望 1)'
          % ('收起' if not exp else '展开', y0, hh, y0 + hh, wb, int(y0 + hh <= wb)))

print('=== F. 显示/隐藏边沿判定 + 隐藏期间零读库(不跟随模式) ===')
reads = [0]
_orig_read = h._read


def _counting(start):
    reads[0] += 1
    return _orig_read(start)


h._read = _counting
real = m.ccswitch_pid
t0 = time.perf_counter()
for _ in range(20):
    m.ccswitch_pid()
print('  轮询 20 次耗时 %.1f ms (每次 %.2f ms, 3s 一轮 -> 占空比 %.3f%%)'
      % ((time.perf_counter() - t0) * 1000, (time.perf_counter() - t0) * 50,
         (time.perf_counter() - t0) / 20 / 3.0 * 100))

# 这一段验的是「隐藏 + 停止读库」那条路; 开了跟随的话掉线是直接退出(那是 X4 的事),
# 所以这里先关掉跟随, 免得把主实例拆了后面全崩。
h.follow = False
m.ccswitch_pid = lambda: None                    # 假装 CC Switch 退出
h._n = m.CC_TICKS - 1                            # 让这一拍真的去查进程
h._tick()
h.root.update()
off_mapped = h.root.winfo_ismapped()
r0 = reads[0]
h._last = 0                                      # 逼一次到期刷新, 看它读不读
h._tick()
h.root.update()
r1 = reads[0]
m.ccswitch_pid = lambda: 999999                  # 假装 CC Switch 又起来
h._n = m.CC_TICKS - 1
h._tick()
h.root.update()
on_mapped = h.root.winfo_ismapped()
r2 = reads[0]
m.ccswitch_pid = real
h.follow = True
print('  不跟随模式下掉线 -> 已隐藏 %s (期望 1; 跟随模式下的掉线退出见 X4)' % int(not off_mapped))
print('  隐藏期间到期刷新 读库次数 %d (期望 0)' % (r1 - r0))
print('  CC Switch 上线 -> 已显示 %s, 读库 %d 次 (期望 1 / 1)' % (int(on_mapped), r2 - r1))
h._read = _orig_read

print('=== G. 托盘: 图标挂上了吗 + 点一下能不能把隐藏的卡片叫回来 ===')
print('  托盘对象: %s' % ('挂上(NIM_ADD 成功), 消息窗口 hwnd=%s' % h.tray.hwnd if h.tray
                          else '挂不上 -> ' + str(h.note)))
u = ctypes.windll.user32
u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]

# G0 图标**本体**取证: NIM_ADD 对 hIcon=0 也返回成功, 所以"挂上了"根本证明不了看得见。
#     实测旧代码的 ICONINFO 少两个字段 -> CreateIconIndirect 返回 NULL -> 托盘里就是一个
#     透明空槽(用户在通知区域截图里看到的那个)。这里直接量位图像素。
class _BM(ctypes.Structure):
    _fields_ = [('bmType', ctypes.c_long), ('bmWidth', ctypes.c_long),
                ('bmHeight', ctypes.c_long), ('bmWidthBytes', ctypes.c_long),
                ('bmPlanes', wt.WORD), ('bmBitsPixel', wt.WORD), ('bmBits', ctypes.c_void_p)]


class _ICO(ctypes.Structure):
    _fields_ = [('fIcon', wt.BOOL), ('xHotspot', wt.DWORD), ('yHotspot', wt.DWORD),
                ('hbmMask', ctypes.c_void_p), ('hbmColor', ctypes.c_void_p)]


g32 = ctypes.windll.gdi32
g32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
g32.GetBitmapBits.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
g32.DeleteObject.argtypes = [ctypes.c_void_p]
u.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ICO)]
u.GetIconInfo.restype = wt.BOOL
bad = []
for on in (True, False):
    hi = m._hicon(16, on)
    ii = _ICO()
    if not hi or not u.GetIconInfo(hi, ctypes.byref(ii)):
        bad.append(('句柄无效', on, hi))
        continue
    bm = _BM()
    g32.GetObjectW(ii.hbmColor, ctypes.sizeof(bm), ctypes.byref(bm))
    buf = ctypes.create_string_buffer(bm.bmWidth * bm.bmHeight * 4)
    g32.GetBitmapBits(ii.hbmColor, bm.bmWidth * bm.bmHeight * 4, buf)
    px = bytes(buf.raw)
    lit = sum(1 for i in range(3, len(px), 4) if px[i] > 8)
    print('  G0 图标 on=%-5s HICON=%s %dx%d 位深%d · 不透明像素 %d/%d'
          % (on, bool(hi), bm.bmWidth, bm.bmHeight, bm.bmBitsPixel, lit, bm.bmWidth * bm.bmHeight))
    if not (bm.bmBitsPixel == 32 and lit > bm.bmWidth * bm.bmHeight * 0.2):
        bad.append(('像素不对', on, bm.bmBitsPixel, lit))
    for hbm in (ii.hbmColor, ii.hbmMask):
        if hbm:
            g32.DeleteObject(hbm)
    u.DestroyIcon(hi)
print('  注册中的图标句柄非 0: %s (期望 True —— 0 就是外壳里的透明空槽)'
      % int(bool(h.tray and h.tray.nid.hIcon)))
assert not bad and h.tray and h.tray.nid.hIcon, bad


def pump(sec=0.5):
    """真链路: PostMessage -> 消息泵 -> WndProc -> 队列 -> Tk 侧 _tick 消费。"""
    msg = wt.MSG()
    end = time.time() + sec
    while time.time() < end:
        while u.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))
        h.root.update()
        time.sleep(0.01)


if h.tray:

    h._set_visible(False)
    pump(0.3)
    hid = not h.root.winfo_ismapped()
    u.PostMessageW(h.tray.hwnd, m.WM_TRAY, 1, 0x202)      # 模拟托盘左键
    pump()
    back = bool(h.root.winfo_ismapped())
    u.PostMessageW(h.tray.hwnd, m.WM_TRAY, 1, 0x202)      # 再点一次 = 再隐藏
    pump()
    away = not h.root.winfo_ismapped()
    print('  先隐藏 -> 已隐藏 %s (期望 1)' % int(hid))
    print('  托盘左键 -> 重新显示 %s (期望 1)' % int(back))
    print('  再点一次 -> 又隐藏 %s (期望 1)' % int(away))
    u.PostMessageW(h.tray.hwnd, m.WM_TRAY, 1, 0x202)
    pump(0.3)
    print('  悬停提示: %r' % h.tray._tip)
    h.tray.quit()

print('=== H. 角落呼出点: 隐藏后有没有留下可点的东西, 能不能拖走 ===')
h._set_visible(False)
pump(0.25)
dot_on = bool(h._pk and h._pk.winfo_ismapped())
panel_off = not h.root.winfo_ismapped()
x, y = h._pk.winfo_x(), h._pk.winfo_y()
w, hh = h._pk.winfo_width(), h._pk.winfo_height()
al, at, ar, ab = m._work_area()
inside = al <= x and x + w <= ar and at <= y and y + hh <= ab
print('  隐藏后: 圆点已显示 %s · 主卡片已收起 %s (期望 1 / 1)' % (int(dot_on), int(panel_off)))
print('  圆点 %dx%d 于 (%d,%d) · 工作区 (%d,%d)-(%d,%d) 内 %s (期望 1)'
      % (w, hh, x, y, al, at, ar, ab, int(inside)))


class _Ev:
    def __init__(self, xr, yr):
        self.x_root, self.y_root = xr, yr


h._pk_drag = (0, 0, x, y)                          # 走拖动分支: 按下点与松开点差 >5px
h._pk.geometry('+%d+%d' % (x - 180, y + 260))
pump(0.15)                                         # 真实拖动时松开前几何早已生效, 这里要补一轮
h._pk_up(_Ev(x - 180, y + 260))
pump(0.2)                                          # geometry 要过一轮事件才读得到新值
nx, ny = h._pk.winfo_x(), h._pk.winfo_y()
saved = h._load().get('peek')
print('  拖到 (%d,%d) -> 位置已改 %s · 写进 hud-state.json %s (期望 1 / 1)'
      % (nx, ny, int((nx, ny) != (x, y)), int(saved == [nx, ny])))
h._pk.geometry('+%d+%d' % (x, y))                  # 复位, 别把测试位置留给下一次
h.state['peek'] = [x, y]
h._save()
h._pk_drag = (0, 0, x, y)                          # 原地松开 = 点击
h._pk_up(_Ev(x, y))
pump(0.3)
back = bool(h.root.winfo_ismapped())
gone = not h._pk.winfo_ismapped()
print('  点一下圆点 -> 主卡片回来 %s · 圆点自己收掉 %s (期望 1 / 1)' % (int(back), int(gone)))
h._set_visible(False)
pump(0.2)
m.ccswitch_pid = lambda: None
h._cc_up = False
h._pk_color()
h.root.update()
print('  CC Switch 没在跑时圆点换色: %s (期望 1)'
      % int(h._pk_img is m._glyph_img(h._pk_d, 'peek', m.FAINT, chip=False, mat=m.BG, hard=True)))
m.ccswitch_pid = real
h._pk_drag = None

print('=== I. 空范围不崩 + 红字会被成功绘制清掉 + 悬停读数 ===')


class _E:
    def __init__(self, x, y, xr=0, yr=0):
        self.x, self.y, self.x_root, self.y_root = x, y, xr, yr


h._set_visible(True)                             # H 段结束时是隐藏的; 不先显示, refresh 会早退, 本节全成空测
h.expanded = True
h.refresh(True)
h.range_i = 0                                    # 今日: 这个点还没有任何请求, 就是它把 max([]) 炸的
h.refresh()
h.root.update()
d0 = h._read(h._start())
print('  空范围 %s: 行数 %d 请求 %d' % (m.RANGES[0][0], len(d0['daily']), d0['reqs']))
print('  画布上的绘制异常红字 %d 个 (期望 0)' % len(h.cv.find_withtag('fatal')))
print('  趋势卡提示语: %r' % h.cv.itemcget(h.ids['c6.rt'], 'text'))
h.range_i = 3
h.refresh(True)
h.root.update()
print('  换回有数据范围后红字 %d 个 (期望 0)' % len(h.cv.find_withtag('fatal')))

h.range_i = 1
h.refresh(True)
h.root.update()
p = h._plot
if not p:
    print('  7 天范围没有可悬停的数据点 —— 悬停测试跳过, 不算通过')
else:
    days, x0, yt, step, H, pad, mt, mc = p
    h._hover(_E(x0 + step * 2, yt + 10, 1900, 300))
    h.root.update()
    tip = h._tip_lab.cget('text')
    print('  悬停第3天 -> 读数框映射 %s · 十字线 %s' % (int(h._tipw.winfo_ismapped()),
                                                  h.cv.itemcget(h.xhair, 'state')))
    print('    内容: %s' % tip.replace(chr(10), ' / '))
    print('    首行日期 == 库里那天: %s (期望 1)' % int(tip.split(chr(10))[0].startswith(days[2][0])))
    h._hover(_E(x0 + step * 2, yt + H + 60))     # 移出绘图区
    h.root.update()
    print('  移出图区 -> 读数框收起 %s · 十字线 %s (期望 1 / hidden)'
          % (int(not h._tipw.winfo_ismapped()), h.cv.itemcget(h.xhair, 'state')))

print('=== J. 定时操作: 到点执行 / 倒计时显示 / 取消 (电源动作打桩, 不碰真机) ===')
ran = []
m.run_power = lambda kind: (ran.append(kind), True)[1]   # 真实现现在要返回"是否下发成功"
# abort_power 也必须在段首就换掉: cancel_power() 在 fired=True 时会真去跑 `shutdown /a`,
# 那会悄悄撤掉用户机器上别的待关机任务。以前它是在段尾才打桩的, 靠时序侥幸。
ab_note = []
m.abort_power = lambda: (ab_note.append('a'), True)[1]
h._tip_hide()
h.range_i = 3
h.pmin = 15
h.arm('off')
pump(0.4)
line = h.cv.itemcget(h.ids['foot.m'], 'text')
def cancel_kind(spec):
    return [it[0] for it in spec if len(it) > 1 and it[1] == '取消定时']

pw = [it[1] for it in h.power_spec() if it[0] not in ('sep', 'gap')]
print('  设了「到点关机 15 分钟」: 底栏 %r' % line)
print('  子菜单状态行 %r · 取消项类型 %s (期望 含剩1x:xx / scmd=点完不关)'
      % ([x for x in pw if '定时关机' in x][0], cancel_kind(h.power_spec())))
print('  倒计时已在跑 %s (期望 1)' % int(h.deadline is not None and '定时关机' in line))
h.cancel_power()
pump(0.2)
print('  取消后: deadline %s · 取消项退回成灰字 %s (期望 None / info)'
      % (h.deadline, cancel_kind(h.power_spec())))
h.arm('sleep')
h.deadline = time.time() + 0.3
pump(0.9)
print('  到点执行: run_power 收到 %s · deadline 已清空 %s (期望 [sleep] / None)' % (ran, h.deadline))
h.arm('off')
h.deadline = time.time() + 0.3
pump(0.9)
ab = []
m.abort_power = lambda: (ab.append('a'), True)[1]
h.cancel_power()
print('  已触发后取消 -> 撤系统倒计时被调用 %s · 取消后退回灰字 %s (期望 1 / info)'
      % (int(bool(ab)), cancel_kind(h.power_spec())))
print('  全程没有真的调用 shutdown: %s (期望 1)' % int(ran.count('off') + ran.count('sleep') == 2))

print('=== K. 自绘右键菜单: 位置不挡字 / 弹出与条目 / 子菜单存活 / 外点关闭 ===')
_u = ctypes.windll.user32


def rects(p):
    return (p.win.winfo_rootx(), p.win.winfo_rooty(), p.w, p.h)


def ov(a, b):
    """两层矩形的重叠面积。子层盖住父层的条目区 = 下面那些条目永远点不到。
    设计上只允许一条 <=8px 的接缝(横移时不留死区), 所以看 ox 而不是面积。"""
    ox = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    oy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return ox, ox * oy


for mx, tag in ((120, '屏幕左侧起'), (int(_u.GetSystemMetrics(0) * 0.96) - 170, '屏幕右边缘起')):
    h._close_menu()
    pp = h.open_menu(mx, 200)
    h.root.update()
    _si = [i for i, r in enumerate(pp.rows) if r[2][0] == 'sub'][0]
    pp._open_sub(_si)
    h.root.update()
    kk = pp.kids[0]
    ox, area = ov(rects(pp), rects(kk))
    print('  %s: 父层 x=%d w=%d · 子层 x=%d w=%d · 展开方向 %s · 横向重叠 %d px (期望 <=8, 只有接缝)'
          % (tag, pp.gx, pp.w, kk.gx, kk.w,
             '右' if kk.gx >= pp.gx + pp.w - 8 else '左(右边缘放不下, 已翻转)', ox))
    print('    子层没压住父层条目区 %s · 两层的纵向接缝存在 %s (期望 1 / 1)'
          % (int(ox <= 8), int(area > 0)))
    pp.close()
h.root.update()

h._close_menu()
p0 = h.open_menu(120, 200)          # 右侧留空间, 走正常展开方向
h.root.update()
p0._hover(0)
lb = p0.labels()
print('  顶层 %d 项, 前 6 项: %s' % (len(lb), [x[1] for x in lb[:6]]))
print('  弹出后窗口映射 %s · 有圆角壳图元 %s (期望 1 / 1)'
      % (int(p0.win.winfo_ismapped()), int(len(p0.imgs) > 1)))
si = [i for i, r in enumerate(p0.rows) if r[2][0] == 'sub'][0]   # 行号≠条目号: 分隔符不占行
p0._open_sub(si)
h.root.update()
sub = p0.kids[0]
print('  定时操作子菜单 %d 项, 含 %s' % (len(sub.rows), [x[1] for x in sub.labels()][:4]))
print('  请求坐标与实际窗口左上角一致 父 %s 子 %s (期望 1 / 1 —— 判定「点在外面」要用它)'
      % (int((p0.gx, p0.gy) == (p0.win.winfo_rootx(), p0.win.winfo_rooty())),
         int((sub.gx, sub.gy) == (sub.win.winfo_rootx(), sub.win.winfo_rooty()))))
inds = [r[5] for r in p0.rows if r[5] is not None]
print('  指示符(●/✓/▸) %d 个, 亮着 %d 个 · 悬停行高亮 %s (期望 >0 / >0 / 1)'
      % (len(inds), sum(1 for o in inds if p0.cv.itemcget(o, 'state') == 'normal'),
         int(p0.cv.itemcget(p0.rows[0][3], 'state') == 'normal')))


class _MI(ctypes.Structure):
    _fields_ = [('dx', wt.LONG), ('dy', wt.LONG), ('mouseData', wt.DWORD),
                ('dwFlags', wt.DWORD), ('time', wt.DWORD), ('dwExtraInfo', ctypes.c_void_p)]


class _INP(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [('mi', _MI)]

    _fields_ = [('type', wt.DWORD), ('u', _U)]


def where():
    p = wt.POINT()
    _u.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def idle(sec=0.18):
    """只跑 Tk 自己的循环。实测: 若先用 PeekMessage+DispatchMessage 抢先把 WM_MOUSEMOVE
    投出去, Tk 的 Motion 事件会被排队后不再补发(Enter 照发), 真链路取证必须走这里。"""
    end = time.time() + sec
    while time.time() < end:
        h.root.update()
        time.sleep(0.01)


def wmove(tx, ty, tries=4):
    """先 SetCursorPos 精确落位(实测准, 但只触发 Enter 不触发 Motion), 再对同一点发一次
    绝对 SendInput 走真输入栈补出 WM_MOUSEMOVE —— 两种单独用都不行(见实测)。"""
    vx, vy = _u.GetSystemMetrics(76), _u.GetSystemMetrics(77)
    vw, vh = _u.GetSystemMetrics(78), _u.GetSystemMetrics(79)
    tx, ty = max(3, min(tx, vx + vw - 4)), max(3, min(ty, vy + vh - 4))
    for _ in range(tries):
        _u.SetCursorPos(tx - 2, ty)         # 先偏 2px 再绝对落到目标: 零位移的绝对注入
        i = _INP()                           # Windows 不派发 Motion(实测), 所以要留位移
        i.type = 0
        i.u.mi = _MI(int((tx - vx) * 65535 / max(1, vw - 1)),
                     int((ty - vy) * 65535 / max(1, vh - 1)), 0, 0x0001 | 0x8000, 0, None)
        _u.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INP))
        idle()
        ax, ay = where()
        if abs(ax - tx) <= 2 and abs(ay - ty) <= 2:
            return ax, ay
        idle(0.10)                            # 落点偏了多半是有人手在动鼠标: 原目标重试
    return where()


if p0._job:                       # 取证期间停掉「外点自动关」, 免得旁人的真点击把窗口拆了
    h.root.after_cancel(p0._job)
    p0._job = None
save_xy = where()
print('  菜单打开时应用是否持有 grab: %s (期望 None —— 有 grab 时子层一个事件都收不到)'
      % (h.root.grab_current()))

_u.GetAncestor.argtypes = [wt.HWND, ctypes.c_uint]
_u.GetAncestor.restype = wt.HWND
_u.WindowFromPoint.restype = wt.HWND


def nhwin(win):
    return _u.GetAncestor(win.winfo_id(), 2) or win.winfo_id()          # 2 = GA_ROOT


def nh(p):
    """浮层真正的顶层 HWND(Tk 的 wrapper 可能被包在里面)。"""
    return nhwin(p.win)


def wrect(p):
    r = wt.RECT()
    _u.GetWindowRect(nh(p), ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def owner(x, y):
    hh = _u.WindowFromPoint(wt.POINT(int(x), int(y)))
    c = ctypes.create_unicode_buffer(64)
    _u.GetClassNameW(hh, c, 64)
    pid = wt.DWORD()
    _u.GetWindowThreadProcessId(hh, ctypes.byref(pid))
    return hh, c.value, pid.value


MY_PID = ctypes.windll.kernel32.GetCurrentProcessId()

tkA = (p0.win.winfo_rootx(), p0.win.winfo_rooty(), p0.w, p0.h)
realA = wrect(p0)
print('  父层: Tk 报 %s / Win32 实得 %s · 一致 %s (期望 1 —— 判定「点在外面」按 Tk 坐标算)'
      % (tkA, realA, int(tkA == realA)))
hh, wc, wpid = owner(realA[0] + realA[2] // 2, realA[1] + realA[3] // 2)
print('  父层中点命中测试: hwnd=%s(%s) 属于本进程 %s · Tk 认为是这个控件 %s (期望 1 / 1)'
      % (wc, hh, int(wpid == MY_PID),
         int(_u.GetAncestor(hh, 2) == nh(p0))))
allev = []
h.root.bind_all('<Motion>', lambda e: allev.append('motion:' + str(e.widget)))
h.root.bind_all('<Enter>', lambda e: allev.append('enter:' + str(e.widget)))
h.expanded = False          # 主卡片(收起 530x353)挪到别处: 它要是盖住菜单落点, Tk 会把
h.refresh()                # Motion 记到主画布上, 浮层就「看不见鼠标」了
h.root.geometry('+1500+40')
h.root.update()
h.root.lift()
h.root.update()




def hop(win, xoff, yoff, tag):
    """把真游标挪到某一层某个位置, 用两条独立途径确认这个像素归这一层。"""
    tx, ty = win.winfo_rootx() + xoff, win.winfo_rooty() + yoff
    ax, ay = wmove(tx, ty)
    hh, wc, wpid = owner(ax, ay)
    mine = int(wpid == MY_PID and hh and _u.GetAncestor(hh, 2) == nhwin(win))
    cw = h.root.winfo_containing(ax, ay)
    tk_top = str(cw.winfo_toplevel()) if cw else '-'
    print('  %s 游标(%d,%d): Win32 命中归这层 %s · Tk 命中浮层 %s'
          % (tag, ax, ay, mine, tk_top == str(win)))
    return ax, ay, mine, tk_top


p0got, probe = [], []
p0.cv.bind('<Motion>', lambda e: p0got.append(1), add='+')
ki = [i for i, r in enumerate(sub.rows)
      if r[2][0] == 'radio' and not r[2][2]][0]      # 挑一个没被选中的, 好看出命令真的跑了
wmove(int(_u.GetSystemMetrics(0) * 0.9), int(_u.GetSystemMetrics(1) * 0.8))
if p0.kids:
    p0._close_subs()
p0.sub_i = p0.active = -1
p0._open_sub(si)                                     # 重新开一层, 后面的 SUB 才是活的那个
h.root.update()
SUB = p0.kids[0]
SUB.cv.bind('<Motion>', lambda e: probe.append(1), add='+')
axA, ayA, mineA, _ = hop(p0.win, p0.w // 2, (p0.rows[si][0] + p0.rows[si][1]) // 2,
                         '父层「%s」行' % p0.rows[si][2][1])
axB, ayB, mineB, _ = hop(SUB.win, SUB.w - 14, (SUB.rows[ki][0] + SUB.rows[ki][1]) // 2,
                         '子层第%d行「%s」' % (ki, SUB.rows[ki][2][1]))
print('  两层各占住自己那块像素(谁也没盖住谁) %s (期望 1)' % int(mineA and mineB))
# 事件派发用 event_generate 走 Tk 自己的派发链: 注入(SendInput)的移动在本机不产生 Tk
# Motion, 只有真人手移动才产生 —— 这一点在 grab 对照实验里量到了(TEMP/pop_grab_probe2.py:
# 同一只手的路径, 无 grab 时归 B 浮层, 有 grab 时全被劫持到 A 且坐标落到 A 外面)。
allev.clear()
p0.cv.event_generate('<Motion>', x=axA - p0.win.winfo_rootx(), y=ayA - p0.win.winfo_rooty())
h.root.update()
opened = int(bool(p0.kids) and p0.active == si)
p0.cv.event_generate('<Leave>')
SUB.cv.event_generate('<Motion>', x=axB - SUB.win.winfo_rootx(),
                       y=ayB - SUB.win.winfo_rooty())
h.root.update()
print('  悬停「%s」开子菜单 %s → 父层 <Leave> + 子层 Motion: 子层没消失 %s · 子层收到 Motion %d 次 (期望 1 / 1 / >0)'
      % (p0.rows[si][2][1], opened, int(SUB in p0.kids and not SUB.closed), len(probe)))
print('  子层高亮落在第 %d 行「%s」(期望 %d) · 父层选中行没丢 %s · 该行高亮 %s · 坐标命中 %s (期望 1 / 1 / 1)'
      % (SUB.active, SUB.rows[SUB.active][2][1] if SUB.active >= 0 else '-', ki,
         int(p0.active == si),
         int(SUB.cv.itemcget(SUB.rows[ki][3], 'state') == 'normal'),
         int(SUB._row(type('E', (), {'x': SUB.w - 14,
                                     'y': (SUB.rows[ki][0] + SUB.rows[ki][1]) // 2})()) == ki)))
print('    真游标挪动期间 Tk 记到的浮层事件: %s' % (allev[:6],))

def click(p, i):
    ev = type('E', (), {'x': p.w - 20, 'y': (p.rows[i][0] + p.rows[i][1]) // 2})()
    p.press = i
    p._up(ev)
    h.root.update()


print('=== K2. 连着点: 选完延迟时长还能接着选到点动作, 再就地取消 ===')
old_pmin = h.pmin
click(SUB, ki)
print('  ① 点「%s」: 延迟时长 %s→%s · 子层没消失 %s · ● 已移到这一行 %s (期望 变了 / 1 / 1)'
      % (SUB.rows[ki][2][1], old_pmin, h.pmin,
         int(SUB in p0.kids and not SUB.closed),
         int(SUB.cv.itemcget(SUB.rows[ki][3], 'state') == 'normal')))
lit = [i for i, r in enumerate(SUB.rows)
       if r[2][0] == 'radio' and r[2][2] and i != ki]
print('  ② 原来选中的那行 ● 灭了(只剩一个选中) %s (期望 1)' % int(not lit))
ai = [i for i, r in enumerate(SUB.rows) if r[2][0] == 'scmd' and '关机' in r[2][1]][0]
click(SUB, ai)
info = [r[2][1] for r in SUB.rows if r[2][0] == 'info']
print('  ③ 点「%s」: 已武装 %s · 子层还没消失 %s · 状态行 %s'
      % (SUB.rows[ai][2][1], int(h.deadline is not None),
         int(SUB in p0.kids and not SUB.closed), [x for x in info if '定时' in x]))
print('    底栏同步 %r · 取消项变成可点 %s (期望 含剩1x:xx / scmd)'
      % (h.cv.itemcget(h.ids['foot.m'], 'text'), cancel_kind(SUB.spec())))
ci = [i for i, r in enumerate(SUB.rows) if r[2][0] == 'scmd' and r[2][1] == '取消定时'][0]
click(SUB, ci)
info = [r[2][1] for r in SUB.rows if r[2][0] == 'info']
print('  ④ 就地取消: deadline→%s · 子层还在 %s · 状态行退回 %s · 取消项退回灰字 %s (期望 None / 1)'
      % (h.deadline, int(SUB in p0.kids and not SUB.closed), info, cancel_kind(SUB.spec())))
click(p0, si)
print('  ⑤ 再点一次父层「定时操作」: 子层收掉 %s · 父层本体还在 %s (期望 1 / 1)'
      % (int(not p0.kids), int(not p0.closed)))
click(p0, si)
print('  ⑥ 第三次点: 子层重新弹出 %s · 是新开的一层 %s · 上一张已销毁 %s (期望 1 / 1 / 1)'
      % (int(len(p0.kids) == 1), int(p0.kids[0] is not SUB),
         int(SUB.closed and not SUB.win.winfo_exists())))
SUB = p0.kids[0]
ri = [i for i, r in enumerate(p0.rows) if r[2][0] == 'cmd' and '立即刷新' in r[2][1]][0]
click(p0, ri)
print('  ⑦ 一次性动作「立即刷新」仍然照旧: 执行完整菜单收起 %s (期望 1)' % int(h.pop is None))
h.set_pmin(old_pmin)
h._close_menu()
h.root.update()


def fake_key(v):
    _u.GetAsyncKeyState.restype = ctypes.c_short
    _u.GetAsyncKeyState = lambda vk, val=v: val


def watch_once(p):
    if p._job:
        h.root.after_cancel(p._job)
        p._job = None
    p._btn_last = False
    p._watch()


h._close_menu()
w0 = h.open_menu(120, 200)
h.root.update()
w0._open_sub(si)
h.root.update()
wsub = w0.kids[0]
try:
    fake_key(0x8000)
    wmove(wsub.win.winfo_rootx() + 12,
          wsub.win.winfo_rooty() + (wsub.rows[ki][0] + wsub.rows[ki][1]) // 2)
    watch_once(w0)
    alive_in = int(not w0.closed)
    wmove(int(_u.GetSystemMetrics(0) * 0.5), int(_u.GetSystemMetrics(1) * 0.96))
    watch_once(w0)
    closed_out = int(w0.closed)
finally:
    del _u.GetAsyncKeyState
    wmove(save_xy[0], save_xy[1])
print('  按下沿时游标在子菜单里 -> 整菜单不关 %s (期望 1)' % alive_in)
print('  按下沿时游标在两层之外 -> 整菜单关闭 %s (期望 1)' % closed_out)
h.root.update()
print('  关闭后浮层销毁 %s · 子层一起销毁 %s (期望 1 / 1)'
      % (int(not h.pop), int(not wsub.win.winfo_exists())))

h._close_menu()
q0 = h.open_menu(120, 200)
h.root.update()
q0._open_sub(si)
h.root.update()
other = [i for i, r in enumerate(q0.rows)
         if i != si and r[2][0] in ('radio', 'check', 'cmd')][0]
q0._hover(other)
print('  斜着滑进子菜单会扫过父层别的条目「%s」-> 子菜单不会被顺手收掉 %s · 浮层本体还在 %s (期望 1 / 1)'
      % (q0.rows[other][2][1], int(bool(q0.kids)), int(not q0.closed)))
q0._hover(si)
print('  换回「%s」行 -> 仍是同一层子菜单 %s · 没重复开一层 %s (期望 1 / 1)'
      % (q0.rows[si][2][1], int(len(q0.kids) == 1), int(q0.kids[0].rows[0][2][1].startswith('延迟时长'))))
q0.close()
h.root.update()

print('=== N. 按应用对账: HUD 的 app 维度 == 库里真值(+cc-haha 并入量) == 小面板那一行 ===')
h._set_visible(True)
st = h._start()
d = h._read(st)
hb0 = m.fetch_haha(st) or {}
bd0 = hb0.get('by_day') or {}
# 并进去的**实际量**(本地日口径) —— 对账基线必须加这一份, 不是索引全量(那是 UTC 日口径)
ha_r = sum(v['msgs'] for v in bd0.values())
ha_c = sum(v['cost'] for v in bd0.values())
ha_t = sum(v['in'] + v['out'] + v['rd'] + v['cc'] for v in bd0.values())
apps = {a: (n, cs, tk) for a, n, cs, tk, _h in d['apps']}
raw = m.sqlite3.connect('file:' + os.path.expanduser('~') + '/.cc-switch/cc-switch.db?mode=ro',
                        uri=True)
NETK = ("coalesce(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0)"
        "-coalesce(sum(case when data_source='codex_session' then cache_read_tokens"
        " else 0 end),0)")
db = {a: (n, c, tk) for a, n, c, tk in raw.execute(
    'select app_type, count(*), coalesce(sum(total_cost_usd),0), ' + NETK
    + ' from proxy_request_logs where created_at>=? group by 1', [st])}
tot = raw.execute('select count(*), coalesce(sum(total_cost_usd),0), ' + NETK
                  + ' from proxy_request_logs where created_at>=?', [st]).fetchone()
raw.close()
base = db.get('claude', (0, 0.0, 0))
db['claude'] = (base[0] + ha_r, base[1] + ha_c, base[2] + ha_t)
tot = (tot[0] + ha_r, tot[1] + ha_c, tot[2] + ha_t)
# 第三路 Qoder: 只有请求数, 成本与 token 都是 0(它本机不落这两维) —— 基线要按同一口径加
qb = m.fetch_qoder(st) or {}
qbr = sum(v['reqs'] for v in (qb.get('by_day') or {}).values())
if qbr:
    db['qoder'] = (qbr, 0.0, 0)
    tot = (tot[0] + qbr, tot[1], tot[2])
# 第四路起: 基线**不取 HUD 自己的数**, 各自用独立查询重算一遍(否则这条断言是循环论证)
def _herd_base(start):
    """牧羊人: 独立扫一遍 events.jsonl, 口径 total = input + output(实测无缓存分项)。"""
    n = tk = 0
    p = m.HERD_LOG
    if not os.path.exists(p):
        return 0, 0.0, 0
    d0 = time.strftime('%Y-%m-%d', time.localtime(start)) if start else '0000-01-01'
    with open(p, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if 'input_tokens' not in line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            ts = j.get('started_at') or j.get('recorded_at') or 0
            try:
                ep = float(ts)
            except (TypeError, ValueError):
                ep = dt.datetime.fromisoformat(str(ts)).timestamp()
            if dt.date.fromtimestamp(ep).isoformat() < d0:
                continue
            n += 1
            tk += int(j.get('input_tokens') or 0) + int(j.get('output_tokens') or 0)
    return n, 0.0, tk


def _codex_gap_base():
    """Codex 漏项的独立基线: 只用文件名取会话 id -> 查 CC Switch 有没有行(SQL 独立判定),
    零行的那些会话才解析最后一个 total_token_usage。CC 的 request_id 尾号不是 rollout 行号
    (实测 261..273 vs 1286,1293...), 所以"同会话内部回填不全"的部分两边都不算。"""
    c = m.sqlite3.connect('file:' + m.DB.replace(os.sep, '/') + '?mode=ro', uri=True)
    have = {r[0] for r in c.execute("select distinct session_id from proxy_request_logs"
                                    " where data_source='codex_session'")}
    d0 = time.strftime('%Y-%m-%d', time.localtime(st)) if st else '0000-01-01'
    n = tk = 0
    for root in m.CODEX_DIRS:
        if not os.path.isdir(root):
            continue
        for dp, _, fs in os.walk(root):
            for fn in fs:
                if not fn.endswith('.jsonl'):
                    continue
                base = fn[:-6]
                parts = base.split('-')
                sid = '-'.join(parts[-5:]) if len(parts) >= 9 else base
                if sid in have:
                    continue
                tot = None
                with open(os.path.join(dp, fn), encoding='utf-8', errors='replace') as fh:
                    for line in fh:
                        if 'total_token_usage' not in line:
                            continue
                        stack = [json.loads(line)]
                        while stack:
                            cur = stack.pop()
                            if isinstance(cur, dict):
                                for k, v in cur.items():
                                    if k == 'total_token_usage' and isinstance(v, dict):
                                        tot = v
                                    elif isinstance(v, (dict, list)):
                                        stack.append(v)
                            elif isinstance(cur, list):
                                stack.extend(cur)
                if not tot:
                    continue
                if dt.date.fromtimestamp(_roll_last_ts(os.path.join(dp, fn))).isoformat() < d0:
                    continue
                n += 1
                tk += int(tot.get('input_tokens') or 0) + int(tot.get('output_tokens') or 0)                     + int(tot.get('cache_write_input_tokens') or 0)
    c.close()
    return n, 0.0, tk


def _roll_last_ts(path):
    last = 0.0
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if '"timestamp"' not in line:
                continue
            try:
                ts = (json.loads(line).get('timestamp') or '')[:19]
                ep = dt.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S').replace(
                    tzinfo=dt.timezone.utc).timestamp()
            except (ValueError, TypeError):
                continue
            last = max(last, ep)
    return last or time.time()

def _wb_base(start, projects, with_credit):
    """WorkBuddy 某一版的**独立**基线: 自己 os.walk 扫 jsonl, 不借道 fetch_workbuddy/_wb_rows。
    返回 (请求数, 成本恒 0, tok=prompt+completion, 逐调用积分和, total_tokens 和, Σprompt, Σcompletion)。
    tok 用 prompt+completion 而不是四桶相加, 是为了让"缓存少减/多减"这类错必须暴露
    (HUD 那边拆成 净输入/命中/写 三桶, 两条路径只有在拆得不多不少时才相等)。"""
    n = tk = tt = psum = osum = 0
    cr = 0.0
    d0 = time.strftime('%Y-%m-%d', time.localtime(start)) if start else '0000-01-01'
    if not os.path.isdir(projects):
        return 0, 0.0, 0, 0.0, 0, 0, 0
    for dp, _, fs in os.walk(projects):
        for fn in fs:
            if not fn.endswith('.jsonl'):
                continue
            with open(os.path.join(dp, fn), encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if '"rawUsage"' not in line:
                        continue
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    pd = o.get('providerData') if isinstance(o, dict) else None
                    ru = pd.get('rawUsage') if isinstance(pd, dict) else None
                    if not isinstance(ru, dict):
                        continue
                    pr = int(ru.get('prompt_tokens') or 0)
                    ot = int(ru.get('completion_tokens') or 0)
                    if not (pr or ot):
                        continue
                    try:
                        ts = float(o.get('timestamp') or 0)
                    except (TypeError, ValueError):
                        continue
                    ep = ts / 1000.0 if ts > 1e12 else ts
                    if not ep or dt.date.fromtimestamp(ep).isoformat() < d0:
                        continue
                    n += 1
                    tk += pr + ot
                    psum += pr
                    osum += ot
                    tt += int(ru.get('total_tokens') or 0)
                    k = ru.get('credit')
                    if with_credit and isinstance(k, (int, float)) and k > 0:
                        cr += k
    return n, 0.0, tk, cr, tt, psum, osum


def _dsh_base(start):
    """DSH 的**独立**基线: 自己 glob + json.load 一遍, 不借道 fetch_dsh。
    返回 (轮次数, 成本恒 0, 四桶相加, {日: [轮次, in, out, rd, cc]}, {模型: [轮次, in+out]})。
    只算 createdAt 归日 >= start 且四项非零的会话(空会话不计请求数)。"""
    n = tk = 0
    days, models = {}, {}
    d0 = time.strftime('%Y-%m-%d', time.localtime(start)) if start else '0000-01-01'
    for p in sorted(glob.glob(os.path.join(m.DSH_DIR, '*.json'))):
        try:
            with open(p, encoding='utf-8', errors='replace') as fh:
                j = json.load(fh)
            rec = j.get('record') or {}
            rows = rec.get('rows') or {}
            tot = ((rows.get('tokenUsage') or {}).get('val') or {}).get('totals') or {}
            ca = (rec.get('identity') or {}).get('createdAt')
            if not isinstance(ca, (int, float)):
                continue
            fi, o, rd, cc = (int(tot.get(k) or 0) for k in
                             ('uncachedInputTokens', 'outputTokens', 'cacheReadTokens',
                              'cacheWriteTokens'))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if fi + o + rd + cc == 0:
            continue
        dte = dt.date.fromtimestamp(ca / 1000.0).isoformat()
        if dte < d0:
            continue
        turns = int((((rows.get('sessionStats') or {}).get('val')) or {}).get('turns') or 0) or 1
        mdl = str(((((rows.get('modelSelection') or {}).get('val')) or {}).get('lastUsed')
                   or {}).get('model') or '(未记录)')
        n += turns
        tk += fi + o + rd + cc
        v = days.setdefault(dte, [0, 0, 0, 0, 0])
        for i, x in enumerate((turns, fi, o, rd, cc)):
            v[i] += x
        mv = models.setdefault(mdl, [0, 0])
        mv[0] += turns
        mv[1] += fi + o
    return n, 0.0, tk, days, models


EXTRA_BASE = {                      # (app, 独立取数)
    'zcode': lambda: (lambda c: (lambda r: (r[0], 0.0, r[1]))(c.execute(
        "select count(*), coalesce(sum(input_tokens+output_tokens+reasoning_tokens"
        " +cache_creation_input_tokens),0) from model_usage where started_at>=?*1000",
        [st]).fetchone()))(
        m.sqlite3.connect('file:' + m.ZCODE_DB.replace(os.sep, '/') + '?mode=ro', uri=True)),
    'herdsman': lambda: _herd_base(st),
    'qoder-cn': lambda: (lambda q: (sum(v['reqs'] for v in q['by_day'].values()), 0.0, 0)
                         if q else (0, 0.0, 0))(m.fetch_qoder(st, m.QDIR_CN)),
    'codex': _codex_gap_base,
    # WorkBuddy 两版: 各自独立扫一遍 jsonl。基线的 tok **直接取 prompt+completion**, 而 HUD 那边
    # 是把 prompt 拆成 净输入/命中/写 三桶再与输出相加 —— 两条路径只有在拆桶不多不少时才相等,
    # 所以这条对账同时管住了"缓存少减/多减"这一类错(实测少减写缓存会多算 29 万/34 万)。
    'workbuddy': lambda: _wb_base(st, m.WB_SOURCES[0][0], True)[:3],
    'workbuddy-ai': lambda: _wb_base(st, m.WB_SOURCES[1][0], False)[:3],
    # 第九路 DSH: 同样是"并进所有视图"的源, 基线自己读一遍 json, 不借道 fetch_dsh
    'dsh': lambda: _dsh_base(st)[:3],
}
for app, fn in EXTRA_BASE.items():
    try:
        n3, c3, t3 = fn()
    except Exception:
        continue
    if not n3:
        continue
    if app in db:                                       # codex 的漏项会并进已有行
        o0 = db[app]
        db[app] = (o0[0] + n3, o0[1] + c3, o0[2] + t3)
    else:
        db[app] = (n3, c3, t3)
    tot = (tot[0] + n3, tot[1] + c3, tot[2] + t3)
assert len(db) >= 2 and set(apps) == set(db), \
    '应用维度对不上: HUD %s vs 库 %s' % (sorted(apps), sorted(db))
one2 = all(apps[a][0] == db[a][0] and abs(apps[a][1] - db[a][1]) < 0.005 and apps[a][2] == db[a][2]
           for a in db)
print('  应用集合一致 1 · 逐个(请求,成本,净tok)一致 %s · claude 已含 cc-haha '
      '+%d 次/%.2f/%s tok · qoder 行 +%d 次(成本与 token 都是 0) (期望 1)'
      % (int(one2), ha_r, ha_c, f'{ha_t:,}', qbr))
assert one2, [(a, apps[a], db[a]) for a in db if apps[a] != db[a]]
sr, sc, sk = (sum(v[0] for v in apps.values()), sum(v[1] for v in apps.values()),
              sum(v[2] for v in apps.values()))
print('  各应用之和 == 范围内总量: 请求 %d/%d/%d · 成本 %.4f/%.4f/%.4f · 净tok %s/%s/%s'
      % (sr, d['reqs'], tot[0], sc, d['cost'], tot[1], f'{sk:,}', f'{d["real"]:,}', f'{tot[2]:,}'))
assert sr == d['reqs'] == tot[0], '应用请求数之和对不上总量(漏一个应用或并入量只进了一半)'
assert abs(sc - d['cost']) < 0.02 and abs(sc - tot[1]) < 0.02
assert sk == d['real'] == tot[2], '净 tok 与「真实消耗」不同口径'
for a, n, cs, tk, hit in d['apps']:
    print('    %-14s 请求 %5d  成本 %9.2f  净tok %12s  命中 %5.1f%%'
          % (m.APP_ALIAS.get(a) or a, n, cs, f'{tk:,}', hit))
h.range_i = 1
h.refresh()
txt = h.cv.itemcget(h.ids['c2.rt'], 'text')
print('  小面板那一行: %r' % txt)
print('  成本前二都标出来 %s · Claude 在列 %s (期望 1 / %s)'
      % (int(all((m.APP_ALIAS.get(a) or a) in txt for a in
                 sorted(apps, key=lambda k: -apps[k][1])[:2])),
         int('Claude' in txt or 'claude' not in apps), int('claude' not in apps or 'Claude' in txt)))
print('=== O. 双击卡片 = 大小面板互切（含「落在可点区被切两次」陷阱）===')
Ev = lambda x, y: type('E', (), {'x': x, 'y': y, 'x_root': 2100 + x, 'y_root': 60 + y})()
h.expanded = False
h.refresh()
h.root.update()
body = Ev(int(h.W / 2), int(round(120 * h.s)))
b0 = h.expanded
h._down(body)
h.root.update()
after_down = h.expanded
h._dbl(body)
h.root.update()
time.sleep(0.2)
h.root.update()
print('  空白处: 按下不改态 %s · 双击切一次 %s · 现在 %s 态 · 窗口高 %d == _H %d (期望 1 / 1 / 展开 / 1)'
      % (int(after_down == b0), int(h.expanded != b0), '展开' if h.expanded else '收起',
         int(h.expanded), int(h.root.winfo_height() == h._H)))
pill = [z for z in h.zones if z[4] == h.toggle][0]
pe = Ev(int((pill[0] + pill[2]) / 2), int((pill[1] + pill[3]) / 2))
b1 = h.expanded
h._down(pe)
h.root.update()
mid = h.expanded
h._dbl(pe)
h.root.update()
print('  双击「收起面板」胶囊: 按下切一次 %s · Double 不再补第二刀 %s (期望 1 / 1 —— 旧代码这里切两下=没反应)'
      % (int(mid != b1), int(h.expanded == mid)))
chip = [z for z in h.zones if z[4] != h.toggle and z[4] != h.hide_now][0]
ce = Ev(int((chip[0] + chip[2]) / 2), int((chip[1] + chip[3]) / 2))
r0, e0 = h.range_i, h.expanded
h._down(ce)
h.root.update()
h._dbl(ce)
h.root.update()
print('  双击范围胶囊: 只换范围 %s · 面板态不变 %s (期望 1 / 1)'
      % (int(h.range_i != r0), int(h.expanded == e0)))
print('  绑定在位: Double=%s Button=%s (期望 True / True)'
      % (bool(h.cv.bind('<Double-Button-1>')), bool(h.cv.bind('<Button-1>'))))
print('=== P. 宽版(横长条)行制版式: 权重排布 / 间隙统一 / 每排底边齐平 / 不越界不撞字 ===')
h.expanded, h.wide = True, True
h.range_i = 1                     # 用 7 天(有数据)那一档: 空范围下峰值/曲线本来就该是空的
h.refresh()
h.root.update()
time.sleep(0.3)
h.root.update()
print('  宽版窗口 %dx%d (竖版 530x1510) · 图元 %d · 未登记槽位 %d'
      % (h.root.winfo_width(), h.root.winfo_height(), len(h.cv.find_all()), len(h._missing)))
overflow('宽版')
collisions()
trunc()
bb = {k: h.cv.bbox(h.ids[k]) for k in h.ids
      if k.endswith('.bg') and k not in ('c5.bg', 'head.bg', 'foot.pbg', 'btn.bg')}
tr = bb['c6.bg']
print('  趋势卡升为全宽行: %dx%d · 占满窗口内宽 %s · 绘图区 %dx%d 物理px'
      % (tr[2] - tr[0], tr[3] - tr[1],
         int((tr[2] - tr[0]) >= h.root.winfo_width() - 2 * int(round(m.PAD * h.s)) - 2),
         h.plot_w, h.plot_h2))
rows = {}
for k, b in bb.items():
    if k != 'c6.bg':
        rows.setdefault(b[1], []).append((k, b))
flat = sorted(rows.items())
print('  按排分组(权重从上往下): %s' % [(t, [k for k, _ in v]) for t, v in flat])
same = all(len(set(b[3] for _, b in v)) == 1 for _, v in flat)
banner = [v for _, v in flat if len(v) == 1 and v[0][0] in ('haha.bg', 'qoder.bg', 'wb.bg')]
print('  每排内部底边齐平 %s · 排数 %d · 每排卡数 %s (期望 1 / 5 / [4, 4, 1, 1, 1] —— 齐平才是矩形)'
      % (int(same), len(flat), [len(v) for _, v in flat]))
print('  三条全宽横幅(cc-haha + Qoder + WorkBuddy) %s · 都占满内宽 %s (期望 3 / 1)'
      % (len(banner), int(all((v[0][1][2] - v[0][1][0])
                              >= h.root.winfo_width() - 2 * int(round(m.PAD * h.s)) - 2
                              for v in banner))))
assert len(banner) == 3, '横幅少于一三条时上面的 all() 会变成空集恒真'
G = int(round(8 * h.s))
Gt = int(round(2 * h.s))
bands = [tr] + [[min(b[1] for _, b in v), min(b[1] for _, b in v),
                 max(b[2] for _, b in v), max(b[3] for _, b in v)] for _, v in flat]
vg = [bands[i + 1][1] - bands[i][3] for i in range(len(bands) - 1)]
# 底栏间隙按**胶囊实测顶边**减掉它的 4 逻辑px 内缩来量(而不是拿 _H 反推带顶):
# 之前用 _H 算, 舍入会把 10 报成 8, 看着像间隙不统一。
pb = h.cv.bbox(h.ids['foot.pbg'])
vg.append(int(round(pb[1] - 4 * h.s)) - bands[-1][3])
assert len(flat) == 5 and [len(v) for _, v in flat] == [4, 4, 1, 1, 1], \
    'P 段版面不是"两排 4 张 + 三条横幅", 后面的空集合 all() 会变成假通过'
print('  竖向间隙 %s · 曲线下面那格 %d(特别小) · 其余间隙全等于 %d(±1) (期望 1)'
      % (vg, Gt, G), int(all(abs(g - G) <= 1 for g in vg[1:-1])) and int(abs(vg[-1] - G) <= 1)
      and int(abs(vg[0] - Gt) <= 1))
hg = [sorted(b[0] for _, b in v) for _, v in flat]
huni = sorted({hg[i][j + 1] - hg[i][j] for i in range(len(hg)) for j in range(len(hg[i]) - 1)})
print('  横向间隙(去重) %s · 只有一个值 %s (期望 1)' % (huni, int(len(huni) == 1)))
# 原来是 `abs(...) < 0`, 恒假 = 一条永远不会红的死断言; 改成真的核对宽版装箱表
badh = [k for k in ('c1', 'c2', 'c3', 'c4', 'c7', 'c8', 'prov', 'model')
        if abs(bb[k + '.bg'][3] - bb[k + '.bg'][1]
               - max(int(round(h._hgt(k) * h.s)),
                     max(int(round(h._hgt(j) * h.s)) for j in
                         next(r for r in h.ROWS if k in r)))) > 2]
print('  行内等高拉伸(短卡外壳被拉长到该排最高卡的高): %s · 与 _hgt 表不符 %s (期望 空)'
      % ({k: bb[k + '.bg'][3] - bb[k + '.bg'][1] for k in ('c1', 'c2', 'prov', 'c3')}, badh or '空'))
pk = h.cv.itemcget(h.ids['c6.peak'], 'text')
print('  峰值标注: %r · 竖线状态 %s (期望 非空 / normal)'
      % (pk, h.cv.itemcget(h.peakline, 'state')))
h.wide = False
h.refresh()
h.root.update()
time.sleep(0.3)
h.root.update()
print('  切回竖版: 窗口 %dx%d · 图元 %d · 未登记槽位 %d (期望 530x1510 / 0 —— 不残留宽版图元)'
      % (h.root.winfo_width(), h.root.winfo_height(), len(h.cv.find_all()), len(h._missing)))
bb2 = {k: h.cv.bbox(h.ids[k]) for k in h.ids
       if k.endswith('.bg') and k not in ('c5.bg', 'head.bg', 'foot.pbg', 'btn.bg')}
bad = [k for k in ('c1', 'c2', 'c3', 'c4', 'c6', 'c7', 'c8', 'prov', 'model')
       if k in bb2 and abs(bb2[k + '.bg'][3] - bb2[k + '.bg'][1]
                           - int(round(h._hgt(k) * h.s))) > 2]
print('  竖版 _hgt 表与实际卡高一致 %s (期望 空 —— 改卡高忘了同步装箱表就会红)' % (bad or '空'))
print('=== Q. 面板落点 = 圆点那个右上角: 改尺寸 / 收起唤回 / 拖动同步, 都不许跑到左上角 ===')
d = int(round(m.PEEK * h.s))
_l, _t, _r, _b = m._work_area()
h.state['peek'] = [_r - d - int(round(28 * h.s)), _t + int(round(36 * h.s))]


def corner():
    h.root.update()
    return h.root.winfo_x() + h.root.winfo_width(), h.root.winfo_y()


def settle():
    h.root.update()
    time.sleep(0.3)
    h.root.update()


h._set_visible(True)                        # 从圆点那个角长出来
settle()
want = h.state['peek'][0] + d               # 圆点右上角 = 面板右上角应该钉住的 x
print('  唤回后: 面板右上角 (%d,%d) vs 圆点右上角 (%d,%d) · 差 %d (期望 <=2 —— 差 31 就是 _clamp 拿旧坐标把卡片又推走)'
      % (corner()[0], corner()[1], want, h.state['peek'][1], abs(corner()[0] - want)))
h.expanded, h.wide = True, True
h.refresh()
settle()
c0 = corner()
h.expanded = False
h.refresh()
settle()
c1 = corner()
h.expanded, h.wide = True, False
h.refresh()
settle()
c2 = corner()
drift = max(abs(c[0] - want) for c in (c0, c1, c2)), max(abs(c[1] - corner()[1]) for c in (c0, c1, c2))
print('  宽版→收起→竖版: 右上角 x %s (锚 %d) · 顶边 y %s · 最大漂移 %d/%d px (期望都 <=2 —— 锚在右上角)'
      % ([c[0] for c in (c0, c1, c2)], want, [c[1] for c in (c0, c1, c2)], drift[0], drift[1]))

h.expanded = False
h.refresh()
settle()
h._set_visible(False)                       # 收起 -> 只剩圆点(用小卡试: 大面板竖版 1510 高,
                                            # 往下挪 180 会被 _clamp 顶回去, 量不到"跟着圆点走")
pk0 = (h._pk.winfo_x(), h._pk.winfo_y())
h._pk.geometry('+%d+%d' % (pk0[0] - 420, pk0[1] + 180))
h.root.update()
pk1 = (h._pk.winfo_x(), h._pk.winfo_y())
h.state['peek'] = [pk1[0], pk1[1]]
h._set_visible(True)                        # 点圆点唤回
settle()
c3 = corner()
print('  把圆点拖到 (%d,%d) 再唤回: 面板右上角 (%d,%d) vs 圆点右上角 (%d,%d) · 差 %d/%d (期望 <=2)'
      % (pk1[0], pk1[1], c3[0], c3[1], pk1[0] + d, pk1[1],
         abs(c3[0] - pk1[0] - d), abs(c3[1] - pk1[1])))

E2 = lambda xr, yr: type('E', (), {'x': 5, 'y': 5, 'x_root': xr, 'y_root': yr})()
before = (h.root.winfo_x(), h.root.winfo_y())
h._down(E2(before[0] + 60, before[1] + 40))
h._move(E2(before[0] - 140, before[1] + 120))
h._up_pos(E2(before[0] - 140, before[1] + 120))
settle()
now = (h.root.winfo_x(), h.root.winfo_y())
want = [max(0, now[0] + h.W - d), now[1]]
print('  拖面板到 (%d,%d) 后: state[peek]=%s · 应等于面板右上角换算 %s · 一致 %s (期望 1)'
      % (now[0], now[1], h.state.get('peek'), want, int(h.state.get('peek') == want)))
h.expanded = False
h.refresh()
settle()
c4 = corner()
print('  拖过之后再收起: 右上角仍跟着面板 (%d,%d) vs (%d,%d) · 差 %d (期望 <=2)'
      % (c4[0], c4[1], now[0] + h.W, now[1], abs(c4[0] - now[0] - h.W)))
h.state['peek'] = [pk0[0], pk0[1]]
h._save()

print('=== R. 第二数据源 cc-haha: 路径自动发现 / 本地日 / 并入守恒 / 双计保险 / 缺库不崩 ===')
import sqlite3
dbp, pdir = m.haha_cfg()
print('  自动发现: 索引=%s' % dbp)
print('           transcript=%s' % pdir)
print('  选中的库 %s 前刚写过 (期望 <5 分钟 —— 挑到停更的死库就是这次事故的根因)'
      % ('5 分钟' if (time.time() - os.path.getmtime(dbp)) < 300 else '**超过 5 分钟, 可疑**'))
print('  两条候选都在时按 mtime 取新: C 盘那份 %s'
      % ('存在(停更)' if os.path.exists(os.path.join(os.path.expanduser('~'), '.claude', m.HDB_SUB))
         else '不存在'))

start = h._start()
hb = m.fetch_haha(start)
h0 = m.fetch_haha(0)
print('  按**本地日**分桶: %s (索引自己的 date 是 UTC 日, 早上 8 点前会错一天)'
      % sorted(hb['by_day']))
print('  重复调用结果稳定 %s · 全库 tok=%s (期望 1 —— 曾经把去重集合做成全局, 第二次调用就空了)'
      % (int(sorted(m.fetch_haha(0)['by_day']) == sorted(h0['by_day'])), format(h0['tok'], ',')))

db = sqlite3.connect('file:' + m.DB.replace(os.sep, '/') + '?mode=ro', uri=True)
d = m.fetch(db, 0)
db.close()
clash = d['claude_sids'] & hb['sids']
print('  会话 id 不相交: CC Switch %d 个 · cc-haha %d 个 · 交集 %d (期望 0 —— 相交就必须停止并入)'
      % (len(d['claude_sids']), len(hb['sids']), len(clash)))
print('  会话 id 是裸 uuid 而不是整条路径 %s (期望 True —— 取错下标会让这个断言形同虚设)'
      % all(len(x) == 36 for x in list(hb['sids'])[:5]))

b_cost, b_real, b_days = d['cost'], d['real'], {r[0] for r in d['daily']}
m.merge_haha(d, h0)
split = d['cin'] + d['cout'] + d['crd'] + d['cwr']
newdays = sorted({r[0] for r in d['daily']} - b_days)
print('  并入: 成本 %.2f -> %.2f (+%.2f) · tok %s -> %s' %
      (b_cost, d['cost'], d['cost'] - b_cost, format(int(b_real), ','), format(int(d['real']), ',')))
print('  守恒: 四项合计 %.2f == 总成本 %s · 按应用之和 == 总成本 %s · 按天之和 == 总成本 %s (期望 真/真/真)'
      % (split, int(abs(split - d['cost']) < 0.01),
         int(abs(sum(a[2] for a in d['apps']) - d['cost']) < 0.01),
         int(abs(sum(r[1] for r in d['daily']) - d['cost']) < 0.01)))
print('  曲线新增日期(CC Switch 完全没有、只有 cc-haha 有): %s (期望 >=1 —— 就是"跑了却没记"那几天)'
      % (newdays or '无'))
print('  请求数单位一致: 新增日按"唯一 API 响应数"计 %s (期望 True)'
      % all(r[3] > 0 for r in d['daily'] if r[0] in newdays))
d2 = m.fetch(sqlite3.connect('file:' + m.DB.replace(os.sep, '/') + '?mode=ro', uri=True), 0)
c2 = d2['cost']
m.merge_haha(d2, dict(h0, sids={list(d2['claude_sids'])[0]}))
print('  双计保险: 人造一个相交会话 -> 成本 %.2f -> %.2f · 拒绝并入 %s · clash=%s (期望 不变 / 1)'
      % (c2, d2['cost'], int(abs(d2['cost'] - c2) < 1e-9), d2['haha'].get('clash')))

h.expanded, h.wide = True, True
h.refresh()
h.root.update()
print('  横幅: %r / %r / %r' % (cv.itemcget(h.ids['haha.add'], 'text'),
                                cv.itemcget(h.ids['haha.addt'], 'text'),
                                cv.itemcget(h.ids['haha.v'], 'text')))
print('  说明行: %r' % cv.itemcget(h.ids['haha.rt'], 'text'))
real = m.fetch_haha
m.fetch_haha = lambda s: None                    # 模拟"这台机没装 cc-haha"
h.refresh()
h.root.update()
nofatal = len(cv.find_withtag('fatal'))
dash = cv.itemcget(h.ids['haha.sess'], 'text')
note = cv.itemcget(h.ids['haha.v'], 'text')
m.fetch_haha = real
h.refresh()
h.root.update()
print('  缺库时: 绘制红字 %d · 数值 %r · 说明 %r · 恢复后 %r (期望 0 / — / 没读到索引库 / 非空)'
      % (nofatal, dash, note, cv.itemcget(h.ids['haha.sess'], 'text')))
print('  全程没有真的执行过电源命令: %s · 记录=%s (期望 1 / 空)'
      % (int(not [x for x in POWERCALLS if 'shutdown' in x.lower()]), POWERCALLS[:2]))
print('=== S. 口径一致性: 四个范围下「总量 = 各视图之和」逐项断言 ===')
# 并入 cc-haha 之后最容易出的错是"总量并了、某个视图没并"—— 数字各说各话。
# 这一段把每条守恒都变成硬门禁(以前 N 段只是 print 出来看着, 对不上也不会红)。
for ri, (rname, _days) in enumerate(m.RANGES):
    h.range_i = ri
    st = h._start()
    dd = h._read(st)
    ha = dd.get('haha') or {}
    bdd = ha.get('by_day') or {}
    eq = [
        ('Σ应用请求==总请求', sum(a[1] for a in dd['apps']), dd['reqs']),
        ('Σ按天请求==总请求', sum(r[3] for r in dd['daily']), dd['reqs']),
        ('Σ小时格==总请求', sum(dd['hourly']), dd['reqs']),
        ('Σ按天净tok==真实消耗', sum(r[2] for r in dd['daily']), dd['real']),
        ('Σ四项==真实消耗', dd['fresh_in'] + dd['out'] + dd['read'] + dd['creat'], dd['real']),
        ('Σ四项成本==总成本', dd['cin'] + dd['cout'] + dd['crd'] + dd['cwr'], dd['cost']),
        ('Σ按天成本==总成本', sum(r[1] for r in dd['daily']), dd['cost']),
        ('Σ应用成本==总成本', sum(a[2] for a in dd['apps']), dd['cost']),
        ('横幅并入成本==真并入', ha.get('mcost', 0.0), sum(v['cost'] for v in bdd.values())),
        ('横幅并入tok==真并入', ha.get('mtok', 0),
         sum(v['in'] + v['out'] + v['rd'] + v['cc'] for v in bdd.values())),
    ]
    bad = [(k, a, b) for k, a, b in eq if abs(a - b) > (0.02 if isinstance(a, float) else 0)]
    le = [('模型表tok≤真实', sum(x[3] for x in dd['models']), dd['real']),
          ('模型表成本≤总成本', sum(x[2] for x in dd['models']), dd['cost']),
          ('今日请求≤总请求', dd['today'][0], dd['reqs']),
          ('近1h请求≤总请求', dd['h1'][0], dd['reqs'])]
    bad += [(k, a, b) for k, a, b in le if a > b + 1e-9]
    print('  %-4s 请求 %-6s (=Σ应用=Σ按天=Σ小时) · 净tok %-14s (=Σ按天) · 模型表 %d 行/请求 %s · '
          '今日 %s 近1h %s · 守恒 %d 项 %s'
          % (rname, f"{dd['reqs']:,}", f"{dd['real']:,}", len(dd['models']),
             f"{sum(x[1] for x in dd['models']):,}", f"{dd['today'][0]:,}", f"{dd['h1'][0]:,}",
             len(eq) + len(le), 'OK' if not bad else bad))
    assert not bad, '%s 口径不一致: %s' % (rname, bad)
    if sum(v['msgs'] for v in bdd.values()):
        assert any(x[1] > 0 for x in dd['models']), '模型表请求数全为 0 = 并入量只并了一半'
h.range_i = ORIG_STATE.get('range', 1)

print('=== T. 审计批次 E 的门禁: 电源下发 / 定时跨重启 / 坏状态 / 托盘 / 位图 / 文案 ===')
# T1 run_power 的**真实参数**以前从没被断言过(J 段把整个函数打桩了), 这里用假 subprocess
#    与假 API 调真函数: 关机必须带 /t 宽限、关屏必须走 Post 而不是同步广播、睡眠不能强杀。
calls = {'run': [], 'post': [], 'send': [], 'susp': []}
_real_run, _real_w = m.subprocess.run, m.ctypes.windll
m.subprocess.run = lambda a, **k: (calls['run'].append(list(a)),
                                   type('R', (), {'returncode': 0})())[1]
u32x = _real_w.user32
calls['post_real'] = u32x.PostMessageW
u32x.PostMessageW = lambda *a: (calls['post'].append(a), 1)[1]
u32x.SendMessageW = lambda *a: (calls['send'].append(a), 1)[1]
_real_w.powrprof.SetSuspendState = lambda *a: (calls['susp'].append(a), 1)[1]
for kind, want in (('off', ['shutdown', '/s', '/t', str(m.GRACE)]),
                   ('reboot', ['shutdown', '/r', '/t', str(m.GRACE)]),
                   ('logout', ['shutdown', '/l'])):
    ok = REAL_RUN_POWER(kind)
    print('  run_power(%-6s) -> %s · 参数 %s (期望 %s)' % (kind, ok, calls['run'][-1], want))
    assert ok and calls['run'][-1] == want
assert REAL_RUN_POWER('screen') and calls['post'] and not calls['send'], \
    '关屏仍走同步广播 SendMessageW: 有一个不泵消息的窗口就能把 UI 线程一起卡死'
assert REAL_RUN_POWER('sleep') and calls['susp'] == [(0, 0, 0)], \
    '睡眠必须是 (0=睡眠, 0=不强杀): %s' % (calls['susp'],)
calls['susp'] = []
assert REAL_RUN_POWER('hibernate') and calls['susp'] == [(1, 0, 0)], \
    '休眠必须是 SetSuspendState(1=休眠, 0=不强杀): %s' % (calls['susp'],)
print('  关屏走 PostMessageW %s · 没碰 SendMessageW %s · 睡眠参数 %s · 休眠参数 %s '
      '(期望 真 / 真 / [(0, 0, 0)] / [(1, 0, 0)])'
      % (bool(calls['post']), not calls['send'], [(0, 0, 0)], calls['susp']))
# 菜单里必须真的列得下每一个动作 —— "休眠"曾经因为只改了标签没改 API 而让用户找不到
labels = [lab for _, lab in m.POWERS]
spec = [x for x in h.power_spec() if x[0] in ('scmd', 'cmd')]
missing = ['到点' + lab for lab in labels if ('到点' + lab) not in [x[1] for x in spec]]
print('  定时子菜单动作项: %s · 缺项 %s (期望 6 项 / 空)'
      % ([x[1] for x in spec if str(x[1]).startswith('到点')], missing))
assert not missing, '定时操作子菜单少了动作: %s' % missing
m.subprocess.run = _real_run
u32x.PostMessageW = calls['post_real']
_real_w.powrprof.SetSuspendState = m.ctypes.windll.powrprof.SetSuspendState

# T2 定时跨重启: 落盘 -> 换一份状态 -> 续上倒计时 / 续上"已交给系统"的撤销口
h.pmin = 15
h.arm('off')
saved = json.loads(open(m.STATE, encoding='utf-8').read())
print('  武装后落盘: dl=%s pk=%s pf=%s (期望 有未来时间戳 / off / False)'
      % (round(saved.get('dl', 0) - time.time(), 1), saved.get('pk'), saved.get('pf')))
assert saved.get('pk') == 'off' and saved.get('dl', 0) > time.time() and not saved.get('pf')
h.deadline, h.power_kind, h.fired = None, None, False
h._pw = [time.time() + 600, 'off', False]
h._resume_power()
print('  重启后接续: deadline 还剩 %.0fs · kind=%s · note=%r (期望 ~600 / off / 已接着上次)'
      % (h.deadline - time.time(), h.power_kind, h.note))
assert h.deadline and h.power_kind == 'off' and '接着上次' in h.note
h.deadline, h.power_kind, h.fired = None, None, False
h._pw = [time.time() - 60, 'off', False]
h._resume_power()
print('  到点时 HUD 不在: 不补执行 %s · note=%r (期望 None / 未执行)' % (h.deadline, h.note))
assert h.deadline is None and '未执行' in h.note
ab2 = []
m.abort_power = lambda: (ab2.append('a'), True)[1]
h.deadline, h.power_kind, h.fired = None, 'off', True
h.cancel_power()
print('  「重启前已交给系统」仍可撤销: abort_power %s 次 · fired=%s (期望 1 / False)'
      % (len(ab2), h.fired))
assert len(ab2) == 1 and h.fired is False and h.power_kind is None
h._pw = [None, 'off', True]
h._resume_power()
print('  fired 状态复活: power_kind=%s fired=%s note=%r (期望 off / True / 可取消)'
      % (h.power_kind, h.fired, h.note))
assert h.fired and h.power_kind == 'off' and '可取消' in h.note
h.cancel_power()

# T3 坏状态文件不许让 HUD 启动即崩: 子进程里换一份临时 STATE 真起一个 HUD
bad_st = os.path.join(tempfile.gettempdir(), 'hud-state-bad.json')
with open(bad_st, 'w', encoding='utf-8') as fh:
    json.dump({'range': 99, 'alpha': 'x', 'pin': None, 'exp': 1, 'wide': 'yes',
               'peek': ['a', 'b'], 'pmin': 'zz', 'dl': 'q', 'pk': 5, 'pf': 'no'}, fh)
kid = os.path.join(tempfile.gettempdir(), 'hud_bad_state.py')
KID = '''import sys, os, tempfile
sys.path.insert(0, r'__DIR__')
from importlib.machinery import SourceFileLoader
m = SourceFileLoader('hud', 'cc-hud.pyw').load_module()
m.STATE = os.path.join(tempfile.gettempdir(), 'hud-state-bad.json')   # 不碰真状态文件
h = m.HUD()
h.refresh(True)
h.root.update()
print('range=%d alpha=%s pin=%s pmin=%s dl=%s win=%dx%d' % (
    h.range_i, h.alpha, h._pinned, h.pmin, h.deadline,
    h.root.winfo_width(), h.root.winfo_height()))
h.root.destroy()
'''
with open(kid, 'w', encoding='utf-8') as fh:
    fh.write(KID.replace('__DIR__', r'G:\AIrenwu\cc-hud'))
_spy = m.subprocess.Popen          # run() 内部找的是模块全局 Popen, 临时换回真身再调
m.subprocess.Popen = _op
try:
    r = _orun([sys.executable, '-X', 'utf8', kid], capture_output=True, timeout=90)
finally:
    m.subprocess.Popen = _spy
out = (r.stdout + r.stderr).decode('utf-8', 'replace').strip().replace('\n', ' | ')
print('  坏状态启动(子进程 rc=%d): %s' % (r.returncode, out))
assert r.returncode == 0 and 'range=3 ' in out and 'alpha=0.96' in out, \
    '坏状态文件仍会让 HUD 起不来: %s' % out

# T4 托盘事件合并: 一次点击外壳会派发多条通知, 逐条翻转等于没反应
h._shown = True
for ev in ('toggle', 'toggle', 'toggle'):
    h.q.put(ev)
h._tick()
print('  连投 3 个 toggle -> 只翻一次: _shown=%s (期望 False)' % h._shown)
assert h._shown is False
h.q.put('toggle')
h.q.put('menu')                      # 右键会同时来 0x204 与 WM_CONTEXTMENU; 混批时以菜单为准
shown = h._shown
h._tick()
h.root.update()
opened = h.pop                       # close() 会把 self.pop 清掉, 先把引用留住
print('  toggle+menu 混批 -> 只弹菜单不翻转显示态: 弹到了 %s · 显示态没动 %s (期望 真 / 真)'
      % (int(opened is not None), int(h._shown is shown)))
assert opened is not None and h._shown is shown
opened.close()
h.q.put('menu')
h.q.put('menu')                      # 同一次右键会派发两条菜单通知 —— 直接数派发次数
disp = []
_real_te = h._tray_event
h._tray_event = lambda ev: (disp.append(ev), None)[1]
h._tick()
h.root.update()
h._tray_event = _real_te
print('  2×menu 混投 -> 实际派发 %s (期望 恰好一次 menu)' % disp)
assert disp == ['menu']
if h.pop:
    h.pop.close()

# T5 圆点位图不再寄存在会被 _layout 清空的 imgs 里
h._set_visible(False)                       # 收起卡片 -> 圆点出现
h.root.update()
assert h._pk is not None, '圆点没建出来'
img0 = h._pk_img
h.refresh(True)                      # force -> _layout() -> imgs.clear()
print('  强制重排版后: imgs 里还有 pk 吗 %s · 圆点位图仍是同一张 %s (期望 False / True)'
      % ('pk' in h.imgs, h._pk_img is img0))
assert 'pk' not in h.imgs and h._pk_img is not None
h._set_visible(True)

# T7 冷启动锚点: 状态里存着 exp+wide 时, 第一次 geometry 就得按宽版宽度算右上角
cold = os.path.join(tempfile.gettempdir(), 'hud-state-cold.json')
PEEKN = [2200, 120]
with open(cold, 'w', encoding='utf-8') as fh:
    json.dump({'peek': PEEKN, 'exp': True, 'wide': True, 'range': 1, 'alpha': 0.96}, fh)
kid2 = os.path.join(tempfile.gettempdir(), 'hud_cold_wide.py')
KID2 = '''import sys, os, tempfile
sys.path.insert(0, r'__DIR__')
from importlib.machinery import SourceFileLoader
m = SourceFileLoader('hud', 'cc-hud.pyw').load_module()
m.STATE = os.path.join(tempfile.gettempdir(), 'hud-state-cold.json')
m._dpi_aware()
h = m.HUD()
h.refresh(True)
h.root.update()
h.root.update_idletasks()
d = int(round(m.PEEK * h.s))
print('wide=%s win=%dx%d right=%d dotright=%d top=%d' % (
    h.wide, h.root.winfo_width(), h.root.winfo_height(),
    h.root.winfo_x() + h.root.winfo_width(), __PEEKN__ + d, h.root.winfo_y()))
h.root.destroy()
'''
with open(kid2, 'w', encoding='utf-8') as fh:
    fh.write(KID2.replace('__DIR__', r'G:\AIrenwu\cc-hud').replace('__PEEKN__', str(PEEKN[0])))
_spy = m.subprocess.Popen
m.subprocess.Popen = _op
try:
    r2 = _orun([sys.executable, '-X', 'utf8', kid2], capture_output=True, timeout=90)
finally:
    m.subprocess.Popen = _spy
out2 = (r2.stdout + r2.stderr).decode('utf-8', 'replace').strip().replace('\n', ' | ')
print('  冷启动宽版(子进程 rc=%d): %s' % (r2.returncode, out2))
assert r2.returncode == 0 and 'right=' in out2, out2
w = dict(p.split('=') for p in out2.split() if '=' in p)
assert int(w['win'].split('x')[0]) == int(round(m.WIDE_W * h.s)), '冷启动宽度不是宽版: %s' % out2
assert abs(int(w['right']) - int(w['dotright'])) <= 2, '冷启动宽版没锚在圆点右上角: %s' % out2
assert int(w['top']) == PEEKN[1], '冷启动顶边没跟住圆点: %s' % out2

# T6 文案与取数对齐
h.range_i = 1                        # 今日只有 1 天 -> 趋势图不画曲线, 峰值标注本来就是空的
h.wide = True
h.refresh(True)
h.root.update()
txts = {k: h.cv.itemcget(t, 'text') for k, t in h.ids.items()
        if isinstance(t, int) and h.cv.type(t) == 'text'}
allt = ' '.join(txts.values())
for k in ('c7.rt', 'c6.peak', 'prov.rt', 'c4.rt', 'cur'):
    print('  %-8s %r' % (k, txts.get(k, '<无此槽位>')))
assert txts['c6.peak'], '7 天档没有峰值标注 = 曲线没画出来'
assert '次/时' not in allt and '累计' in txts['c7.rt'], '24小时格仍写成"次/时"(它是跨天累计)'
assert txts['c6.peak'].startswith('最大一天'), '趋势图峰值标注仍与左轴同叫"峰值"'
assert '计价来源' not in allt, '「计价来源 response」是无字段支撑的写死文案'
assert '未选Provider' not in allt
assert h.ids.get('c8.rt') is None or txts.get('c8.rt', '') != '', 'c8.rt 是注册了从不赋值的死槽位'

# T6b 延迟卡分母文案。原来这一条绑死在某一档上, 而代理实测会随时间掉出窗口 ——
# 2026-10-18 实测: proxy_request_logs 最大 created_at 是 10-11, 今日与 7 天档一条都没有,
# 于是卡片合法地写"本范围无实测", 绑死的断言就假红。改成四档全跑, 每档该走哪个分支
# 由**独立 SQL** 数出来的样本数决定(与 HUD 同一条件 latency_ms>0, 但不读它算出来的数),
# 有实测的档必须写全分母、没实测的档必须落到空态文案, 两个分支都各有门禁。
_db6 = sqlite3.connect('file:' + m.DB.replace(os.sep, '/') + '?mode=ro', uri=True)
_have = _none = 0
h.expanded = True                      # 延迟卡只在展开/宽版排版里才建槽位, 收起态没有
for ri, (rname, rdays) in enumerate(m.RANGES):
    s0 = 0 if not rdays else int(dt.datetime.combine(
        dt.date.today() - dt.timedelta(days=rdays - 1), dt.time.min).timestamp())
    n = _db6.execute('select count(*) from proxy_request_logs where ' +
                     ('created_at>=? and latency_ms > 0' if s0 else 'latency_ms > 0'),
                     () if not s0 else (s0,)).fetchone()[0]
    h.range_i = ri
    h.wide = True
    h.refresh(True)
    h.root.update()
    assert h.ids.get('c4.rt'), '%s 档展开宽版后没有 c4.rt 槽位' % rname
    rt = h.cv.itemcget(h.ids['c4.rt'], 'text')
    if n:
        _have += 1
        assert '实测' in rt and '首token' in rt, \
            '%s 档库里有 %d 条代理实测, 延迟卡却没写全三个分母: %r' % (rname, n, rt)
    else:
        _none += 1
        assert '无实测' in rt and '首token' not in rt, \
            '%s 档库里 0 条代理实测, 延迟卡却写了分母(会读成"有数"): %r' % (rname, rt)
    print('  %-5s 档: 库里代理实测 %6d 条 -> c4.rt %r' % (rname, n, rt))
_db6.close()
assert _have, '四个范围里 CC Switch 一条代理实测都没有 —— 这段门禁成了空集(换机/清库?), 需人工确认'
print('  两个分支都覆盖到: 有实测 %d 档 · 空态 %d 档 (期望都 >=1)' % (_have, _none))
h.range_i = ORIG_STATE.get('range', 1)
h.expanded = False
h.wide = False
h.refresh()
h.root.update()
# 还原成**本次运行开始时**的用户偏好(以前是整份覆写成一个旧备份, 会把用户中途
# 拖过的圆点位置、改过的范围一起抹掉)
# T7 导出对账数据: 落盘位置 + 底栏文案。此前 verify 只测过 _redact_export(纯函数),
#    从没真正调过 HUD.export() —— 于是「ROOTDIR 漏进 const.__all__, 星导入带不进 cchud.hud,
#    export() 里裸引用抛 NameError, 又被 except Exception 吞成底栏一句'导出失败'」这个 bug
#    在 112 条判据全绿的情况下漏网了。这一条把它钉死。
assert hasattr(m, 'ROOTDIR'), \
    'ROOTDIR 没从 cchud.const 星导入进来(它漏在 const.__all__ 里?) —— ' \
    'HUD.export() 会因此抛 NameError 并被吞成底栏"导出失败"'
_exp = os.path.join(m.ROOTDIR, 'ccswitch-对账数据.json')
_old_note = h.note
if os.path.exists(_exp):
    os.remove(_exp)
_refresh = h.refresh                  # export() 末尾会 refresh(True), 而 refresh 里
h.refresh = lambda *a, **k: None      # 有 `note, self.note = self.note, None` 会把 note 消费掉


def _tmp_name(nm):
    return os.path.join(tempfile.gettempdir(), nm)


_note_bad_target = _tmp_name('hud-export-note.json')
for p in (_exp, _note_bad_target):
    if os.path.exists(p):
        os.remove(p)
try:
    assert m.ROOTDIR == os.path.dirname(m.STATE), \
        'ROOTDIR 不是 STATE 所在目录: %r vs %r' % (m.ROOTDIR, os.path.dirname(m.STATE))
    h.export()
    _note = h.note
    _written = os.path.exists(_exp)
    _parsed = None
    if _written:
        with open(_exp, encoding='utf-8') as _f:
            _parsed = json.load(_f)
    print('  导出: note=%r · 落在 %s = %s · 可 json.loads = %s (顶层键 %s) (期望 已写出 / True / True)'
          % (_note, os.path.basename(_exp), _written, _parsed is not None,
             len(_parsed) if isinstance(_parsed, dict) else '非字典'))
    assert not str(_note or '').startswith('导出失败'), \
        'HUD.export() 失败(底栏: %r) —— 多半是 ROOTDIR 之类的基址没从 const 星导入进来' % (_note,)
    assert _note == '已写出 ccswitch-对账数据.json', '导出成功的文案变了: %r' % (_note,)
    assert _written, 'export() 说写成功, 但 %s 不存在' % _exp
    assert isinstance(_parsed, dict) and _parsed, '导出的 JSON 解析不出非空字典'
    # 再验一次「导出的内容确实是当前口径」: 至少要有请求数与成本这两个键, 且请求数 > 0
    _k = [k for k in ('reqs', 'requests', 'total_reqs') if k in _parsed]
    assert _k, '导出的 JSON 里找不到请求数键(现有键: %s)' % sorted(_parsed)[:12]
finally:
    h.refresh = _refresh
    h.note = _old_note
    if os.path.exists(_exp):
        os.remove(_exp)               # 不留产物在工作区
    if os.path.exists(_note_bad_target):
        os.remove(_note_bad_target)
assert not os.path.exists(_exp), '导出判据跑完没清理掉 ccswitch-对账数据.json'
print('  导出判据跑完已清理产物 · 工作区无残留')

print('=== U. 第三路 Qoder: 只并请求数+credits / token 拿不到 / 双计保险 / 缺目录 ===')
h.expanded = True                     # 横幅只在"展开+宽版"才画, 前面各段把版式切来切去过
h.wide = True
h.range_i = 3
st = h._start()
dbq = m.sqlite3.connect('file:' + m.DB.replace(os.sep, '/') + '?mode=ro', uri=True)
dbq.execute('pragma busy_timeout=1500')
base = m.fetch(dbq, st)
dbq.close()
qb1 = m.fetch_qoder(st)
qb2 = m.fetch_qoder(st)
same_q = (qb1['reqs'] == qb2['reqs'] and abs(qb1['credits'] - qb2['credits']) < 1e-9
          and sorted(qb1['by_day']) == sorted(qb2['by_day']))
ids = set()
for p in sorted(glob.glob(m.QDIR + os.sep + '**' + os.sep + '*.jsonl', recursive=True)):
    for mid, ep, cr in m._parse_qoder(p):
        ids.add(mid)
print('  两次解析一致 %s · 全库唯一响应 id %d 个 · 本次并入请求 %s (期望 真 / >0 / <=全库)'
      % (int(same_q), len(ids), f"{qb1['reqs']:,}"))
assert same_q and len(ids) > 0 and qb1['reqs'] <= len(ids)
assert qb1['reqs'] == sum(v['reqs'] for v in qb1['by_day'].values()) == sum(qb1['hourly'])
# token 这一路"拿不到"是事实断言: 若哪天 Qoder 开始落 token, 这条会红 -> 提醒重新评估口径
tok_nonzero = 0
scanned = 0
for p in sorted(glob.glob(m.QDIR + os.sep + '**' + os.sep + '*.jsonl', recursive=True),
                key=os.path.getmtime, reverse=True)[:6]:
    with open(p, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            scanned += 1
            try:
                u = (json.loads(line).get('message') or {}).get('usage') or {}
            except ValueError:
                continue
            if any(u.get(k) for k in ('input_tokens', 'output_tokens',
                                      'cache_read_input_tokens', 'cache_creation_input_tokens')):
                tok_nonzero += 1
print('  抽样 %d 条响应里 token 四项非零的有 %d 条 (期望 0 —— 非 0 就该重新考虑要不要并 token)'
      % (scanned, tok_nonzero))
assert scanned > 100 and tok_nonzero == 0
# 会话 id 与 CC Switch 不相交(双计前提)
clash = qb1['sids'] & base['all_sids']
print('  会话 id 不相交: Qoder %d 个 · CC Switch %d 个 · 交集 %d (期望 0)'
      % (len(qb1['sids']), len(base['all_sids']), len(clash)))
assert not clash
# 并入守恒: 请求数加得起来, token/成本一个字节都没动
d0 = dict(base)
m.merge_qoder(d0, qb1)
assert d0['reqs'] == base['reqs'] + qb1['reqs']
assert d0['real'] == base['real'] and abs(d0['cost'] - base['cost']) < 1e-9, 'Qoder 不该碰 token/成本'
assert sum(a[1] for a in d0['apps']) == d0['reqs'] == sum(r[3] for r in d0['daily']) == sum(d0['hourly'])
assert abs(d0['credits'] - sum(v['credits'] for v in qb1['by_day'].values())) < 1e-6
print('  守恒: 请求 %s+%s=%s(=Σ应用=Σ按天=Σ小时) · 净tok 未变 %s · 成本未变 %s · credits %.2f'
      % (f"{base['reqs']:,}", f"{qb1['reqs']:,}", f"{d0['reqs']:,}",
         int(d0['real'] == base['real']), int(abs(d0['cost'] - base['cost']) < 1e-9), d0['credits']))
# 双计保险: 人造一个已存在的会话 id -> 整路拒绝并入
d1 = dict(base)
m.merge_qoder(d1, dict(qb1, sids=qb1['sids'] | {next(iter(base['all_sids']))}))
print('  双计保险: 人造相交 -> 请求 %s(未变=%s) · credits %s · clash=%d (期望 不变 / 真 / 0)'
      % (f"{d1['reqs']:,}", int(d1['reqs'] == base['reqs']), d1['credits'], d1['qoder']['clash']))
assert d1['reqs'] == base['reqs'] and d1['credits'] == 0.0 and d1['qoder']['clash'] == 1
# 缺目录: 整路缺席但不崩、数字不变
real_qdir = m.QDIR
m.QDIR = os.path.join(tempfile.gettempdir(), 'no-such-qoder-dir')
assert m.fetch_qoder(st) is None
h.refresh(True)
h.root.update()
nofatal = len(h.cv.find_withtag('fatal'))
dash = h.cv.itemcget(h.ids['qoder.reqs'], 'text')
m.QDIR = real_qdir
h.refresh(True)
h.root.update()
print('  缺目录时: 红字 %d · 请求格 %r · 恢复后 %r (期望 0 / — / 非空)'
      % (nofatal, dash, h.cv.itemcget(h.ids['qoder.reqs'], 'text')))
assert nofatal == 0 and dash == '—'
assert h.cv.itemcget(h.ids['qoder.reqs'], 'text') not in ('—', '')
# 竖版不画这张卡
h.wide = False
h.refresh(True)
h.root.update()
left = [k for k in h.ids if k.startswith('qoder.')]
print('  切竖版后残留的 qoder 槽位 %s (期望 空)' % (left or '空'))
assert not left
h.wide = True
h.refresh(True)
h.root.update()
for k in ('add', 'reqs', 'sess', 'days', 'streak', 'avg'):
    print('    qoder.%-6s %r' % (k, h.cv.itemcget(h.ids['qoder.' + k], 'text')))
print('    说明行 %r' % h.cv.itemcget(h.ids['qoder.rt'], 'text'))
assert h.cv.itemcget(h.ids['qoder.rt'], 'text').startswith('不走代理')

print('=== V. 第四路起: ZCode / 牧羊人 / Codex 漏项 / Qoder CN 的口径与双计 ===')
h.expanded = True
h.wide = True
h.range_i = 3
st = h._start()
dv = h._read(st)
ex = dv.get('extra') or {}
print('  实际并进来的额外源: %s' % {k: (v.get('reqs'), v.get('in'), v.get('rd')) for k, v in ex.items() if v})
assert {'zcode', 'herdsman', 'codexgap', 'qoder-cn'} <= set(ex), '四个真账源没全并进来'
# V1 ZCode: input 含缓存读 -> 净输入必须已减, 且四项相加 == 面板净 tok
zc = ex['zcode']
cz = m.sqlite3.connect('file:' + m.ZCODE_DB.replace(os.sep, '/') + '?mode=ro', uri=True)
raw = cz.execute('select count(*), sum(input_tokens), sum(cache_read_input_tokens),'
                 ' sum(output_tokens+reasoning_tokens), sum(cache_creation_input_tokens)'
                 ' from model_usage').fetchone()
cz.close()
assert zc['reqs'] == raw[0] and zc['in'] == raw[1] - raw[2] and zc['rd'] == raw[2] \
    and zc['out'] == raw[3] and zc['cc'] == raw[4], (zc, raw)
print('  ZCode: 请求 %s = 表行数 %s · 净输入 %s = input(%s) - cache_read(%s) · 缓存读 %s'
      % (zc['reqs'], raw[0], format(zc['in'], ','), format(raw[1], ','), format(raw[2], ','),
         format(zc['rd'], ',')))
assert zc['in'] >= 0 and zc['rd'] > 0, 'ZCode 的缓存读没减 = 四项会凭空多一倍'
# V2 牧羊人: 实测 total = in + out, 无缓存分项
hd = ex['herdsman']
print('  牧羊人: 请求 %s · in %s · out %s · rd=%s cc=%s (期望 缓存两项为 0)'
      % (hd['reqs'], format(hd['in'], ','), format(hd['out'], ','), hd['rd'], hd['cc']))
assert hd['rd'] == 0 and hd['cc'] == 0
# V3 Codex 漏项: 每一个会话 id 在 CC Switch 里必须真的零行(独立 SQL), 否则就是双计
cg = ex['codexgap']
cx = m.sqlite3.connect('file:' + m.DB.replace(os.sep, '/') + '?mode=ro', uri=True)
nz = [sid for sid in cg['sids'] if cx.execute(
    'select count(*) from proxy_request_logs where session_id=?', (sid,)).fetchone()[0]]
cx.close()
print('  Codex 漏项: %d 个会话 / %s 净tok · 其中在 CC Switch 里有行的 %d 个 (期望 0)'
      % (len(cg['sids']), format(cg['in'] + cg['out'] + cg['rd'], ','), len(nz)))
assert not nz, '这些会话 CC Switch 已记过, 再并就是双计: %s' % nz[:3]
# V4 Qoder CN: token 恒 0 -> 只并请求数与 credits
qc = ex['qoder-cn']
assert qc['in'] == 0 and qc['out'] == 0 and qc['rd'] == 0 and qc['cc'] == 0
print('  Qoder CN: 请求 %s · credits %.2f · token 四项 %s (期望 全 0)'
      % (qc['reqs'], qc['credits'], (qc['in'], qc['out'], qc['rd'], qc['cc'])))
# V5 总量守恒仍然成立(九路一起)
assert sum(a[1] for a in dv['apps']) == dv['reqs'] == sum(r[3] for r in dv['daily']) == sum(dv['hourly'])
assert sum(r[2] for r in dv['daily']) == dv['real'] == dv['fresh_in'] + dv['out'] + dv['read'] + dv['creat']
print('  九路合并后: 请求 %s (=Σ应用=Σ按天=Σ小时) · 净tok %s (=Σ按天=四项) · 成本 %.2f (=Σ应用)'
      % (f"{dv['reqs']:,}", f"{int(dv['real']):,}", dv['cost']))
# V6 面板上看得见, 且无定价这件事写明了
h.refresh(True)
h.root.update()
txt = {k: h.cv.itemcget(t, 'text') for k, t in h.ids.items()
       if isinstance(t, int) and h.cv.type(t) == 'text'}
prov = ' '.join(v for k, v in txt.items() if k.startswith('prov.n'))
print('  应用表出现 ZCode %s · 牧羊人 %s · Qoder CN %s · 状态行 %r'
      % ('ZCode' in prov, ('牧羊人' in prov or 'herdsman' in prov), 'Qoder CN' in prov,
         txt.get('prov.rt', '')))
qv = txt.get('qoder.v', '')
print('  横幅明细行 %r' % qv)
for nm in ('ZCode', 'Qoder CN', '牧羊人', 'Codex未回填'):
    assert nm in prov or nm in qv, '%s 既不在应用表也不在横幅 = 并进来却看不见' % nm
assert '无本机定价' in txt.get('prov.rt', ''), '额外源不记钱这件事必须写在状态行上'
# V7 源文件缺失: 整路缺席但数字与界面都不坏
bak = (m.ZCODE_DB, m.HERD_LOG, m.CODEX_DIRS)
m.ZCODE_DB = os.path.join(tempfile.gettempdir(), 'no-zcode.sqlite')
m.HERD_LOG = os.path.join(tempfile.gettempdir(), 'no-herd.jsonl')
m.CODEX_DIRS = [os.path.join(tempfile.gettempdir(), 'no-codex')]
d0v = h._read(st)
h.refresh(True)
h.root.update()
nf = len(h.cv.find_withtag('fatal'))
m.ZCODE_DB, m.HERD_LOG, m.CODEX_DIRS = bak
h.refresh(True)
h.root.update()
print('  三个源文件都不在: 红字 %d · 请求 %s -> 恢复后 %s (期望 0 / 少一截 / 回来)'
      % (nf, f"{d0v['reqs']:,}", f"{h._read(st)['reqs']:,}"))
assert nf == 0 and d0v['reqs'] < dv['reqs']
assert h._read(st)['reqs'] == dv['reqs'] or abs(h._read(st)['reqs'] - dv['reqs']) <= 5
# V8 第九路 DSH: 会话级累计账 —— 缺目录不崩 / 数值与独立基线逐项相等 / 归日与 createdAt 一致
#    / 小时只能记到创建时刻(近似, 但必须守恒) / 并入总账守恒 / 面板上看得见
#    (本段自己一份浅拷贝: Y 段的 _cp 在下面才定义, 这里不能借用)


def _cpv(b):
    c = dict(b)
    for k in ('daily', 'apps', 'models', 'hourly'):
        c[k] = list(b[k])
    c['htok'] = [dict(x) for x in b['htok']]
    c['extra'] = dict(b.get('extra') or {})
    c['model_names'] = set(b.get('model_names') or ())
    c['app_parts'] = dict(b.get('app_parts') or {})
    return c


dsh = m.fetch_dsh(0)
assert dsh is not None, '本机 %s 读不到任何 DSH 会话, 这一段无从验起' % m.DSH_DIR
nD, _cD, tkD, daysD, modelsD = _dsh_base(0)
bdD = dsh['by_day']
print('  DSH: 轮次 %s = 独立基线 %s · 净输入 %s · 输出 %s · 命中 %s · 缓存写 %s · %d 天 / %d 会话'
      % (f"{dsh['reqs']:,}", nD, f"{dsh['in']:,}", f"{dsh['out']:,}", f"{dsh['rd']:,}",
         f"{dsh['cc']:,}", dsh['days'], dsh['sessions']))
# 1 数值正确性: 四项逐项与独立基线相等(不拿 HUD 自己的数自证)
assert dsh['reqs'] == nD, 'DSH 轮次数与独立基线不符: %s vs %s' % (dsh['reqs'], nD)
assert sum(v['in'] for v in bdD.values()) == sum(v[1] for v in daysD.values())
assert sum(v['out'] for v in bdD.values()) == sum(v[2] for v in daysD.values())
assert sum(v['rd'] for v in bdD.values()) == sum(v[3] for v in daysD.values())
assert sum(v['cc'] for v in bdD.values()) == sum(v[4] for v in daysD.values())
assert dsh['in'] + dsh['out'] + dsh['rd'] + dsh['cc'] == tkD, '四桶相加与独立基线不符'
# 2 归日正确: 键都是 YYYY-MM-DD, 且集合与 createdAt 换算出来的日子一致
assert all(re.fullmatch(r'\d{4}-\d{2}-\d{2}', k) for k in bdD), \
    'by_day 键不是 YYYY-MM-DD: %s' % list(bdD)
assert set(bdD) == set(daysD), '归日与 createdAt 换算不一致: %s vs %s' % (sorted(bdD), sorted(daysD))
for k in bdD:
    assert bdD[k]['reqs'] == daysD[k][0] and bdD[k]['in'] == daysD[k][1] \
        and bdD[k]['out'] == daysD[k][2] and bdD[k]['rd'] == daysD[k][3] \
        and bdD[k]['cc'] == daysD[k][4], 'DSH %s 当天数与独立基线不符' % k
# 2b 归日**反向**校验(上面 2 只证"两条路径算得一样", 证不了换算本身对):
#    _dsh_base 与 fetch_dsh 用的是同一句 ca/1000 换算, 若那句本身写错(例如错减 86400、
#    或把毫秒当秒用), 两边会错得一模一样 -> 2 照样绿。所以这里绕开 daysD 与 fromtimestamp,
#    直接从原始毫秒值独立算一遍日子: 取 UTC 纪元偏移时区再手动加本地偏移, 与 by_day 对。
_utc_off = -time.timezone if not time.daylight else -time.altzone
for _p in sorted(glob.glob(os.path.join(m.DSH_DIR, '*.json'))):
    try:
        with open(_p, encoding='utf-8', errors='replace') as _fh:
            _j = json.load(_fh)
        _rec = _j.get('record') or {}
        _rows = _rec.get('rows') or {}
        _tot = ((_rows.get('tokenUsage') or {}).get('val') or {}).get('totals') or {}
        _ca = (_rec.get('identity') or {}).get('createdAt')
        _s = sum(int(_tot.get(_k) or 0) for _k in
                 ('uncachedInputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens'))
    except (OSError, ValueError, TypeError, AttributeError):
        continue
    if not isinstance(_ca, (int, float)) or _s == 0:
        continue
    # 纯算术: 毫秒 -> 本地日。用 time.gmtime 取 UTC 年月日, 与"本地日"这条路径完全不同源。
    _local_sec = _ca / 1000.0 + _utc_off
    _d_utc = time.gmtime(_local_sec)
    _dte_calc = '%04d-%02d-%02d' % (_d_utc.tm_year, _d_utc.tm_mon, _d_utc.tm_mday)
    # 与本机用 fromtimestamp 得到的那天核对(若两者不等, 是时区换算本身有错, 先炸出来)
    assert _dte_calc == dt.date.fromtimestamp(_ca / 1000.0).isoformat(), \
        ('DSH 归日换算本身不一致: 算术法 %s vs fromtimestamp %s (%s)'
         % (_dte_calc, dt.date.fromtimestamp(_ca / 1000.0).isoformat(), os.path.basename(_p)))
    assert _dte_calc in bdD, \
        'DSH 会话 %s 应为 %s, 但 by_day 里没有这一天: %s' % (
            os.path.basename(_p), _dte_calc, sorted(bdD))
print('    归日 %s (与 createdAt 换算的 %d 天逐一相等)'
      % (', '.join('%s:%d轮' % (k, bdD[k]['reqs']) for k in sorted(bdD)), len(daysD)))
# 3 模型表: 全部模型都计入(不做 deepseek 筛选), 且 [轮次, in+out] 与独立基线相等
assert dsh['models'] == modelsD, 'DSH 模型表与独立基线不符: %s vs %s' % (dsh['models'], modelsD)
assert len(dsh['models']) >= 2, 'DSH 只并进 %d 个模型, 全模型计入的口径没落实' % len(dsh['models'])
print('    模型 %s' % ', '.join('%s:%d轮/%s' % (k, v[0], f"{v[1]:,}")
                                for k, v in sorted(dsh['models'].items(), key=lambda x: -x[1][1])))
# 4 小时口径: 只能记到创建时刻(近似), 但 Σ小时 / Σhtok 必须与总量逐项守恒 ——
#   这一条正是本路口径的核心: 没把累计值平摊到多个小时, 也没让小时视图与总量脱节
htD = m.hourly_rows(dsh['htok'])
assert sum(dsh['hourly']) == dsh['reqs'] == sum(v['reqs'] for v in bdD.values()), \
    'DSH Σ小时 != 总轮次 = 今日档条形会少画'
assert sum(sum(v['hours']) for v in bdD.values()) == dsh['reqs'], 'DSH 逐日 hours 与轮次不守恒'
assert sum(r[3] for r in htD) == dsh['reqs'], 'DSH htok 请求数与轮次不守恒'
assert sum(r[2] for r in htD) == tkD, 'DSH htok token 与四桶总量不守恒'
assert dsh['h1'] == sum(v['h1'] for v in bdD.values()) and dsh['h1'] <= dsh['reqs'], \
    'DSH 近1小时与逐日 h1 不守恒(或超过总轮次)'
print('    Σ小时 %s = 总轮次 %s · Σhtok token %s = 四桶 %s (记到创建时刻, 近似)'
      % (f"{sum(dsh['hourly']):,}", f"{dsh['reqs']:,}",
         f"{sum(r[2] for r in htD):,}", f"{tkD:,}"))
# 5 并入总账守恒: reqs / real 的增量 == DSH 自己的值, 且各视图仍然互相对平
dD = _cpv(h._read(st))
b0 = (dD['reqs'], dD['real'], dD['cost'])
nDs = m.fetch_dsh(st)
assert nDs is not None, '范围档下 DSH 应当仍有量'
m.merge_extra(dD, nDs)
assert dD['reqs'] == b0[0] + nDs['reqs'], '并入后请求数增量 != DSH 的轮次'
assert abs(dD['real'] - (b0[1] + nDs['in'] + nDs['out'] + nDs['rd'] + nDs['cc'])) < 1, \
    '并入后真实消耗增量 != DSH 四桶'
assert abs(dD['cost'] - b0[2]) < 1e-9, 'DSH 不该产生美元成本'
assert sum(a[1] for a in dD['apps']) == dD['reqs'] == sum(r[3] for r in dD['daily']) \
    == sum(dD['hourly']) == sum(b['reqs'] for b in dD['htok']), \
    'DSH 并进来之后总账不再自洽(应用/按天/小时/htok 有一处没并齐)'
assert abs(sum(r[2] for r in dD['daily']) - dD['real']) < 1, 'DSH 并进来之后按天净 tok 与总量脱节'
print('    并入守恒: 请求 %s + %s = %s (=Σ应用=Σ按天=Σ小时=Σhtok) · 净tok %s + %s = %s · 成本未变 %s'
      % (f"{b0[0]:,}", f"{nDs['reqs']:,}", f"{dD['reqs']:,}",
         f"{int(b0[1]):,}", f"{nDs['in'] + nDs['out'] + nDs['rd'] + nDs['cc']:,}",
         f"{int(dD['real']):,}", int(abs(dD['cost'] - b0[2]) < 1e-9)))
# 6 双计保险: DSH 的会话 uuid 一旦出现在 CC Switch 里就整路拒绝并入(与其它额外源同一套)
baseD = h._read(st)
assert not (dsh['sids'] & set(baseD['all_sids'])), 'DSH 会话 id 与 CC Switch 相交 -> 会双计'
dC2 = _cpv(baseD)
m.merge_extra(dC2, dict(dsh, sids=dsh['sids'] | {next(iter(baseD['all_sids']))}))
assert dC2['reqs'] == baseD['reqs'] and dC2['extra']['dsh'].get('clash'), \
    '人造会话 id 相交后 DSH 没被拒绝并入'
print('    双计保险: 与 CC Switch %d 个会话 id 不相交 · 人造相交后整路拒绝(请求 %s 未变)'
      % (len(baseD['all_sids']), f"{dC2['reqs']:,}"))
# 7 缺目录: 整路缺席、返回 None、不崩、不碰任何数, 也不影响其它八路
real_dsh_dir = m.DSH_DIR
m.DSH_DIR = os.path.join(tempfile.gettempdir(), 'no-such-dsh-dir')
try:
    assert m.fetch_dsh(0) is None, 'DSH 目录不存在却返回了账'
    assert m.fetch_dsh(st) is None, 'DSH 目录不存在却返回了范围账'
    dM = _cpv(h._read(st))
    beforeM = (dM['reqs'], dM['real'], dM['hit'], len(dM.get('extra') or {}))
    m.merge_extra(dM, m.fetch_dsh(0) or {})
    assert (dM['reqs'], dM['real'], dM['hit'], len(dM.get('extra') or {})) == beforeM, \
        'DSH 目录不存在却改动了对账数字'
    assert set(dM.get('extra') or {}) == set(dv.get('extra') or {}) - {'dsh'}, \
        'DSH 缺席时其它八路的 extra 被动了: %s' % sorted(dM.get('extra') or {})
    h.refresh(True)
    h.root.update()
    assert not h.cv.find_withtag('fatal'), 'DSH 目录不存在时面板出了红字'
    print('    缺目录: fetch 返回 None · 请求/净tok/命中率/extra 全不变 1 · 红字 0 · '
          '其它八路仍在 %s' % sorted(set(dM.get('extra') or {})))
finally:
    m.DSH_DIR = real_dsh_dir
h.refresh(True)
h.root.update()
# 8 面板上看得见: 应用表或横幅明细里必须出现 DSH(并进来却看不见 = 用户视角没有这一路)
txtD = {k: h.cv.itemcget(t, 'text') for k, t in h.ids.items()
        if isinstance(t, int) and h.cv.type(t) == 'text'}
provD = ' '.join(v for k, v in txtD.items() if k.startswith('prov.n'))
qvD = txtD.get('qoder.v', '')
assert 'DSH' in provD or 'DSH' in qvD, 'DSH 既不在应用表也不在横幅 = 并进来却看不见'
print('    面板可见: 应用表 %s · 横幅 %s' % ('DSH' in provD, 'DSH' in qvD))
# 快照是临时产物, 不许留在 %TEMP% 里(与 T7 导出判据同一套收尾纪律)
m.DSH_DIR = _REAL_DSH_DIR
try:
    import shutil as _sh
    _sh.rmtree(_DSH_SNAP, ignore_errors=True)
except OSError:
    pass
print('    DSH 判据跑完: 已切回真目录 %s · 临时快照已清理 %s'
      % (os.path.basename(_REAL_DSH_DIR), not os.path.isdir(_DSH_SNAP)))

print('=== W. 今日档按小时条形图: 九路小时守恒 / 画法切换 / 悬停 / 无残留 ===')
h.expanded = True
h.wide = True
h.range_i = 0                                        # 今日
h.refresh(True)
h.root.update()
time.sleep(0.2)
h.root.update()
d0w = h._read(h._start())
ht = d0w['htok']
assert len(ht) == 24, '小时桶必须是 24 格'
sr = sum(b['reqs'] for b in ht)
st = sum(b['in'] + b['out'] + b['rd'] + b['cc'] for b in ht)
sc = sum(b['cost'] for b in ht)
g = lambda k: h.cv.itemcget(h.ids[k], 'text') if k in h.ids else '<无槽位>'
print('  九路逐小时: Σ请求 %s == 总请求 %s · Σ净tok %s == 真实消耗 %s · Σ成本 %.2f == 总成本 %.2f'
      % (sr, d0w['reqs'], format(int(st), ','), format(int(d0w['real']), ','), sc, d0w['cost']))
assert sr == d0w['reqs'], '有源的请求没落到小时桶 = 条形会少画'
assert abs(st - d0w['real']) < 1, '逐小时 token 与真实消耗不等 = 柱高与顶部数字对不上'
assert abs(sc - d0w['cost']) < 0.02, '逐小时成本与总成本不等 = 折线与总成本对不上'
assert h._barm and g('c6.rt').startswith('按小时'), '今日档没切到条形模式: %r' % g('c6.rt')
assert (g('c6.d0'), g('c6.dm'), g('c6.d1')) == ('00时', '12时', '23时'), 'X 轴没换成小时刻度'
lgs = [g('lg%d' % i) for i in range(5)]
print('  图例 %s · 说明行 %r' % (lgs, g('c6.rt')))
assert lgs[0].startswith('净token') and lgs[1].startswith('成本')
assert not any(lgs[2:]), '条形档还留着曲线档的图例文字(残留)'
for i in (2, 3, 4):                                   # 圆点也得挪出可视区, 不然留几个孤点
    cx, cy = h.cv.coords(h.ids['lg.dot%d' % i])[:2]
    assert cx < 0 or cy < 0, 'lg.dot%d 还在画布上 (%.0f,%.0f)' % (i, cx, cy)
# 悬停: 落在第 i 格就该读那一小时(带状布局, 不能四舍五入到柱心)
days, px0, pyt, pstep, pH, ppad, pmt, pmc = h._plot
act = [i for i, r in enumerate(days) if r[3]]
assert act, '今日没有任何小时有请求, 无法验悬停'
i0 = act[len(act) // 2]
Ev2 = lambda x, y: type('E', (), {'x': x, 'y': y, 'x_root': 1200, 'y_root': 300})()
h._hover(Ev2(px0 + (i0 + 0.5) * pstep, pyt + pH / 2.0))
tip = h._tip_lab.cget('text').splitlines()
print('  悬停第 %d 格 -> 首行 %r (期望 %r)' % (i0, tip[0], '%s 这一小时 · 今日' % days[i0][0]))
assert tip[0] == '%s 这一小时 · 今日' % days[i0][0], '悬停读到了别的小时'
assert '请求 %s' % format(days[i0][3], ',') in tip[1], '读数里的请求数与该小时桶不符'
h._tip_hide()
# 切回 7 天档: 必须回到折线, 且条形档的图例/标签不留痕
h.range_i = 1
h.refresh(True)
h.root.update()
time.sleep(0.2)
h.root.update()
lgs2 = [g('lg%d' % i) for i in range(5)]
print('  切 7 天档: 条形模式=%s · 图例 %s · 峰值 %r · 说明 %r'
      % (h._barm, lgs2, g('c6.peak'), g('c6.rt')))
assert not h._barm and lgs2[0] == '成本' and len(set(lgs2)) == 5
assert g('c6.peak').startswith('最大一天'), '多天档的峰值标注丢了'
assert g('c6.rt').startswith('左轴token')
# 空档: 一根柱都没有也不能崩
h.range_i = 0
_bak = m.DB
h.refresh(True)
h.root.update()
zero = [b['reqs'] for b in d0w['htok']]
print('  今日 24 格里 %d 格有请求 · 全零格不画柱(有请求但无 token 的源画短提示)'
      % sum(1 for v in zero if v))
assert h.cv.find_withtag('fatal') == ()

print('=== X. 跟随启停: 开机只判定一回 + CC Switch 退出则跟着退出 ===')
# X1 启动文件夹里不该再有"直接启动 HUD"的快捷方式, 只该有判定器
#     .lnk 用 Python 直接解: 目标路径与参数是文件里的 UTF-16LE 串, 不依赖 PowerShell 的递归
startup = os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows', 'Start Menu',
                       'Programs', 'Startup')
assert os.path.isdir(startup), '找不到启动文件夹: %s' % startup


def lnk_text(path):
    raw = open(path, 'rb').read()
    runs = re.findall(b'(?:[ -~]\x00){4,}', raw)
    return ' '.join(r.decode('utf-16le', 'replace') for r in runs).lower()


lnks = {f: lnk_text(os.path.join(startup, f)) for f in os.listdir(startup)
        if f.lower().endswith('.lnk')}
hud_direct = sorted(f for f, t in lnks.items() if 'cc-hud.pyw' in t)
probe_lnk = sorted(f for f, t in lnks.items() if 'follow-probe.pyw' in t)
print('  启动文件夹共 %d 个快捷方式 · 指向 HUD 本体 %s · 指向判定器 %s (期望 0 个 / 1 个)'
      % (len(lnks), hud_direct, probe_lnk))
for f in probe_lnk:
    print('    %s -> %s' % (f, lnks[f][:150]))
assert not hud_direct, 'HUD 还在开机自启名单里: %s' % hud_direct
assert len(probe_lnk) == 1, '判定器的快捷方式没装对: %s' % list(lnks)

# X2 判定函数的完整真值表(只判定一回 = 纯函数, 不轮询不常驻)
from importlib.machinery import SourceFileLoader as _SFL
probe = _SFL('probe', r'G:\AIrenwu\cc-hud\follow-probe.pyw').load_module()
cases = [
    (None, False, None, False),      # CC 没跑 -> 不起
    (None, True, None, False),       # CC 没跑且 HUD 在(不该发生) -> 不起
    (111, True, None, False),        # HUD 已有一份 -> 不起
    (111, False, None, True),        # CC 在跑且没有 HUD -> 起
    (111, False, 111, False),        # 用户在这个 CC 生命周期里主动退过 -> 不起
    (111, False, 222, True),         # 标记属于上一个 CC 进程 -> 照常跟随
    (111, True, 111, False),         # 三个条件同时 -> 不起
    (222, False, 111, True),         # CC 重启换了 PID -> 恢复跟随
]
bad = [(c, r, probe.should_launch(c[0], c[1], c[2])) for c in cases
       for r in [c[3]] if probe.should_launch(c[0], c[1], c[2]) != r]
print('  判定真值表 %d 组, 判错 %d 组 (期望 0)' % (len(cases), len(bad)))
assert not bad, bad

# X3 mark_quit 与判定器真的联动(写盘 -> 判定器读到 -> 不再拉起)
old_mark = probe.MARKER
probe.MARKER = m.QUIT_MARK = os.path.join(tempfile.gettempdir(), 'hud-x3-marker')
try:
    os.path.exists(probe.MARKER) and os.remove(probe.MARKER)
    h.mark_quit()
    mk = probe.marker_pid()
    print('  mark_quit 写入 %r · 判定器读到 %r · 再判定 %s (期望 有 PID / 同值 / False)'
          % (open(probe.MARKER, encoding='utf-8').read(), mk,
             probe.should_launch(mk, False, mk)))
    assert mk and not probe.should_launch(mk, False, mk)
finally:
    if os.path.exists(probe.MARKER):
        os.remove(probe.MARKER)
    probe.MARKER = old_mark

# X4 CC Switch 消失 -> HUD 跟着退出; 但挂着定时电源时不能退(否则取消不了关机)
# X4「CC Switch 消失 -> HUD 跟着退出」这条只能在独立子进程里验(一个进程建两个 HUD 会共用
#     模块级精灵缓存, ImageTk 位图绑定 Tcl 解释器, 第二个实例一隐藏就报 pyimage doesn't exist)。
#     子进程实测结果见 %TEMP%/hud_follow_quit.py 的输出; 这里只钉住代码路径不被改坏。
# 拆分后实现在 cchud/*.py 里: 源码文本判据改成扫「启动器 + 包」全部源码, 判据本身不变
src4 = ''.join(open(_p, encoding='utf-8').read() for _p in
               [r'G:\AIrenwu\cc-hud\cc-hud.pyw'] + sorted(glob.glob(r'G:\AIrenwu\cc-hud\cchud\*.py')))
assert '暂不跟随退出' in src4 and src4.count('self.quit()') >= 2,     '跟随退出的两条分支(有定时不退 / 无定时退)被改掉了'
print('  跟随退出分支在位: 定时未清不退 %s · 无定时跟着 quit %s (期望 真 / 真)'
      % (int('暂不跟随退出' in src4), int(src4.count('self.quit()') >= 2)))

print('=== Y. 第七、八路 WorkBuddy(国内/国外): 拆桶不多不少 / 与独立基线对账 / 积分只认国内 / 双计保险 / 缺目录 ===')


def _cp(b):
    """浅拷贝一份可变的容器再并 —— merge_extra 会就地改 daily/apps/models/htok。"""
    c = dict(b)
    for k in ('daily', 'apps', 'models', 'hourly'):
        c[k] = list(b[k])
    c['htok'] = [dict(x) for x in b['htok']]
    c['extra'] = dict(b.get('extra') or {})
    c['model_names'] = set(b.get('model_names') or ())
    c['app_parts'] = dict(b.get('app_parts') or {})
    return c


stY = h._start()
allZ = {}
for projects, key, cred in m.WB_SOURCES:
    z = m.fetch_workbuddy(0, projects, key, cred)
    allZ[key] = z
    if not os.path.isdir(projects):
        assert z is None, '目录不存在却返回了账'
        print('  %-13s 目录不存在 -> 整路缺席(None), 不碰任何数' % key)
        continue
    n, _c0, tk, cr, tt, psum, osum = _wb_base(0, projects, cred)
    bd = z['by_day']
    four = z['in'] + z['out'] + z['rd'] + z['cc']
    print('  %s: 独立数 %5d 次 / HUD %5d 次 · 净输入 %s + 命中 %s + 写 %s + 输出 %s'
          % (key, n, z['reqs'], f"{z['in']:,}", f"{z['rd']:,}", f"{z['cc']:,}", f"{z['out']:,}"))
    assert z['reqs'] == n, '请求数与独立基线不符'
    # 拆桶不多不少: 净输入+命中+写 必须正好还原成应用自己记的 prompt_tokens
    assert z['in'] + z['rd'] + z['cc'] == psum, \
        '净输入+命中+写 != Σprompt(缓存少减/多减了): %s vs %s' % (f"{z['in']+z['rd']+z['cc']:,}", f'{psum:,}')
    assert z['out'] == osum, '输出与独立基线不符'
    assert four == tk == tt, '四桶相加 != prompt+completion != 应用自记 total_tokens'
    # 每一路都要"并进所有视图", 只进一半是这个 HUD 历史上真发生过的 bug
    assert sum(v['reqs'] for v in bd.values()) == n
    assert sum(z['hourly']) == n == sum(sum(v['hours']) for v in bd.values())
    htY = m.hourly_rows(z['htok'])
    assert sum(r[3] for r in htY) == n and sum(r[2] for r in htY) == four, '逐小时与总量不守恒'
    assert sum(v['in'] for v in bd.values()) == z['in'] and sum(v['rd'] for v in bd.values()) == z['rd']
    # 积分: 国内版逐调用记得到 -> 与独立基线逐分对齐; 国外版两本账互相矛盾 -> 一个都不并
    assert abs(z['credits'] - (cr if cred else 0.0)) < 1e-6, \
        '%s 积分并错了: HUD %.2f vs 基线 %.2f(该版原始带值积分)' % (key, z['credits'], cr)
    raw_ai = _wb_base(0, projects, True)[3]
    print('    积分: HUD %.2f · 该版原始逐调用 Σ%.2f · 会话 %d · 有账 %d 天'
          % (z['credits'], raw_ai, z['sessions'], z['days']))
    if not cred:
        assert raw_ai > 0, '国外版本机一条积分都没有? 那"不并"的理由就变了, 要重写说明'
    # 双计保险: 会话 id 既不能撞上 CC Switch, 也不能撞上另一版
    dY = h._read(stY)
    assert not (z['sids'] & dY['all_sids']), '与 CC Switch 会话 id 相交 -> 会双计'
    # 人造一个相交会话 -> merge_extra 必须整路拒绝, 一个数都不进
    dC = _cp(dY)
    m.merge_extra(dC, dict(z, sids=z['sids'] | {next(iter(dY['all_sids']))}))
    zz = dC['extra'][key]
    assert dC['reqs'] == dY['reqs'] and zz.get('clash') and not zz['by_day'], '人造相交没被拒绝'
    print('    双计保险: 与 CC Switch %d 个会话 id 不相交 · 人造相交后整路拒绝(请求 %s 未变)'
          % (len(dY['all_sids']), f"{dC['reqs']:,}"))
if len(allZ) == 2 and allZ.get('workbuddy') and allZ.get('workbuddy-ai'):
    ov = allZ['workbuddy']['sids'] & allZ['workbuddy-ai']['sids']
    print('  两版会话 id 交集 %d (期望 0 —— 国内/国外各记各的账)' % len(ov))
    assert not ov, '两版会话 id 相交 -> 会双计'
# 缺目录: 整路缺席, 不崩也不碰任何数
old = m.WB_SOURCES
m.WB_SOURCES = [(os.path.join(tempfile.gettempdir(), 'no-such-workbuddy'), 'workbuddy', True),
                (os.path.join(tempfile.gettempdir(), 'no-such-workbuddy-ai'), 'workbuddy-ai', False)]
assert m.fetch_workbuddy(0, m.WB_SOURCES[0][0], 'workbuddy', True) is None
dN = _cp(h._read(stY))
before = (dN['reqs'], dN['real'], dN['hit'], len(dN.get('extra') or {}))
m.merge_extra(dN, m.fetch_workbuddy(0, m.WB_SOURCES[0][0], 'workbuddy', True) or {})
assert (dN['reqs'], dN['real'], dN['hit'], len(dN.get('extra') or {})) == before, \
    '目录不存在却改动了对账数字'
print('  缺目录: fetch 返回 None · 并入后 请求/净tok/命中率/extra 全不变 %s (期望 真)'
      % int((dN['reqs'], dN['real'], dN['hit'], len(dN.get('extra') or {})) == before))
m.WB_SOURCES = old
# 横幅槽位: 全部档下六格 + 两行说明都必须被赋值, 且"仅国内"字样在位
h.range_i = len(m.RANGES) - 1
h.expanded, h.wide = True, True
h.refresh(True)
h.root.update()
txtY = {k: h.cv.itemcget(h.ids['wb.' + k], 'text')
        for k in ('cred', 'reqs', 'tok', 'sess', 'days', 'avg', 'v', 'rt')}
for k, v in txtY.items():
    print('    wb.%-5s %r' % (k, v))
assert all(v for v in txtY.values()), '全部档横幅有空槽位(静默失效)'
assert '仅国内' in h.cv.itemcget(h.ids['wb.credl'], 'text'), '积分格没写明只有国内版给得出'
assert '不并' in txtY['rt'], '说明行没交代国外版积分为何不并'

print('=== Z. 展开必须居中 / 收起回到圆球那个角 / 点圆球一定浮到最前 ===')
dd = int(round(m.PEEK * h.s))
zl, zt, zr, zb = m._work_area(hwnd=h.root.winfo_id())
h.expanded, h.wide = False, True
h.refresh(True)
settle()
h.state['peek'] = [zr - dd - int(round(28 * h.s)), zt + int(round(36 * h.s))]
h._set_visible(True)
settle()
h.toggle()                                   # 小 -> 大
settle()
zw, zh = h.root.winfo_width(), h.root.winfo_height()
zx, zy = h.root.winfo_x(), h.root.winfo_y()
ecx, ecy = zl + (zr - zl - zw) // 2, zt + (zb - zt - zh) // 2
print('  展开后左上 (%d,%d) 尺寸 %dx%d · 工作区(%d,%d,%d,%d)正中应为 (%d,%d) · 偏 %d/%d px (期望 <=2)'
      % (zx, zy, zw, zh, zl, zt, zr, zb, ecx, ecy, abs(zx - ecx), abs(zy - ecy)))
assert abs(zx - ecx) <= 2 and abs(zy - ecy) <= 2, '大面板没落在屏幕正中'
assert h._place_next is None, '居中标记没被消费 —— 那样每次刷新都会被拽回正中, 用户拖不动'
# 居中只管"这一次切换": 之后拖到哪儿都该留在哪儿
h.root.geometry('+%d+%d' % (zl + 40, zt + 40))
h.refresh(True)
settle()
print('  拖到 (%d,%d) 后再刷新: 实测 (%d,%d) · 没被拽回 %s (期望 真)'
      % (zl + 40, zt + 40, h.root.winfo_x(), h.root.winfo_y(),
         int((h.root.winfo_x(), h.root.winfo_y()) == (zl + 40, zt + 40))))
assert (h.root.winfo_x(), h.root.winfo_y()) == (zl + 40, zt + 40), '拖完之后刷新又被搬走了'
# 大 -> 小: 回到圆球那个角, 且是"沿圆球向左下扩展"(右上角对齐圆点右上角, 不是左上角)
h.toggle()
settle()
cx2, cy2 = h.root.winfo_x() + h.root.winfo_width(), h.root.winfo_y()
wx2, wy2 = h.state['peek'][0] + dd, h.state['peek'][1]
print('  收起后右上角 (%d,%d) vs 圆球右上角 (%d,%d) · 差 %d/%d (期望都 <=2 —— 向左下长)'
      % (cx2, cy2, wx2, wy2, abs(cx2 - wx2), abs(cy2 - wy2)))
assert abs(cx2 - wx2) <= 2 and abs(cy2 - wy2) <= 2, '收起态没沿圆球向左下扩展'
# 点圆球唤回: 必须真的映射出来并浮在最前(用 Win32 的 WS_EX_TOPMOST 位判, 不信 attributes 的返回形状)
h._set_visible(False)
settle()
px_, py_ = h._pk.winfo_x() + 9, h._pk.winfo_y() + 9
Ev = lambda: type('E', (), {'x_root': px_, 'y_root': py_})()
h._pk_down(Ev())
h._pk_up(Ev())
settle()
mapped = bool(h.root.winfo_ismapped())
_hw = ctypes.windll.user32.GetAncestor(h.root.winfo_id(), 3)          # GA_ROOT: 样式位在顶层窗口上
_ex = ctypes.windll.user32.GetWindowLongW(_hw, -20)                  # GWL_EXSTYLE
exs = _ex & 0x8                                                      # WS_EX_TOPMOST
cx3 = h.root.winfo_x() + h.root.winfo_width()
print('  点圆球: 面板映射 %s · EXSTYLE=0x%X 含 WS_EX_TOPMOST->%s · 右上角 %d vs 圆点右上角 %d (期望 真 / 真 / 差<=2)'
      % (mapped, _ex & 0xFFFFFFFF, bool(exs), cx3, wx2))
assert mapped and exs, '点圆球没把面板显示出来 / 没浮到最前'
assert abs(cx3 - wx2) <= 2, '点圆球唤出的小面板没贴在圆球上'
h.state['peek'] = [pk0[0], pk0[1]]
h._save()

h.state.clear()
h.state.update(ORIG_STATE)
if not h.deadline and not h.fired:            # 测试武装过的定时不能留在用户的状态文件里
    for k in ('dl', 'pk', 'pf'):
        h.state.pop(k, None)
h._save()
h.quit()
