"""布局切换事务：原生 resize 成功才落盘；非布局设置不重定位；透明策略分离。"""
import json

import pytest

from cchud_next.bridge import Bridge
from cchud_next.host import Host
from cchud_next.settings import SettingsStore, use_colorkey

from conftest import local_noon


class FakeOps:
    def __init__(self, fail_place: bool = False):
        self.calls: list[tuple] = []
        self.fail_place = fail_place
        self.hwnd = 0
        self._rect = (100, 50, 524, 380)

    def place(self, w, h, monitor=0, anchor="top-right", margin=16, keep_size=True):
        self.calls.append(("place", w, h, anchor))
        if self.fail_place:
            raise RuntimeError("place boom")
        return {"x": 0, "y": 0, "w": w, "h": h, "monitor": "m"}

    def set_alpha(self, a):
        self.calls.append(("alpha", a))
        return True

    def set_colorkey(self, c, a):
        self.calls.append(("colorkey", c, a))
        return True

    def set_round_region(self, w, h, r):
        self.calls.append(("region", w, h, r))
        return True

    def clear_region(self):
        self.calls.append(("clear-region",))
        return True

    def set_topmost(self, on):
        self.calls.append(("topmost", on))
        return True

    def rect(self):
        return self._rect

    def move(self, x, y, w, h):
        self.calls.append(("move", x, y, w, h))
        return {}

    def client_origin(self):
        return (0, 0)


class FakeWin:
    def __init__(self):
        self.js: list[str] = []

    def evaluate_js(self, s):
        self.js.append(s)
        return None


def make_host(layout="card", hollow=False, fail=False) -> Host:
    h = Host.__new__(Host)
    h.settings = {"alpha": 0.96, "topmost": True, "peek": True, "range": "1d",
                  "layout": layout, "theme": "dark", "hollow": hollow}
    h.status = {"layout": layout}
    h.ops = FakeOps(fail)
    h.window = FakeWin()
    h._card_pos = None
    h._write_status = lambda: None
    return h


@pytest.fixture(autouse=True)
def _dpi96(monkeypatch):
    monkeypatch.setenv("CC_HUD_FORCE_DPI", "96")
    monkeypatch.delenv("CC_HUD_SIZE", raising=False)
    monkeypatch.delenv("CC_HUD_SELFTEST", raising=False)


def test_card_to_insights_resizes_immediately():
    h = make_host("card")
    h.apply_settings({**h.settings, "layout": "insights"})
    assert ("place", 1180, 800, "center") in h.ops.calls
    assert h.settings["layout"] == "insights"
    assert h.status["layout"] == "insights"


def test_resize_failure_keeps_old_settings_and_status():
    h = make_host("card", fail=True)
    with pytest.raises(RuntimeError, match="窗口应用失败"):
        h.apply_settings({**h.settings, "layout": "insights"})
    assert h.settings["layout"] == "card"
    assert h.status["layout"] == "card"
    assert any(c[0] == "alpha" for c in h.ops.calls)     # 回滚恢复整窗效果


def test_range_change_does_not_reposition():
    h = make_host("card")
    h.apply_settings({**h.settings, "range": "7d"})
    assert not [c for c in h.ops.calls if c[0] == "place"]
    assert h.settings["range"] == "7d"


def test_large_layout_ignores_hollow_region():
    assert use_colorkey({"layout": "insights", "hollow": True}) is False
    assert use_colorkey({"layout": "card", "hollow": True}) is True
    h = make_host("insights", hollow=False)
    h.apply_settings({**h.settings, "hollow": True})
    assert not [c for c in h.ops.calls if c[0] in ("region", "colorkey")]
    assert h.status.get("hollow_mode") == "alpha"
    assert any(c[0] == "alpha" for c in h.ops.calls)


def test_card_hollow_uses_round_region():
    h = make_host("card", hollow=False)
    h.apply_settings({**h.settings, "hollow": True})
    assert [c for c in h.ops.calls if c[0] == "region"]
    assert h.status.get("hollow_mode") == "region"


def test_collapse_restores_saved_position():
    h = make_host("card")
    h.apply_settings({**h.settings, "layout": "insights"})
    h.apply_settings({**h.settings, "layout": "card"})
    assert ("move", 100, 50, 424, 330) in h.ops.calls


class Port:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def apply_settings(self, settings):
        self.calls.append(dict(settings))
        if self.fail:
            raise RuntimeError("native boom")


def make_bridge(tmp_path, paths, port):
    return Bridge(root=tmp_path, paths=paths, settings=SettingsStore(tmp_path / "s.json"),
                  power=object(), window=port, now_fn=lambda: local_noon())


def test_bridge_resize_failure_does_not_persist(tmp_path, paths):
    port = Port(fail=True)
    b = make_bridge(tmp_path, paths, port)
    with pytest.raises(RuntimeError):
        b.set_settings({"layout": "insights"})
    assert b._settings_store.load()["layout"] == "card"
    assert not (tmp_path / "s.json").exists() or json.loads(
        (tmp_path / "s.json").read_text(encoding="utf-8"))["layout"] == "card"


def test_bridge_persists_after_native_success(tmp_path, paths):
    port = Port()
    b = make_bridge(tmp_path, paths, port)
    out = b.set_settings({"layout": "insights"})
    assert out["layout"] == "insights"
    assert b._settings_store.load()["layout"] == "insights"
    assert port.calls[-1]["layout"] == "insights"
