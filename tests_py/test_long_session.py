"""长会话 / 大 transcript：正确性 + 时间上限 + 进程内缓存。"""
import json
import sqlite3
import time

from cchud_next.accounting import collect, merge
from cchud_next.sources import cchaha, workbuddy

from conftest import iso_utc, local_noon

N = 20000
WB = 5000


def _home_with_big_sources(home):
    cfg = home / ".claude" / "cc-haha"
    (cfg / "db").mkdir(parents=True)
    projects = home / ".claude" / "projects"
    t = local_noon()
    lines = []
    for i in range(N):
        lines.append(json.dumps({
            "timestamp": iso_utc(t + i % 3600),
            "message": {"id": f"m{i}", "model": "claude-x", "usage": {
                "input_tokens": 10, "output_tokens": 5,
                "cache_read_input_tokens": 100, "cache_creation_input_tokens": 2}},
        }))
    # 两个文件：后半段是 fork 抄写（同 id），验证跨文件去重
    half = N // 2
    (projects).mkdir(parents=True, exist_ok=True)
    (projects / "sid-a.jsonl").write_text("\n".join(lines[:half]), encoding="utf-8")
    (projects / "sid-b.jsonl").write_text("\n".join(lines[half:]), encoding="utf-8")
    (projects / "sid-c.jsonl").write_text("\n".join(lines[:half]), encoding="utf-8")  # fork 抄写

    db = cfg / "db" / "index-v1.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table activity_daily_models (transcript_path text, date text, cost_usd real)")
    con.executemany("insert into activity_daily_models values (?,?,?)",
                    [(str(projects / "sid-a.jsonl"), "2026-11-07", 6.0),
                     (str(projects / "sid-b.jsonl"), "2026-11-07", 6.0)])
    con.commit()
    con.close()

    wb = home / ".workbuddy" / "projects" / "p"
    wb.mkdir(parents=True)
    wb_lines = []
    for i in range(WB):
        wb_lines.append(json.dumps({
            "timestamp": str(int((t + i) * 1000)), "sessionId": "wb-1",
            "providerData": {"model": "wb-m", "rawUsage": {
                "prompt_tokens": 100, "completion_tokens": 10,
                "prompt_cache_hit_tokens": 70, "prompt_cache_write_tokens": 20,
                "credit": 0.5}},
        }))
    (wb / "s.jsonl").write_text("\n".join(wb_lines), encoding="utf-8")


def test_big_transcripts_correct_and_bounded(home, paths, monkeypatch):
    # conftest 的 home fixture 已设置 CLAUDE_CONFIG_DIR
    _home_with_big_sources(home)
    cchaha._CACHE.clear()
    workbuddy._CACHE.clear()

    t0 = time.time()
    sources = collect(paths, "1d")
    first = time.time() - t0
    by_key = {s.key: s for s in sources}

    ch = by_key["cchaha"]
    assert ch.totals()["reqs"] == N, ch.totals()
    assert ch.totals()["cache_read"] == 100 * N
    assert ch.sids == {"sid-a", "sid-b", "sid-c"}

    wb_snap = by_key["workbuddy"]
    assert wb_snap.totals()["reqs"] == WB
    assert wb_snap.totals()["fresh_in"] == 10 * WB

    agg = merge(sources, "1d")
    assert all(c["ok"] for c in agg["conservation"]), [c for c in agg["conservation"] if not c["ok"]]
    assert agg["totals"]["tokens"] >= 100 * N + 100 * WB

    # 冷启动上限（本机实测 2 万行 cc-haha + 5 千行 WB 远低于此）
    assert first < 20.0, f"cold collect too slow: {first:.2f}s"

    # 进程内缓存：第二次应显著更快
    t1 = time.time()
    collect(paths, "1d")
    second = time.time() - t1
    assert second < first, (first, second)
