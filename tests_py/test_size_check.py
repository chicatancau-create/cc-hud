"""尺寸生效校验：SetWindowPos 的返回值与回读矩形都要进结果，宿主侧据此记账/熔断。"""
import ctypes
from ctypes import wintypes as wt

import pytest

from cchud_next import win32 as win32_mod
from cchud_next.win32 import WindowOps

from hostfakes import OpsStub, make_host, patch_win32


class FakeUser32:
    """只实现 place() 用到的两个 API；GetWindowRect 把矩形写回 byref(RECT)。"""

    def __init__(self, rect, ok=True, after=None):
        self.rect = rect
        self.ok = ok
        self.after = after
        self.calls: list[tuple] = []

    def GetWindowRect(self, hwnd, ref):
        target = ctypes.cast(ref, ctypes.POINTER(wt.RECT)).contents
        target.left, target.top, target.right, target.bottom = self.rect
        return 1

    def SetWindowPos(self, hwnd, insert_after, x, y, w, h, flags):
        self.calls.append((int(x), int(y), int(w), int(h), int(flags)))
        if self.ok and self.after is not None:
            self.rect = self.after
        return 1 if self.ok else 0


def _ops(monkeypatch, fake) -> WindowOps:
    monkeypatch.setattr(win32_mod, "user32", fake)
    monkeypatch.setattr(win32_mod, "monitors",
                        lambda: [{"work": (0, 0, 800, 600), "device": "M"}])
    monkeypatch.setattr(win32_mod, "work_area", lambda hwnd=0: (0, 0, 800, 600))
    return WindowOps(1234)


def test_place_reports_setwindowpos_failure(monkeypatch):
    fake = FakeUser32(rect=(10, 10, 410, 310), ok=False)
    ops = _ops(monkeypatch, fake)
    res = ops.place(424, 330, 0, "top-right", 16, keep_size=False)

    assert res["ok"] is False
    assert res["requested"] == [424, 330]
    assert (res["w"], res["h"]) == (400, 300)      # 回读的真实值，不是请求值
    assert (res["x"], res["y"]) == (10, 10)
    assert "err" in res


def test_place_reports_clamped_size_not_requested(monkeypatch):
    # WinForms 按 Min/Max 夹取：请求 900x500，实际只有 400x300
    fake = FakeUser32(rect=(10, 10, 410, 310), ok=True, after=(0, 0, 400, 300))
    ops = _ops(monkeypatch, fake)
    res = ops.place(900, 500, 0, "top-right", 16, keep_size=False)

    assert res["ok"] is True and res["read_ok"] is True
    assert (res["w"], res["h"]) == (400, 300)
    assert (res["w"], res["h"]) != tuple(res["requested"])


@pytest.fixture()
def _env(monkeypatch):
    monkeypatch.setenv("CC_HUD_FORCE_DPI", "96")
    monkeypatch.delenv("CC_HUD_SIZE", raising=False)


def _host(tmp_path, monkeypatch, ops):
    patch_win32(monkeypatch, ops)
    return make_host(tmp_path, ops=ops)


def test_layout_size_drift_is_recorded_not_raised(tmp_path, monkeypatch, _env):
    # 请求成功但被框架夹到 400x300：旧实现直接 raise，把一次可纠正的漂移判成致命
    ops = OpsStub(place_result={"x": 0, "y": 0, "w": 400, "h": 300, "ok": True})
    h = _host(tmp_path, monkeypatch, ops)
    guards: list[tuple] = []
    h._start_rect_guard = lambda target, ticks=40: guards.append(target)

    h._apply_layout_size(h.settings)                # 不抛

    assert h.status["size_mismatch"]["requested"] == [424, 330]
    assert h.status["size_mismatch"]["actual"] == [400, 300]
    assert guards[-1][2:] == (424, 330)             # 守卫目标仍是请求值


def test_layout_size_setwindowpos_failure_raises(tmp_path, monkeypatch, _env):
    ops = OpsStub(place_result={"x": 0, "y": 0, "w": 424, "h": 330, "ok": False, "err": 5})
    h = _host(tmp_path, monkeypatch, ops)
    guards: list[tuple] = []
    h._start_rect_guard = lambda target, ticks=40: guards.append(target)

    with pytest.raises(RuntimeError, match="SetWindowPos 失败"):
        h._apply_layout_size(h.settings)
    assert guards == []                             # 没搬动就不该起矩形守卫


def test_layout_size_match_clears_previous_mismatch(tmp_path, monkeypatch, _env):
    ops = OpsStub()
    h = _host(tmp_path, monkeypatch, ops)
    h.status["size_mismatch"] = {"requested": [1, 1], "actual": [2, 2], "at": 0.0}

    h._apply_layout_size(h.settings)

    assert "size_mismatch" not in h.status
