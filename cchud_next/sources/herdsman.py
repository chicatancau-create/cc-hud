"""第 6 路：牧羊人（本地推理服务）。total = input + output，无缓存分项。"""
from __future__ import annotations

import datetime as dt
import json

from ..model import SourceSnapshot, add_usage
from ..paths import Paths
from ..ranges import start_epoch
from .base import local_date, local_hour


def _epoch(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if value > 1e12 else float(value)
    try:
        return dt.datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def load(paths: Paths, rng: str, now: float | None = None, exclude_sids=None) -> SourceSnapshot:
    snap = SourceSnapshot(key="herdsman", name="牧羊人", kind="local",
                          note="本地推理服务 · 无缓存分项 · 不记钱")
    p = paths.herdsman_log
    if not p.exists():
        return snap.mark_unsupported("未安装牧羊人")
    start = start_epoch(rng, now)
    start_day = local_date(start) if start else None
    try:
        fh = open(p, encoding="utf-8", errors="replace")
    except OSError as exc:
        return snap.mark_error(str(exc))
    with fh:
        for line in fh:
            if "token" not in line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if not isinstance(j.get("input_tokens"), (int, float)):
                continue
            ep = _epoch(j.get("started_at") or j.get("recorded_at") or 0)
            if not ep:
                continue
            dte = local_date(ep)
            if start_day and dte < start_day:
                continue
            fi = int(j["input_tokens"])
            out = int(j.get("output_tokens") or 0)
            add_usage(snap.day(dte), reqs=1, fresh_in=fi, out=out,
                      model=str(j.get("model") or "(未记录)"), hour=local_hour(ep))
            if ep > (snap.last_seen or 0):
                snap.last_seen = ep
    snap.sessions = 0        # 事件级数据，没有会话 id；不把 request_id 当会话
    return snap.finish()
