"""最终验收编排：跑完全部门禁并给出唯一结论。

标准未满足时退出码 1；双屏/系统缩放不满足时标记 blocked，不伪造通过。
用法：
    python tools/final_acceptance.py
    CC_HUD_EXPECT_DPI=96 python tools/final_acceptance.py   # 期望系统缩放 100%
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
OUT = ROOT / "artifacts" / "final-acceptance.json"


def run(name: str, argv: list[str], cwd: Path, timeout: int = 900) -> dict:
    started = time.time()
    if not argv[0].lower().endswith(".exe"):
        argv = ["cmd", "/c", *argv]
    proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    return {
        "name": name,
        "rc": proc.returncode,
        "seconds": round(time.time() - started, 1),
        "tail": "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-6:]),
    }


def host_running() -> bool:
    # 标题 "cc-hud" 会命中 explorer 的 TabProxyWindow，不能用 FindWindow；查单实例互斥体。
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.OpenMutexW.restype = ctypes.c_void_p
    h = k32.OpenMutexW(0x00100000, False, r"Local\cc-hud-single")
    if h:
        k32.CloseHandle(ctypes.c_void_p(h))
        return True
    return False


def main() -> int:
    if host_running():
        out = {"ok": False,
               "blocked": ["hud_running: quit the running HUD before final acceptance"],
               "hint": "验收工具会自起 HUD；单实例闸门下必须先退出正在运行的实例"}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False))
        return 2
    gates: list[dict] = []
    gates.append(run("pytest", [PY, "-m", "pytest", "tests_py", "-q"], ROOT))
    gates.append(run("reconcile", [PY, "tools/reconcile.py"], ROOT))
    web = ROOT / "web"
    for name, cmd in (("lint", ["npm", "run", "lint"]),
                      ("typecheck", ["npm", "run", "typecheck"]),
                      ("vitest", ["npm", "test"]),
                      ("build", ["npm", "run", "build"]),
                      ("playwright", ["npx", "playwright", "test"])):
        gates.append(run(name, cmd, web))

    shots = (
        ("verify_card", ["--layout", "card", "--wait", "30", "--shot", "ACCEPT-card"]),
        ("verify_insights", ["--layout", "insights", "--wait", "30", "--shot", "ACCEPT-insights"]),
        ("verify_diagnostics", ["--layout", "diagnostics", "--wait", "30", "--shot", "ACCEPT-diagnostics"]),
        ("verify_settings", ["--layout", "settings", "--wait", "30", "--shot", "ACCEPT-settings"]),
        ("verify_peek", ["--layout", "card", "--hidden", "--wait", "12", "--shot", "ACCEPT-peek"]),
        ("verify_hollow", ["--layout", "card", "--hollow", "--wait", "30", "--shot", "ACCEPT-hollow"]),
        ("verify_export", ["--layout", "card", "--selftest", "export", "--wait", "40", "--shot", "ACCEPT-export"]),
        ("verify_power", ["--layout", "card", "--selftest", "power", "--wait", "30", "--shot", "ACCEPT-power"]),
    )
    for name, args in shots:
        g = run(name, [PY, "tools/verify_windows.py", *args], ROOT, timeout=180)
        if g["rc"] != 0:                      # 连续起窗偶发时序抖动，重试一次仍须通过
            g2 = run(name + "_retry", [PY, "tools/verify_windows.py", *args], ROOT, timeout=180)
            g = {**g2, "first_attempt_rc": g["rc"], "first_tail": g["tail"]}
        gates.append(g)
    gates.append(run("tray_pixel", [PY, "tools/tray_pixel.py"], ROOT, timeout=180))
    gates.append(run("tray_click", [PY, "tools/tray_click.py"], ROOT, timeout=180))
    gates.append(run("settings_persist", [PY, "tools/verify_settings_persist.py"], ROOT, timeout=180))

    sys.path.insert(0, str(ROOT))
    from cchud_next.win32 import monitors  # noqa: E402

    mons = monitors()
    blocked: list[str] = []
    if len(mons) < 2:
        blocked.append(f"multi_monitor: only {len(mons)} display(s)")

    expect = os.environ.get("CC_HUD_EXPECT_DPI")
    if expect:
        data = {}
        try:
            data = json.loads((ROOT / "artifacts" / "runtime.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        actual = int(data.get("dpi") or 0)
        if actual != int(expect):
            blocked.append(f"system_dpi: expected {expect}, got {actual}")

    failed = [g["name"] for g in gates if g["rc"] != 0]
    ok = not failed and not blocked
    result = {
        "ok": ok,
        "blocked": blocked,
        "failed_gates": failed,
        "monitors": [m.get("device") for m in mons],
        "expect_dpi": expect,
        "gates": gates,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("ok", "blocked", "failed_gates", "monitors")},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
