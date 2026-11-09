"""设置持久化：校验、夹取、原子写。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .ranges import RANGES

ALPHAS = (1.0, 0.96, 0.92, 0.86, 0.78)
DEFAULTS = {
    "alpha": 0.96,
    "topmost": True,
    "peek": True,
    "range": "1d",
    "layout": "card",
    "theme": "dark",
    "hollow": False,
}
BOOL_KEYS = ("topmost", "peek", "hollow")
LAYOUTS = ("card", "insights", "diagnostics", "settings")
LAYOUT_SIZES = {
    "card": (424, 330),
    "insights": (1180, 800),
    "diagnostics": (1080, 760),
    "settings": (760, 640),
}


def use_colorkey(settings: dict | None) -> bool:
    """小卡局部镂空；大面板一律整窗 alpha。"""
    s = settings or {}
    return s.get("layout") == "card" and bool(s.get("hollow"))


def validate(raw: dict | None) -> dict:
    out = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for k in DEFAULTS:
        if k not in raw:
            continue
        v = raw[k]
        if k in BOOL_KEYS:
            out[k] = bool(v)
        elif k == "alpha":
            try:
                a = float(v)
            except (TypeError, ValueError):
                continue
            out[k] = min(ALPHAS, key=lambda x: abs(x - a))
        elif k == "range":
            if v in RANGES:
                out[k] = v
        elif k == "layout":
            if v in LAYOUTS:
                out[k] = v
        elif k == "theme":
            if v in ("dark", "light"):
                out[k] = v
    return out


class SettingsStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return dict(DEFAULTS)
        return validate(raw)

    def save(self, data: dict) -> dict:
        clean = validate(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(clean, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return clean

    def update(self, patch: dict) -> dict:
        cur = self.load()
        if isinstance(patch, dict):
            cur.update({k: v for k, v in patch.items() if k in DEFAULTS})
        return self.save(cur)
