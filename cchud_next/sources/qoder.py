"""第 3/4 路：Qoder 国际版 / 国内版。只出请求数与 credits。"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from ..model import SourceSnapshot, add_session, add_usage
from ..paths import Paths
from ..ranges import start_epoch
from .base import local_date, local_hour

_CACHE: dict[str, tuple] = {}
_CACHE_MAX = 400


def _parse(path: Path) -> list[tuple[str, float, float]]:
    rows: list[tuple[str, float, float]] = []
    seen: set[str] = set()
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
            if not mid or mid in seen:
                continue
            seen.add(mid)
            try:
                ep = dt.datetime.strptime((j.get("timestamp") or "")[:19],
                                          "%Y-%m-%dT%H:%M:%S").replace(
                    tzinfo=dt.timezone.utc).timestamp()
            except ValueError:
                continue
            rows.append((mid, ep, float(u.get("credits") or 0.0)))
    return rows


def _one(paths: Paths, root: Path, key: str, name: str, rng: str,
         now: float | None) -> SourceSnapshot:
    snap = SourceSnapshot(key=key, name=name, kind="session", supports_tokens=False,
                          supports_credits=True,
                          note="本机没有 token/成本，只并请求数与 credits")
    if not root.is_dir():
        return snap.mark_unsupported(f"未安装 {name}")
    start = start_epoch(rng, now)
    start_day = local_date(start) if start else None
    files = []
    for dirpath, _dirs, names in os.walk(root):
        for fn in names:
            if fn.endswith(".jsonl"):
                files.append(Path(dirpath) / fn)
    seen: set[str] = set()
    for path in sorted(files):
        try:
            st = path.stat()
        except OSError:
            continue
        if start and st.st_mtime < start - 3600:
            continue
        cache_key = (st.st_size, int(st.st_mtime))
        got = _CACHE.get(str(path))
        if got and got[0] == cache_key:
            rows = got[1]
        else:
            rows = _parse(path)
            if len(_CACHE) > _CACHE_MAX:
                _CACHE.clear()
            _CACHE[str(path)] = (cache_key, rows)
        snap.sids.add(path.stem)
        s_reqs, s_credits, s_last = 0, 0.0, 0.0
        for mid, ep, credits in rows:
            if mid in seen:
                continue
            seen.add(mid)
            dte = local_date(ep)
            if start_day and dte < start_day:
                continue
            add_usage(snap.day(dte), reqs=1, credits=credits, hour=local_hour(ep))
            s_reqs += 1
            s_credits += credits
            s_last = max(s_last, ep)
            if ep > (snap.last_seen or 0):
                snap.last_seen = ep
        add_session(snap, path.stem, reqs=s_reqs, credits=s_credits,
                    last_seen=s_last or None)
    return snap.finish()


def load(paths: Paths, rng: str, now: float | None = None, exclude_sids=None) -> SourceSnapshot:
    """两本账各自独立；这里返回合并视图供 accounting 统一做双计检查。"""
    a = _one(paths, paths.qoder_dir, "qoder", "Qoder", rng, now)
    b = _one(paths, paths.qoder_cn_dir, "qoder_cn", "Qoder CN", rng, now)
    return [a.finish(), b.finish()]
