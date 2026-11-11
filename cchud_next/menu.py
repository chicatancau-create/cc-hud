"""功能菜单的唯一命令模型。

托盘右键（Win32 原生菜单）与主面板右键（React 菜单）都从这里取同一份树，
执行也走同一个 Host.run_menu，避免两套菜单各自漂移。

节点结构：
    {id, title, kind, enabled, checked, danger, children}
    kind: command | check | radio | submenu | separator

命令 id 的命名空间即分发前缀：
    panel.*   主面板显隐      view.*  四个视图       range.*  四个统计范围
    action.*  刷新/导出/设置页 setting.* 现有设置项  power.*  危险电源动作
    app.*     进程级动作
"""
from __future__ import annotations

from .ranges import RANGE_LABELS, RANGES

VIEWS = (("card", "小卡"), ("insights", "洞察"), ("diagnostics", "诊断"), ("settings", "设置"))
ALPHAS = (1.0, 0.96, 0.92, 0.86, 0.78)
POWERS = (("lock", "锁定"), ("sleep", "睡眠"), ("hibernate", "休眠"),
          ("shutdown", "关机"), ("restart", "重启"), ("logoff", "注销"))

# 只出现在菜单 id 里、不会进入用户可见设置的开发命令（capture/dpi/place/selftest）不在本模块登记。


def _sep() -> dict:
    return {"id": "-", "title": "", "kind": "separator"}


def _leaf(cid: str, title: str, kind: str = "command", *, enabled: bool = True,
          checked: bool = False, danger: bool = False) -> dict:
    return {"id": cid, "title": title, "kind": kind, "enabled": bool(enabled),
            "checked": bool(checked), "danger": bool(danger), "children": []}


def _group(cid: str, title: str, children: list[dict], *, danger: bool = False) -> dict:
    return {"id": cid, "title": title, "kind": "submenu", "enabled": True,
            "checked": False, "danger": bool(danger), "children": children}


def build(settings: dict, hidden: bool = False, tray_ok: bool = True) -> list[dict]:
    """按当前设置生成菜单树；hidden/tray_ok 只影响可用性与文案。"""
    s = settings or {}
    layout = s.get("layout", "card")
    rng = s.get("range", "1d")
    alpha = float(s.get("alpha", 0.96))
    theme = s.get("theme", "dark")

    views = [_leaf(f"view.{key}", label, "radio", checked=layout == key) for key, label in VIEWS]
    ranges = [_leaf(f"range.{key}", RANGE_LABELS[key], "radio", checked=rng == key) for key in RANGES]
    alphas = [_leaf(f"setting.alpha.{int(round(a * 100))}", f"{int(round(a * 100))}%",
                    "radio", checked=abs(alpha - a) < 1e-6) for a in ALPHAS]
    themes = [_leaf(f"setting.theme.{key}", label, "radio", checked=theme == key)
              for key, label in (("dark", "深色"), ("light", "浅色"))]
    powers = [_leaf(f"power.{key}", label, danger=True) for key, label in POWERS]

    display = [
        _group("submenu.alpha", "透明度", alphas),
        _leaf("setting.topmost", "窗口置顶", "check", checked=bool(s.get("topmost", True))),
        _group("submenu.theme", "主题", themes),
        _leaf("setting.hollow", "小卡圆角镂空", "check", checked=bool(s.get("hollow", False))),
        _leaf("action.open_settings", "打开设置页…"),
    ]

    return [
        # 托盘不可用时禁止隐藏：只能显示，否则面板会无法找回
        _leaf("panel.toggle", "隐藏主面板" if not hidden else "显示主面板",
              enabled=(tray_ok or hidden)),
        _sep(),
        _group("submenu.view", "视图", views),
        _group("submenu.range", "统计范围", ranges),
        _sep(),
        _leaf("action.refresh", "刷新数据"),
        _leaf("action.export", "导出 JSON"),
        _sep(),
        _group("submenu.settings", "显示设置", display),
        _sep(),
        _group("submenu.power", "电源（危险操作）", powers, danger=True),
        _sep(),
        _leaf("app.quit", "退出程序", danger=True),
    ]


def walk(items: list[dict]):
    for item in items:
        yield item
        children = item.get("children") or ()
        if children:
            yield from walk(children)


def resolve(items: list[dict], cmd_id: str) -> dict | None:
    """在树里找叶子命令；submenu 自身不可执行。"""
    for item in walk(items):
        if item.get("id") == cmd_id and item.get("kind") != "submenu":
            return item
    return None


def leaves(items: list[dict]) -> list[dict]:
    return [i for i in walk(items) if i.get("kind") in ("command", "check", "radio")]


def is_known(cmd_id: str) -> bool:
    """不看设置的前缀白名单：防止前端/托盘传入开发命令。"""
    prefix = cmd_id.split(".", 1)[0]
    return prefix in ("panel", "view", "range", "action", "setting", "power", "app")


def patch_for(cmd_id: str) -> dict | None:
    """把 id 翻译成设置补丁；电气/动作类命令不走这里。"""
    parts = cmd_id.split(".")
    head = parts[0]
    if head == "view" and len(parts) == 2 and parts[1] in dict(VIEWS):
        return {"layout": parts[1]}
    if head == "range" and len(parts) == 2 and parts[1] in RANGES:
        return {"range": parts[1]}
    if head == "setting" and len(parts) >= 2:
        key = parts[1]
        if key == "alpha" and len(parts) == 3:
            try:
                return {"alpha": int(parts[2]) / 100.0}
            except ValueError:
                return None
        if key == "theme" and len(parts) == 3 and parts[2] in ("dark", "light"):
            return {"theme": parts[2]}
    if cmd_id == "action.open_settings":
        return {"layout": "settings"}
    return None


# check 类设置项需要按当前值取反，单独给 host 用
TOGGLES = ("topmost", "hollow")
