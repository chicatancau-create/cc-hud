"""四范围 × 九路对账门禁：守恒检查全绿、totals==Σdays、Σhours==reqs、models<=total。

用法：python tools/reconcile.py [--json]
失败退出码 1。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cchud_next.accounting import collect, merge  # noqa: E402
from cchud_next.paths import Paths  # noqa: E402


def main() -> int:
    paths = Paths.default()
    out = {}
    ok = True
    for rng in ("1d", "7d", "30d", "all"):
        t0 = time.time()
        sources = collect(paths, rng)
        agg = merge(sources, rng)
        dt = time.time() - t0
        bad = [c["name"] for c in agg["conservation"] if not c["ok"]]

        for s in sources:
            if s.suppressed or s.status != "ok":
                continue
            t = s.totals()
            days = sum(int(d["reqs"]) for d in s.days.values())
            hours = sum(sum(int(x) for x in d["hours"]) for d in s.days.values())
            if t["reqs"] != days:
                bad.append(f"{s.key}.reqs!=Σdays")
            if t["reqs"] != hours:
                bad.append(f"{s.key}.reqs!=Σhours")

        t = agg["totals"]
        day_sum = {
            "reqs": sum(d["reqs"] for d in agg["daily"]),
            "tokens": sum(d["tokens"] for d in agg["daily"]),
        }
        if t["reqs"] != day_sum["reqs"] or t["tokens"] != day_sum["tokens"]:
            bad.append("totals!=Σdaily")

        out[rng] = {
            "seconds": round(dt, 2),
            "sources": len(sources),
            "included": sum(1 for s in sources if s.status == "ok" and not s.suppressed),
            "checks": len(agg["conservation"]),
            "bad": bad,
            "tokens": t["tokens"],
            "reqs": t["reqs"],
            "cost": round(t["cost"], 2),
            "sessions": agg["session_total"],
        }
        ok = ok and not bad
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        for k, v in out.items():
            print(f"{k:>4}  {v['seconds']:>6.2f}s  tokens={v['tokens']:>13,}  reqs={v['reqs']:>7,}  "
                  f"cost=${v['cost']:>8.2f}  sessions={v['sessions']:>5}  checks={v['checks']}  bad={v['bad'] or 'none'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
