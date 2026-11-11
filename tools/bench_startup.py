"""启动耗时实测：冷/热各多轮，取中位数；同时读 Host 打点与常驻内存。

测量口径（写进报告）：
- 冷启动：每轮先结束所有 HUD 进程，再删除指定 profile 目录，测量
  「Popen -> runtime.json 里 ready=true」的墙钟时间。
- 热启动：复用同一 profile 目录（WebView2 已有缓存），同样测 Popen -> ready。
- ready 内部拆分来自 cchud_next.bench 的打点（webview_import / host_ready / bench）。
- 常驻内存：ready 后等待 settle 秒，读进程 PrivateMemorySize64。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_W = ROOT / ".venv" / "Scripts" / "pythonw.exe"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
OUT = ROOT / "artifacts" / "startup-bench.json"
RUNTIME = ROOT / "artifacts" / "runtime.json"


def _hud_mutex_held() -> bool:
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.OpenMutexW.restype = ctypes.c_void_p
    h = k32.OpenMutexW(0x00100000, False, r"Local\cc-hud-single")
    if h:
        k32.CloseHandle(ctypes.c_void_p(h))
        return True
    return False


def _kill_running() -> None:
    """结束 cc-hud.pyw 进程并等互斥体真正释放。

    不等会让下一轮撞上单实例闸门：新进程秒退、runtime.json 不写，测出 ready=None。
    """
    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*cc-hud.pyw*' } "
        "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script],
                   capture_output=True, text=True)
    end = time.time() + 15
    while time.time() < end:
        if not _hud_mutex_held():
            time.sleep(0.4)                 # 再让 Shell/WebView2 收尾一会儿
            return
        time.sleep(0.2)


def _mem_mb(pid: int) -> float | None:
    """被测 pythonw 的整棵进程树私有内存之和（本体 + msedgewebview2 等后代）。

    只按命令行匹配 cc-hud.pyw 会漏掉 WebView2 子进程，两版口径不可比，
    所以从被测 PID 沿 ParentProcessId 递归收全部后代。
    """
    ps1 = Path(tempfile.gettempdir()) / "cchud-bench-mem.ps1"
    ps1.write_text(
        "param([int]$Root)\n"
        "$all = Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId\n"
        "$ids = New-Object System.Collections.Generic.List[int]\n"
        "$ids.Add($Root)\n"
        "for ($i = 0; $i -lt $ids.Count; $i++) {\n"
        "  $cur = $ids[$i]\n"
        "  foreach ($p in $all) { if ($p.ParentProcessId -eq $cur -and -not $ids.Contains($p.ProcessId)) "
        "{ $ids.Add($p.ProcessId) } }\n"
        "}\n"
        "$sum = 0\n"
        "foreach ($id in $ids) {\n"
        "  $g = Get-Process -Id $id -ErrorAction SilentlyContinue\n"
        "  if ($g) { $sum += $g.PrivateMemorySize64 }\n"
        "}\n"
        "Write-Output $sum\n", encoding="utf-8")
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                          "-File", str(ps1), str(pid)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return round(int(out) / 1024 / 1024, 1)
    except ValueError:
        return None


def _tree(pid: int) -> dict:
    """被测 PID 的后代进程统计：进程数 + 按名字分组。第二窗口会多一个 WebView2 渲染进程。"""
    ps1 = Path(tempfile.gettempdir()) / "cchud-bench-tree.ps1"
    ps1.write_text(
        "param([int]$Root)\n"
        "$all = Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name\n"
        "$ids = New-Object System.Collections.Generic.List[int]\n"
        "$ids.Add($Root)\n"
        "for ($i = 0; $i -lt $ids.Count; $i++) {\n"
        "  $cur = $ids[$i]\n"
        "  foreach ($p in $all) { if ($p.ParentProcessId -eq $cur -and -not $ids.Contains($p.ProcessId)) "
        "{ $ids.Add($p.ProcessId) } }\n"
        "}\n"
        "$names = @()\n"
        "foreach ($id in $ids) {\n"
        "  $n = ($all | Where-Object { $_.ProcessId -eq $id } | Select-Object -First 1).Name\n"
        "  if ($n) { $names += $n } else { $names += 'pythonw.exe' }\n"
        "}\n"
        "Write-Output ($names -join ',')\n", encoding="utf-8")
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                          "-File", str(ps1), str(pid)],
                         capture_output=True, text=True).stdout.strip()
    names = [n for n in out.split(",") if n]
    counts: dict[str, int] = {}
    for n in names:
        counts[n.lower()] = counts.get(n.lower(), 0) + 1
    return {"count": len(names), "by_name": counts}


def run_once(root: Path, profile: Path, settle: float, pyw: Path = PY_W) -> dict:
    env = dict(os.environ, CC_HUD_PROFILE=str(profile), CC_HUD_LAYOUT="card")
    env.pop("CC_HUD_SIZE", None)
    runtime = root / "artifacts" / "runtime.json"
    try:
        runtime.unlink()
    except OSError:
        pass
    _kill_running()          # 上一轮没退干净会撞单实例闸门，测出 None
    t0 = time.perf_counter()
    proc = subprocess.Popen([str(pyw), str(root / "cc-hud.pyw")], cwd=str(root), env=env)
    data: dict = {}
    ready_ms = None
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            data = json.loads(runtime.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data.get("ready"):
            ready_ms = round((time.perf_counter() - t0) * 1000, 1)
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    mem = None
    tree = None
    if ready_ms is not None and settle > 0:
        time.sleep(settle)
        mem = _mem_mb(proc.pid)
        tree = _tree(proc.pid)
    hwnd = int(data.get("hwnd") or 0)
    if hwnd:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Add-Type -Namespace W -Name U -MemberDefinition "
                        "'[DllImport(\"user32.dll\")] public static extern bool PostMessageW("
                        "IntPtr h,uint m,IntPtr w,IntPtr l);'; "
                        f"[W.U]::PostMessageW([IntPtr]{hwnd},0x0010,[IntPtr]::Zero,[IntPtr]::Zero)"],
                       capture_output=True)
    for _ in range(20):
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return {
        "ready_ms": ready_ms,
        "bench": data.get("bench") or {},
        "rss_mb": mem,
        "tree": tree,
        "tray_added": bool(data.get("tray_added")),
        "dot_created": data.get("dot_created"),
    }


def summarize(rows: list[dict]) -> dict:
    vals = [r["ready_ms"] for r in rows if r.get("ready_ms")]
    mems = [r["rss_mb"] for r in rows if r.get("rss_mb")]
    return {
        "rounds": len(rows),
        "ready_ms_median": round(statistics.median(vals), 1) if vals else None,
        "ready_ms_min": min(vals) if vals else None,
        "ready_ms_max": max(vals) if vals else None,
        "rss_mb_median": round(statistics.median(mems), 1) if mems else None,
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--settle", type=float, default=2.0)
    ap.add_argument("--root", default=str(ROOT),
                    help="被测项目根（可用 git worktree 指向改造前版本做前后对比）")
    ap.add_argument("--label", default="current")
    ap.add_argument("--out", default="")
    ap.add_argument("--python", default=str(PY_W), help="用哪个 pythonw 跑被测版本")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    pyw = Path(args.python)

    profile = Path(tempfile.mkdtemp(prefix="cchud-bench-profile-"))
    cold: list[dict] = []
    warm: list[dict] = []
    try:
        for _ in range(args.rounds):
            _kill_running()
            shutil.rmtree(profile, ignore_errors=True)
            cold.append(run_once(root, profile, args.settle, pyw))
        _kill_running()
        for _ in range(args.rounds):        # 热启动复用同一个 profile（WebView2 缓存）
            warm.append(run_once(root, profile, args.settle, pyw))
    finally:
        _kill_running()
        shutil.rmtree(profile, ignore_errors=True)

    result = {
        "label": args.label,
        "root": str(root),
        "method": {
            "cold": "每轮先结束 HUD 并删除 profile 目录；测 Popen -> runtime.json ready=true",
            "warm": "复用同一 profile 目录（WebView2 缓存命中）；同样测 Popen -> ready",
            "median": "statistics.median",
            "rss": "ready 后 settle 秒取 PrivateMemorySize64",
        },
        "cold": summarize(cold),
        "warm": summarize(warm),
        "dot_created_seen": sorted({str(r.get("dot_created")) for r in cold + warm}),
    }
    ok = bool(result["cold"]["ready_ms_median"]) and bool(result["warm"]["ready_ms_median"])
    result["ok"] = ok
    out = Path(args.out) if args.out else (
        OUT.with_name(f"startup-bench-{args.label}.json") if args.label != "current" else OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    brief = {
        "ok": ok,
        "label": args.label,
        "cold": {k: v for k, v in result["cold"].items() if k != "rows"},
        "warm": {k: v for k, v in result["warm"].items() if k != "rows"},
        "dot_created_seen": result["dot_created_seen"],
    }
    print(json.dumps(brief, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
