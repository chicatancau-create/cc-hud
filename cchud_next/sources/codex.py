"""第 7 路：Codex CLI rollout。只补 CC Switch 零行的会话（have_sids）。"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from ..model import SourceSnapshot, add_session, add_usage
from ..paths import Paths
from ..ranges import start_epoch
from .base import local_date, local_hour


def _session_id(path: Path) -> str:
    base = path.name[:-6]
    parts = base.split("-")
    return "-".join(parts[-5:]) if len(parts) >= 9 else base


def _last_usage(path: Path) -> tuple[dict | None, float | None]:
    tot = None
    last = None
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    with fh:
        for line in fh:
            if "total_token_usage" not in line:
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
                        if k == "total_token_usage" and isinstance(v, dict):
                            tot = v
                        elif isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(cur, list):
                    stack.extend(cur)
            try:
                ts = dt.datetime.strptime((j.get("timestamp") or "")[:19],
                                          "%Y-%m-%dT%H:%M:%S").replace(
                    tzinfo=dt.timezone.utc).timestamp()
                if last is None or ts > last:
                    last = ts
            except ValueError:
                pass
    return tot, last


def load(paths: Paths, rng: str, now: float | None = None, exclude_sids=None) -> SourceSnapshot:
    snap = SourceSnapshot(key="codex", name="Codex 未回填", kind="session",
                          note="只补 CC Switch 零行的会话 · input 含缓存读(已减)")
    if not any(p.is_dir() for p in paths.codex_dirs):
        return snap.mark_unsupported("未安装 Codex CLI")
    start = start_epoch(rng, now)
    start_day = local_date(start) if start else None
    have = set(exclude_sids or ())
    found_any_session = False
    for root in paths.codex_dirs:
        if not root.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fn in sorted(files):
                if not fn.endswith(".jsonl"):
                    continue
                found_any_session = True
                path = Path(dirpath) / fn
                sid = _session_id(path)
                if sid in have:
                    continue
                tot, last = _last_usage(path)
                if not tot:
                    continue
                try:
                    ep = last if last is not None else path.stat().st_mtime
                except OSError:
                    continue
                dte = local_date(ep)
                if start_day and dte < start_day:
                    continue
                fi = max(0, int(tot.get("input_tokens") or 0)
                         - int(tot.get("cached_input_tokens") or 0))
                out = int(tot.get("output_tokens") or 0)
                rd = int(tot.get("cached_input_tokens") or 0)
                cw = int(tot.get("cache_write_input_tokens") or 0)
                add_usage(snap.day(dte), reqs=1, fresh_in=fi, out=out, cache_read=rd,
                          cache_write=cw, model="(codex 未回填)", hour=local_hour(ep))
                snap.sids.add(sid)
                add_session(snap, sid, reqs=1, tokens=fi + out + rd + cw,
                            model="(codex 未回填)", last_seen=ep)
                if ep > (snap.last_seen or 0):
                    snap.last_seen = ep
    if not found_any_session:
        return snap.mark_unsupported("Codex 会话目录为空")
    return snap.finish()
