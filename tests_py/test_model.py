import pytest

from cchud_next.model import (
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    SourceSnapshot,
    add_usage,
    new_day,
    token_total,
)


def test_add_usage_keeps_model_and_day_in_sync():
    d = new_day()
    add_usage(d, reqs=2, fresh_in=10, out=5, cache_read=100, cache_write=3,
              cost=0.25, credits=1.5, model="m1", hour=9)
    assert d["reqs"] == 2
    assert token_total(d) == 118
    assert d["hours"][9] == 2
    assert d["models"]["m1"]["cache_read"] == 100
    assert d["cost"] == pytest.approx(0.25)
    assert d["credits"] == pytest.approx(1.5)


def test_totals_equal_sum_of_days():
    s = SourceSnapshot(key="x", name="X")
    add_usage(s.day("2026-11-06"), reqs=1, fresh_in=1, out=2, cache_read=3, cache_write=4)
    add_usage(s.day("2026-11-07"), reqs=2, fresh_in=5, out=6, cache_read=7, cache_write=8)
    t = s.totals()
    assert t["reqs"] == 3
    assert t["fresh_in"] == 6 and t["out"] == 8 and t["cache_read"] == 10 and t["cache_write"] == 12
    assert t["tokens"] == sum(token_total(d) for d in s.days.values())


def test_finish_distinguishes_empty_from_zero():
    empty = SourceSnapshot(key="e", name="E").finish()
    assert empty.status == STATUS_EMPTY

    zero = SourceSnapshot(key="z", name="Z")
    zero.day("2026-11-07")  # 有记录但全为真实 0
    zero.finish()
    assert zero.status == STATUS_OK
    assert zero.totals()["tokens"] == 0


def test_finish_keeps_unsupported_reason():
    s = SourceSnapshot(key="u", name="U").mark_unsupported("未安装").finish()
    assert s.status == STATUS_UNSUPPORTED
    assert s.reason == "未安装"


def test_to_dict_serializes_sorted_days_and_zero_defaults():
    s = SourceSnapshot(key="k", name="K")
    add_usage(s.day("2026-11-07"), reqs=1, fresh_in=2, model="m")
    s.finish()
    out = s.to_dict()
    assert list(out["days"]) == ["2026-11-07"]
    assert out["days"]["2026-11-07"]["hours"] == [0] * 24
    assert out["totals"]["tokens"] == 2
    assert out["status"] == STATUS_OK
    assert isinstance(out["sessions"], int)
