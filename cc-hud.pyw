# -*- coding: utf-8 -*-
r"""CC Switch 悬浮统计 HUD · 只读两份库 (mode=ro): %USERPROFILE%\.cc-switch\cc-switch.db
 与 cc-haha 的会话索引库(路径自动发现, 见 haha_db)。

口径(两路数据源合并后的总量, 单看 CC Switch 那一路仍与它界面逐位对账过):
  新增输入 = sum(input_tokens) - sum(cache_read_tokens where data_source='codex_session')
             ^ codex 回填行的 input_tokens 本身已含缓存读, 不减就是重复计(全库 20.0亿 vs 净 14.1亿)
  真实消耗 = 新增输入 + 输出 + 缓存创建 + 缓存命中
  缓存命中率 = 命中 / (命中 + 新增输入 + 创建)
  第二路 cc-haha(直连 Claude Code, 不经过 CC Switch 代理)按**本地日**并进上面每一个维度:
  成本/四项token/请求数/小时分布/模型表/应用表/今日·昨日·近1小时 全部一起并 —— 并一半就会
  出现「总请求 272 而应用行相加 34」这种各说各话, verify S 段按四个范围逐项钉住。
  能并的前提是两个源的会话 id 不相交(双计保险在 merge_haha, R 段断言)。
  只有**状态码与延迟**仍是 CC Switch 口径 —— cc-haha 的 transcript 里没有这两维, 面板上写明了。
计时只存在于 data_source='proxy' 的行(代理转发实测), 会话日志回填的行和 cc-haha 那一路都没有计时。
只读取用量与配置字段, 绝不读取 providers.settings_config / universal_providers / cc-haha 的
providers.json —— 那三处存明文 API key。两份库一律 mode=ro。
刷新只就地改文字/坐标/颜色, 不销毁重建 -> 无闪烁。

启动机制: 跟随器就是进程本身 —— 每 3s 用 Toolhelp32 快照查一次 cc-switch.exe,
CC Switch 起来就显示, 退出就隐藏并停止读库(隐藏时零 SQL)。
「启动文件夹\CC Switch HUD.lnk」让它开机常驻(命名互斥体保证只有一份)。
隐藏后从系统托盘找回: 左键/双击 = 显示·隐藏互切, 右键 = 弹同一个菜单。
托盘图标默认被 Windows 收在任务栏溢出菜单里, 要常驻需在
「设置 → 个性化 → 任务栏 → 其他系统托盘图标」打开本项。
"""
import ctypes
import json
import math
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import datetime as dt
from urllib.parse import urlsplit, urlunsplit
from ctypes import wintypes as wt

import tkinter as tk
from tkinter import font as tkfont

DB = os.path.join(os.path.expanduser('~'), '.cc-switch', 'cc-switch.db')
# Qoder 的 agent 会话目录(第三路)。它不走 CC Switch 代理, 所以那 943 条代理行里根本没有它;
# 与 cc-haha 一样按候选位置找, 找不到就整路缺席(不报错)。
QDIR = os.path.join(os.path.expanduser('~'), '.qoder', 'projects')
# Qoder CN 是**另一个**目录(国际版 .qoder / CN 版 .qoder-cn), 两套会话账互不相干。
QDIR_CN = os.path.join(os.path.expanduser('~'), '.qoder-cn', 'projects')
ZCODE_DB = os.path.join(os.path.expanduser('~'), '.zcode', 'cli', 'db', 'db.sqlite')
HERD_LOG = os.path.join(os.path.expanduser('~'), '.herdsman', 'model_stats', 'events.jsonl')
CODEX_DIRS = [os.path.join(os.path.expanduser('~'), '.codex', 'sessions'),
              os.path.join(os.path.expanduser('~'), '.codex', 'archived_sessions')]
# cc-haha(Claude Code 桌面壳)的索引库。它的配置目录**会被整机搬走**(实测: 先 C:\Users\Admin\.claude,
# 10-08 之后搬到 E:\cc-haha), 写死任一路径都会静默读到一份不再更新的旧索引 —— 所以这里按候选位置
# 逐个找、取 mtime 最新的那个。找法与 cc-haha 自己的扫描根一致: <配置目录>\cc-haha\db\index-v1.sqlite。
HDB_SUB = os.path.join('cc-haha', 'db', 'index-v1.sqlite')
_QODER_FILES = {}         # Qoder 会话 jsonl 的按文件解析缓存(同 _HAHA_FILES 一套做法)
_HAHA_FILES = {}          # transcript -> ((size, mtime_ns, file_id), {message id: ...})


def _fixed_drives():
    """只数**本地固定盘**。GetLogicalDrives 会把已断开的映射盘/空光驱也算进来, 对它们做
    isdir() 可能阻塞几十秒 —— 这是界面线程, 不能冒这个险。"""
    try:
        k = ctypes.windll.kernel32
        mask = k.GetLogicalDrives()
        return ['%s:\\' % chr(65 + i) for i in range(26)
                if (mask & (1 << i)) and k.GetDriveTypeW('%s:\\' % chr(65 + i)) == 3]
    except Exception:
        return []


def haha_cfg():
    """返回 (cc-haha 索引库路径, transcript 根目录), 找不到则 (None, None)。

    cc-haha 的配置目录整机搬过家(C 盘 .claude -> E:\\cc-haha), 写死任一处都会在搬家后
    **静默读到一份不再更新的死库** —— 所以按候选逐个 stat 取 mtime 最新的那个, 每次刷新
    重找(实测 0.2ms)。"""
    cands = []
    env = os.environ.get('CLAUDE_CONFIG_DIR')
    if env:
        cands.append(env)
    cands.append(os.path.join(os.path.expanduser('~'), '.claude'))
    for d in _fixed_drives():
        cands.append(os.path.join(d, 'cc-haha'))
    best, bm, broot = None, 0.0, None
    for root in cands:
        try:
            m = os.path.getmtime(os.path.join(root, HDB_SUB))
        except OSError:
            continue
        if m > bm:
            best, bm, broot = os.path.join(root, HDB_SUB), m, root
    return (best, os.path.join(broot, 'projects')) if best else (None, None)


def sid_of(path):
    """transcript 路径 -> 所属会话 id。子代理文件在 <父会话uuid>/subagents/agent-x.jsonl 下,
    归属要算到父会话(它索引里 session_id 记的就是父 id)。"""
    q = str(path).replace(os.sep, '/').rstrip('/')
    # 子代理在 <父会话uuid>/subagents/agent-x.jsonl 下: rsplit 只切两刀, [-3] 还是整条前缀,
    # 必须再取一次 basename 才是父 id(否则和 CC Switch 的 session_id 永不相等, 防双计形同虚设)
    return q.rsplit('/', 2)[-3].rsplit('/', 1)[-1] if '/subagents/' in q else q.rsplit('/', 1)[-1][:-6]


def _parse_transcript(path):
    """单个 transcript -> {message id: (本地日期, 本地秒, in, out, 缓存命中, 缓存创建, 模型)}。
    文件内先按 id 收敛(流式回写会把同一响应重复几行)。
    带上「本地秒 + 模型」是为了让请求数也能并进 近1小时 / 24小时 / 模型表 ——
    索引库只有 UTC 日聚合, 给不出小时, 也给不出每模型几次响应。"""
    rows = {}
    try:
        fh = open(path, encoding='utf-8', errors='replace')
    except OSError:
        return rows
    with fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            msg = j.get('message')
            u = msg.get('usage') if isinstance(msg, dict) else None
            if not isinstance(u, dict):
                continue
            mid = msg.get('id') or j.get('uuid') or ''
            if not mid:
                continue
            try:
                ep = dt.datetime.strptime((j.get('timestamp') or '')[:19],
                                          '%Y-%m-%dT%H:%M:%S').replace(
                    tzinfo=dt.timezone.utc).timestamp()
            except ValueError:
                continue
            # 流式回写可能先落一条不完整 usage，再用同一个 message id 补全；
            # 保留文件中最后一条，避免 first-write-wins 把最终 token 永久截断。
            rows[mid] = (dt.date.fromtimestamp(ep).isoformat(), int(ep),
                         int(u.get('input_tokens') or 0), int(u.get('output_tokens') or 0),
                         int(u.get('cache_read_input_tokens') or 0),
                         int(u.get('cache_creation_input_tokens') or 0),
                         str(msg.get('model') or '(未记录)'))
    return rows


def haha_days(pdir):
    """自己按**本地日**给 cc-haha 那一路分桶, 并做**跨文件全局去重**。两个理由:
    ① 索引里的 date 是 UTC 日, 直接并进来会把「本地 00:00~08:00 的量」整段记到昨天
      (实测同一会话 10-09T23:48Z 与 10-10T00:30Z 被拆成两行, 而本地都是 10-10);
    ② 一条 API 响应 = 一个 message id, 但 fork/续跑会把整段历史抄进新文件 —— 只按文件去重
      会把它算两次(实测 53.1M vs 全局去重 42.9M, 差 24%)。所以按路径定序全局去重。
    成本 transcript 里没有, 所以这里只出 token 分项 + 每会话的日份额, 成本由 fetch_haha 分摊。
    另外顺手记下每(日,模型)与每(日,小时)的响应数: 索引库只有 UTC 日聚合, 给不出小时、也
    给不出"某个模型今天响应了几次", 而面板的 24 小时格 / 模型表请求数要这两维才能并齐。
    缓存按 (size, mtime): transcript 只追加, 一个文件变了才重解析那一个(首次 90ms, 命中 1ms)。
    """
    days, per_sid, sids = {}, {}, set()
    ex = {'mreqs': {}, 'hours': {}, 'h1': 0, 'mtoks': {}, 'sid_models': {},
          'htok': new_hourly()}
    # mreqs/hours/mtoks 都按本地日分桶；sid_models 用于把索引库成本按真实
    # transcript 的本地日和模型 token 份额分摊，避免 UTC 日与本地日错位。
    if not pdir or not os.path.isdir(pdir):
        return days, per_sid, sids, ex
    paths = []
    for dp, _, fs in os.walk(pdir):
        for fn in fs:
            if fn.endswith('.jsonl'):
                paths.append(os.path.join(dp, fn))
    # 去重集合必须是**每次调用局部**的: 上一版把它做成模块级全局, 第一次调用就把 id 全
    # 领完了, 之后每次聚合都以为"这些响应别人算过了" -> by_day 直接空, 并入量凭空消失。
    seen = set()
    now = time.time()
    for path in sorted(paths):                      # 定序 => 去重结果可复现
        try:
            st = os.stat(path)
        except OSError:
            continue
        # 秒级 mtime 会漏掉同一秒内的追加/修订；纳秒时间和文件身份一起作为缓存键。
        key = (st.st_size, getattr(st, 'st_mtime_ns', int(st.st_mtime * 1_000_000_000)),
               getattr(st, 'st_ino', 0))
        got = _HAHA_FILES.get(path)
        if got and got[0] == key:
            rows = got[1]
        else:
            rows = _parse_transcript(path)
            _HAHA_FILES[path] = (key, rows)
            if len(_HAHA_FILES) > 400:               # 缓存只是加速器, 涨过头就整份重来
                _HAHA_FILES.clear()
                _HAHA_FILES[path] = (key, rows)
        sid = sid_of(path)
        sids.add(sid)
        mine = per_sid.setdefault(sid, {})
        for mid, (dte, ep, i, o, r, c, mdl) in rows.items():
            if mid in seen:
                continue
            seen.add(mid)
            for bag in (days.setdefault(dte, NEWDAY()), mine.setdefault(dte, NEWDAY())):
                bag['in'] += i
                bag['out'] += o
                bag['rd'] += r
                bag['cc'] += c
                bag['msgs'] += 1
            mr = ex['mreqs'].setdefault(dte, {})
            mr[mdl] = mr.get(mdl, 0) + 1
            hr = ex['hours'].setdefault(dte, [0] * 24)
            hr[time.localtime(ep).tm_hour] += 1
            hb = ex['htok'][time.localtime(ep).tm_hour]      # 逐小时四项(今日档条形要用)
            hb['in'] += i
            hb['out'] += o
            hb['rd'] += r
            hb['cc'] += c
            hb['reqs'] += 1
            mt = ex['mtoks'].setdefault(dte, {}).setdefault(mdl, [0, 0, 0, 0, 0])
            mt[0] += i
            mt[1] += o
            mt[2] += r
            mt[3] += c
            mt[4] += 1
            sm = ex['sid_models'].setdefault(sid, {}).setdefault(mdl, 0)
            ex['sid_models'][sid][mdl] = sm + i + o + r + c
            if ep >= now - 3600:
                ex['h1'] += 1
    return days, per_sid, sids, ex


NEWDAY = lambda: {'in': 0, 'out': 0, 'rd': 0, 'cc': 0, 'cost': 0.0, 'msgs': 0}
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hud-state.json')
REFRESH_MS = 30_000
POLL_MS = 150                                          # 界面心跳: 收托盘事件
CC_TICKS = 20                                          # 每 20 拍(≈3s)查一次 CC Switch
RANGES = [('今日', 1), ('7 天', 7), ('30 天', 30), ('全部', 0)]
ALPHAS = (1.0, 0.96, 0.92, 0.86, 0.78)

CARD_W = 424                                   # 逻辑像素
WIDE_W = 1560                                  # 宽版总宽: 1560 逻辑px = 1950 物理px @125% (4 列 × 2 排 + 趋势一整行)
CHIP_BLOCK_W = 380                             # 范围胶囊那一块的最大宽度(宽版下不跟着拉长)
PAD = 13
PEEK = 34                                      # 隐藏后留在角落的呼出圆点直径
# 下面每一档都是从用户参考图实测出来的占比最高色, 不是眼睛估的:
#   页面底 #0b0e14(21%) 卡片 #10131d(27%) 卡片亮档 #171a24 描边 #22262e~#2a2d36
#   轨道 #1c1f2a 琥珀 #fbbf24 靛底 #1d2040 青底 #122937 绿底 #102a2b
BG, CARD, CARD2 = '#0b0e14', '#10131d', '#171a24'
EDGE, TRACK = '#262b36', '#1c1f2a'
FG, DIM, FAINT, MUTED = '#e8edf5', '#8a97a8', '#5c6878', '#454f63'
CY, GR, VI, AM, PK, TE, MA, IN = ('#38bdf8', '#34d399', '#a78bfa', '#fbbf24',
                                  '#f472b6', '#2dd4bf', '#c084fc', '#6366f1')
# CC Switch 原版「使用统计」曲线配色(从其界面截图实测的色桶): 输入蓝/输出绿/创建橙/命中紫/成本红
CH_IN, CH_OUT, CH_CW, CH_RD, CH_COST = '#3b82f6', '#10b981', '#f97316', '#a855f7', '#ef4444'
# CC Switch 对「非代理来源」的请求记的是合成 provider_id, 这里只做显示别名;
# 导出的 JSON 里仍是原始 id。
PROV_ALIAS = {'_codex_session': 'Codex会话回填', '_session': 'Claude会话回填',
              '_opencode_session': 'OpenCode回填'}
# app_type → CC Switch 侧边栏显示名(库里目前只出现过 codex/claude/opencode, 其余按官方列表补齐)
APP_ALIAS = {'codex': 'Codex', 'claude': 'Claude Code', 'claude-desktop': 'Claude Desktop',
             'gemini': 'Gemini CLI', 'grok': 'Grok Build', 'opencode': 'OpenCode',
             'openclaw': 'OpenClaw', 'hermes': 'Hermes', 'pi': 'Pi', 'minimax': 'MiniMax Code',
             'qoder': 'Qoder', 'qoder-cn': 'Qoder CN', 'zcode': 'ZCode',
             'herdsman': '牧羊人(本地)'}        # 不走代理的直连客户端, 见 fetch_qoder/fetch_zcode


def money(v):
    return '$%.2f' % v if abs(v) < 100 else '$%.0f' % v


def big(n):
    n = int(n)
    if n >= 1_0000_0000:
        return '%.2f亿' % (n / 1_0000_0000)
    if n >= 1_0000:
        return '%.1f万' % (n / 1_0000)
    return f'{n:,}'


def secs(ms):
    """P95 耗时实测到 122.9s —— 裸秒写成 '122.9s' 没法一眼读, 进位成分秒。"""
    if ms is None:
        return '—'
    if ms < 10000:
        return '%.2fs' % (ms / 1000)
    if ms < 60000:
        return '%.1fs' % (ms / 1000)
    return '%d分%02d秒' % (ms // 60000, (ms % 60000) // 1000)


def stamp(ts):
    if not ts:
        return '-'
    return dt.datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts).strftime('%m-%d %H:%M')


def host(u):
    return re.sub(r'^https?://', '', (u or '').rstrip('/'))


def redact_url(u):
    """导出用 URL：保留站点和路径，去掉查询串、片段和认证信息。"""
    try:
        p = urlsplit(str(u))
        if not p.netloc:
            return str(u)
        netloc = p.hostname or ''
        if p.port:
            netloc += ':%d' % p.port
        return urlunsplit((p.scheme, netloc, p.path, '', ''))
    except Exception:
        return '<REDACTED_URL>'


_SECRET_TEXT = re.compile(r'(?i)(bearer\s+|api[_-]?key\s*[=:]\s*|token\s*[=:]\s*)[^\s,;]+')


def _redact_export(value, key=''):
    if isinstance(value, dict):
        return {k: _redact_export(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_export(v, key) for v in value]
    if isinstance(value, str):
        value = re.sub(r'https?://[^\s)]+', lambda m: redact_url(m.group(0)), value)
        return _SECRET_TEXT.sub(r'\1<REDACTED>', value)
    return value


def _scale():
    try:
        import ctypes
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0


def _dpi_aware():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class _MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('rcMonitor', wt.RECT),
                ('rcWork', wt.RECT), ('dwFlags', wt.DWORD)]


def _work_area(hwnd=None, point=None):
    """返回目标显示器的工作区；目标不可用时回退到系统主工作区。"""
    u = ctypes.windll.user32
    try:
        if hwnd:
            mon = u.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        elif point is not None:
            pt = wt.POINT(int(point[0]), int(point[1]))
            mon = u.MonitorFromPoint(pt, 2)
        else:
            mon = None
        if mon:
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if u.GetMonitorInfoW(mon, ctypes.byref(info)):
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom
    except (AttributeError, OSError, TypeError, ctypes.ArgumentError):
        pass
    r = wt.RECT()
    u.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
    return r.left, r.top, r.right, r.bottom


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


def _pct(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, int(len(v) * q))]


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


POWERS = [('screen', '关闭显示器'), ('sleep', '睡眠'), ('hibernate', '休眠'),
          ('logout', '注销'),
          ('reboot', '重启'), ('off', '关机')]
PMINS = [(15, '15 分钟'), (30, '30 分钟'), (60, '1 小时'), (120, '2 小时')]
PMIN_LO, PMIN_HI = 1, 720        # 自定义步进的钳位范围(分钟)
PROV_ROWS = 8                    # 应用与供应商合表行数: 3 行应用 + 5 行供应商/回填

GRACE = 15                                       # 到点后留给 shutdown 自己的反悔窗口(秒)


POWERSD = dict(POWERS)


def run_power(kind):
    """执行电源动作, 返回 True 只代表"确实下发出去了"。
    关屏/睡眠/休眠走 API, 关机/重启走 shutdown 并带 /t 宽限, 注销走 shutdown /l(无宽限、不可撤)。"""
    u = ctypes.windll.user32
    if kind == 'screen':
        # SC_MONITORPOWER + 2 = 关屏; 动一下鼠标就回来, 不影响任何程序。
        # 必须是 Post: SendMessageW 对 0xFFFF(所有顶层窗口)是**同步广播**, 只要有一个
        # 不泵消息的窗口在, UI 线程就跟着一起卡死 —— 而这条链就挂在 _tick 里。
        return bool(u.PostMessageW(0xFFFF, 0x112, 0xF170, 2))
    if kind in ('sleep', 'hibernate'):
        # SetSuspendState(bHibernate, bForce, bWakeupEventsDisabled)。第一参才是关键:
        #   0 = 睡眠(本机实测只有 S0 低电量待机, S3 待机固件不支持)
        #   1 = 休眠(写 hiberfil.sys 后断电, powercfg /a 里"休眠"在可用列表)
        # 第二参一律 0 = 不强杀应用 —— 强杀会丢未保存的东西, 与关机不带 /f 同一个理由。
        return bool(ctypes.windll.powrprof.SetSuspendState(1 if kind == 'hibernate' else 0, 0, 0))
    flag = {'logout': '/l', 'reboot': '/r', 'off': '/s'}[kind]
    args = ['shutdown', flag] + ([] if kind == 'logout' else ['/t', str(GRACE)])
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=10, creationflags=0x08000000)   # 0x08000000 = 无窗口
    except Exception:
        return False
    return r.returncode == 0


def abort_power():
    """撤掉已经交给系统的关机/重启倒计时。返回 False = 系统那边本来就没有倒计时。"""
    try:
        return subprocess.run(['shutdown', '/a'], capture_output=True,
                              timeout=10).returncode == 0
    except Exception:
        return False


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


# ── 数据层: 每个字段都来自真实 SQL ──────────────────────────────────────────
def merge_extra(d, s):
    """把"额外真账源"(ZCode / 牧羊人 / Codex 漏项 / Qoder CN)并进总量。

    只并这个源**实际给得出**的维度: token 四项为 0 的源不产生 token, 没有定价的源成本记 0,
    credits 只有 Qoder 系给。双计保险与另两路同一套 —— 会话/请求 id 一旦与 CC Switch 交集
    就整路拒绝并入。"""
    d.setdefault('extra', {})
    if not s or not s.get('by_day'):          # 这一路缺席: 只在 extra 里留个空位, 不碰任何数
        return d
    d['extra'][s['key']] = s
    clash = set(s['sids']) & set(d.get('all_sids') or ())
    if clash:
        z = dict(s, clash=len(clash), by_day={}, reqs=0, credits=0.0, hourly=[0] * 24, h1=0)
        z.update({'in': 0, 'out': 0, 'rd': 0, 'cc': 0})   # in/out/rd/cc 是关键字, 只能这样塞
        d['extra'][s['key']] = z
        return d
    bd = s['by_day']
    n = sum(v['reqs'] for v in bd.values())
    d['reqs'] += n
    d['credits'] = d.get('credits', 0.0) + sum(v['credits'] for v in bd.values())
    d['fresh_in'] += s['in']
    d['out'] += s['out']
    d['read'] += s['rd']
    d['creat'] += s['cc']
    d['real'] = d['fresh_in'] + d['out'] + d['read'] + d['creat']
    dn = d['read'] + d['fresh_in'] + d['creat']
    d['hit'] = (d['read'] / dn * 100) if dn else 0.0
    d['hourly'] = [a + b for a, b in zip(d['hourly'], s['hourly'])]
    if s.get('htok'):
        merge_hour(d['htok'], s['htok'])                      # ZCode/牧羊人/Codex漏项: 逐请求时间戳
    else:
        for v in s['by_day'].values():                        # Qoder CN: 只有响应数
            for hh, k in enumerate(v.get('hours') or []):
                add_hour(d['htok'], hh, 0, 0, 0, 0, k)
    d['h1'] = (d['h1'][0] + s['h1'], d['h1'][1])
    today = time.strftime('%Y-%m-%d')
    yday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    d['today'] = (d['today'][0] + bd.get(today, {}).get('reqs', 0), d['today'][1])
    d['yday'] = (d['yday'][0] + bd.get(yday, {}).get('reqs', 0), d['yday'][1])
    pos = {r[0]: i for i, r in enumerate(d['daily'])}
    for dte in sorted(bd):
        v = bd[dte]
        if dte in pos:
            i = pos[dte]
            o = d['daily'][i]
            fi, ot, cw, rd = o[5] + v['in'], o[6] + v['out'], o[7] + v['cc'], o[8] + v['rd']
            dn2 = rd + fi + cw
            d['daily'][i] = (o[0], o[1], fi + ot + cw + rd, o[3] + v['reqs'],
                             (rd / dn2 * 100) if dn2 else o[4], fi, ot, cw, rd)
        else:
            d['daily'].append((dte, 0.0, v['in'] + v['out'] + v['rd'] + v['cc'], v['reqs'],
                               0.0, v['in'], v['out'], v['cc'], v['rd']))
    d['daily'].sort()
    d['adays'] = max(int(d.get('adays') or 0), len(d['daily']))
    names = d.setdefault('model_names', set())
    for mdl, (rq, tk) in (s.get('models') or {}).items():
        names.add(mdl)
        old = [m for m in d['models'] if m[0] == mdl]
        if old:
            i = d['models'].index(old[0])
            m0 = d['models'][i]
            d['models'][i] = (m0[0], m0[1] + rq, m0[2], m0[3] + tk)
        else:
            d['models'].append((mdl, rq, 0.0, tk))
    d['models'].sort(key=lambda r: -r[2])
    d['models'] = d['models'][:4]
    d['nmodel'] = len(names)
    # 应用行的命中率走 app_parts(与 fetch 同一套 rd/fi/cw 三元组), 不从展示值反推
    app = s['app']
    ap = d.setdefault('app_parts', {})
    rd0, fi0, cw0 = ap.get(app, (0, 0, 0))
    rd1, fi1, cw1 = rd0 + s['rd'], fi0 + s['in'], cw0 + s['cc']
    ap[app] = (rd1, fi1, cw1)
    dn = rd1 + fi1 + cw1
    hit = (rd1 / dn * 100) if dn else 0.0
    tk = s['in'] + s['out'] + s['rd'] + s['cc']
    old = [a for a in d['apps'] if a[0] == app]
    if old:
        i = d['apps'].index(old[0])
        a0 = d['apps'][i]
        d['apps'][i] = (a0[0], a0[1] + n, a0[2], a0[3] + tk, hit)
    else:
        d['apps'].append((app, n, 0.0, tk, hit))
    d['apps'].sort(key=lambda r: -r[2])
    if s.get('last') and (not d['last'] or s['last'] > d['last']):
        d['last'] = s['last']
    return d


def new_hourly():
    """24 个小时桶。今日档的趋势卡要按小时画用量, 所以每一路都得能按小时给出
    净输入/输出/缓存两项/请求数/成本 —— 缺一路, 柱高就和顶部总量对不上。"""
    return [{'reqs': 0, 'in': 0, 'out': 0, 'rd': 0, 'cc': 0, 'cost': 0.0} for _ in range(24)]


def add_hour(ht, hh, i, o, rd, cc, rq, cost=0.0):
    if 0 <= hh < 24:
        b = ht[hh]
        b['in'] += i
        b['out'] += o
        b['rd'] += rd
        b['cc'] += cc
        b['reqs'] += rq
        b['cost'] += cost


def merge_hour(dst, src):
    for i, b in enumerate(src or []):
        add_hour(dst, i, b['in'], b['out'], b['rd'], b['cc'], b['reqs'], b['cost'])


def hourly_rows(ht):
    """整形成与 daily 行**同一个元组形状** —— 悬停读数/峰值/左右轴都按那个形状取字段,
    今日档换画法就不用再写一套读数。"""
    out = []
    for hh, b in enumerate(ht):
        fi, o, cw, rd = b['in'], b['out'], b['cc'], b['rd']
        dn = rd + fi + cw
        out.append(('%02d时' % hh, b['cost'], fi + o + cw + rd, b['reqs'],
                    (rd / dn * 100) if dn else 0.0, fi, o, cw, rd))
    return out


def spread_cost(ht, total):
    """只有区间级成本的源(cc-haha / ZCode / 牧羊人), 按各小时 token 份额摊到小时上:
    合计不变, 今日档(区间就是一天)摊法精确; 多天档不画条形, 摊法只影响看不见的桶。"""
    tk = [b['in'] + b['out'] + b['rd'] + b['cc'] for b in ht]
    t = sum(tk)
    if total <= 0:
        return ht
    if t <= 0:
        nz = [i for i, b in enumerate(ht) if b['reqs']]
        for i in nz:
            ht[i]['cost'] += total / len(nz)
        return ht
    for i, v in enumerate(tk):
        ht[i]['cost'] += total * v / t
    return ht


def fetch(db, start):
    cond = 'created_at >= ?' if start else '1'
    cond2 = 'l.created_at >= ?' if start else '1'
    p = [start] if start else []
    q = lambda sql: db.execute(sql, p).fetchall()
    one = lambda sql: db.execute(sql, p).fetchone()

    reqs, cost, tin, tout, cread, ccreat, codexread, ok = (float(x) for x in one(f"""
        select count(*), coalesce(sum(total_cost_usd),0), coalesce(sum(input_tokens),0),
            coalesce(sum(output_tokens),0), coalesce(sum(cache_read_tokens),0),
            coalesce(sum(cache_creation_tokens),0),
            coalesce(sum(case when data_source='codex_session' then cache_read_tokens else 0 end),0),
            coalesce(sum(case when status_code=200 then 1 else 0 end),0)
        from proxy_request_logs where {cond}"""))
    fresh_in = tin - codexread
    denom = cread + fresh_in + ccreat
    cin, cout, crd, cwr = (float(x) for x in one(f"""
        select coalesce(sum(input_cost_usd),0), coalesce(sum(output_cost_usd),0),
            coalesce(sum(cache_read_cost_usd),0), coalesce(sum(cache_creation_cost_usd),0)
        from proxy_request_logs where {cond}"""))

    providers = []
    for n, app, rc, cs, tkn, rd, i_t, cw2, cxs in q(f"""
        select coalesce(nullif(p.name,''), l.provider_id), l.app_type, count(*),
            coalesce(sum(l.total_cost_usd),0),
            coalesce(sum(l.input_tokens+l.output_tokens+l.cache_read_tokens+l.cache_creation_tokens),0),
            coalesce(sum(l.cache_read_tokens),0), coalesce(sum(l.input_tokens),0),
            coalesce(sum(l.cache_creation_tokens),0),
            coalesce(sum(case when l.data_source='codex_session' then l.cache_read_tokens else 0 end),0)
        from proxy_request_logs l left join providers p on p.id = l.provider_id
        where {cond2} group by 1,2 order by 4 desc"""):
        fi = i_t - cxs
        dn = rd + fi + cw2
        providers.append((n, app, int(rc), cs, tkn, (rd / dn * 100) if dn else 0.0))
    # 会话日志回填的行没有 provider_id(库里是 '_session'/'_codex_session'), 它们不是
    # 「用过的 API 接口」, 单独分组, 别占掉真服务商的展示槽位。
    isbf = lambda r: (not r[0]) or str(r[0]).startswith('_')
    backfill = [r for r in providers if isbf(r)]
    providers = [r for r in providers if not isbf(r)]

    # 按应用(app_type)汇总: CC Switch 顶栏那一排应用过滤就是这一维。
    # 之前 HUD 只有跨应用合计 + 供应商表, 用户的 Claude Code 用量(1187 请求/$165.98)
    # 只在表里以「Claude会话回填」出现, 看着就像完全没记录。
    apps = []
    app_parts = {}
    for a, rc, cs, tkn, rd, i_t, cw2, cxs in q(f"""
        select app_type, count(*), coalesce(sum(total_cost_usd),0),
            coalesce(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0),
            coalesce(sum(cache_read_tokens),0), coalesce(sum(input_tokens),0),
            coalesce(sum(cache_creation_tokens),0),
            coalesce(sum(case when data_source='codex_session' then cache_read_tokens else 0 end),0)
        from proxy_request_logs where {cond} group by 1 order by 3 desc"""):
        fi = i_t - cxs
        dn = rd + fi + cw2
        # 第 4 位与「真实消耗」同口径: codex 回填行的 input_tokens 本身含缓存读,
        # 四项直接相加会把那段缓存算两遍(实测全库 20.0亿 vs 净 14.1亿)。
        apps.append((a, int(rc), cs, tkn - cxs, (rd / dn * 100) if dn else 0.0))
        app_parts[a] = (rd, fi, cw2)

    # cc-haha 的索引只给四项 token 和一个总成本, 不给分项成本。分项单价从 CC Switch 里
    # claude 行的实测值反推(全库口径, 不随范围抖动), 再把 cc-haha 的总成本按这个比例摊到四项上,
    # 这样「四项合计」永远等于总成本, 不会出现两个对不上的总数。
    cprice = [float(x or 0) for x in db.execute(
        "select coalesce(sum(input_cost_usd),0)/nullif(sum(input_tokens),0),"
        " coalesce(sum(output_cost_usd),0)/nullif(sum(output_tokens),0),"
        " coalesce(sum(cache_read_cost_usd),0)/nullif(sum(cache_read_tokens),0),"
        " coalesce(sum(cache_creation_cost_usd),0)/nullif(sum(cache_creation_tokens),0)"
        " from proxy_request_logs where app_type='claude'").fetchone()]

    # 「本范围N个模型」用**范围过滤后**的去重集合: 不能拿 limit 4 的展示表判重
    # (否则范围里排不进前四的模型会被当成新模型, 模型表出现两条同名行), 也不能拿全库
    # 去重集合(那样今日会报出 15 个, 写的却是「本范围」)。
    model_names = {r[0] for r in db.execute(
        "select distinct coalesce(nullif(model,''),'(未记录)') from proxy_request_logs"
        " where %s" % cond, p)}
    models = [(r[0], int(r[1]), r[2], r[3] - r[4]) for r in q(f"""
        select coalesce(nullif(model,''),'(未记录)'), count(*),
        coalesce(sum(total_cost_usd),0),
        coalesce(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0),
        coalesce(sum(case when data_source='codex_session' then cache_read_tokens else 0 end),0)
        from proxy_request_logs where {cond} group by 1 order by 3 desc limit 4""")]
    prices = {r[0]: (r[1], r[2]) for r in db.execute(
        'select model_id, input_cost_per_million, output_cost_per_million from model_pricing')}

    daily = []
    day_parts = {}
    for d, cs, tkn, rc, rd, i_t, cw2, cxs, tin_d, tout_d in q(f"""
        select date(created_at,'unixepoch','localtime'), coalesce(sum(total_cost_usd),0),
            coalesce(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0),
            count(*), coalesce(sum(cache_read_tokens),0), coalesce(sum(input_tokens),0),
            coalesce(sum(cache_creation_tokens),0),
            coalesce(sum(case when data_source='codex_session' then cache_read_tokens else 0 end),0),
            coalesce(sum(input_tokens),0), coalesce(sum(output_tokens),0)
        from proxy_request_logs where {cond} group by 1 order by 1"""):
        fi = i_t - cxs
        dn = rd + fi + cw2
        # 第 3 位 = 当日净 token(四项相加, 输入已减掉 codex 双计), 第 6 位 = 净新增输入:
        # 曲线的「输入」线、峰值标注、悬停读数都从这里取, 必须与顶部「真实消耗」同一口径。
        daily.append((d, cs, fi + tout_d + cw2 + rd, rc, (rd / dn * 100) if dn else 0.0,
                      fi, tout_d, cw2, rd))
        day_parts[d] = (rd, fi, cw2)

    hourly = [0] * 24
    for hh, n in q("select cast(strftime('%H', created_at,'unixepoch','localtime') as int), count(*)"
                   f" from proxy_request_logs where {cond} group by 1"):
        if 0 <= hh <= 23:
            hourly[hh] = n

    ht = new_hourly()
    for hh, rc, i_t, o_t, rd_t, cw_t, cxs, cs in q(f"""
        select cast(strftime('%H', created_at,'unixepoch','localtime') as int), count(*),
            coalesce(sum(input_tokens),0), coalesce(sum(output_tokens),0),
            coalesce(sum(cache_read_tokens),0), coalesce(sum(cache_creation_tokens),0),
            coalesce(sum(case when data_source='codex_session' then cache_read_tokens
                      else 0 end),0), coalesce(sum(total_cost_usd),0)
        from proxy_request_logs where {cond} group by 1"""):
        add_hour(ht, hh, int(i_t) - int(cxs), int(o_t), int(rd_t), int(cw_t), int(rc), cs)

    lat = [r[0] for r in q('select latency_ms from proxy_request_logs where %s and latency_ms > 0' % cond)]
    ftt = [r[0] for r in q('select first_token_ms from proxy_request_logs where %s and first_token_ms > 0' % cond)]
    sp_w, sp_g = [], []
    for o, l, f in q('select output_tokens, latency_ms, first_token_ms from proxy_request_logs'
                     ' where %s and latency_ms > 0 and output_tokens > 0' % cond):
        sp_w.append(o / (l / 1000.0))
        if f and l > f and l - f > 500:
            sp_g.append(o / ((l - f) / 1000.0))
    mlast, mtot = db.execute('select max(created_at), count(*) from proxy_request_logs'
                             ' where latency_ms > 0').fetchone()

    now = time.time()
    t0 = int(dt.datetime.combine(dt.date.today(), dt.time.min).timestamp())
    win = lambda lo, hi: db.execute('select count(*), coalesce(sum(total_cost_usd),0)'
                                    ' from proxy_request_logs where created_at>=? and created_at<?',
                                    [lo, hi]).fetchone()
    today, yday, h1, h5 = win(t0, now + 1), win(t0 - 86400, t0), win(now - 3600, now + 1), \
        win(now - 5 * 3600, now + 1)
    first, last, sess, nmodel, adays = one(f"""select min(created_at), max(created_at),
        count(distinct session_id), count(distinct model),
        count(distinct date(created_at,'unixepoch','localtime')) from proxy_request_logs where {cond}""")
    status = q('select status_code, count(*) from proxy_request_logs where %s group by 1'
               ' order by 2 desc' % cond)
    errors = q("select coalesce(nullif(error_message,''),'(无描述)'), count(*) from proxy_request_logs"
               " where %s and status_code <> 200 group by 1 order by 2 desc limit 2" % cond)

    cur = {r[0]: r[1] for r in db.execute('select app_type, name from providers where is_current=1')}
    ptotal = db.execute('select count(*) from providers').fetchone()[0]
    eps = db.execute("select coalesce(nullif(p.name,''), e.provider_id), e.app_type, e.url"
                     ' from provider_endpoints e left join providers p on p.id = e.provider_id').fetchall()
    chk = db.execute('select provider_name, app_type, response_time_ms, http_status, tested_at'
                     ' from stream_check_logs order by tested_at desc limit 1').fetchone()
    pc = db.execute("select listen_address, listen_port, streaming_first_byte_timeout,"
                    " streaming_idle_timeout, non_streaming_timeout, max_retries,"
                    " auto_failover_enabled, circuit_failure_threshold, circuit_error_rate_threshold,"
                    " circuit_min_requests, enable_logging from proxy_config where app_type='codex'").fetchone()
    if pc is None:
        pc = ('-', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    o = db.execute("select value from settings where key='optimizer_config'").fetchone()
    try:
        opt = json.loads(o[0]) if o and o[0] else {}
        opt = opt if isinstance(opt, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        opt = {}
    c = db.execute("select value from settings where key='common_config_codex'").fetchone()
    ctx = c[0] if c else ''
    g = lambda pat: (re.search(pat + r'\s*=\s*"?([\w.]+)"?', ctx) or [None, None])[1]
    roll = db.execute('select max(date), sum(request_count) from usage_daily_rollups').fetchone()
    try:
        dsize = os.path.getsize(DB) / 1048576.0
    except OSError:
        dsize = 0.0

    return {
        'reqs': int(reqs), 'cost': cost, 'ok': int(ok), 'fail': int(reqs - ok),
        'credits': 0.0,                    # 只有 Qoder 那一路给得出这个维度, 先建好键免得下游 KeyError
        'fresh_in': fresh_in, 'out': tout, 'creat': ccreat, 'read': cread,
        'real': fresh_in + tout + ccreat + cread,
        'hit': (cread / denom * 100) if denom else 0.0,
        'cin': cin, 'cout': cout, 'crd': crd, 'cwr': cwr,
        'providers': providers, 'backfill': backfill, 'apps': apps,
        'models': models, 'prices': prices,
        'daily': daily, 'hourly': hourly, 'htok': ht,
        'lat': {'n': len(lat), 'p50': _pct(lat, .5), 'p95': _pct(lat, .95),
                'ftt_n': len(ftt), 'ftt': _pct(ftt, .5), 'ftt95': _pct(ftt, .95),
                'sp_w': _pct(sp_w, .5), 'sp_g': _pct(sp_g, .5), 'sp_n': len(sp_g),
                'last': mlast, 'total': mtot},
        'today': (int(today[0]), today[1]), 'yday': (int(yday[0]), yday[1]),
        'h1': (int(h1[0]), h1[1]), 'h5': (int(h5[0]), h5[1]),
        'sessions': sess, 'nmodel': nmodel, 'adays': adays, 'first': first, 'last': last,
        'status': status, 'errors': errors, 'cur': cur, 'ptotal': ptotal, 'eps': eps,
        'chk': chk, 'proxy': pc, 'opt': opt,
        'ctx_window': g('model_context_window'), 'compact': g('model_auto_compact_token_limit'),
        'effort': g('model_reasoning_effort'),
        'rollup': roll, 'dsize': dsize, 'cprice': cprice,
        'model_names': model_names,
        'claude_sids': {r[0] for r in db.execute(
            "select distinct session_id from proxy_request_logs where app_type='claude'")},
        'codex_sids': {r[0] for r in db.execute(
            "select distinct session_id from proxy_request_logs"
            " where data_source='codex_session'")},
        # Qoder 那一路的双计保险要看**全部** data_source: 哪天 Qoder 被改去走代理,
        # 它的会话 id 就会出现在这里, merge_qoder 于是整路拒绝并入。
        'all_sids': {r[0] for r in db.execute(
            "select distinct session_id from proxy_request_logs")},
        'day_parts': day_parts, 'app_parts': app_parts,
    }


def dur(ms):
    """会话时长量级是小时, 不能套 secs() 的秒。"""
    if not ms:
        return '—'
    s = int(ms / 1000)
    if s >= 3600:
        r = s % 3600 // 60
        return '%d小时%d分' % (s // 3600, r) if r else '%d小时' % (s // 3600)
    if s >= 60:
        return '%d分%d秒' % (s // 60, s % 60) if s % 60 else '%d分' % (s // 60)
    return '%d秒' % s


def fetch_haha(start):
    """cc-haha(Claude Code CLI 桌面壳)的索引库 —— 只读, 读不到就返回 None, 不算错误。

    它索引的是 cc-haha 自己的 Claude Code 配置目录 —— 实测在 E:\\cc-haha(以前是
    C:\\Users\\Admin\\.claude, 整机搬过一次), 所以路径交给 haha_cfg() 自动发现: 写死任一处
    都会静默读到一份不再更新的死库。按天明细不用它索引的 date(那是 UTC 日), 而是自己解析
    transcript 按本地日分桶, 见 haha_days()。CC Switch 的 claude 回填只扫 C 盘那个旧目录, 于是
    **10-08 之后的 Claude 用量两边都没有**(10-08 $6.51 / 10-09 $26.49 / 10-10 $12.43),
    这就是用户说的"疯狂跑却一点没记"。所以这一路的钱和 token **要并入总量**(merge_haha)。
    不会重复计的依据: 两个源的父会话 id 交集为 0(CC Switch 4 个老会话 / cc-haha 3 个新会话),
    verify R 段专门断言这件事 —— 哪天开始重叠了 R 段先红, 而不是让总量静默翻倍。
    """
    try:
        path, pdir = haha_cfg()
        if not path:
            return None
        db = sqlite3.connect('file:' + path.replace(os.sep, '/') + '?mode=ro', uri=True)
    except Exception:
        return None
    try:
        db.execute('pragma busy_timeout=1200')
        # start 是本地日午夜；索引库 date 是 UTC 日。查询下界先换成 UTC，
        # 最终 token/模型/请求口径再由本地 transcript 明细裁剪。
        local_d0 = time.strftime('%Y-%m-%d', time.localtime(start)) if start else '0000-01-01'
        db_d0 = (dt.datetime.fromtimestamp(start, dt.timezone.utc).date().isoformat()
                 if start else '0000-01-01')
        tok, cost, rd, fin = db.execute(
            "select coalesce(sum(input_tokens+output_tokens+cache_read_input_tokens"
            " +cache_creation_input_tokens),0), coalesce(sum(cost_usd),0),"
            " coalesce(sum(cache_read_input_tokens),0),"
            " coalesce(sum(input_tokens+output_tokens+cache_creation_input_tokens),0)"
            " from activity_daily_models where date>=?", (db_d0,)).fetchone()
        msgs = calls = 0
        for adate, mcount, ccount in db.execute(
                "select date, coalesce(sum(message_count),0), coalesce(sum(tool_call_count),0)"
                " from activity_daily where date>=? group by date", (db_d0,)):
            try:
                local_date = dt.datetime.strptime(str(adate)[:10], '%Y-%m-%d').replace(
                    tzinfo=dt.timezone.utc).astimezone().date().isoformat()
            except ValueError:
                continue
            if local_date >= local_d0:
                msgs += int(mcount or 0)
                calls += int(ccount or 0)
        days = []          # 先占位, 解析完 transcript 再用**本地日**填(见下方 by_day)
        # 子代理 transcript 的 session_id 记的是**父会话**的 id, 按 session_id 去重会把
        # 14 个子代理算成 1 个 —— 所以这里按 transcript_path(文件)数, 主/子分开数。
        session_rows = db.execute(
            "select s.transcript_path, s.message_count, s.active_duration_ms, s.last_timestamp,"
            " a.is_subagent, a.project_path from activity_sessions s"
            " join activity_sources a on a.path=s.transcript_path").fetchall()
        selected_sessions = []
        for row in session_rows:
            try:
                last_local = dt.datetime.strptime(str(row[3])[:19], '%Y-%m-%dT%H:%M:%S').replace(
                    tzinfo=dt.timezone.utc).astimezone().date().isoformat()
            except (TypeError, ValueError):
                continue
            if last_local >= local_d0:
                selected_sessions.append(row)
        ss = (len({r[0] for r in selected_sessions if not r[4]}),
              sum(int(r[1] or 0) for r in selected_sessions),
              max((int(r[2] or 0) for r in selected_sessions), default=0),
              max((r[3] for r in selected_sessions if r[3]), default=None),
              len({r[0] for r in selected_sessions if r[4]}),
              len({r[5] for r in selected_sessions if r[5]}))
        lepoch = None                             # 库里的时间戳是 UTC 字符串, 换成本地秒再交给 stamp()
        if ss[3]:
            try:
                lepoch = dt.datetime.strptime(str(ss[3])[:19], '%Y-%m-%dT%H:%M:%S').replace(
                    tzinfo=dt.timezone.utc).timestamp()
            except Exception:
                lepoch = None
        # 按天: 自己解析 transcript 拿**本地日**的四项 token, 成本用索引里该会话的合计
        # 按各本地日的 token 份额分摊(成本 transcript 里没有, 只能这么办; 分摊后按天求和
        # 仍等于该会话的索引成本, 不会凭空多也不会少)。
        by_day, per_sid, sids, ex = haha_days(pdir)
        scost = {}
        for pth, cs in db.execute(
                "select transcript_path, sum(cost_usd) from activity_daily_models group by 1"):
            scost[sid_of(pth)] = scost.get(sid_of(pth), 0.0) + float(cs or 0.0)
        for sid, share in per_sid.items():
            tot = sum(v['in'] + v['out'] + v['rd'] + v['cc'] for v in share.values())
            c_s = scost.get(sid, 0.0)
            for dte, v in share.items():
                if tot > 0:
                    v['cost'] = c_s * (v['in'] + v['out'] + v['rd'] + v['cc']) / tot
                by_day.get(dte, {}).update({'cost': by_day.get(dte, {}).get('cost', 0.0) + v['cost']})
        by_day = {k: v for k, v in by_day.items() if k >= local_d0}
        days = sorted(by_day)                       # 活跃/连续天数一律按本地日, 与曲线同一口径
        streak = 0
        for i in range(len(days) - 1, -1, -1):      # 从最后一个活跃日往回数连续段
            if days[i] != (dt.date.fromisoformat(days[-1]) - dt.timedelta(days=streak)).isoformat():
                break
            streak += 1
        # 模型请求数和 token 必须来自 transcript 的本地日明细。索引库的 date
        # 是 UTC 日，直接按 date 查询会把本地午夜前后的数据拆错。
        by_model = {}
        for dte, models in ex['mtoks'].items():
            if dte < local_d0:
                continue
            for mdl, vals in models.items():
                e = by_model.setdefault(mdl, [0, 0.0, 0])
                e[0] += sum(vals[:4])
        selected_total = sum(e[0] for e in by_model.values()) or 1
        selected_cost = sum(v['cost'] for v in by_day.values())
        for e in by_model.values():
            e[1] = selected_cost * e[0] / selected_total
        # 响应次数也按 transcript 的本地日筛，与 by_day 同一口径
        hourly = [0] * 24
        for dte, per in ex['mreqs'].items():
            if dte < local_d0:
                continue
            for mdl, k in per.items():
                e = by_model.setdefault(mdl, [0, 0.0, 0])
                e[2] += k
        for dte, hs in ex['hours'].items():
            if dte < local_d0:
                continue
            hourly = [a + b for a, b in zip(hourly, hs)]
        mcost = sum(v['cost'] for v in by_day.values())
        mtok = sum(v['in'] + v['out'] + v['rd'] + v['cc'] for v in by_day.values())
        mrd = sum(v['rd'] for v in by_day.values())
        mfin = sum(v['in'] + v['out'] + v['cc'] for v in by_day.values())
        mmsgs = sum(v['msgs'] for v in by_day.values())
        return {'tok': int(mtok), 'cost': float(mcost), 'rd': int(mrd), 'fin': int(mfin),
                'mcost': float(mcost), 'mtok': int(mtok), 'hourly': hourly,
                'htok': ex['htok'],
                'h1': int(ex['h1']),
                'msgs': int(mmsgs), 'calls': int(calls), 'days': len(days), 'streak': streak,
                'sess': int(ss[0] or 0), 'sub': int(ss[4] or 0), 'proj': int(ss[5] or 0),
                'act': ss[2] or 0, 'last': lepoch, 'by_day': by_day, 'by_model': by_model,
                'sids': sids}
    except Exception:
        return None
    finally:
        db.close()


def _parse_qoder(path):
    """单个 Qoder 会话 -> [(message id, 本地秒, credits)](文件内先按 id 收敛)。"""
    rows, seen = [], set()
    try:
        fh = open(path, encoding='utf-8', errors='replace')
    except OSError:
        return rows
    with fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            msg = j.get('message')
            u = msg.get('usage') if isinstance(msg, dict) else None
            if not isinstance(u, dict):
                continue
            mid = msg.get('id') or j.get('uuid') or ''
            if not mid or mid in seen:
                continue
            seen.add(mid)
            try:
                ep = int(dt.datetime.strptime((j.get('timestamp') or '')[:19],
                                              '%Y-%m-%dT%H:%M:%S').replace(
                    tzinfo=dt.timezone.utc).timestamp())
            except ValueError:
                continue
            rows.append((mid, ep, float(u.get('credits') or 0.0)))
    return rows


def qoder_days(start, qdir=None):
    """Qoder(本机 IDE 的 agent 会话, 不走 CC Switch 代理)按**本地日**汇总。

    只给得出「请求数 + credits」: 实测它 `message.usage` 里 input/output/cache_read/
    cache_creation 四个 token 字段**恒为 0**(全库 5235 条响应无一非零), 而
    `requestTokenAnchor` 只存两个 SHA-256 摘要、没有正文 —— 本机拿不到 token,
    所以这一路绝不往 token/成本里加任何一个数。
    按 mtime 先筛文件: 一条消息的时间戳不可能晚于它所在文件的修改时间, 所以
    mtime 早于范围起点的整份跳过(240 个文件里近 7 天只有 34 个)。
    跨文件全局去重同 haha_days(fork/续跑会把历史抄进新文件)。
    """
    days, sids, last = {}, set(), 0
    qdir = qdir or QDIR            # 默认参数在 def 时就绑死了, 这里改成调用时取(便于整体换目录)
    if not os.path.isdir(qdir):
        return days, sids, last
    seen = set()
    now = time.time()
    paths = []
    for dp, _, fs in os.walk(qdir):
        for fn in fs:
            if fn.endswith('.jsonl'):
                paths.append(os.path.join(dp, fn))
    for path in sorted(paths):
        try:
            st = os.stat(path)
        except OSError:
            continue
        if start and st.st_mtime < start - 3600:      # 整份都在范围之前
            continue
        key = (st.st_size, int(st.st_mtime))
        got = _QODER_FILES.get(path)
        if got and got[0] == key:
            rows = got[1]
        else:
            rows = _parse_qoder(path)
            _QODER_FILES[path] = (key, rows)
            if len(_QODER_FILES) > 400:               # 缓存只是加速器, 涨过头就整份重来
                _QODER_FILES.clear()
                _QODER_FILES[path] = (key, rows)
        sids.add(os.path.basename(path)[:-6])
        for mid, ep, cr in rows:
            if mid in seen:
                continue
            seen.add(mid)
            if ep > last:
                last = ep
            dte = dt.date.fromtimestamp(ep).isoformat()
            d = days.setdefault(dte, {'reqs': 0, 'credits': 0.0, 'h1': 0, 'hours': [0] * 24})
            d['reqs'] += 1
            d['credits'] += cr
            d['hours'][time.localtime(ep).tm_hour] += 1
            if ep >= now - 3600:
                d['h1'] += 1
    return days, sids, last


def fetch_qoder(start, qdir=None, key='qoder', name='Qoder'):
    """Qoder 这一路的汇总。读不到/没装就返回 None —— 少并一路, 不影响原有口径。

    同一个函数也服务 Qoder CN: 实测它的 message.usage 四个 token 字段同样恒为 0,
    只有 credits 是真值, 所以两个目录都只并「请求数 + credits」。"""
    try:
        days, sids, last = qoder_days(start, qdir)
    except Exception:
        return None
    d0 = time.strftime('%Y-%m-%d', time.localtime(start)) if start else '0000-01-01'
    days = {k: v for k, v in days.items() if k >= d0}
    if not days:
        return None
    hourly = [0] * 24
    for v in days.values():
        hourly = [a + b for a, b in zip(hourly, v['hours'])]
    ds = sorted(days)
    streak = 0
    for i in range(len(ds) - 1, -1, -1):
        if ds[i] != (dt.date.fromisoformat(ds[-1]) - dt.timedelta(days=streak)).isoformat():
            break
        streak += 1
    return {'key': key, 'name': name, 'reqs': sum(v['reqs'] for v in days.values()),
            'credits': sum(v['credits'] for v in days.values()),
            'days': len(ds), 'streak': streak, 'sessions': len(sids), 'last': last,
            'by_day': days, 'hourly': hourly, 'h1': sum(v['h1'] for v in days.values()),
            'sids': sids}


def _src(key, name, app, by_day, sids, hourly, h1, last, models, note):
    """统一形状: by_day 里每天固定有 reqs/credits/in/out/rd/cc 六项(没有的填 0)。"""
    ds = sorted(by_day)
    streak = 0
    for i in range(len(ds) - 1, -1, -1):
        if ds[i] != (dt.date.fromisoformat(ds[-1]) - dt.timedelta(days=streak)).isoformat():
            break
        streak += 1
    g = lambda k: sum(v[k] for v in by_day.values())
    return {'key': key, 'name': name, 'app': app, 'by_day': by_day, 'sids': sids,
            'hourly': hourly, 'h1': h1, 'last': last, 'models': models, 'note': note,
            'reqs': g('reqs'), 'credits': g('credits'), 'in': g('in'), 'out': g('out'),
            'rd': g('rd'), 'cc': g('cc'), 'days': len(ds), 'streak': streak,
            'sessions': len(sids)}


def _newday():
    return {'reqs': 0, 'credits': 0.0, 'in': 0, 'out': 0, 'rd': 0, 'cc': 0,
            'h1': 0, 'hours': [0] * 24}


def fetch_zcode(start):
    """ZCode(智谱 AI IDE)的 `~/.zcode/cli/db/db.sqlite::model_usage` —— 本机最规整的一路:
    963 行逐请求账, 含 input/output/reasoning/cache_read/cache_creation 与 model/session。
    口径: 实测 `raw_usage_json` 里 totalTokens = inputTokens + outputTokens, 而 cacheReadTokens
    是 input 的**子集**(364,052,424 in 里含 360,494,528 缓存读) -> 与 codex 回填同一套,
    新增输入要减缓存读, 否则四项相加会凭空多一倍。
    它不记钱: 成本一律 0, 面板上在状态行写明"无本机定价"。"""
    if not os.path.exists(ZCODE_DB):
        return None
    try:
        c = sqlite3.connect('file:' + ZCODE_DB.replace(os.sep, '/') + '?mode=ro', uri=True)
        c.execute('pragma busy_timeout=1200')
        rows = c.execute('select started_at, input_tokens, output_tokens, reasoning_tokens,'
                         ' cache_read_input_tokens, cache_creation_input_tokens, model_id,'
                         ' session_id from model_usage').fetchall()
        c.close()
    except Exception:
        return None
    d0 = time.strftime('%Y-%m-%d', time.localtime(start)) if start else '0000-01-01'
    by_day, sids, models = {}, set(), {}
    hourly = [0] * 24
    htok = new_hourly()
    h1 = last = 0
    now = time.time()
    for ms, i_t, o_t, r_t, rd, cw, mdl, sid in rows:
        ms = int(ms or 0)
        if ms > last:
            last = ms
        ep = ms / 1000.0
        dte = dt.date.fromtimestamp(ep).isoformat()
        if dte < d0:
            continue
        d = by_day.setdefault(dte, _newday())
        fi = max(0, int(i_t or 0) - int(rd or 0))          # input 含缓存读, 先减
        o = int(o_t or 0) + int(r_t or 0)                  # reasoning 也是生成的
        d['reqs'] += 1
        d['in'] += fi
        d['out'] += o
        d['rd'] += int(rd or 0)
        d['cc'] += int(cw or 0)
        hh = time.localtime(ep).tm_hour
        d['hours'][hh] += 1
        hourly[hh] += 1
        if ep >= now - 3600:
            d['h1'] += 1
            h1 += 1
        sids.add(str(sid))
        m = models.setdefault(str(mdl or '(未记录)'), [0, 0])
        m[0] += 1
        m[1] += fi + o + int(rd or 0) + int(cw or 0)
        add_hour(htok, hh, fi, o, int(rd or 0), int(cw or 0), 1)
    if not by_day:
        return None
    z = _src('zcode', 'ZCode', 'zcode', by_day, sids, hourly, h1, int(last / 1000),
             models, 'input 含缓存读(已减) · 本机不记钱')
    z['htok'] = htok
    return z


def fetch_herdsman(start):
    """Herdsman AI(本机牧羊人推理服务)的 `~/.herdsman/model_stats/events.jsonl`。
    实测 total_tokens = input_tokens + output_tokens(203,168 + 52,110 = 255,278),
    没有缓存分项 -> rd/cc 记 0, 不参与命中率分母。"""
    if not os.path.exists(HERD_LOG):
        return None
    by_day, sids, models = {}, set(), {}
    hourly = [0] * 24
    htok = new_hourly()
    h1 = last = 0
    now = time.time()
    try:
        fh = open(HERD_LOG, encoding='utf-8', errors='replace')
    except OSError:
        return None
    with fh:
        for line in fh:
            if 'token' not in line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if not isinstance(j.get('input_tokens'), (int, float)):
                continue
            ts = j.get('started_at') or j.get('recorded_at') or 0
            try:
                ep = float(ts)                      # 有的版本落 unix 秒
            except (TypeError, ValueError):
                try:                                # 实测更多见的是带时区的 ISO 串
                    ep = dt.datetime.fromisoformat(str(ts)).timestamp()
                except ValueError:
                    continue
            if not ep:
                continue
            if ep > last:
                last = ep
            dte = dt.date.fromtimestamp(ep).isoformat()
            if start and dte < time.strftime('%Y-%m-%d', time.localtime(start)):
                continue
            d = by_day.setdefault(dte, _newday())
            fi, o = int(j['input_tokens']), int(j.get('output_tokens') or 0)
            d['reqs'] += 1
            d['in'] += fi
            d['out'] += o
            hh = time.localtime(ep).tm_hour
            d['hours'][hh] += 1
            hourly[hh] += 1
            if ep >= now - 3600:
                d['h1'] += 1
                h1 += 1
            rid = str(j.get('request_id') or '')
            if rid:
                sids.add(rid)
            m = models.setdefault(str(j.get('model') or '(未记录)'), [0, 0])
            m[0] += 1
            m[1] += fi + o
            add_hour(htok, hh, fi, o, 0, 0, 1)
    if not by_day:
        return None
    z = _src('herdsman', '牧羊人', 'herdsman', by_day, sids, hourly, h1, int(last),
             models, '本地推理服务 · 无缓存分项 · 不记钱')
    z['htok'] = htok
    return z


def fetch_codex_gap(start, have_sids):
    """Codex CLI 里 **CC Switch 一行都没回填**的那些会话。
    实测 37 个 rollout 里 35 个能按会话 id 对上 CC Switch 的 codex_session 行(逐会话四项
    token 一致, 所以不重复), 剩下几个 CC 里零行 -> 只补这些, 有行的会话一律不碰:
    CC 的 request_id 尾号(261..273)不是 rollout 的行号(1286,1293...), 拿不到逐请求对应关系,
    所以"同一会话内部回填不全"的那部分**只报不并**, 宁少不双计。
    取每个文件最后一条 total_token_usage(累计值), 口径同 codex_session: input 含缓存读。"""
    by_day, sids, models = {}, set(), {}
    hourly = [0] * 24
    htok = new_hourly()
    h1 = last = 0
    now = time.time()
    d0 = time.strftime('%Y-%m-%d', time.localtime(start)) if start else '0000-01-01'
    for root in CODEX_DIRS:
        if not os.path.isdir(root):
            continue
        for dp, _, fs in os.walk(root):
            for fn in fs:
                if not fn.endswith('.jsonl'):
                    continue
                path = os.path.join(dp, fn)
                base = fn[:-6]
                parts = base.split('-')
                sid = '-'.join(parts[-5:]) if len(parts) >= 9 else base
                if sid in have_sids:
                    continue
                tot = None
                with open(path, encoding='utf-8', errors='replace') as fh:
                    for line in fh:
                        if 'total_token_usage' not in line:
                            continue
                        try:
                            j = json.loads(line)
                        except ValueError:
                            continue
                        stack = [j]
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
                        try:
                            ts = dt.datetime.strptime((j.get('timestamp') or '')[:19],
                                                      '%Y-%m-%dT%H:%M:%S').replace(
                                tzinfo=dt.timezone.utc).timestamp()
                            if ts > last:
                                last = ts
                        except ValueError:
                            pass
                if not tot:
                    continue
                fi = max(0, int(tot.get('input_tokens') or 0)
                         - int(tot.get('cached_input_tokens') or 0))
                o = int(tot.get('output_tokens') or 0)
                rd = int(tot.get('cached_input_tokens') or 0)
                cw = int(tot.get('cache_write_input_tokens') or 0)
                ep = last or now
                dte = dt.date.fromtimestamp(ep).isoformat()
                if dte < d0:
                    continue
                d = by_day.setdefault(dte, _newday())
                d['reqs'] += 1                     # 一个未回填的会话算一条汇总
                hh = time.localtime(ep).tm_hour    # 小时格也要加, 否则 Σ小时 != 总请求
                d['hours'][hh] += 1
                hourly[hh] += 1
                add_hour(htok, hh, fi, o, rd, cw, 1)   # 只有会话级时间戳, 小时归属是近似的
                d['in'] += fi
                d['out'] += o
                d['rd'] += rd
                d['cc'] += cw
                sids.add(sid)
                m = models.setdefault('(codex 未回填)', [0, 0])
                m[0] += 1
                m[1] += fi + o + rd + cw
    if not by_day:
        return None
    z = _src('codexgap', 'Codex未回填', 'codex', by_day, sids, hourly, h1, int(last),
             models, 'CC Switch 零行的会话才补 · 同会话内部回填不全的部分只报不并')
    z['htok'] = htok
    return z


def merge_qoder(d, qb):
    """把 Qoder 的量并进**它给得出的那些维度**: 总请求数 / 按天请求 / 24小时 / 今日·昨日·近1小时
    / 应用表, 外加一个新的 credits 维度。token、成本、命中率一个都不碰(它本机没有)。

    双计保险: 它的会话 id 一旦出现在 CC Switch 任何一行里, 说明那批流量已经被代理记过,
    整路拒绝并入(与 cc-haha 的 claude_sids 保险同一套)。"""
    d['qoder'] = qb
    if not qb or not qb.get('by_day'):
        return d
    clash = set(qb['sids']) & set(d.get('all_sids') or ())
    if clash:
        d['qoder'] = dict(qb, clash=len(clash), by_day={}, reqs=0, credits=0.0,
                          hourly=[0] * 24, h1=0)
        return d
    bd = qb['by_day']
    n = sum(v['reqs'] for v in bd.values())
    cr = sum(v['credits'] for v in bd.values())
    d['reqs'] += n
    d['credits'] = d.get('credits', 0.0) + cr
    d['hourly'] = [a + b for a, b in zip(d['hourly'], qb['hourly'])]
    for v in bd.values():                                     # Qoder 系 token 恒 0, 只记请求数
        for hh, k in enumerate(v.get('hours') or []):
            add_hour(d['htok'], hh, 0, 0, 0, 0, k)
    d['h1'] = (d['h1'][0] + qb['h1'], d['h1'][1])
    today = time.strftime('%Y-%m-%d')
    yday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    d['today'] = (d['today'][0] + bd.get(today, {}).get('reqs', 0), d['today'][1])
    d['yday'] = (d['yday'][0] + bd.get(yday, {}).get('reqs', 0), d['yday'][1])
    pos = {r[0]: i for i, r in enumerate(d['daily'])}
    for dte in sorted(bd):
        v = bd[dte]
        if dte in pos:
            i = pos[dte]
            o = d['daily'][i]
            d['daily'][i] = o[:3] + (o[3] + v['reqs'],) + o[4:]
        else:
            d['daily'].append((dte, 0.0, 0, v['reqs'], 0.0, 0, 0, 0, 0))
    d['daily'].sort()
    d['adays'] = max(int(d.get('adays') or 0), len(d['daily']))
    old = [a for a in d['apps'] if a[0] == 'qoder']
    if old:
        i = d['apps'].index(old[0])
        a0 = d['apps'][i]
        d['apps'][i] = (a0[0], a0[1] + n, a0[2], a0[3], a0[4])
    else:
        d['apps'].append(('qoder', n, 0.0, 0, 0.0))
    d['apps'].sort(key=lambda r: -r[2])
    if qb.get('last') and (not d['last'] or qb['last'] > d['last']):
        d['last'] = qb['last']
    return d


def merge_haha(d, hb):
    """把 cc-haha 索引的量并进总量: 成本 / 四项 token / 命中率 / 请求数 / 小时分布 /
    今日·昨日·近1小时 / 模型表 / 应用表 / 按天曲线 —— 只要面板上出现"总量"这一维, 两路都得并齐,
    并一半就会出现「总请求 272 而应用行相加 34」这种各说各话(verify S 段按范围逐项断言)。

    **前提是两个源的会话 id 不相交** —— 现在成立(CC Switch 4 个老会话 / cc-haha 7 个新会话,
    交集 0), verify R 段专门断言这件事; 哪天重叠了 R 段会先红, 而不是让总量静默翻倍。
    只有**状态码和延迟** cc-haha 侧拿不到: 实测它的 transcript 每行只有
    timestamp/model/usage/stop_reason 这些键, 1352 行响应里没有任何 HTTP 状态或耗时字段。
    那两格仍是 CC Switch 口径, 状态行与横幅说明里都写明了。
    """
    d['haha'] = hb                      # 横幅卡要拿这一路的明细画图, 合并成不成都得留着
    if not hb or not hb.get('by_day'):
        return d
    # 双计保险: 两源一旦有同一个会话 id, 说明它们在看同一批 transcript —— 宁可不并, 也别
    # 把同一笔钱算两遍(死库/备份被 touch 一下 mtime 就会走到这里)。
    clash = set(hb.get('sids') or ()) & set(d.get('claude_sids') or ())
    if clash:
        d['haha'] = dict(hb, clash=len(clash), by_day={}, mcost=0.0, mtok=0,
                         hourly=[0] * 24, h1=0)
        return d
    bd = hb['by_day']
    v_in = sum(v['in'] for v in bd.values())
    v_out = sum(v['out'] for v in bd.values())
    v_rd = sum(v['rd'] for v in bd.values())
    v_cc = sum(v['cc'] for v in bd.values())
    v_cost = sum(v['cost'] for v in bd.values())
    v_tk = v_in + v_out + v_rd + v_cc
    v_msgs = sum(v['msgs'] for v in bd.values())       # 一次响应=一次请求, 与 count(*) 同单位
    d['cost'] += v_cost
    d['reqs'] += v_msgs
    d['fresh_in'] += v_in
    d['out'] += v_out
    d['creat'] += v_cc
    d['read'] += v_rd
    d['real'] += v_tk
    dn = d['read'] + d['fresh_in'] + d['creat']
    d['hit'] = (d['read'] / dn * 100) if dn else 0.0

    pr = d.get('cprice') or [0, 0, 0, 0]
    raw = [v_in * pr[0], v_out * pr[1], v_rd * pr[2], v_cc * pr[3]]
    tot = sum(raw)
    if tot > 0:
        raw = [x * v_cost / tot for x in raw]
    else:                                   # 没有 claude 行可推单价时, 按 token 份额摊
        sh = [v_in, v_out, v_rd, v_cc]
        t2 = sum(sh) or 1.0
        raw = [v_cost * x / t2 for x in sh]
    for k, val in zip(('cin', 'cout', 'crd', 'cwr'), raw):
        d[k] += val

    dp = d.setdefault('day_parts', {})
    pos = {r[0]: i for i, r in enumerate(d['daily'])}
    for dte in sorted(bd):
        v = bd[dte]
        rd, fi, cc = dp.get(dte, (0, 0, 0))
        rd += v['rd']
        fi += v['in']
        cc += v['cc']
        dp[dte] = (rd, fi, cc)
        dn2 = rd + fi + cc
        hit = (rd / dn2 * 100) if dn2 else 0.0
        if dte in pos:
            i = pos[dte]
            o = d['daily'][i]
            d['daily'][i] = (o[0], o[1] + v['cost'],
                             (o[5] + v['in']) + (o[6] + v['out']) + rd + cc, o[3] + v['msgs'],
                             hit, o[5] + v['in'], o[6] + v['out'], o[7] + v['cc'], rd)
        else:
            # 第 4 位是请求数: haha 那边按"唯一 message id 数"计, 一条响应=一次请求,
            # 与 CC Switch 的 count(*) 同单位(索引里的 message_count 是消息数, 不能拿来当请求数)
            d['daily'].append((dte, v['cost'], v['in'] + v['out'] + v['rd'] + v['cc'],
                               v['msgs'], hit, v['in'], v['out'], v['cc'], v['rd']))
    d['daily'].sort()
    d['adays'] = max(int(d.get('adays') or 0), len(d['daily']))

    # 判重要用**全量模型名**, 不能用被 limit 4 截断的展示表: 否则一个"CC Switch 里有但没进
    # 前四"的模型会被当成新模型, nmodel 虚报、模型表里出现两条同名行。
    names = d.setdefault('model_names', set())
    for mdl, (tk, cs, rq) in hb['by_model'].items():
        fresh = mdl not in names
        names.add(mdl)
        old = [m for m in d['models'] if m[0] == mdl]
        if old:
            i = d['models'].index(old[0])
            m = d['models'][i]
            d['models'][i] = (m[0], m[1] + rq, m[2] + cs, m[3] + tk)
        else:
            d['models'].append((mdl, rq, cs, tk))
    d['models'].sort(key=lambda r: -r[2])
    d['models'] = d['models'][:4]
    d['nmodel'] = len(names)

    ap = d.setdefault('app_parts', {})
    rd, fi, cc = ap.get('claude', (0, 0, 0))
    rd, fi, cc = rd + v_rd, fi + v_in, cc + v_cc
    ap['claude'] = (rd, fi, cc)
    dn3 = rd + fi + cc
    old = [a for a in d['apps'] if a[0] == 'claude']
    if old:
        i = d['apps'].index(old[0])
        a0 = d['apps'][i]
        d['apps'][i] = (a0[0], a0[1] + v_msgs, a0[2] + v_cost, a0[3] + v_tk,
                        (rd / dn3 * 100) if dn3 else 0.0)
    else:
        d['apps'].append(('claude', v_msgs, v_cost, v_tk, (rd / dn3 * 100) if dn3 else 0.0))
    d['apps'].sort(key=lambda r: -r[2])

    d['hourly'] = [a + b for a, b in zip(d['hourly'], hb.get('hourly') or [0] * 24)]
    spread_cost(hb.get('htok') or new_hourly(), v_cost)       # 索引级成本按小时 token 份额摊
    merge_hour(d['htok'], hb.get('htok'))
    d['h1'] = (d['h1'][0] + int(hb.get('h1') or 0), d['h1'][1])
    today = time.strftime('%Y-%m-%d')
    yday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    d['today'] = (d['today'][0] + bd.get(today, {}).get('msgs', 0),
                  d['today'][1] + bd.get(today, {}).get('cost', 0.0))
    d['yday'] = (d['yday'][0] + bd.get(yday, {}).get('msgs', 0),
                 d['yday'][1] + bd.get(yday, {}).get('cost', 0.0))
    if hb.get('last') and (not d['last'] or hb['last'] > d['last']):
        d['last'] = hb['last']
    return d


def _clamp_xy(x, y, w, h):
    """把浮层左上角收进工作区, 右下角留 4px 余量。"""
    wl, wt, wr, wb = _work_area(point=(x, y))
    return max(wl, min(x, wr - w - 4)), max(wt, min(y, wb - h - 4))


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
                 ('check', '跟随 CC Switch 显示', self.follow, self.set_follow),
                 ('info', ('CC Switch 运行中 · PID %d' % pid) if pid
                  else 'CC Switch 未运行 · 自动刷新已停(手动刷新仍会读库)')]
        spec += [('cmd', '立即隐藏  (圆点/托盘可再叫出)', self.hide_now)
                 if (self.follow and self._shown) else ('info', '立即隐藏  (已经是隐藏态)')]
        spec += [('sub', '定时操作', self.power_spec), ('sep',),
                 ('cmd', '复制对账数据 (JSON → 剪贴板)', self.copy_json),
                 ('cmd', '导出对账数据 (JSON → 文件)', self.export), ('sep',),
                 ('cmd', '退出  (托盘图标一并消失)', self.quit)]
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
                    self._set_visible(up)
                    if self.tray:
                        self.tray.set(self._shown, self._tip())
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
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ccswitch-对账数据.json')
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
                  lambda: fetch_codex_gap(start, d.get('codex_sids') or set())):
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

    def _rr(self, key, x, y, w, h, r, fill, outline=''):
        img = self._sprite(w, h, r, fill, outline)
        i = self.cv.create_image(int(round(x + w / 2.0)), int(round(y + h / 2.0)),
                                 image=img, tags='fg')
        if key:
            self.ids[key] = i
            self.imgs[key] = img                    # 断引用 Tk 会回收图片, 必须自己持有
        return i

    def _rr2(self, key, x, y, w, h, r, off, on, mat=CARD, hard=False):
        """两态圆角壳(选中/未选中): 两张图预先烘好, 刷新只换图不新建图元。"""
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
        """圆角进度条 = 中间矩形 + 两端圆头。oval 自带抗锯齿, 所以条也是圆的且不露齿。"""
        it = self.ids.get(key)
        if it is None:
            r = h / 2.0
            it = (self.cv.create_rectangle(0, 0, 0, 0, fill=fill, outline='', tags='fg'),
                  self.cv.create_oval(0, 0, 0, 0, fill=fill, outline='', tags='fg'),
                  self.cv.create_oval(0, 0, 0, 0, fill=fill, outline='', tags='fg'))
            self.ids[key] = it
            self.barh[key] = h
        rect, ol, orr = it
        h = self.barh[key]
        r = min(h / 2.0, max(0.0, w) / 2.0)
        x, y = int(round(x)), int(round(y))
        self.cv.coords(rect, x + r, y, x + w - r, y + h)
        self.cv.coords(ol, x, y, x + 2 * r, y + h)
        self.cv.coords(orr, x + w - 2 * r, y, x + w, y + h)
        if fill is not None:
            for i in it:
                if self.cv.itemcget(i, 'fill') != fill:
                    self.cv.itemconfig(i, fill=fill)

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
              'haha': self._haha, 'qoder': self._qoder}
        self._gap = 0                             # 纵向推进由本函数负责, 卡片不再各自加间隙
        y = fn['c6'](y, x0, pw) + Gt              # 趋势图: 全宽一整行
        n = len(self.ROWS[0])
        colw = (pw - (n - 1) * G) // n
        for row in self.ROWS:
            minh = max(int(round(self._hgt(k) * s)) for k in row)
            for i, k in enumerate(row):
                fn[k](y, x0 + i * (colw + G), colw, minh)
            y += minh + G
        y = fn['haha'](y, x0, pw) + G             # 倒数第二行: 全宽横幅(cc-haha 直连会话)
        y = fn['qoder'](y, x0, pw) + G            # 最后一行: 全宽横幅(Qoder, 不走代理)
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
            self._t('c2.%sl' % k, xx, y + int(round(47 * s)), lab, FAINT, self.f_micro)
            self._t('c2.%s' % k, xx, y + int(round(63 * s)), '', c, self.f_num)
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
        self.zones.clear()
        px, pw = int(round(PAD * s)), W - 2 * int(round(PAD * s))
        y = int(round(12 * s))
        # 标题卡片: 标题行 + 范围胶囊行包进实心卡(镂空时不会被一起透掉)。展开态就这两行的头;
        # 收起态整张面板只有这一张卡, 所以它要按 _head_h 长到能装下正文。
        self._head_h = 62 if self.expanded else 224
        self._panel('head.bg', px, y, pw, int(round(self._head_h * s)),
                    int(round(11 * s)), accent=CY)
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
                  BG if self.expanded else CARD, self.expanded)
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
            self._t(k + '.l', xx, y + int(round(46 * s)), lab, FAINT, self.f_micro)
            self._t(k + '.v', xx, y + int(round(61 * s)), '', c, self.f_num)
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
            self._t(k + '.l', xx, y + int(round(45 * s)), lab, FAINT, self.f_micro)
            self._t(k + '.v', xx, y + int(round(61 * s)), '—', c, self.f_num)
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
                    y + int(round(47 * s)), head, FAINT, self.f_tiny, 'w' if ax == 0 else 'e')
            for i in range(nrow):
                self._t('%s.%s%d' % (key, letter, i), self.cx + int(self.cw * ax),
                        y + int(round(62 * s)) + int(round(12 * s)) * i, '', col,
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
            self._t('c8.l%d' % i, self.cx, y + int(round(46 * s)) + int(round(12 * s)) * i, '',
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
            self._t('haha.%sl' % k, xx, y + int(round(47 * s)), lab, FAINT, self.f_micro)
            self._t('haha.%s' % k, xx, y + int(round(63 * s)), '', c, self.f_num)
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
            self._t('qoder.%sl' % k, xx, y + int(round(47 * s)), lab, FAINT, self.f_micro)
            self._t('qoder.%s' % k, xx, y + int(round(63 * s)), '', c, self.f_num)
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

    def run(self):
        self._tick()                                 # 刷新与跟随判定共用这一条 after 链
        self.root.mainloop()


if __name__ == '__main__':
    _dpi_aware()
    if already_running():
        os._exit(0)                              # 开机自启已有一份在跑, 不再叠第二张卡片
    HUD().run()
