import json

from cchud_next.accounting import collect, merge
from cchud_next.model import SourceSnapshot, add_usage

from conftest import iso_utc, jlines, local_noon, write_ccswitch


def base_env(paths):
    t = local_noon()
    write_ccswitch(paths, [(t, 1.0, 100, 10, 50, 5, "proxy", "s1", "m1")])


def test_clash_route_is_suppressed(paths):
    base_env(paths)
    # Qoder 会话 id 与基准路相同 → 整路拒绝并入
    jlines(paths.qoder_dir / "s1.jsonl", [
        {"timestamp": iso_utc(local_noon()),
         "message": {"id": "m1", "usage": {"credits": 9.0}}},
    ])
    sources = collect(paths, "1d")
    q = [s for s in sources if s.key == "qoder"][0]
    assert q.suppressed == {"by": "ccswitch", "clash": 1, "by_all": ["ccswitch"]}
    agg = merge(sources, "1d")
    assert agg["totals"]["credits"] == 0.0
    assert agg["totals"]["reqs"] == 1


def test_suppression_names_real_conflicting_source(paths):
    """by 必须指向真正先计入该 sid 的那一路；旧实现硬编码 "ccswitch"。"""
    jlines(paths.qoder_dir / "dup-1.jsonl", [
        {"timestamp": iso_utc(local_noon()), "message": {"id": "q1", "usage": {"credits": 1.0}}},
    ])
    jlines(paths.home / ".workbuddy" / "projects" / "p1" / "other.jsonl", [
        {"timestamp": local_noon() * 1000, "sessionId": "dup-1",
         "providerData": {"rawUsage": {"prompt_tokens": 10, "completion_tokens": 5},
                          "model": "wb"}},
    ])
    sources = collect(paths, "1d")
    wb = [s for s in sources if s.key == "workbuddy"][0]
    assert wb.suppressed["by"] == "qoder"
    assert wb.suppressed["by_all"] == ["qoder"]
    assert wb.suppressed["clash"] == 1
    merged = merge(sources, "1d")
    assert "workbuddy" not in {r["source"] for r in merged["session_rows"]}


def test_conservation_all_true_and_models_le_total(paths):
    base_env(paths)
    sources = collect(paths, "1d")
    agg = merge(sources, "1d")
    assert agg["conservation"], "至少要有校验项"
    assert all(c["ok"] for c in agg["conservation"]), agg["conservation"]
    assert sum(m["tokens"] for m in agg["models"]) <= agg["totals"]["tokens"] + 1e-9


def test_gap_source_excludes_all_counted_sids(paths):
    # Qoder 先计入 sid-x；DSH 同名会话必须被排除（否则跨源双计）
    jlines(paths.qoder_dir / "sid-x.jsonl", [
        {"timestamp": iso_utc(local_noon()), "message": {"id": "q1", "usage": {"credits": 1.0}}},
    ])
    d = paths.dsh_projcache / "sid-x.json"
    d.parent.mkdir(parents=True)
    d.write_text(json.dumps({"record": {
        "identity": {"createdAt": int(local_noon() * 1000)},
        "rows": {"tokenUsage": {"val": {"totals": {"uncachedInputTokens": 10, "outputTokens": 5,
                                                  "cacheReadTokens": 1, "cacheWriteTokens": 0}}},
                 "sessionStats": {"val": {"turns": 1}}}}}), encoding="utf-8")
    sources = collect(paths, "1d")
    dsh = [s for s in sources if s.key == "dsh"][0]
    assert dsh.totals()["reqs"] == 0, dsh.to_dict()


def test_session_rows_merged_and_sorted(paths):
    base_env(paths)
    sources = collect(paths, "1d")
    agg = merge(sources, "1d")
    assert agg["session_total"] >= 1
    assert agg["session_rows"][0]["tokens"] >= agg["session_rows"][-1]["tokens"]
    assert agg["session_rows"][0]["source"] == "ccswitch"


def test_kpis_null_when_dimension_unsupported(paths):
    # 只有 Qoder（credits-only）→ cost 必须 None，而不是 0
    jlines(paths.qoder_dir / "s.jsonl", [
        {"timestamp": iso_utc(local_noon()), "message": {"id": "q1", "usage": {"credits": 2.0}}},
    ])
    agg = merge(collect(paths, "1d"), "1d")
    assert agg["kpis"]["cost"] is None
    assert agg["kpis"]["cache_hit"] is None
    assert agg["kpis"]["credits"] == 2.0


def test_suppressed_source_keeps_own_totals_but_not_merged():
    a = SourceSnapshot("a", "A")
    add_usage(a.day("2026-11-07"), reqs=1, fresh_in=10)
    a.sids = {"s1"}
    a.finish()
    b = SourceSnapshot("b", "B")
    add_usage(b.day("2026-11-07"), reqs=1, fresh_in=5)
    b.sids = {"s1"}
    b.finish()
    b.suppressed = {"by": "a", "clash": 1}
    agg = merge([a, b], "1d")
    assert agg["totals"]["fresh_in"] == 10
    assert b.totals()["fresh_in"] == 5
