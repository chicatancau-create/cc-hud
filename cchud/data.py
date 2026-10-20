# -*- coding: utf-8 -*-
"""cc-hud 数据层: 八路数据源的取数与合并。"""
import datetime as dt
import json
import os
import re
import sqlite3
import time

from .const import *
from .util import *

__all__ = [
    '_parse_transcript', 'haha_days', 'merge_extra', 'new_hourly', 'add_hour', 'merge_hour',
    'hourly_rows', 'spread_cost', 'fetch', 'dur', '_fold_hours', 'fetch_haha', '_parse_qoder',
    'qoder_days', 'fetch_qoder', '_src', '_newday', 'fetch_zcode', 'fetch_herdsman',
    'fetch_codex_gap', '_wb_ts', '_wb_rows', 'fetch_workbuddy', 'merge_qoder', 'merge_haha',
]


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
          'htok': {}}     # htok 按本地日分桶, 由 fetch_haha 再按范围筛(区间级会多算别的日子)
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
            hb = ex['htok'].setdefault(dte, new_hourly())[time.localtime(ep).tm_hour]
            # 逐小时四项(今日档条形要用)
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


def _fold_hours(per_day, d0):
    """把按本地日分的 24 小时桶折成一个区间级 24 桶 —— 只折范围内的日子。
    不筛就会把别的日子灌进今日档的柱子(实测 Σ小时 比总请求多出 607 次)。"""
    out = new_hourly()
    for dte, buckets in (per_day or {}).items():
        if dte < d0:
            continue
        for hh, b in enumerate(buckets):
            add_hour(out, hh, b['in'], b['out'], b['rd'], b['cc'], b['reqs'], b['cost'])
    return out


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
                'htok': _fold_hours(ex['htok'], local_d0),
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


def _wb_ts(v):
    """WorkBuddy 的 timestamp 实测是**毫秒字符串**("1789270258822"), 兼容数值型与秒。"""
    try:
        t = float(v)
    except (TypeError, ValueError):
        return None
    return t / 1000.0 if t > 1e12 else t


def _wb_rows(fp, psid):
    """单个 WorkBuddy 会话文件 -> [(本地秒, 会话 id, 模型, 净输入, 输出, 缓存读, 缓存写, 积分)]。
    按 (size, mtime_ns) 缓存: 国内版最大那个文件 7.3MB、两版合计 28MB, 这些 transcript 写完就不再
    改, 不能每轮 CC_TICKS 重解析一遍。读到一半报错(OSError)时**不写缓存**, 下一轮还会重读。"""
    try:
        st = os.stat(fp)
        sig = (st.st_size, st.st_mtime_ns)
    except OSError:
        return []
    got = _WB_FILES.get(fp)
    if got and got[0] == sig:
        return got[1]
    rows = []
    ok = True
    try:
        with open(fp, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if '"rawUsage"' not in line:          # 绝大多数行是工具调用/快照, 先廉价跳过
                    continue
                line = line.strip()
                if not line.startswith('{'):
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict):
                    continue
                pd = o.get('providerData')
                ru = pd.get('rawUsage') if isinstance(pd, dict) else None
                if not isinstance(ru, dict):
                    continue
                pr = int(ru.get('prompt_tokens') or 0)
                ot = int(ru.get('completion_tokens') or 0)
                if not (pr or ot):
                    continue
                ep = _wb_ts(o.get('timestamp'))
                if ep is None:
                    continue
                ptd = ru.get('prompt_tokens_details')
                ptd = ptd if isinstance(ptd, dict) else {}
                rd = ru.get('prompt_cache_hit_tokens')
                if rd is None:                        # 两条命名都见过: OpenAI 风格顶层 -> 嵌套兜底
                    rd = ptd.get('cached_tokens') or 0
                rd = int(rd or 0)
                # 缓存写: 实测国内版走 cache_creation_input_tokens、国外版走 prompt_cache_write_tokens,
                # 且两者同时出现时相等 -> 任一非零即为该行的写缓存量。
                cw = int(ru.get('prompt_cache_write_tokens')
                         or ru.get('cache_creation_input_tokens')
                         or ptd.get('cached_creation_tokens') or 0)
                cr = ru.get('credit')
                rows.append((ep, str(o.get('sessionId') or psid),
                             str(pd.get('model') or pd.get('requestModelId') or '(未记录)'),
                             max(0, pr - rd - cw), ot, rd, cw,
                             float(cr) if isinstance(cr, (int, float)) and cr > 0 else 0.0))
    except OSError:
        ok = False
    if ok:
        _WB_FILES[fp] = (sig, rows)
    return rows


def fetch_workbuddy(start, projects, key, with_credit):
    """WorkBuddy 桌面版(国内/国外各一路)的逐请求真账:
    `<数据目录>/projects/**/*.jsonl` 里每条带 `providerData.rawUsage` 的记录 = 一次模型调用。
    实测 2026-10-18: 国内 1432 条 / 国外 1182 条, 每条记录 id 唯一 -> 本路内部不重复。
    国外版有 3 个 `subagents/agent-*.jsonl`, 路径上归父会话, 但里面记的是子 agent 自己的
    sessionId(实测与父会话不同), 所以两种 id 都进 sids —— 只会让双计保险更严, 不会漏。

    口径: **`prompt_tokens` 同时含缓存读与缓存写** —— 实测 1432/1432 行满足
    `prompt = prompt_cache_hit + prompt_cache_miss + 写缓存`, 所以净输入要把两项都拆出去
    (只减命中会把写缓存重复算一次: 国内 290,867 / 国外 337,552)。拆完四桶相加恰好等于
    应用自己记的 `total_tokens`(国内 179,934,868 / 国外 151,440,924) —— 这是 Y 段的对账不变式。
    命中率 = 命中/prompt, 实测国内 98.46% / 国外 97.31%; 不拆的话并入量会从 855 万虚报成 3.31 亿。
    与 ZCode/codex 回填同一类坑, 但这一路的写缓存字段名两版还不一样(见 _wb_rows)。

    成本: 这一路拿不到美元成本(它只记官方积分), 与 ZCode 一样成本记 0。
    credits: 只有国内版逐调用记得全(实测覆盖 96.2%, Σ678.64)。国外版 1182 条里只有 20 条带值
    (Σ647.55, 均值 32.4/次), 而且与它自己的 `workbuddy.db::session_usage.credit_json`(Σ103.68)
    差 5 倍 —— 两本账对不上就是没有基线, 所以 with_credit=False 时一个积分都不并。
    """
    if not os.path.isdir(projects):
        return None
    d0 = time.strftime('%Y-%m-%d', time.localtime(start)) if start else '0000-01-01'
    by_day, sids, models = {}, set(), {}
    hourly = [0] * 24
    htok = new_hourly()
    h1 = 0
    last = 0.0
    now = time.time()
    for dp, _, fs in os.walk(projects):
        for fn in fs:
            if not fn.endswith('.jsonl'):
                continue
            fp = os.path.join(dp, fn)
            rel = os.path.relpath(fp, projects).split(os.sep)
            if len(rel) < 2:
                continue
            psid = rel[1][:-6] if rel[1].endswith('.jsonl') else rel[1]
            sids.add(psid)
            for ep, sid, mdl, fi, ot, rd, cw, cr in _wb_rows(fp, psid):
                sids.add(sid)
                if ep > last:
                    last = ep
                dte = dt.date.fromtimestamp(ep).isoformat()
                if dte < d0:
                    continue
                d = by_day.setdefault(dte, _newday())
                d['reqs'] += 1
                d['in'] += fi
                d['out'] += ot
                d['rd'] += rd
                d['cc'] += cw
                if with_credit:
                    d['credits'] += cr
                hh = time.localtime(ep).tm_hour
                d['hours'][hh] += 1
                hourly[hh] += 1
                if ep >= now - 3600:
                    d['h1'] += 1
                    h1 += 1
                m = models.setdefault(mdl, [0, 0])
                m[0] += 1
                m[1] += fi + ot + rd + cw
                add_hour(htok, hh, fi, ot, rd, cw, 1)
    if not by_day:
        return None
    z = _src(key, APP_ALIAS.get(key, key), key, by_day, sids, hourly, h1, int(last),
             models, 'prompt 含缓存读与写(两项均已拆出) · 本机不记钱'
             + ('' if with_credit else ' · 国外版积分两本账互相矛盾, credits 不并'))
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
