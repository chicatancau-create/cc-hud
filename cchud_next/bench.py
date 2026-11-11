"""启动耗时打点：进程内单调时钟，只记录相对毫秒，不参与任何业务判断。"""
from __future__ import annotations

import time

T0 = time.perf_counter()
_marks: dict[str, float] = {}


def mark(name: str) -> float:
    ms = round((time.perf_counter() - T0) * 1000.0, 1)
    _marks[name] = ms
    return ms


def note(name: str, ms: float) -> None:
    """记录外部（前端 performance.now）上报的耗时；只放不覆盖已有更早的同名点。"""
    _marks.setdefault(name, round(float(ms), 1))


def marks() -> dict[str, float]:
    return dict(_marks)
