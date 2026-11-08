"""第 2 路：cc-haha（Claude Code 桌面壳）—— 索引库给成本，transcript 给本地日四项。"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path

from ..model import SourceSnapshot, add_session, add_usage
from ..paths import Paths, cchaha_index_and_projects
from ..ranges import start_epoch
from ..sqlite_ro import SourceReadError, SourceUnavailable, connect_ro, table_exists
from .base import local_date, local_hour, sid_from_transcript

_CACHE: dict[str, tuple] = {}
_CACHE_MAX = 400


def _parse_transcript(path: Path) -> dict[str, tuple]:
    """message id -> (本地日, 秒, in, out, read, write, model)；保留最后一条 usage。"""
    rows: dict[str, tuple] = {}
    try:
        fh = open(path, encoding="utf-8", errors="replace")
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
            msg = j.get("message")
            u = msg.get("usage") if isinstance(msg, dict) else None
            if not isinstance(u, dict):
                continue
            mid = msg.get("id") or j.get("uuid") or ""
            if not mid:
                continue
            try:
                ep = dt.datetime.strptime((j.get("timestamp") or "")[:19],
                                          "%Y-%m-%dT%H:%M:%S").replace(
                    tzinfo=dt.timezone.utc).timestamp()
            except ValueError:
                continue
            tools = [b.get("name") for b in (msg.get("content") or [])
                     if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name")]
            rows[mid] = (
                local_date(ep), ep,
                int(u.get("input_tokens") or 0),
                int(u.get("output_tokens") or 0),
                int(u.get("cache_read_input_tokens") or 0),
                int(u.get("cache_creation_input_tokens") or 0),
                str(msg.get("model") or "(未记录)"),
                tools,
            )
    return rows


def load(paths: Paths, rng: str, now: float | None = None, exclude_sids=None) -> SourceSnapshot:
    snap = SourceSnapshot(key="cchaha", name="cc-haha", kind="session",
                          note="索引成本按本地日 token 份额分摊 · 跨文件按 message id 去重")
    idx, projects = cchaha_index_and_projects(paths)
    if not idx or not projects or not Path(idx).exists():
        return snap.mark_unsupported("未找到 cc-haha 索引库")
    start = start_epoch(rng, now)
    started = start is not None
    start_day = local_date(start) if started else None
    try:
        with connect_ro(idx) as con:
            if not table_exists(con, "activity_daily_models"):
                return snap.mark_unsupported("索引库缺少 activity_daily_models")
            cols = {r[1] for r in con.execute("pragma table_info(activity_daily_models)")}
            s_day_cost: dict[tuple[str, str], float] = {}
            if "date" in cols:
                for tpath, dte, cost in con.execute(
                        "select transcript_path, date, sum(cost_usd) "
                        "from activity_daily_models group by 1,2"):
                    sid = sid_from_transcript(Path(tpath))
                    k = (sid, str(dte))
                    s_day_cost[k] = s_day_cost.get(k, 0.0) + float(cost or 0.0)
            else:
                for tpath, cost in con.execute(
                        "select transcript_path, sum(cost_usd) "
                        "from activity_daily_models group by 1"):
                    sid = sid_from_transcript(Path(tpath))
                    k = (sid, "*")
                    s_day_cost[k] = s_day_cost.get(k, 0.0) + float(cost or 0.0)
    except SourceUnavailable as exc:
        return snap.mark_unsupported(str(exc))
    except SourceReadError as exc:
        return snap.mark_error(str(exc))

    paths_list = []
    for dirpath, _dirs, files in os.walk(projects):
        for fn in files:
            if fn.endswith(".jsonl"):
                paths_list.append(Path(dirpath) / fn)
    seen: set[str] = set()
    per_sid_day: dict[str, dict[str, int]] = {}
    per_sid_meta: dict[str, dict] = {}
    for path in sorted(paths_list):
        try:
            st = path.stat()
        except OSError:
            continue
        key = (st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        got = _CACHE.get(str(path))
        if got and got[0] == key:
            rows = got[1]
        else:
            rows = _parse_transcript(path)
            if len(_CACHE) > _CACHE_MAX:
                _CACHE.clear()
            _CACHE[str(path)] = (key, rows)
        sid = sid_from_transcript(path)
        for mid, (dte, ep, fi, o, rd, cw, mdl, tools) in rows.items():
            if mid in seen:
                if start_day is None or dte >= start_day:
                    snap.sids.add(sid)   # fork 复制的同一会话，仍算已见过的 sid
                continue
            seen.add(mid)
            if start_day is not None and dte < start_day:
                continue
            snap.sids.add(sid)
            add_usage(snap.day(dte), reqs=1, fresh_in=fi, out=o, cache_read=rd,
                      cache_write=cw, model=mdl, hour=local_hour(ep))
            if ep > (snap.last_seen or 0):
                snap.last_seen = ep
            for tname in tools:
                e = snap.tool_counts.setdefault(str(tname), {"n": 0, "sessions": set(), "last": 0.0})
                e["n"] += 1
                e["sessions"].add(sid)
                e["last"] = max(e["last"], ep)
            b = per_sid_day.setdefault(sid, {})
            b[dte] = b.get(dte, 0) + fi + o + rd + cw
            meta = per_sid_meta.setdefault(sid, {"last": 0.0, "models": {}, "reqs": 0})
            meta["reqs"] += 1
            meta["models"][mdl] = meta["models"].get(mdl, 0) + 1
            if ep > meta["last"]:
                meta["last"] = ep

    for sid, meta in per_sid_meta.items():
        top_model = max(meta["models"], key=meta["models"].get) if meta["models"] else None
        add_session(snap, sid, reqs=meta["reqs"],
                    tokens=sum(per_sid_day.get(sid, {}).values()),
                    model=top_model, last_seen=meta["last"] or None)
    for (sid, dte), cost in s_day_cost.items():
        if cost <= 0:
            continue
        if dte == "*":                      # 旧库无 date 列：按期内 token 份额分摊
            days = per_sid_day.get(sid, {})
            total = sum(days.values())
            if total <= 0:
                continue
            for day, toks in days.items():
                if day in snap.days:
                    snap.days[day]["cost"] += cost * toks / total
        elif dte in snap.days:              # 有日期就只记到该日，不跨期摊
            snap.days[dte]["cost"] += cost
    if snap.days:
        snap.note = "索引成本按本地日 token 份额分摊 · 跨文件按 message id 去重"
    return snap.finish()
