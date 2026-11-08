"""第 5 路：ZCode（智谱 AI IDE）。input 含缓存读；out 含 reasoning；无本机定价。"""
from __future__ import annotations

from ..model import SourceSnapshot, add_session, add_usage
from ..paths import Paths
from ..ranges import start_epoch
from ..sqlite_ro import SourceReadError, SourceUnavailable, connect_ro, table_exists
from .base import local_date, local_hour


def load(paths: Paths, rng: str, now: float | None = None, exclude_sids=None) -> SourceSnapshot:
    snap = SourceSnapshot(key="zcode", name="ZCode", kind="session",
                          note="input 含缓存读(已减) · 本机不记钱")
    p = paths.zcode_db
    if not p.exists():
        return snap.mark_unsupported("未安装 ZCode")
    start = start_epoch(rng, now)
    try:
        with connect_ro(p) as con:  # finally close 由上下文管理器保证（旧实现的缺陷已修）
            if not table_exists(con, "model_usage"):
                return snap.mark_unsupported("库中没有 model_usage")
            rows = con.execute(
                "select started_at, input_tokens, output_tokens, reasoning_tokens,"
                " cache_read_input_tokens, cache_creation_input_tokens, model_id, session_id"
                " from model_usage"
            ).fetchall()
    except SourceUnavailable as exc:
        return snap.mark_unsupported(str(exc))
    except SourceReadError as exc:
        return snap.mark_error(str(exc))

    start_day = local_date(start) if start else None
    per_sid: dict[str, dict] = {}
    for ms, i_t, o_t, r_t, rd, cw, mdl, sid in rows:
        try:
            ep = int(ms or 0) / 1000.0
        except (TypeError, ValueError):
            continue
        if ep <= 0:
            continue
        dte = local_date(ep)
        if start_day and dte < start_day:
            continue
        fresh = max(0, int(i_t or 0) - int(rd or 0))
        out = int(o_t or 0) + int(r_t or 0)
        add_usage(snap.day(dte), reqs=1, fresh_in=fresh, out=out,
                  cache_read=int(rd or 0), cache_write=int(cw or 0),
                  model=str(mdl or "(未记录)"), hour=local_hour(ep))
        if sid:
            snap.sids.add(str(sid))
            e = per_sid.setdefault(str(sid), {"reqs": 0, "tokens": 0, "last": 0.0, "model": None})
            e["reqs"] += 1
            e["tokens"] += fresh + out + int(rd or 0) + int(cw or 0)
            e["last"] = max(e["last"], ep)
            e["model"] = str(mdl or "(未记录)")
        if ep > (snap.last_seen or 0):
            snap.last_seen = ep
    for sid, e in per_sid.items():
        add_session(snap, sid, reqs=e["reqs"], tokens=e["tokens"],
                    model=e["model"], last_seen=e["last"] or None)
    return snap.finish()
