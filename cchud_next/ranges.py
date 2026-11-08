"""四档时间范围：今日 / 7 天 / 30 天 / 全部。以本地日 00:00 为界。"""
from __future__ import annotations

import datetime as dt
import time

RANGES = ("1d", "7d", "30d", "all")
RANGE_LABELS = {"1d": "今日", "7d": "7 天", "30d": "30 天", "all": "全部"}
RANGE_DAYS = {"1d": 1, "7d": 7, "30d": 30, "all": 0}


def start_date(rng: str, now: float | None = None) -> str | None:
    """返回范围起始本地日（含）；全部范围返回 None。"""
    if rng not in RANGES:
        raise ValueError(f"unknown range: {rng}")
    if rng == "all":
        return None
    now = time.time() if now is None else now
    today = dt.date.fromtimestamp(now)
    days = RANGE_DAYS[rng]
    return (today - dt.timedelta(days=days - 1)).isoformat()


def start_epoch(rng: str, now: float | None = None) -> int | None:
    sd = start_date(rng, now)
    if sd is None:
        return None
    return int(dt.datetime.combine(dt.date.fromisoformat(sd), dt.time.min).timestamp())


def in_range(date: str, rng: str, now: float | None = None) -> bool:
    sd = start_date(rng, now)
    return sd is None or date >= sd
