"""第 1 路：CC Switch 代理日志（基准路）。只 SELECT。"""
from __future__ import annotations

from ..model import SourceSnapshot, add_session, add_usage
from ..paths import Paths
from ..ranges import start_epoch
from ..sqlite_ro import SourceReadError, SourceUnavailable, connect_ro, table_exists
from .base import local_date


def load(paths: Paths, rng: str, now: float | None = None, exclude_sids=None) -> SourceSnapshot:
    snap = SourceSnapshot(
        key="ccswitch",
        name="CC Switch",
        kind="proxy",
        note="代理日志 · 基准路",
        supports_cost=True,
    )
    p = paths.ccswitch_db
    if not p.exists():
        return snap.mark_unsupported("未安装 CC Switch（缺少 cc-switch.db）")
    start = start_epoch(rng, now)
    where = "created_at >= ?" if start else "1"
    params: tuple = (start,) if start else ()
    try:
        with connect_ro(p) as con:
            if not table_exists(con, "proxy_request_logs"):
                return snap.mark_unsupported("库中没有 proxy_request_logs")
            con.execute("BEGIN")     # 六条 SELECT 共享同一读快照，避免守恒被并发写撕裂
            rows = con.execute(
                f"""select date(created_at,'unixepoch','localtime') d,
                    count(*), coalesce(sum(total_cost_usd),0),
                    coalesce(sum(input_tokens),0), coalesce(sum(output_tokens),0),
                    coalesce(sum(cache_read_tokens),0), coalesce(sum(cache_creation_tokens),0),
                    coalesce(sum(case when data_source='codex_session'
                                      then cache_read_tokens else 0 end),0)
                from proxy_request_logs where {where} group by 1""",
                params,
            ).fetchall()
            day_models = con.execute(
                f"""select date(created_at,'unixepoch','localtime') d,
                    coalesce(nullif(model,''),'(未记录)') m, count(*),
                    coalesce(sum(input_tokens+output_tokens+cache_read_tokens
                                 +cache_creation_tokens),0),
                    coalesce(sum(case when data_source='codex_session'
                                      then cache_read_tokens else 0 end),0),
                    coalesce(sum(total_cost_usd),0)
                from proxy_request_logs where {where} group by 1,2""",
                params,
            ).fetchall()
            hour_rows = con.execute(
                f"""select date(created_at,'unixepoch','localtime') d,
                    cast(strftime('%H', created_at,'unixepoch','localtime') as int) h,
                    count(*) from proxy_request_logs where {where} group by 1,2""",
                params,
            ).fetchall()
            sids = {r[0] for r in con.execute(
                f"select distinct session_id from proxy_request_logs where {where}", params
            ) if r[0]}
            cols = {r[1] for r in con.execute("pragma table_info(proxy_request_logs)")}
            lat_rows = []
            if {"latency_ms", "first_token_ms"} <= cols:
                lat_rows = con.execute(
                    f"""select latency_ms, first_token_ms from proxy_request_logs
                        where {where} and latency_ms > 0""", params).fetchall()
            sess_rows = con.execute(
                f"""select session_id, count(*), coalesce(sum(total_cost_usd),0),
                    coalesce(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0),
                    coalesce(sum(case when data_source='codex_session'
                                      then cache_read_tokens else 0 end),0),
                    max(created_at)
                from proxy_request_logs where {where} and session_id is not null
                group by session_id""",
                params,
            ).fetchall()
            meta = con.execute(
                "select max(created_at), count(distinct session_id) from proxy_request_logs"
                + (" where created_at >= ?" if start else ""),
                params,
            ).fetchone()
            if meta and meta[0]:
                snap.last_seen = float(meta[0])
            snap.sessions = int(meta[1] or 0) if meta else 0
    except SourceUnavailable as exc:
        return snap.mark_unsupported(str(exc))
    except SourceReadError as exc:
        return snap.mark_error(str(exc))

    for d, reqs, cost, tin, tout, rd, cw, cxs in rows:
        if not d:
            continue
        fresh = max(0, int(tin) - int(cxs))
        add_usage(snap.day(str(d)), reqs=int(reqs), fresh_in=fresh, out=int(tout),
                  cache_read=int(rd), cache_write=int(cw), cost=float(cost))
    for d, model, reqs, tok, cxs, cost in day_models:
        if not d:
            continue
        net = max(0, int(tok) - int(cxs))
        m = snap.day(str(d))["models"].setdefault(
            str(model), {"reqs": 0, "fresh_in": 0, "out": 0, "cache_read": 0,
                         "cache_write": 0, "cost": 0.0})
        m["reqs"] += int(reqs)
        m["fresh_in"] += net  # 模型级只保证总量；四桶细项由 daily 统一
        m["cost"] += float(cost)
    for d, hh, n in hour_rows:
        if d is None or hh is None:
            continue
        day = snap.day(str(d))
        if 0 <= int(hh) <= 23:
            day["hours"][int(hh)] += int(n)
    def pct(vals, q):
        if not vals:
            return None
        v = sorted(vals)
        return float(v[min(len(v) - 1, int(len(v) * q))])

    lat = [float(r[0]) for r in lat_rows if r[0]]
    ftt = [float(r[1]) for r in lat_rows if r[1]]
    snap.timing = {
        "n": len(lat), "p50": pct(lat, 0.5), "p95": pct(lat, 0.95),
        "ftt_n": len(ftt), "ftt_p50": pct(ftt, 0.5), "ftt_p95": pct(ftt, 0.95),
    }
    for sid, n, cs, tok, cxs, last in sess_rows:
        add_session(snap, str(sid), reqs=int(n), tokens=max(0, int(tok) - int(cxs)),
                    cost=float(cs), last_seen=float(last) if last else None)
    snap.sids = sids
    return snap.finish()
