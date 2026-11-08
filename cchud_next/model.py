"""数据结构：按天账、来源快照、序列化。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ERROR = "error"
STATUSES = (STATUS_OK, STATUS_EMPTY, STATUS_UNSUPPORTED, STATUS_ERROR)

TOKEN_KEYS = ("fresh_in", "out", "cache_read", "cache_write")


def new_model() -> dict[str, Any]:
    return {"reqs": 0, "fresh_in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0}


def new_day() -> dict[str, Any]:
    d = {
        "reqs": 0,
        "credits": 0.0,
        "fresh_in": 0,
        "out": 0,
        "cache_read": 0,
        "cache_write": 0,
        "cost": 0.0,
        "hours": [0] * 24,
        "models": {},
    }
    return d


def add_hour(day: dict[str, Any], hour: int, reqs: int, tokens: int = 0, cost: float = 0.0) -> None:
    if 0 <= hour <= 23:
        day["hours"][hour] += int(reqs)


def add_usage(
    day: dict[str, Any],
    *,
    reqs: int = 0,
    fresh_in: int = 0,
    out: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
    cost: float = 0.0,
    credits: float = 0.0,
    model: str | None = None,
    hour: int | None = None,
) -> None:
    day["reqs"] += int(reqs)
    day["fresh_in"] += int(fresh_in)
    day["out"] += int(out)
    day["cache_read"] += int(cache_read)
    day["cache_write"] += int(cache_write)
    day["cost"] += float(cost)
    day["credits"] += float(credits)
    if hour is not None and 0 <= hour <= 23:
        day["hours"][hour] += int(reqs)
    if model:
        m = day["models"].setdefault(model, new_model())
        m["reqs"] += int(reqs)
        m["fresh_in"] += int(fresh_in)
        m["out"] += int(out)
        m["cache_read"] += int(cache_read)
        m["cache_write"] += int(cache_write)
        m["cost"] += float(cost)


def model_tokens(m: dict[str, Any]) -> int:
    return sum(int(m.get(k) or 0) for k in TOKEN_KEYS)


@dataclass
class SourceSnapshot:
    key: str
    name: str
    kind: str = "session"  # proxy | session | local
    status: str = STATUS_OK
    reason: str | None = None
    note: str = ""
    supports_cost: bool = False
    supports_credits: bool = False
    supports_tokens: bool = True
    days: dict[str, dict[str, Any]] = field(default_factory=dict)
    sids: set[str] = field(default_factory=set)
    sessions: int | None = None
    last_seen: float | None = None
    warnings: list[str] = field(default_factory=list)
    suppressed: dict[str, Any] | None = None
    session_rows: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, Any] | None = None
    tool_counts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def day(self, date: str) -> dict[str, Any]:
        return self.days.setdefault(date, new_day())

    def mark_unsupported(self, reason: str) -> "SourceSnapshot":
        self.status = STATUS_UNSUPPORTED
        self.reason = reason
        return self

    def mark_error(self, reason: str) -> "SourceSnapshot":
        self.status = STATUS_ERROR
        self.reason = reason
        return self

    def finish(self) -> "SourceSnapshot":
        if self.status in (STATUS_UNSUPPORTED, STATUS_ERROR):
            return self
        if not self.days:
            self.status = STATUS_EMPTY
            if not self.reason:
                self.reason = "本期无记录"
        else:
            self.status = STATUS_OK
        if self.sessions is None:
            self.sessions = len(self.sids)
        return self

    def totals(self) -> dict[str, Any]:
        out = {
            "reqs": 0,
            "credits": 0.0,
            "fresh_in": 0,
            "out": 0,
            "cache_read": 0,
            "cache_write": 0,
            "cost": 0.0,
            "tokens": 0,
        }
        for d in self.days.values():
            out["reqs"] += int(d["reqs"])
            out["credits"] += float(d["credits"])
            for k in TOKEN_KEYS:
                out[k] += int(d[k])
            out["cost"] += float(d["cost"])
        out["tokens"] = sum(out[k] for k in TOKEN_KEYS)
        return out

    def to_dict(self) -> dict[str, Any]:
        days = {}
        for date in sorted(self.days):
            d = self.days[date]
            days[date] = {
                "reqs": int(d["reqs"]),
                "credits": float(d["credits"]),
                "fresh_in": int(d["fresh_in"]),
                "out": int(d["out"]),
                "cache_read": int(d["cache_read"]),
                "cache_write": int(d["cache_write"]),
                "cost": float(d["cost"]),
                "hours": [int(x) for x in d["hours"]],
                "models": {
                    name: {**{k: (float(v) if k == "cost" else int(v)) for k, v in m.items()}}
                    for name, m in sorted(d["models"].items())
                },
            }
        return {
            "key": self.key,
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "reason": self.reason,
            "note": self.note,
            "supports_cost": self.supports_cost,
            "supports_credits": self.supports_credits,
            "supports_tokens": self.supports_tokens,
            "totals": self.totals(),
            "days": days,
            "sessions": int(self.sessions or 0),
            "last_seen": self.last_seen,
            "warnings": list(self.warnings),
            "suppressed": self.suppressed,
            "session_rows": self.session_rows[:500],
            "timing": self.timing,
            "tools": [
                {"name": k, "n": v["n"], "sessions": len(v["sessions"]), "last_seen": v["last"]}
                for k, v in sorted(self.tool_counts.items(), key=lambda kv: -kv[1]["n"])[:50]
            ],
        }


def add_session(snap: "SourceSnapshot", sid: str, *, reqs: int = 0, tokens: int = 0,
                cost: float = 0.0, credits: float = 0.0, model: str | None = None,
                last_seen: float | None = None) -> None:
    """会话级汇总（真实数据；九路各自能给的维度不同，缺的留空而不是编）。"""
    if not sid or (reqs == 0 and tokens == 0 and credits == 0):
        return
    snap.session_rows.append({
        "id": str(sid), "source": snap.key, "reqs": int(reqs), "tokens": int(tokens),
        "cost": float(cost), "credits": float(credits),
        "model": model, "last_seen": last_seen,
    })


def token_total(d: dict[str, Any]) -> int:
    return sum(int(d.get(k) or 0) for k in TOKEN_KEYS)
