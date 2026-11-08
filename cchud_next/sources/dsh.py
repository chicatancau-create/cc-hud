"""第 9 路：DSH。

- projcache：`record.rows.tokenUsage.val.totals` 会话累计值，按 `identity.createdAt` 归日；
- V4：`sessions/**/session.v4.jsonl.zstd`，Python 3.14 `compression.zstd` 解码；
  只有存在结构化 usage 时才计 token，否则 `unsupported`（不伪造）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..model import SourceSnapshot, add_session, add_usage
from ..paths import Paths
from ..ranges import start_epoch
from .base import local_date, local_hour

try:  # Python 3.14+
    from compression import zstd as _zstd
except ImportError:  # pragma: no cover - 非 3.14 环境
    _zstd = None


def _projcache(paths: Paths, rng: str, now: float | None,
               exclude_sids: set[str]) -> SourceSnapshot:
    snap = SourceSnapshot(key="dsh", name="DSH", kind="session",
                          note="会话累计 · 只补 CC Switch 零行的会话 · 小时归属是近似的 · 不记钱")
    root = paths.dsh_projcache
    if not root.is_dir():
        return snap.mark_unsupported("未安装 DSH")
    start = start_epoch(rng, now)
    start_day = local_date(start) if start else None
    for path in sorted(root.glob("*.json")):
        sid = path.stem
        if sid in exclude_sids:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                j = json.load(fh)
            rec = j.get("record") or {}
            rows = rec.get("rows") or {}
            ident = rec.get("identity") or {}
            tot = ((rows.get("tokenUsage") or {}).get("val") or {}).get("totals") or {}
            stt = ((rows.get("sessionStats") or {}).get("val")) or {}
            msel = ((rows.get("modelSelection") or {}).get("val")) or {}
            ca = ident.get("createdAt")
            if not isinstance(ca, (int, float)):
                continue
            fi = int(tot.get("uncachedInputTokens") or 0)
            out = int(tot.get("outputTokens") or 0)
            rd = int(tot.get("cacheReadTokens") or 0)
            cw = int(tot.get("cacheWriteTokens") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if fi + out + rd + cw == 0:
            continue  # 空会话不计请求数
        ep = ca / 1000.0
        dte = local_date(ep)
        if start_day and dte < start_day:
            continue
        turns = int(stt.get("turns") or 0) or 1
        model = str(((msel.get("lastUsed") or {}).get("model")) or "(未记录)")
        add_usage(snap.day(dte), reqs=turns, fresh_in=fi, out=out, cache_read=rd,
                  cache_write=cw, model=model, hour=local_hour(ep))
        snap.sids.add(sid)
        add_session(snap, sid, reqs=turns, tokens=fi + out + rd + cw, model=model, last_seen=ep)
        if ep > (snap.last_seen or 0):
            snap.last_seen = ep
    return snap.finish()


def _usage_of(event: dict) -> dict | None:
    """V4 事件里找结构化 usage；找不到返回 None（不拿字符串里的数字充数）。"""
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    cands = [data.get("usage"), (data.get("message") or {}).get("usage")
             if isinstance(data.get("message"), dict) else None,
             data.get("tokenUsage"), data.get("response", {}).get("usage")
             if isinstance(data.get("response"), dict) else None]
    for u in cands:
        if isinstance(u, dict) and any(
                k in u for k in ("inputTokens", "outputTokens", "input_tokens", "output_tokens")):
            return u
    return None


def _v4(paths: Paths, rng: str, now: float | None,
        exclude_sids: set[str]) -> SourceSnapshot:
    snap = SourceSnapshot(key="dsh_v4", name="DSH V4", kind="session",
                          note="zstd JSONL 会话 · 仅结构化 usage 入账")
    root = paths.dsh_sessions
    if not root.is_dir():
        return snap.mark_unsupported("未找到 DSH V4 会话目录")
    if _zstd is None:
        return snap.mark_unsupported("当前 Python 无 compression.zstd")
    start = start_epoch(rng, now)
    start_day = local_date(start) if start else None
    files = []
    for dirpath, _dirs, names in os.walk(root):
        for fn in names:
            if fn.endswith(".zstd"):
                files.append(Path(dirpath) / fn)
    if not files:
        return snap.mark_unsupported("DSH V4 会话目录为空")
    seen_usage = False
    v4_reqs: dict[str, int] = {}
    v4_tokens: dict[str, int] = {}
    v4_last: dict[str, float] = {}
    v4_model: dict[str, str] = {}
    for path in sorted(files):
        sid = path.parent.name
        if sid in exclude_sids:
            continue
        try:
            raw = _zstd.decompress(path.read_bytes())
        except Exception:
            snap.warnings.append(f"{path.name}: 解压失败")
            continue
        for line in raw.decode("utf-8", "replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            u = _usage_of(ev)
            if not u:
                continue
            seen_usage = True
            ts = ev.get("time")
            if not isinstance(ts, (int, float)):
                continue
            ep = ts / 1000.0
            dte = local_date(ep)
            if start_day and dte < start_day:
                continue
            fi = int(u.get("inputTokens") or u.get("input_tokens") or 0)
            rd = int(u.get("cacheReadTokens") or u.get("cache_read_tokens") or 0)
            out = int(u.get("outputTokens") or u.get("output_tokens") or 0)
            cw = int(u.get("cacheWriteTokens") or u.get("cache_write_tokens") or 0)
            src = ev.get("data", {}).get("source") if isinstance(ev.get("data"), dict) else {}
            model = str((src or {}).get("model") or "(未记录)") if isinstance(src, dict) else "(未记录)"
            add_usage(snap.day(dte), reqs=1, fresh_in=fi, out=out, cache_read=rd,
                      cache_write=cw, model=model, hour=local_hour(ep))
            snap.sids.add(sid)
            v4_reqs[sid] = v4_reqs.get(sid, 0) + 1
            v4_tokens[sid] = v4_tokens.get(sid, 0) + fi + out + rd + cw
            v4_last[sid] = max(v4_last.get(sid, 0.0), ep)
            v4_model[sid] = model
            if ep > (snap.last_seen or 0):
                snap.last_seen = ep
    for sid in v4_reqs:
        add_session(snap, sid, reqs=v4_reqs[sid], tokens=v4_tokens[sid],
                    model=v4_model.get(sid), last_seen=v4_last.get(sid) or None)
    if not seen_usage:
        snap.days.clear()
        snap.sids.clear()
        return snap.mark_unsupported("V4 会话无结构化 usage 字段，不伪造 token")
    return snap.finish()


def load(paths: Paths, rng: str, now: float | None = None, exclude_sids=None):
    have = set(exclude_sids or ())
    pc = _projcache(paths, rng, now, have)
    v4 = _v4(paths, rng, now, have | set(pc.sids))
    return [pc, v4]
