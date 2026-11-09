"""桥接层：pywebview js_api 的实现。不启动服务、不监听端口。"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Protocol

from . import __version__
from .accounting import collect, merge, overall_status
from .export import write_export
from .paths import Paths
from .ranges import RANGE_LABELS, RANGES, start_date
from .settings import SettingsStore, validate

SOURCE_META = [
    ("ccswitch", "CC Switch", "proxy"),
    ("cchaha", "cc-haha", "session"),
    ("qoder", "Qoder", "session"),
    ("qoder_cn", "Qoder CN", "session"),
    ("zcode", "ZCode", "session"),
    ("herdsman", "牧羊人", "local"),
    ("codex", "Codex 未回填", "session"),
    ("workbuddy", "WorkBuddy 国内", "session"),
    ("workbuddy_ai", "WorkBuddy 国外", "session"),
    ("dsh", "DSH", "session"),
    ("dsh_v4", "DSH V4", "session"),
]

POWER_ACTIONS = ("sleep", "hibernate", "shutdown", "restart", "logoff", "lock")


class PowerPort(Protocol):
    def run(self, action: str, delay: int = 15) -> dict: ...
    def cancel(self) -> dict: ...


class SystemPower:
    """真实电源动作；只有 confirmed=True 才会走到这里。"""

    def run(self, action: str, delay: int = 15) -> dict:
        if action == "lock":
            cmd = ["rundll32.exe", "user32.dll,LockWorkStation"]
            delay = 0
        elif action == "sleep":
            cmd = ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
            delay = 0
        elif action == "hibernate":
            cmd = ["shutdown", "/h"]
            delay = 0
        elif action == "shutdown":
            cmd = ["shutdown", "/s", "/t", str(delay)]
        elif action == "restart":
            cmd = ["shutdown", "/r", "/t", str(delay)]
        elif action == "logoff":
            cmd = ["shutdown", "/l"]
            delay = 0
        else:
            return {"ok": False, "reason": f"未知电源动作: {action}"}
        subprocess.run(cmd, check=False)
        return {"ok": True, "scheduled": delay > 0, "action": action, "delay": delay}

    def cancel(self) -> dict:
        subprocess.run(["shutdown", "/a"], check=False)
        return {"ok": True, "action": "cancel"}


class _Service:
    def __init__(self, paths: Paths, ttl: float, capacity: int, now_fn):
        self.paths = paths
        self.ttl = ttl
        self.capacity = capacity
        self.now_fn = now_fn
        self.revision = 0
        self.last_seq = 0
        self.hits = 0
        self.misses = 0
        self._cache: OrderedDict[str, tuple[float, int, dict]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, rng: str, seq: int = 0) -> dict:
        if rng not in RANGES:
            raise ValueError(f"unknown range: {rng}")
        with self._lock:
            if seq and seq < self.last_seq:
                return {"stale": True, "seq": seq, "revision": self.revision, "range": rng}
            self.last_seq = max(self.last_seq, int(seq or 0))
            now = self.now_fn()
            got = self._cache.get(rng)
            if got and now - got[0] < self.ttl:
                self.hits += 1
                self._cache.move_to_end(rng)
                payload = dict(got[2])
                self.revision += 1      # 命中缓存也是一次新响应，revision 不得回退
            else:
                self.misses += 1
                sources = collect(self.paths, rng, now)
                agg = merge(sources, rng, now)
                self.revision += 1
                payload = {
                    "schema": 1,
                    "revision": self.revision,
                    "range": rng,
                    "generated_at": now,
                    "status": overall_status(sources),
                    "totals": agg["totals"],
                    "kpis": agg["kpis"],
                    "daily": agg["daily"],
                    "hourly": agg["hourly"],
                    "models": agg["models"],
                    "timing": agg["timing"],
                    "tools": agg["tools"],
                    "session_rows": agg["session_rows"],
                    "session_total": agg["session_total"],
                    "apps": agg["apps"],
                    "sources": [s.to_dict() for s in sources],
                    "conservation": agg["conservation"],
                    "start_date": agg["start_date"],
                }
                self._cache[rng] = (now, self.revision, payload)
                while len(self._cache) > self.capacity:
                    self._cache.popitem(last=False)
            out = dict(payload)          # 缓存里存的是原始快照，回包不能改它
            out["revision"] = self.revision
            out["seq"] = int(seq or 0)
            out["cache"] = {"hits": self.hits, "misses": self.misses,
                            "entries": len(self._cache), "capacity": self.capacity}
            return out


class Bridge:
    def __init__(self, root: Path | None = None, paths: Paths | None = None,
                 settings: SettingsStore | None = None, power: PowerPort | None = None,
                 window: Any = None, now_fn=time.time, ttl: float = 15.0,
                 capacity: int = 8, dpi: Any = None, settings_provider=None):
        self._root = Path(root) if root else Path(__file__).resolve().parents[1]
        self._paths = paths or Paths.default()
        self._settings_store = settings or SettingsStore(self._root / "hud-next-state.json")
        self._settings_provider = settings_provider
        self._power_port = power or SystemPower()
        self._window_port = window
        self.dpi = dpi
        self._service = _Service(self._paths, ttl, capacity, now_fn)

    # --- 数据 ---
    def bootstrap(self) -> dict:
        return {
            "version": __version__,
            "ranges": [{"key": r, "label": RANGE_LABELS[r]} for r in RANGES],
            "settings": self.get_settings(),
            "sources_meta": [{"key": k, "name": n, "kind": kd} for k, n, kd in SOURCE_META],
            "dpi": self.dpi,
            "platform": "windows",
            "fake_power": not isinstance(self._power_port, SystemPower),
            "start_date": start_date("1d"),
            "selftest_layout": os.environ.get("CC_HUD_SELFTEST") == "layout",
        }

    def snapshot(self, rng: str = "1d", seq: int = 0) -> dict:
        return self._service.get(rng, int(seq or 0))

    def detail(self, source_key: str, rng: str = "1d") -> dict:
        sources = collect(self._paths, rng, self._service.now_fn())
        for s in sources:
            if s.key == source_key:
                return {"source": s.to_dict(), "range": rng}
        return {"source": None, "range": rng, "reason": "未知来源"}

    # --- 设置 ---
    def get_settings(self) -> dict:
        if self._settings_provider is not None:
            return dict(self._settings_provider())
        return self._settings_store.load()

    def set_settings(self, patch: dict | None = None) -> dict:
        """原生应用成功后才落盘；落盘失败则把窗口回滚到旧设置再向上抛。

        旧实现先 apply 再 save，save 一抛异常就是「内存/窗口/磁盘」三方分叉：
        窗口已是新设置、磁盘还是旧设置，而调用方只看到异常。"""
        old = self.get_settings()
        candidate = validate({**old, **(patch or {})})
        if self._window_port is not None:
            self._window_port.apply_settings(candidate)   # 失败必须向上抛，禁止吞掉
        try:
            return self._settings_store.save(candidate)
        except Exception as exc:
            if self._window_port is None:
                raise
            try:
                self._window_port.apply_settings(old)
            except Exception as rollback_exc:
                raise RuntimeError(
                    f"设置落盘失败，且窗口回滚也失败：save={exc!r} "
                    f"rollback={rollback_exc!r}") from exc
            raise

    # --- 导出 ---
    def export_json(self, rng: str = "1d") -> dict:
        payload = self._service.get(rng, 0)
        path = self._root / f"cc-hud-usage-{rng}.json"
        return write_export(payload, path)

    # --- 电源 ---
    def power(self, action: str, confirmed: bool = False) -> dict:
        if action not in POWER_ACTIONS:
            return {"ok": False, "reason": f"未知电源动作: {action}"}
        if confirmed is not True:
            return {"ok": False, "reason": "需要二次确认", "action": action}
        return self._power_port.run(action, 15)

    def cancel_power(self) -> dict:
        return self._power_port.cancel()

    # --- 窗口 ---
    def window(self, action: str, value: Any = None) -> dict:
        if self._window_port is None:
            return {"ok": False, "reason": "无窗口宿主（浏览器预览）"}
        return self._window_port.command(action, value)
