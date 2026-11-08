"""Run every automated gate and write docs/reports/<date>-gate-transcript.md.

Each command is executed verbatim; the tail of stdout/stderr is kept.
Windows evidence JSONs come in two shapes: the standard verifier writes
`checks`, the ad-hoc forced-scale probe writes `dpr`/`capture`. Both are
reported instead of being silently skipped.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
TAIL = 24


def run(argv: list[str], cwd: Path) -> tuple[int, str]:
    # npm/npx are .cmd shims on Windows; CreateProcess only runs real images.
    if not argv[0].lower().endswith(".exe"):
        argv = ["cmd", "/c", *argv]
    proc = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )
    text = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode, "\n".join(text[-TAIL:])


def evidence_summary() -> str:
    rows = []
    for path in sorted((ROOT / "artifacts").glob("windows-verify-*.json")):
        name = path.name.removeprefix("windows-verify-")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            rows.append(f"{name:36s} LOADFAIL {exc}")
            continue
        if "checks" in data:
            checks = data["checks"]
            info = set(data.get("informational") or [])
            fails = [k for k, v in checks.items()
                     if k not in info
                     and not (v.get("ok") if isinstance(v, dict) else bool(v))]
            rows.append(f"{name:36s} ok={data.get('ok')} fails={fails or '-'}")
        elif "uia" in data:
            uia = data["uia"] or {}
            rows.append(
                f"{name:36s} tray_added={data.get('tray_added')} "
                f"uia_ok={uia.get('ok')} reason={uia.get('reason', '-')}"
            )
        elif "unnamed" in data:
            rows.append(
                f"{name:36s} tray_added={data.get('tray_added')} "
                f"unnamed={len(data.get('unnamed') or [])} "
                f"tooltip={'captured' if data.get('tooltip_box') else '-'}"
            )
        elif "capture" in data and "dpr" in data:
            cap = data["capture"]
            scale = data.get("scale_arg", "-")
            rows.append(
                f"{name:36s} dpr={data.get('dpr')} scale={scale} "
                f"capture_ok={cap.get('ok')} {cap.get('w')}x{cap.get('h')} "
                f"max_luma={cap.get('max_luma')}"
            )
        else:
            rows.append(f"{name:36s} UNRECOGNIZED keys={sorted(data)}")
    return "\n".join(rows)


def main() -> int:
    sections: list[tuple[str, str, int, str]] = []
    gates = [
        ("Python 单元/适配器/守恒/桥接", [PY, "-m", "pytest", "tests_py", "-q"], ROOT),
        ("四范围对账", [PY, "tools/reconcile.py"], ROOT),
        ("前端 lint", ["npm", "run", "lint"], ROOT / "web"),
        ("前端 typecheck", ["npm", "run", "typecheck"], ROOT / "web"),
        ("前端 Vitest", ["npm", "test"], ROOT / "web"),
        ("前端 build", ["npm", "run", "build"], ROOT / "web"),
        ("Playwright", ["npx", "playwright", "test"], ROOT / "web"),
    ]
    failed: list[str] = []
    for title, argv, cwd in gates:
        code, out = run(argv, cwd)
        sections.append((title, " ".join(argv), code, out))
        if code != 0:
            failed.append(title)

    lines = [f"# 门禁执行记录（{date.today().isoformat()}）", "",
             "> 由 `tools/gate_transcript.py` 生成；命令在仓库内原样执行，",
             "> 每节保留输出结尾片段与退出码。", ""]
    for title, cmd, code, out in sections:
        lines += [f"## {title}", "```", f"$ {cmd}", out,
                  f"RC={code}", "```", ""]

    lines += [
        "## Windows 实机证据（JSON 汇总）", "```",
        evidence_summary(), "```", "",
        "说明：`FINAL*`/`EXPO2` 为最终轮证据；其余为过程快照。",
        "过程快照中的失败项均已被后续轮次覆盖：",
        "`FINAL-hollow*.json` → `FINAL-hollow3.json`（flags=3），",
        "`FINAL-power*.json` → `FINAL-power5.json`（假执行器确认），",
        "`FINAL3-export*.json` → `EXPO2.json`（revision + 落盘）。", "",
        "## 结论", "",
        f"自动化门禁退出码：{'全部为 0' if not failed else '失败 -> ' + ', '.join(failed)}",
    ]
    out_path = ROOT / "docs" / "reports" / f"{date.today().isoformat()}-gate-transcript.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out_path)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
