import json

from cchud_next.bridge import Bridge
from cchud_next.export import redact, write_export
from cchud_next.paths import Paths
from cchud_next.settings import SettingsStore

from conftest import local_noon, write_ccswitch


class FakePower:
    def __init__(self):
        self.calls = []

    def run(self, action, delay=15):
        self.calls.append((action, delay))
        return {"ok": True, "action": action, "scheduled": delay > 0}

    def cancel(self):
        self.calls.append(("cancel", 0))
        return {"ok": True}


def make(tmp_path, paths, **kw):
    return Bridge(root=tmp_path, paths=paths, settings=SettingsStore(tmp_path / "s.json"),
                  power=kw.pop("power", FakePower()), now_fn=kw.pop("now_fn", None) or (lambda: local_noon()),
                  **kw)


def test_bootstrap_shape(tmp_path, paths):
    b = make(tmp_path, paths)
    boot = b.bootstrap()
    assert [r["key"] for r in boot["ranges"]] == ["1d", "7d", "30d", "all"]
    assert len(boot["sources_meta"]) >= 9
    assert boot["settings"]["range"] == "1d"


def test_snapshot_latest_wins_and_cache(tmp_path, paths):
    t = local_noon()
    write_ccswitch(paths, [(t, 1.0, 100, 10, 50, 5, "proxy", "s1", "m1")])
    b = make(tmp_path, paths)
    first = b.snapshot("1d", 5)
    assert first["seq"] == 5 and first["revision"] >= 1
    stale = b.snapshot("1d", 4)
    assert stale.get("stale") is True
    second = b.snapshot("1d", 6)
    assert second["seq"] == 6
    assert second["cache"]["hits"] >= 1


def test_cache_payload_not_mutated_by_seq(tmp_path, paths):
    write_ccswitch(paths, [])
    b = make(tmp_path, paths)
    first = b.snapshot("1d", 1)
    second = b.snapshot("1d", 2)
    assert first["seq"] == 1 and second["seq"] == 2
    _ts, _rev, cached = b._service._cache["1d"]
    assert "seq" not in cached and "cache" not in cached
    assert b.snapshot("1d", 1).get("stale") is True


def test_revision_monotonic_across_cache_hit(tmp_path, paths):
    write_ccswitch(paths, [])
    b = make(tmp_path, paths)
    r1 = b.snapshot("1d", 1)["revision"]
    r2 = b.snapshot("7d", 2)["revision"]
    r3 = b.snapshot("1d", 3)["revision"]      # 命中缓存
    assert r1 < r2 < r3


def test_cache_capacity(tmp_path, paths):
    write_ccswitch(paths, [])
    b = make(tmp_path, paths, capacity=2)
    for i, rng in enumerate(("1d", "7d", "30d", "all", "1d")):
        b.snapshot(rng, i + 1)
    assert b._service._cache.__len__() <= 2
    assert b.snapshot("7d", 9)["cache"]["capacity"] == 2


def test_export_has_revision_and_is_redacted(tmp_path, paths):
    write_ccswitch(paths, [])
    b = make(tmp_path, paths)
    out = b.export_json("7d")
    data = json.loads(open(out["path"], encoding="utf-8").read())
    assert data["revision"] == out["revision"]
    assert out["bytes"] > 0
    sample = redact({"url": "https://u:p@example.com/x?token=abc123",
                     "note": "Bearer sk-zzz", "keep": "https://example.com/path"})
    assert "token=" not in sample["url"] and "u:p@" not in sample["url"]
    assert "sk-zzz" not in sample["note"]
    assert sample["keep"] == "https://example.com/path"


def test_power_requires_confirmation(tmp_path, paths):
    fake = FakePower()
    b = make(tmp_path, paths, power=fake)
    assert b.power("shutdown")["ok"] is False
    assert fake.calls == []
    assert b.power("shutdown", True)["ok"] is True
    assert fake.calls == [("shutdown", 15)]
    assert b.power("rm -rf", True)["ok"] is False


def test_settings_clamp_and_persist(tmp_path, paths):
    store = SettingsStore(tmp_path / "s.json")
    store.save({"alpha": 0.5, "topmost": False, "range": "9d", "bogus": 1})
    got = store.load()
    assert got["alpha"] in (1.0, 0.96, 0.92, 0.86, 0.78)
    assert got["topmost"] is False
    assert got["range"] == "1d"
    assert "bogus" not in got

    b = make(tmp_path, paths)
    assert b.set_settings({"peek": False})["peek"] is False
    assert b.get_settings()["peek"] is False


def test_detail_unknown_source(tmp_path, paths):
    b = make(tmp_path, paths)
    assert b.detail("nope", "1d")["source"] is None
