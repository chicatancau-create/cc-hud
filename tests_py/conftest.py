import datetime as dt
import json
import sqlite3
import time

import pytest

from cchud_next.paths import Paths


def local_noon(days_ago: int = 0) -> float:
    d = dt.date.today() - dt.timedelta(days=days_ago)
    return time.mktime(dt.datetime.combine(d, dt.time(12, 0)).timetuple())


def iso_utc(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    return tmp_path


@pytest.fixture()
def paths(home):
    return Paths(home=home)


def write_ccswitch(paths, rows):
    db = paths.ccswitch_db
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute(
        """create table proxy_request_logs (
            created_at real, total_cost_usd real, input_tokens int, output_tokens int,
            cache_read_tokens int, cache_creation_tokens int, data_source text,
            session_id text, model text, latency_ms real, first_token_ms real)"""
    )
    con.executemany(
        "insert into proxy_request_logs (created_at,total_cost_usd,input_tokens,output_tokens,"
        "cache_read_tokens,cache_creation_tokens,data_source,session_id,model)"
        " values (?,?,?,?,?,?,?,?,?)", rows
    )
    con.commit()
    con.close()


def jlines(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
