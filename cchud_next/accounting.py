"""合并九路：整路拒绝（会话 id 交集）、只补缺口、守恒校验、模型/应用聚合。"""
from __future__ import annotations

import time
from typing import Any

from .model import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    SourceSnapshot,
    new_day,
    token_total,
)
from .paths import Paths
from .ranges import RANGES, start_date
from .sources import cchaha, ccswitch, codex, dsh, herdsman, qoder, workbuddy, zcode

GAP_SOURCES = {"codex", "dsh", "dsh_v4"}


def _as_list(value) -> list[SourceSnapshot]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def collect(paths: Paths, rng: str, now: float | None = None) -> list[SourceSnapshot]:
    if rng not in RANGES:
        raise ValueError(f"unknown range: {rng}")
    now = time.time() if now is None else now
    base = ccswitch.load(paths, rng, now)
    counted: set[str] = set(base.sids)
    # sid -> 先把它计入合计的那一路；被抑制时 by 要指向真正的冲突来源（不能写死 ccswitch）
    owner: dict[str, str] = {sid: base.key for sid in base.sids}
    out: list[SourceSnapshot] = [base]

    def credit(snap: SourceSnapshot) -> None:
        for sid in snap.sids:
            counted.add(sid)
            owner.setdefault(sid, snap.key)

    for mod in (cchaha, qoder, zcode, herdsman, codex, workbuddy, dsh):
        for snap in _as_list(mod.load(paths, rng, now, exclude_sids=counted)):
            snap.finish()
            if snap.status in (STATUS_UNSUPPORTED, STATUS_ERROR):
                out.append(snap)
                continue
            if snap.key in GAP_SOURCES:
                credit(snap)
                out.append(snap)
                continue
            clash = snap.sids & counted
            if clash:
                by = sorted({owner.get(sid, "unknown") for sid in clash})
                snap.suppressed = {"by": by[0], "clash": len(clash), "by_all": by}
                snap.days.clear()
                out.append(snap)
                continue
            credit(snap)
            out.append(snap)
    return out


def merge(sources: list[SourceSnapshot], rng: str, now: float | None = None) -> dict[str, Any]:
    """把未 suppressed 的来源按天合并；所有合计都可回溯到来源。"""
    now = time.time() if now is None else now
    included = [s for s in sources if not s.suppressed and s.status == STATUS_OK]
    days: dict[str, dict] = {}
    total_cost_supported = any(s.supports_cost for s in included)
    total_credits_supported = any(s.supports_credits for s in included)

    for s in included:
        for date, d in s.days.items():
            tgt = days.setdefault(date, new_day())
            tgt["reqs"] += int(d["reqs"])
            tgt["credits"] += float(d["credits"])
            tgt["fresh_in"] += int(d["fresh_in"])
            tgt["out"] += int(d["out"])
            tgt["cache_read"] += int(d["cache_read"])
            tgt["cache_write"] += int(d["cache_write"])
            tgt["cost"] += float(d["cost"])
            tgt["hours"] = [a + int(b) for a, b in zip(tgt["hours"], d["hours"])]
            for name, m in d["models"].items():
                mm = tgt["models"].setdefault(
                    name, {"reqs": 0, "fresh_in": 0, "out": 0, "cache_read": 0,
                           "cache_write": 0, "cost": 0.0})
                for k in ("reqs", "fresh_in", "out", "cache_read", "cache_write"):
                    mm[k] += int(m.get(k) or 0)
                mm["cost"] += float(m.get("cost") or 0.0)

    totals = {
        "reqs": 0, "credits": 0.0, "fresh_in": 0, "out": 0,
        "cache_read": 0, "cache_write": 0, "cost": 0.0, "tokens": 0,
    }
    for d in days.values():
        totals["reqs"] += int(d["reqs"])
        totals["credits"] += float(d["credits"])
        for k in ("fresh_in", "out", "cache_read", "cache_write"):
            totals[k] += int(d[k])
        totals["cost"] += float(d["cost"])
    totals["tokens"] = sum(totals[k] for k in ("fresh_in", "out", "cache_read", "cache_write"))

    daily = []
    for date in sorted(days):
        d = days[date]
        daily.append({
            "date": date,
            "reqs": int(d["reqs"]),
            "tokens": token_total(d),
            "cost": float(d["cost"]),
            "fresh_in": int(d["fresh_in"]),
            "out": int(d["out"]),
            "cache_read": int(d["cache_read"]),
            "cache_write": int(d["cache_write"]),
            "credits": float(d["credits"]),
        })

    hourly = []
    for hh in range(24):
        reqs = sum(int(d["hours"][hh]) for d in days.values())
        # 小时级 token/成本未按来源拆分；保持 0，不伪造分布
        hourly.append({"hour": hh, "reqs": reqs, "tokens": 0, "cost": 0.0})

    models: dict[str, dict] = {}
    for s in included:
        for d in s.days.values():
            for name, m in d["models"].items():
                e = models.setdefault(name, {"name": name, "reqs": 0, "tokens": 0,
                                             "cost": 0.0, "sources": []})
                e["reqs"] += int(m.get("reqs") or 0)
                e["tokens"] += token_total(m)
                e["cost"] += float(m.get("cost") or 0.0)
                if s.key not in e["sources"]:
                    e["sources"].append(s.key)
    model_rows = sorted(models.values(), key=lambda x: (-x["tokens"], -x["reqs"], x["name"]))[:12]

    apps = []
    for s in included:
        t = s.totals()
        apps.append({"key": s.key, "name": s.name, "reqs": t["reqs"],
                     "tokens": t["tokens"], "cost": t["cost"]})
    apps.sort(key=lambda x: (-x["tokens"], x["name"]))

    timing = next((s.timing for s in included if s.timing), None)
    tools: dict[str, dict] = {}
    for src in included:
        for k, v in src.tool_counts.items():
            e = tools.setdefault(k, {"name": k, "n": 0, "sessions": 0})
            e["n"] += v["n"]
            e["sessions"] += len(v["sessions"])
    session_rows: list[dict] = []
    for src in included:
        session_rows.extend(src.session_rows)
    session_rows.sort(key=lambda r: (-int(r.get("tokens") or 0), str(r.get("id") or "")))

    denom = totals["cache_read"] + totals["fresh_in"] + totals["cache_write"]
    kpis = {
        "sessions": sum(int(s.sessions or 0) for s in included),
        "active_days": len(days),
        "cost": totals["cost"] if total_cost_supported else None,
        "tokens": totals["tokens"],
        "cache_hit": (totals["cache_read"] / denom * 100.0) if denom else None,
        "credits": totals["credits"] if total_credits_supported else None,
    }

    return {
        "totals": totals,
        "kpis": kpis,
        "daily": daily,
        "hourly": hourly,
        "models": model_rows,
        "apps": apps,
        "timing": timing,
        "tools": sorted(tools.values(), key=lambda x: -x["n"])[:12],
        "session_rows": session_rows[:200],
        "session_total": len(session_rows),
        "conservation": conservation(sources, totals, days),
        "range": rng,
        "start_date": start_date(rng, now),
    }


def conservation(sources: list[SourceSnapshot], totals: dict,
                 days: dict | None = None) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    if days is not None:
        s = {k: 0 for k in ("reqs", "fresh_in", "out", "cache_read", "cache_write")}
        for d in days.values():
            for k in s:
                s[k] += int(d[k])
        add("totals_eq_days", all(totals[k] == s[k] for k in s),
            "合计 == Σ按天：" + ", ".join(f"{k}={totals[k]}" for k in s))
        tokens_ok = totals["tokens"] == sum(s[k] for k in ("fresh_in", "out", "cache_read", "cache_write"))
        add("tokens_eq_parts", tokens_ok, f"tokens={totals['tokens']}")

    for src in sources:
        if src.suppressed or src.status != STATUS_OK:
            continue
        t = src.totals()
        sd = {k: 0 for k in ("reqs", "fresh_in", "out", "cache_read", "cache_write")}
        hours = 0
        for d in src.days.values():
            for k in sd:
                sd[k] += int(d[k])
            hours += sum(int(x) for x in d["hours"])
        add(f"{src.key}.totals_eq_days", all(t[k] == sd[k] for k in sd), src.key)
        add(f"{src.key}.hours_eq_reqs", hours == t["reqs"],
            f"{src.key}: Σhours={hours} reqs={t['reqs']}")
        models_tok = sum(token_total(m) for d in src.days.values() for m in d["models"].values())
        add(f"{src.key}.models_le_total", models_tok <= t["tokens"],
            f"{src.key}: models={models_tok} <= total={t['tokens']}")
    return checks


def overall_status(sources: list[SourceSnapshot]) -> str:
    st = {s.status for s in sources}
    if STATUS_ERROR in st:
        return STATUS_ERROR
    if STATUS_OK in st:
        return STATUS_OK
    if STATUS_EMPTY in st:
        return STATUS_EMPTY
    return STATUS_UNSUPPORTED
