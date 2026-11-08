import json
import sqlite3

from cchud_next.sources import (
    cchaha,
    ccswitch,
    codex,
    dsh,
    herdsman,
    qoder,
    workbuddy,
    zcode,
)

from conftest import iso_utc, jlines, local_noon, write_ccswitch
from cchud_next.sources.base import local_date


def test_ccswitch_net_input_and_cost(paths):
    t = local_noon()
    write_ccswitch(paths, [
        (t, 0.10, 100, 10, 50, 5, "proxy", "s1", "claude-sonnet"),
        (t + 60, 0.20, 40, 4, 60, 0, "codex_session", "s2", "gpt-5"),
    ])
    s = ccswitch.load(paths, "1d")
    t0 = s.totals()
    # 汇总口径：Σinput - Σcodex_session.cache_read = 140 - 60
    assert t0["fresh_in"] == 80
    assert t0["out"] == 14
    assert t0["cache_read"] == 110
    assert t0["cache_write"] == 5
    assert t0["cost"] == 0.30000000000000004
    assert s.totals()["tokens"] == 80 + 14 + 110 + 5
    assert s.sids == {"s1", "s2"}
    rows = {r["id"]: r for r in s.session_rows}
    assert s.timing is not None and s.timing["n"] == 0  # 夹具未写延迟列值
    assert rows["s1"]["reqs"] == 1 and rows["s1"]["tokens"] == 165
    assert rows["s2"]["tokens"] == 44


def test_ccswitch_timing_percentiles(paths):
    import sqlite3

    t = local_noon()
    write_ccswitch(paths, [
        (t, 0.1, 100, 10, 50, 5, "proxy", "s1", "m"),
        (t + 60, 0.1, 100, 10, 50, 5, "proxy", "s2", "m"),
    ])
    con = sqlite3.connect(paths.ccswitch_db)
    con.execute("update proxy_request_logs set latency_ms=1000, first_token_ms=200 where session_id='s1'")
    con.execute("update proxy_request_logs set latency_ms=3000, first_token_ms=600 where session_id='s2'")
    con.commit(); con.close()
    s = ccswitch.load(paths, "1d")
    assert s.timing["n"] == 2
    assert s.timing["p50"] == 3000 and s.timing["p95"] == 3000
    assert s.timing["ftt_p50"] == 600


def test_ccswitch_missing_db_is_unsupported(paths):
    assert ccswitch.load(paths, "1d").status == "unsupported"


def test_cchaha_global_dedupe_and_local_cost_split(home, paths):
    cfg = home / ".claude" / "cc-haha"
    (cfg / "db").mkdir(parents=True)
    projects = home / ".claude" / "projects"
    msg = {
        "timestamp": iso_utc(local_noon()),
        "message": {"id": "m1", "model": "claude-x",
                    "content": [{"type": "tool_use", "name": "Read"},
                                {"type": "tool_use", "name": "Bash"}],
                    "usage": {"input_tokens": 10, "output_tokens": 5,
                              "cache_read_input_tokens": 100,
                              "cache_creation_input_tokens": 2}},
    }
    jlines(projects / "sid-a.jsonl", [msg])
    jlines(projects / "sid-b.jsonl", [msg])  # fork 抄写同一 message
    db = cfg / "db" / "index-v1.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table activity_daily_models (transcript_path text, date text, cost_usd real)")
    con.execute("insert into activity_daily_models values (?,?,?)", (str(projects / "sid-a.jsonl"), local_date(local_noon()), 2.0))
    con.commit()
    con.close()

    s = cchaha.load(paths, "7d")
    assert s.totals()["reqs"] == 1
    assert s.totals()["fresh_in"] == 10
    assert s.totals()["cache_read"] == 100
    assert abs(s.totals()["cost"] - 2.0) < 1e-9
    assert s.sids == {"sid-a", "sid-b"}
    tools = {t["name"]: t["n"] for t in s.to_dict()["tools"]}
    assert tools == {"Read": 1, "Bash": 1}


def test_cchaha_cost_stays_on_its_day(home, paths):
    """会话跨两天时，索引里的当日成本不能摊到另一天。"""
    cfg = home / ".claude" / "cc-haha"
    (cfg / "db").mkdir(parents=True)
    projects = home / ".claude" / "projects"
    now = local_noon()
    yday = now - 86400
    msgs = []
    for i, t in enumerate((yday, now)):
        msgs.append({
            "timestamp": iso_utc(t),
            "message": {"id": f"m{i}", "model": "claude-x", "content": [],
                        "usage": {"input_tokens": 10, "output_tokens": 0}},
        })
    jlines(projects / "sid-c.jsonl", msgs)
    db = cfg / "db" / "index-v1.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table activity_daily_models (transcript_path text, date text, cost_usd real)")
    con.execute("insert into activity_daily_models values (?,?,?)",
                (str(projects / "sid-c.jsonl"), local_date(yday), 2.0))
    con.execute("insert into activity_daily_models values (?,?,?)",
                (str(projects / "sid-c.jsonl"), local_date(now), 3.0))
    con.commit()
    con.close()

    s = cchaha.load(paths, "7d")
    assert abs(s.days[local_date(yday)]["cost"] - 2.0) < 1e-9
    assert abs(s.days[local_date(now)]["cost"] - 3.0) < 1e-9


def test_cchaha_stale_session_not_registered(home, paths):
    """范围外的会话不能进 sids，否则会误伤其他来源的去重窗口。"""
    cfg = home / ".claude" / "cc-haha"
    (cfg / "db").mkdir(parents=True)
    projects = home / ".claude" / "projects"
    old = local_noon() - 3 * 86400
    jlines(projects / "sid-old.jsonl", [{
        "timestamp": iso_utc(old),
        "message": {"id": "old-1", "model": "claude-x",
                    "content": [], "usage": {"input_tokens": 5, "output_tokens": 5}},
    }])
    db = cfg / "db" / "index-v1.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table activity_daily_models (transcript_path text, date text, cost_usd real)")
    con.commit()
    con.close()

    s = cchaha.load(paths, "1d")
    assert s.totals()["reqs"] == 0
    assert s.sids == set()


def test_qoder_credits_only(paths):
    t = local_noon()
    jlines(paths.qoder_dir / "p" / "s1.jsonl", [
        {"timestamp": iso_utc(t), "message": {"id": "m1", "usage": {"credits": 3.5}}},
        {"timestamp": iso_utc(t), "message": {"id": "m1", "usage": {"credits": 3.5}}},
    ])
    s = qoder.load(paths, "1d")
    q = [x for x in s if x.key == "qoder"][0]
    assert q.totals()["reqs"] == 1
    assert q.totals()["credits"] == 3.5
    assert q.totals()["tokens"] == 0
    assert q.supports_tokens is False


def test_zcode_net_input_and_reasoning(paths):
    db = paths.zcode_db
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("""create table model_usage (started_at int, input_tokens int, output_tokens int,
                   reasoning_tokens int, cache_read_input_tokens int,
                   cache_creation_input_tokens int, model_id text, session_id text)""")
    con.execute("insert into model_usage values (?,?,?,?,?,?,?,?)",
                (int(local_noon() * 1000), 100, 10, 5, 60, 4, "glm-5", "z1"))
    con.commit()
    con.close()
    s = zcode.load(paths, "1d")
    t = s.totals()
    assert t["fresh_in"] == 40
    assert t["out"] == 15
    assert t["tokens"] == 40 + 15 + 60 + 4


def test_herdsman_iso_time(paths):
    t = local_noon()
    jlines(paths.herdsman_log, [
        {"input_tokens": 20, "output_tokens": 8, "model": "qwen",
         "request_id": "r1", "started_at": iso_utc(t)},
        {"note": "no tokens"},
    ])
    s = herdsman.load(paths, "1d")
    assert s.totals()["reqs"] == 1
    assert s.totals()["tokens"] == 28
    assert s.sessions == 0 and s.sids == set()   # request_id 不是会话


def test_codex_skips_have_sids(paths):
    t = local_noon()
    name = "rollout-2026-11-07T10-00-00-11111111-2222-3333-4444-555555555555.jsonl"
    jlines(paths.codex_dirs[0] / "2026" / "11" / "07" / name, [
        {"timestamp": iso_utc(t),
         "payload": {"total_token_usage": {"input_tokens": 100, "cached_input_tokens": 70,
                                           "output_tokens": 20, "cache_write_input_tokens": 5}}},
    ])
    sid = "11111111-2222-3333-4444-555555555555"
    skipped = codex.load(paths, "1d", exclude_sids={sid})
    assert skipped.totals()["reqs"] == 0
    s = codex.load(paths, "1d")
    assert s.totals()["fresh_in"] == 30
    assert s.totals()["cache_read"] == 70
    assert s.totals()["tokens"] == 125


def test_workbuddy_net_input_and_credit_rules(paths):
    t = local_noon()
    rec = {"timestamp": str(int(t * 1000)), "sessionId": "child-1",
           "providerData": {"model": "wb-model", "rawUsage": {
               "prompt_tokens": 100, "completion_tokens": 10,
               "prompt_cache_hit_tokens": 70, "prompt_cache_write_tokens": 20,
               "credit": 1.25}}}
    jlines(paths.workbuddy_sources[0][0] / "p" / "parent.jsonl", [rec])
    jlines(paths.workbuddy_sources[1][0] / "p" / "parent.jsonl", [rec])
    domestic, intl = workbuddy.load(paths, "1d")
    assert domestic.totals()["fresh_in"] == 10
    assert domestic.totals()["tokens"] == 110  # prompt 100 + completion 10
    assert domestic.totals()["credits"] == 1.25
    assert intl.totals()["credits"] == 0.0
    assert "parent" in domestic.sids and "child-1" in domestic.sids
    assert domestic.session_rows[0]["id"] == "parent"
    assert domestic.session_rows[0]["tokens"] == 110


def test_workbuddy_dedupes_copied_session_files(paths):
    t = local_noon()
    rec = {"timestamp": str(int(t * 1000)), "sessionId": "wb-1",
           "providerData": {"model": "m", "rawUsage": {
               "prompt_tokens": 10, "completion_tokens": 2,
               "prompt_cache_hit_tokens": 4, "credit": 0.5}}}
    jlines(paths.workbuddy_sources[0][0] / "p1" / "s.jsonl", [rec])
    jlines(paths.workbuddy_sources[0][0] / "p2" / "s.jsonl", [rec])   # 复制副本
    dom, _intl = workbuddy.load(paths, "1d")
    assert dom.totals()["reqs"] == 1


def test_dsh_projcache_turns_and_model(paths):
    t = local_noon()
    p = paths.dsh_projcache / "sid1.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"record": {
        "identity": {"createdAt": int(t * 1000)},
        "rows": {
            "tokenUsage": {"val": {"totals": {"uncachedInputTokens": 11, "outputTokens": 7,
                                              "cacheReadTokens": 90, "cacheWriteTokens": 0}}},
            "sessionStats": {"val": {"turns": 3}},
            "modelSelection": {"val": {"lastUsed": {"model": "deepseek-v4"}}},
        }}}), encoding="utf-8")
    (paths.dsh_projcache / "empty.json").write_text(json.dumps({"record": {
        "identity": {"createdAt": int(t * 1000)},
        "rows": {"tokenUsage": {"val": {"totals": {"uncachedInputTokens": 0, "outputTokens": 0,
                                                  "cacheReadTokens": 0, "cacheWriteTokens": 0}}}},
    }}), encoding="utf-8")
    s = dsh.load(paths, "1d")
    pc = [x for x in s if x.key == "dsh"][0]
    assert pc.totals()["reqs"] == 3
    assert pc.totals()["tokens"] == 108
    assert pc.days[list(pc.days)[0]]["models"]["deepseek-v4"]["reqs"] == 3


def test_dsh_v4_without_usage_is_unsupported(paths):
    from compression import zstd

    d = paths.dsh_sessions / "--proj--" / "uuid-1"
    d.mkdir(parents=True)
    lines = [
        {"type": "session", "version": 4, "id": "uuid-1", "createdAt": int(local_noon() * 1000)},
        {"type": "assistant/message", "time": int(local_noon() * 1000),
         "data": {"message": {"role": "assistant", "content": []}, "source": {"model": "m"}}},
    ]
    (d / "session.v4.jsonl.zstd").write_bytes(
        zstd.compress("\n".join(json.dumps(x) for x in lines).encode())
    )
    pc, v4 = dsh.load(paths, "1d")
    assert v4.status == "unsupported"
    assert "不伪造" in (v4.reason or "")
    assert v4.totals()["tokens"] == 0
