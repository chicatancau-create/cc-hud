# -*- coding: utf-8 -*-
"""cc-hud 基础工具: 数值/时间/文本/DPI/工作区/路径发现。"""
import ctypes
import datetime as dt
import os
import re
from ctypes import wintypes as wt
from urllib.parse import urlsplit, urlunsplit

from .const import *

__all__ = [
    '_fixed_drives', 'haha_cfg', 'sid_of', 'money', 'big', 'secs', 'stamp', 'host', 'redact_url',
    '_SECRET_TEXT', '_redact_export', '_scale', '_dpi_aware', '_MONITORINFO', '_work_area', '_pct',
    '_clamp_xy',
]


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


def _pct(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, int(len(v) * q))]


def _clamp_xy(x, y, w, h):
    """把浮层左上角收进工作区, 右下角留 4px 余量。"""
    wl, wt, wr, wb = _work_area(point=(x, y))
    return max(wl, min(x, wr - w - 4)), max(wt, min(y, wb - h - 4))
