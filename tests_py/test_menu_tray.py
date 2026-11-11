"""功能菜单与托盘语义：同一命令模型、左键单击只切一次、右键只弹菜单、托盘不可用不隐藏。"""
from __future__ import annotations

import json
import threading

import pytest

from cchud_next import menu as menu_mod
from cchud_next import tray as tray_mod

from hostfakes import OpsStub, StubWin, make_host, patch_win32

SETTINGS = {"alpha": 0.96, "topmost": True, "peek": True, "range": "7d",
            "layout": "insights", "theme": "dark", "hollow": False}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CC_HUD_FORCE_DPI", "96")
    monkeypatch.delenv("CC_HUD_SIZE", raising=False)


def _host(tmp_path, monkeypatch, settings=None):
    ops = OpsStub()
    patch_win32(monkeypatch, ops)
    h = make_host(tmp_path, ops=ops, window=StubWin())
    h.settings = dict(settings or SETTINGS)
    h.hidden = False
    h._write_status = lambda: None
    h.bridge = _FakeBridge(h)
    return h


class _FakeBridge:
    def __init__(self, host):
        self.host = host
        self.saved: list[dict] = []

    def set_settings(self, patch):
        self.saved.append(dict(patch))
        self.host.settings = {**self.host.settings, **patch}
        return dict(self.host.settings)

    def export_json(self, rng):
        return {"path": "cc-hud-usage-7d.json", "bytes": 12, "revision": 3, "range": rng}


# ── 命令模型 ─────────────────────────────────────────────
def test_menu_covers_required_commands_and_marks_current_state():
    items = menu_mod.build(SETTINGS, hidden=False, tray_ok=True)
    ids = {i["id"] for i in menu_mod.leaves(items)}
    required = {
        "panel.toggle", "action.refresh", "action.export", "action.open_settings",
        "setting.topmost", "setting.hollow", "app.quit",
        "view.card", "view.insights", "view.diagnostics", "view.settings",
        "range.1d", "range.7d", "range.30d", "range.all",
        "setting.alpha.100", "setting.theme.dark", "power.shutdown",
    }
    assert required <= ids

    checked = {i["id"] for i in menu_mod.leaves(items) if i["checked"]}
    assert {"view.insights", "range.7d", "setting.alpha.96", "setting.theme.dark"} <= checked
    assert "setting.topmost" in checked          # check 项按当前值显示

    powers = next(i for i in items if i["id"] == "submenu.power")
    assert powers["danger"] is True
    assert all(p["danger"] for p in powers["children"])


def test_menu_hides_dev_commands():
    ids = {i["id"] for i in menu_mod.walk(menu_mod.build(SETTINGS))}
    for dev in ("capture", "dpi", "place", "selftest"):
        assert not any(dev in i for i in ids), dev


def test_panel_toggle_disabled_when_tray_unavailable():
    items = menu_mod.build(SETTINGS, hidden=False, tray_ok=False)
    toggle = next(i for i in menu_mod.leaves(items) if i["id"] == "panel.toggle")
    assert toggle["enabled"] is False
    # 已隐藏时仍要能「显示主面板」
    again = menu_mod.build(SETTINGS, hidden=True, tray_ok=False)
    toggle2 = next(i for i in menu_mod.leaves(again) if i["id"] == "panel.toggle")
    assert toggle2["enabled"] is True
    assert toggle2["title"] == "显示主面板"


def test_patch_for_maps_ids_to_settings():
    assert menu_mod.patch_for("view.card") == {"layout": "card"}
    assert menu_mod.patch_for("range.all") == {"range": "all"}
    assert menu_mod.patch_for("setting.alpha.86") == {"alpha": 0.86}
    assert menu_mod.patch_for("setting.theme.light") == {"theme": "light"}
    assert menu_mod.patch_for("action.open_settings") == {"layout": "settings"}
    assert menu_mod.patch_for("panel.toggle") is None
    assert menu_mod.patch_for("capture") is None


# ── 分发：两处菜单同一条路径 ────────────────────────────────
def test_run_menu_view_range_and_settings_reuse_bridge(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)
    assert h.run_menu("view.card")["ok"] is True
    assert h.bridge.saved[-1] == {"layout": "card"}
    assert h.run_menu("range.30d")["ok"] is True
    assert h.bridge.saved[-1] == {"range": "30d"}
    assert h.run_menu("setting.alpha.86")["ok"] is True
    assert h.bridge.saved[-1] == {"alpha": 0.86}


def test_run_menu_check_item_toggles_once(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)          # topmost 当前 True
    h.run_menu("setting.topmost")
    assert h.bridge.saved[-1] == {"topmost": False}
    h.run_menu("setting.topmost")
    assert h.bridge.saved[-1] == {"topmost": True}


def test_run_menu_export_uses_existing_export_path(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)
    out = h.run_menu("action.export")
    assert out["ok"] is True
    assert out["range"] == "7d"
    assert out["result"]["revision"] == 3


def test_run_menu_rejects_unknown_and_dev_commands(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)
    assert h.run_menu("capture")["ok"] is False
    assert h.run_menu("dpi")["ok"] is False
    assert h.run_menu("nonsense")["ok"] is False


def test_run_menu_power_requires_confirmation(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)
    out = h.run_menu("power.shutdown")
    assert out["ok"] is True and out["needs_confirm"] is True
    assert out["power"] == "shutdown"


# ── 托盘语义 ─────────────────────────────────────────────
class _FakeTray:
    def __init__(self, picked=None):
        self.picked = picked
        self.popups = 0
        self.added = True
        self.hwnd = 99
        self.getrect_rc = 0

    def popup(self, items):
        self.popups += 1
        self.last_items = items
        return self.picked

    def set(self, on, tip):
        self.state = (on, tip)


def test_left_click_toggles_exactly_once(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)
    h.tray = _FakeTray()
    h._on_tray("toggle")
    assert h.hidden is True
    h._on_tray("toggle")
    assert h.hidden is False


def test_right_click_opens_menu_only_and_does_not_toggle(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)
    h.tray = _FakeTray(picked=None)
    h._on_tray("menu")
    assert h.hidden is False
    assert h.tray.popups == 1
    # 菜单树与 bridge.menu_model 同源（同一 build 函数）
    assert isinstance(h.tray.last_items, list)
    assert any(i["id"] == "panel.toggle" for i in menu_mod.walk(h.tray.last_items))


def test_tray_menu_pick_prefers_frontend_dispatch(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)
    h.tray = _FakeTray(picked="view.card")
    calls = []
    h.window.evaluate_js = lambda js: calls.append(js) or True
    h._on_tray("menu")
    assert calls and "__cchudTrayMenu" in calls[0] and "view.card" in calls[0]
    assert h.status["tray_menu_via"] == "frontend"
    assert h.bridge.saved == []               # 前端执行时宿主不再重复执行


def test_tray_menu_pick_falls_back_to_host_when_frontend_gone(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)

    def boom(_js):
        raise RuntimeError("webview gone")

    h.window.evaluate_js = boom
    h.tray = _FakeTray(picked="view.card")
    h._on_tray("menu")
    assert h.bridge.saved[-1] == {"layout": "card"}
    assert h.status["tray_menu_via"] == "host"


def test_click_debounce_suppresses_duplicate_shell_messages():
    # 一次物理单击会被 Shell 发成多条消息；同事件在窗口内只认第一条
    q = __import__("queue").Queue()
    t = tray_mod.Tray.__new__(tray_mod.Tray)
    t.q = q
    t._last = {}
    t.suppressed = 0
    assert t._accept("toggle") is True
    assert t._accept("toggle") is False
    assert t._accept("toggle") is False
    assert t.suppressed == 2
    assert t._accept("menu") is True           # 不同事件类型互不影响


def test_tray_struct_has_popup_and_quit_releases():
    assert hasattr(tray_mod.Tray, "popup")
    assert hasattr(tray_mod.Tray, "quit")


# ── 旧配置兼容 ───────────────────────────────────────────
def test_legacy_settings_with_peek_still_load(tmp_path):
    from cchud_next.settings import SettingsStore

    path = tmp_path / "hud-next-state.json"
    path.write_text(json.dumps({"alpha": 0.86, "topmost": False, "peek": True,
                                "range": "30d", "layout": "insights",
                                "theme": "light", "hollow": True}), encoding="utf-8")
    got = SettingsStore(path).load()
    assert got["layout"] == "insights"
    assert got["peek"] is True                 # 键仍可读，但 UI 已不再提供
    assert got["hollow"] is True


def test_defaults_keep_peek_key_for_backwards_compat():
    from cchud_next.settings import DEFAULTS, validate

    assert "peek" in DEFAULTS
    assert validate({"peek": False})["peek"] is False
