import sqlite3

import pytest

from cchud_next.sqlite_ro import SourceReadError, SourceUnavailable, connect_ro


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "t.db"
    con = sqlite3.connect(p)
    con.execute("create table t (x int)")
    con.execute("insert into t values (1), (2)")
    con.commit()
    con.close()
    return p


def test_reads_rows(db):
    with connect_ro(db) as con:
        assert con.execute("select sum(x) from t").fetchone()[0] == 3


def test_write_is_rejected(db):
    with pytest.raises(SourceReadError):
        with connect_ro(db) as con:
            con.execute("insert into t values (3)")


def test_missing_db_is_unavailable(tmp_path):
    with pytest.raises(SourceUnavailable):
        with connect_ro(tmp_path / "nope.db"):
            pass


def test_connection_closed_even_on_error(db):
    con = None
    with pytest.raises(SourceReadError):
        with connect_ro(db) as con:
            con.execute("insert into t values (9)")
    assert con is not None
    with pytest.raises(sqlite3.ProgrammingError):
        con.execute("select 1")


def test_uri_is_ro(db):
    with connect_ro(db) as con:
        assert con.execute("pragma query_only").fetchone()[0] == 1
