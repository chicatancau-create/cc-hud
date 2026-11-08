"""只读 SQLite：mode=ro + query_only + busy_timeout + finally close。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote


class SourceUnavailable(Exception):
    """来源不存在（未安装/未落盘）—— 与读取失败区分。"""


class SourceReadError(Exception):
    """来源存在但读取失败（权限、损坏、被占用）。"""


def ro_uri(path: Path | str) -> str:
    p = Path(path)
    return "file:" + quote(p.as_posix(), safe="/:") + "?mode=ro"


@contextmanager
def connect_ro(path: Path | str, busy_timeout_ms: int = 1200):
    p = Path(path)
    if not p.exists():
        raise SourceUnavailable(str(p))
    try:
        con = sqlite3.connect(ro_uri(p), uri=True, timeout=busy_timeout_ms / 1000.0)
    except sqlite3.Error as exc:
        raise SourceReadError(f"{p}: {exc}") from exc
    try:
        con.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        con.execute("PRAGMA query_only=ON")
        yield con
    except sqlite3.Error as exc:
        raise SourceReadError(f"{p}: {exc}") from exc
    finally:
        con.close()


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "select 1 from sqlite_master where type='table' and name=?", (name,)
    ).fetchone()
    return bool(row)
