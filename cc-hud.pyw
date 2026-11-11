# -*- coding: utf-8 -*-
"""cc-hud 入口：pywebview + Edge WebView2（React 前端）。

pythonw 没有控制台：依赖缺失/启动失败时必须弹 MessageBox 并落日志，
否则用户看到的就是「双击没反应」。这里不再让 start-hud.bat 另起进程预检。
"""
import ctypes
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = Path(__file__).resolve().parent


def _fatal(title: str, message: str) -> None:
    try:
        log = ROOT / "artifacts" / "startup-error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(message, encoding="utf-8")
    except OSError:
        pass
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def main() -> None:
    try:
        from cchud_next.host import main as run
    except Exception:
        detail = traceback.format_exc()
        hint = ""
        if "No module named 'webview'" in detail or "No module named 'webview." in detail:
            hint = "\n\n缺少 pywebview。请在项目目录执行：\n  .venv\\Scripts\\python.exe -m pip install -e ."
        _fatal("cc-hud 启动失败", f"无法导入宿主模块：\n\n{detail}{hint}\n\n日志：{ROOT / 'artifacts' / 'startup-error.log'}")
        raise SystemExit(1)
    try:
        run()
    except SystemExit:
        raise
    except Exception:
        detail = traceback.format_exc()
        _fatal("cc-hud 启动失败", f"{detail}\n\n日志：{ROOT / 'artifacts' / 'startup-error.log'}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
