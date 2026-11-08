"""第 8 路：WorkBuddy 国内 / 国外。prompt 含缓存读写，净输入两项都要拆。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..model import SourceSnapshot, add_session, add_usage
from ..paths import Paths
from ..ranges import start_epoch
from .base import local_date, local_hour

_CACHE: dict[str, tuple] = {}
_CACHE_MAX = 600


def _ts(value) -> float | None:
    try:
        t = float(value)
    except (TypeError, ValueError):
        return None
    return t / 1000.0 if t > 1e12 else t


def _rows(path: Path, parent_sid: str) -> list[tuple]:
    try:
        st = path.stat()
        sig = (st.st_size, st.st_mtime_ns)
    except OSError:
        return []
    got = _CACHE.get(str(path))
    if got and got[0] == sig:
        return got[1]
    rows: list[tuple] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"rawUsage"' not in line:
                    continue
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict):
                    continue
                pd = o.get("providerData")
                ru = pd.get("rawUsage") if isinstance(pd, dict) else None
                if not isinstance(ru, dict):
                    continue
                pr = int(ru.get("prompt_tokens") or 0)
                ot = int(ru.get("completion_tokens") or 0)
                if not (pr or ot):
                    continue
                ep = _ts(o.get("timestamp"))
                if ep is None:
                    continue
                ptd = ru.get("prompt_tokens_details")
                ptd = ptd if isinstance(ptd, dict) else {}
                rd = ru.get("prompt_cache_hit_tokens")
                if rd is None:
                    rd = ptd.get("cached_tokens") or 0
                rd = int(rd or 0)
                cw = int(ru.get("prompt_cache_write_tokens")
                         or ru.get("cache_creation_input_tokens")
                         or ptd.get("cached_creation_tokens") or 0)
                cr = ru.get("credit")
                rows.append((ep, str(o.get("sessionId") or parent_sid),
                             str(pd.get("model") or pd.get("requestModelId") or "(未记录)"),
                             max(0, pr - rd - cw), ot, rd, cw,
                             float(cr) if isinstance(cr, (int, float)) and cr > 0 else 0.0))
    except OSError:
        return []
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.clear()
    _CACHE[str(path)] = (sig, rows)
    return rows


def _one(projects: Path, key: str, name: str, with_credit: bool, rng: str,
         now: float | None) -> SourceSnapshot:
    snap = SourceSnapshot(key=key, name=name, kind="session", supports_credits=with_credit,
                          note="prompt 含缓存读与写（两项均已拆出） · 本机不记钱"
                               + ("" if with_credit else " · 国外版积分两本账矛盾，不并"))
    if not projects.is_dir():
        return snap.mark_unsupported(f"未安装 {name}")
    start = start_epoch(rng, now)
    start_day = local_date(start) if start else None
    found = False
    seen: set[tuple] = set()     # fork/复制的会话文件会把同一行抄两份
    for dirpath, _dirs, files in os.walk(projects):
        for fn in sorted(files):
            if not fn.endswith(".jsonl"):
                continue
            found = True
            fp = Path(dirpath) / fn
            rel = os.path.relpath(fp, projects).split(os.sep)
            parent = rel[1][:-6] if len(rel) >= 2 and rel[1].endswith(".jsonl") else fp.stem
            p_reqs, p_tokens, p_credits, p_last, p_model = 0, 0, 0.0, 0.0, None
            for ep, sid, mdl, fi, ot, rd, cw, cr in _rows(fp, parent):
                key = (sid, ep, mdl, fi, ot, rd, cw)
                dte = local_date(ep)
                in_range = not start_day or dte >= start_day
                if key in seen:
                    if in_range:      # 复制文件里的同一行，会话仍算本路见过
                        snap.sids.add(sid)
                        snap.sids.add(parent)
                    continue
                seen.add(key)
                if not in_range:
                    continue
                snap.sids.add(sid)
                snap.sids.add(parent)
                add_usage(snap.day(dte), reqs=1, fresh_in=fi, out=ot, cache_read=rd,
                          cache_write=cw, credits=(cr if with_credit else 0.0),
                          model=mdl, hour=local_hour(ep))
                p_reqs += 1
                p_tokens += fi + ot + rd + cw
                p_credits += cr if with_credit else 0.0
                p_last = max(p_last, ep)
                p_model = mdl
                if ep > (snap.last_seen or 0):
                    snap.last_seen = ep
            add_session(snap, parent, reqs=p_reqs, tokens=p_tokens, credits=p_credits,
                        model=p_model, last_seen=p_last or None)
    if not found:
        return snap.finish()  # 有目录无会话 → empty
    return snap.finish()


def load(paths: Paths, rng: str, now: float | None = None, exclude_sids=None):
    out = []
    for projects, key, with_credit in paths.workbuddy_sources:
        name = "WorkBuddy 国内" if key == "workbuddy" else "WorkBuddy 国外"
        out.append(_one(projects, key, name, with_credit, rng, now))
    return out
