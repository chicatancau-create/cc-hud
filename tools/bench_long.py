"""10 万行级 transcript 基准（一次性工具，不进默认测试）。

用法：python tools/bench_long.py [N]
生成临时 home，构造 cc-haha 索引 + transcript、WorkBuddy transcript，跑 collect+merge 两遍。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cchud_next.accounting import collect, merge  # noqa: E402
from cchud_next.paths import Paths  # noqa: E402
from cchud_next.sources import cchaha, workbuddy  # noqa: E402


def build(home: Path, n: int, wb: int) -> None:
    import datetime as dt

    now = time.time()
    iso = lambda ep: dt.datetime.fromtimestamp(ep, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    cfg = home / ".claude" / "cc-haha"
    (cfg / "db").mkdir(parents=True)
    projects = home / ".claude" / "projects"
    projects.mkdir(parents=True)
    with open(projects / "sid-a.jsonl", "w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({"timestamp": iso(now - i % 86400),
                                 "message": {"id": f"m{i}", "model": "claude-x",
                                             "usage": {"input_tokens": 10, "output_tokens": 5,
                                                       "cache_read_input_tokens": 100,
                                                       "cache_creation_input_tokens": 2}}}) + "\n")
    con = sqlite3.connect(cfg / "db" / "index-v1.sqlite")
    con.execute("create table activity_daily_models (transcript_path text, date text, cost_usd real)")
    con.execute("insert into activity_daily_models values (?,?,?)",
                (str(projects / "sid-a.jsonl"), "2026-11-07", 10.0))
    con.commit()
    con.close()

    wbdir = home / ".workbuddy" / "projects" / "p"
    wbdir.mkdir(parents=True)
    with open(wbdir / "s.jsonl", "w", encoding="utf-8") as fh:
        for i in range(wb):
            fh.write(json.dumps({"timestamp": str(int((now - i) * 1000)), "sessionId": "wb",
                                 "providerData": {"model": "wb-m", "rawUsage": {
                                     "prompt_tokens": 100, "completion_tokens": 10,
                                     "prompt_cache_hit_tokens": 70,
                                     "prompt_cache_write_tokens": 20}}}) + "\n")


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    wb = max(1, n // 5)
    with tempfile.TemporaryDirectory(prefix="cchud-bench-") as tmp:
        home = Path(tmp)
        build(home, n, wb)
        paths = Paths(home=home)
        cchaha._CACHE.clear()
        workbuddy._CACHE.clear()
        t0 = time.time()
        sources = collect(paths, "7d")
        cold = time.time() - t0
        agg = merge(sources, "7d")
        by = {s.key: s for s in sources}
        assert by["cchaha"].totals()["reqs"] == n, by["cchaha"].totals()
        assert by["workbuddy"].totals()["reqs"] == wb
        assert all(c["ok"] for c in agg["conservation"])
        t1 = time.time()
        collect(paths, "7d")
        warm = time.time() - t1
        print(json.dumps({"n": n, "wb": wb, "cold_s": round(cold, 2), "warm_s": round(warm, 2),
                          "tokens": agg["totals"]["tokens"], "requests": agg["totals"]["reqs"],
                          "conservation": len(agg["conservation"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
