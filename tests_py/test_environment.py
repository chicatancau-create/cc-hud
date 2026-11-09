import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_python_is_314_or_newer():
    assert sys.version_info >= (3, 14), sys.version


def test_pywebview_importable():
    import webview  # noqa: F401


def test_web_dist_contract():
    assert (ROOT / "web" / "src" / "main.tsx").exists(), "前端入口缺失"
    assert (ROOT / "web" / "package.json").exists(), "前端脚手架缺失"


def test_no_transparent_true_anywhere():
    import ast

    hits = []
    for path in (ROOT / "cchud_next").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and any(
                kw.arg == "transparent" and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            ):
                hits.append(f"{path}:{node.lineno}")
    assert hits == [], f"Windows 禁止 pywebview transparent=True: {hits}"
