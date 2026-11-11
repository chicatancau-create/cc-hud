"""宿主分步建立：外观步骤失败只记它自己，不拖垮 ready/托盘；只有拿不到 HWND 才轮询重试。

桌面小圆点（cc-hud-dot 第二窗口）已删除，这里同时守「不再出现 dot」的约束。
"""
import pytest

from cchud_next import host as host_mod

from hostfakes import (FlakyNativeWin, OpsStub, StubWin, join_retries, make_host,
                       patch_win32)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CC_HUD_FORCE_DPI", "96")
    monkeypatch.delenv("CC_HUD_SIZE", raising=False)
    monkeypatch.delenv("CC_HUD_START_HIDDEN", raising=False)
    monkeypatch.delenv("CC_HUD_SELFTEST", raising=False)


def _host(tmp_path, monkeypatch, ops=None, window=None):
    ops = ops if ops is not None else OpsStub()
    win = window if window is not None else StubWin()
    patch_win32(monkeypatch, ops)
    return make_host(tmp_path, ops=ops, window=win)


def test_topmost_failure_keeps_host_ready_and_runs_tray(tmp_path, monkeypatch):
    # 审计现场：set_topmost 返回 0 —— 旧实现把整个宿主判死（ready/tray 全没了）
    ops = OpsStub(topmost_fail_times=99)
    h = _host(tmp_path, monkeypatch, ops=ops)
    h._ensure_window_ready()
    join_retries(h)

    assert h.status["host_ready"] is True
    assert h.status["ready"] is True
    assert h._initialized is True
    assert "置顶设置失败" in h.status["step_errors"]["window_apply"]
    assert h.status["tray_added"] is True
    assert h.status["hwnd"] == 4242


def test_host_never_creates_dot_window(tmp_path, monkeypatch):
    # 只允许主窗口：没有 self.dot，也没有 dot 启动步骤/状态键
    ops = OpsStub()
    h = _host(tmp_path, monkeypatch, ops=ops)
    assert not hasattr(h, "dot")
    assert not hasattr(h, "_place_dot")
    h._ensure_window_ready()
    join_retries(h)
    assert h.status["host_ready"] is True
    for key in ("dot_created", "dot_placed", "dot_hwnd", "peek_visible"):
        assert key not in h.status


def test_show_hide_never_touch_dot(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)
    h.tray = None
    h.hidden = False
    h._write_status = lambda: None

    # 任何对已删属性 dot 的访问都会 AttributeError，这里验「调用链里根本没有它」
    h.hide()
    h.show()
    assert h.hidden is False
    assert not hasattr(h, "dot")


def test_hide_refused_when_tray_unavailable(tmp_path, monkeypatch):
    # 托盘建不起来时不允许把面板藏走：保持可见 + 给出可见错误
    h = _host(tmp_path, monkeypatch)
    h.tray = None
    h.hidden = False
    h._write_status = lambda: None
    h.hide()
    assert h.hidden is False
    assert "托盘不可用" in h.status["last_error"]
    assert h.status["hide_blocked"]


def test_only_window_apply_step_is_retried(tmp_path, monkeypatch):
    # 托盘重复创建会多出一个图标，绝不能进重试队列
    ops = OpsStub(topmost_fail_times=99)
    h = _host(tmp_path, monkeypatch, ops=ops)
    h._ensure_window_ready()
    assert set(h._retry_threads) == {"window_apply"}
    join_retries(h)


def test_window_apply_retry_recovers_error(tmp_path, monkeypatch):
    ops = OpsStub(topmost_fail_times=1)     # 第一次失败（含回滚那一次之后就能成功）
    h = _host(tmp_path, monkeypatch, ops=ops)
    h._ensure_window_ready()
    join_retries(h, timeout=5.0)

    assert "window_apply" not in h.status.get("step_errors", {})
    assert "置顶设置失败" in h.status["step_recovered"]["window_apply"]


def test_hwnd_failure_is_retryable(tmp_path, monkeypatch):
    win = FlakyNativeWin()
    h = _host(tmp_path, monkeypatch, window=win)

    h._ensure_window_ready()
    assert h._initialized is False
    assert h._init_started is False          # 允许下一次（轮询线程）再试
    assert h.status["last_error"].startswith("hwnd:")
    assert "host_ready" not in h.status

    win.fail = False
    h._ensure_window_ready()
    assert h._initialized is True
    assert h.status["ready"] is True


def test_wait_hwnd_keeps_polling_until_host_ready(tmp_path, monkeypatch):
    h = _host(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_ensure():
        calls["n"] += 1
        if calls["n"] >= 2:                  # 第一次没建成宿主，第二次才成
            h._initialized = True

    h._ensure_window_ready = fake_ensure
    monkeypatch.setattr(host_mod.time, "sleep", lambda _seconds: None)
    h._wait_hwnd()

    assert calls["n"] >= 2                   # 旧实现调一次就 return
    assert h.status.get("last_error") != "hwnd wait timeout"


def test_place_command_keeps_ok_contract_and_exposes_place_ok(tmp_path, monkeypatch):
    # bridge 契约里 command("place") 的 ok 是「已受理」；真实 SetWindowPos 结果另开键
    ops = OpsStub(place_result={"x": 0, "y": 0, "w": 424, "h": 330, "ok": False, "err": 5})
    h = _host(tmp_path, monkeypatch, ops=ops)
    out = h.command("place", 1)
    assert out["ok"] is True
    assert out["place_ok"] is False
    assert out["err"] == 5
