"""适配器协议与公共工具。"""
from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

from ..model import SourceSnapshot


def local_date(epoch: float) -> str:
    return dt.date.fromtimestamp(epoch).isoformat()


def local_hour(epoch: float) -> int:
    return time.localtime(epoch).tm_hour


def walk_jsonl(root: Path):
    if not root.is_dir():
        return
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            if fn.endswith(".jsonl"):
                yield Path(dirpath) / fn


def sid_from_transcript(path: Path) -> str:
    """子代理在 <父会话>/subagents/agent-x.jsonl 下，归属父会话。"""
    q = str(path).replace(os.sep, "/").rstrip("/")
    if "/subagents/" in q:
        return q.rsplit("/", 2)[-3].rsplit("/", 1)[-1]
    return q.rsplit("/", 1)[-1][:-6]


def new_snapshot(key: str, name: str, **kwargs) -> SourceSnapshot:
    return SourceSnapshot(key=key, name=name, **kwargs)
