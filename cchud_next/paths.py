"""本地数据源路径。测试通过 Paths(home=...) 指向夹具目录，不碰真实用户数据。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_home() -> Path:
    return Path(os.environ.get("CC_HUD_HOME") or Path.home())


@dataclass(frozen=True)
class Paths:
    home: Path

    @classmethod
    def default(cls) -> "Paths":
        return cls(_env_home())

    # CC Switch 代理日志（基准路）
    @property
    def ccswitch_db(self) -> Path:
        return self.home / ".cc-switch" / "cc-switch.db"

    # Qoder 国际版 / 国内版
    @property
    def qoder_dir(self) -> Path:
        return self.home / ".qoder" / "projects"

    @property
    def qoder_cn_dir(self) -> Path:
        return self.home / ".qoder-cn" / "projects"

    @property
    def zcode_db(self) -> Path:
        return self.home / ".zcode" / "cli" / "db" / "db.sqlite"

    @property
    def herdsman_log(self) -> Path:
        return self.home / ".herdsman" / "model_stats" / "events.jsonl"

    @property
    def codex_dirs(self) -> list[Path]:
        return [self.home / ".codex" / "sessions", self.home / ".codex" / "archived_sessions"]

    @property
    def workbuddy_sources(self) -> list[tuple[Path, str, bool]]:
        return [
            (self.home / ".workbuddy" / "projects", "workbuddy", True),
            (self.home / ".workbuddy-ai" / "projects", "workbuddy_ai", False),
        ]

    @property
    def dsh_projcache(self) -> Path:
        return self.home / ".dsh" / "storages" / "session_projcache" / "sessions"

    @property
    def dsh_sessions(self) -> Path:
        return self.home / ".dsh" / "sessions"

    def cchaha_candidates(self) -> list[Path]:
        """cc-haha 配置目录会整机搬家：取索引库 mtime 最新的候选。"""
        cands: list[Path] = []
        env = os.environ.get("CLAUDE_CONFIG_DIR")
        if env:
            cands.append(Path(env))
        cands.append(self.home / ".claude")
        for drive in _fixed_drives():
            cands.append(Path(drive) / "cc-haha")
        return cands


def _fixed_drives() -> list[str]:
    """只数本地固定盘；映射盘/空光驱 isdir 可能阻塞界面线程。"""
    try:
        import ctypes

        k = ctypes.windll.kernel32
        mask = k.GetLogicalDrives()
        out = []
        for i in range(26):
            if mask & (1 << i):
                root = "%s:\\" % chr(65 + i)
                if k.GetDriveTypeW(root) == 3:
                    out.append(root)
        return out
    except Exception:
        return []


def cchaha_index_and_projects(paths: Paths) -> tuple[Path | None, Path | None]:
    best: tuple[float, Path] | None = None
    for root in paths.cchaha_candidates():
        idx = root / "cc-haha" / "db" / "index-v1.sqlite"
        try:
            m = idx.stat().st_mtime
        except OSError:
            continue
        if best is None or m > best[0]:
            best = (m, root)
    if best is None:
        return None, None
    root = best[1]
    return root / "cc-haha" / "db" / "index-v1.sqlite", root / "projects"
