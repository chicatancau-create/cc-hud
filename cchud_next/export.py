"""导出：带 revision、脱敏 URL 与 secret。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_SECRET = re.compile(r"(?i)(bearer\s+|api[_-]?key\s*[=:]\s*|token\s*[=:]\s*)[^\s,;]+")
_SECRET_KEY = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|cookie)")
_URL = re.compile(r"https?://[^\s)\"']+")


def redact_url(u: str) -> str:
    try:
        p = urlsplit(str(u))
        if not p.netloc:
            return str(u)
        netloc = p.hostname or ""
        if p.port:
            netloc += f":{p.port}"
        return urlunsplit((p.scheme, netloc, p.path, "", ""))
    except Exception:
        return "<REDACTED_URL>"


def redact(value, key: str = ""):
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, key) for v in value]
    if key and _SECRET_KEY.search(str(key)):
        return "<REDACTED>"
    if isinstance(value, str):
        value = _URL.sub(lambda m: redact_url(m.group(0)), value)
        return _SECRET.sub(r"\1<REDACTED>", value)
    return value


def write_export(payload: dict, path: Path) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = redact(payload)
    text = json.dumps(clean, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return {"path": str(path), "bytes": len(text.encode("utf-8")),
            "revision": payload.get("revision")}
