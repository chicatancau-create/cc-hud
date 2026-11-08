# cc-hud 重构最终验收审计（2026-11-08）

入口：`G:\cc-hud\start-hud.bat` → `cc-hud.pyw`（pywebview 6.2.1 + Edge WebView2，`file://` + `http_server=False`）。
本机常驻：runtime pid 29812（launcher 9472），`tools/verify_installed.py` ok=true。

## 逐条完成标准

| 完成标准 | 状态 | 真实命令 | 证据 |
|---|---|---|---|
| Python 单测 / 适配器 / 守恒 / 桥接 | ✅ | `.venv\Scripts\python.exe -m pytest tests_py -q` | 64 passed（每次验收 rc=0） |
| 前端 lint / tsc / Vitest / build | ✅ | `cd web && npm run lint && npm run typecheck && npm test && npm run build` | 0 / 0 / 16 / 成功 |
| Playwright 交互与视觉 | ✅ | `cd web && npx playwright test` | 10 passed（Edge） |
| WebView2 / 窗口 / 圆点 / DPI / 镂空 / PrintWindow | ✅ | `python tools/verify_windows.py --layout card ...` 等 8 组 | `artifacts/final-acceptance.json` 对应 8 项 rc=0；`ACCEPT-*.png` |
| 托盘行为 | ✅ | `python tools/tray_click.py` | ok=true（隐藏→圆点→恢复） |
| 托盘像素 | ✅ | `python tools/tray_pixel.py` | 282 绿像素、`GetRect=0`、ok=true |
| 多显示器实机 | ⏸ 搁置（无第二屏） | `python tools/final_acceptance.py` | 本机仅 `\\.\DISPLAY21`；其余输出 CDS_TEST 全部 -1，MuMu 虚拟适配器无模式；第二块屏未接入 |
| 小卡 / 大面板 / 诊断 / 设置 | ✅ | 8 组 verify + 截图 | `ACCEPT-card/insights/diagnostics/settings.png`、`REPLACED-card.png` |
| 四范围 × 九路对账 | ✅ | `python tools/reconcile.py` | 1d/7d/30d/all 全部 `bad=none` |
| latest-wins / revision / 缓存 / 长会话 | ✅ | `pytest`（bridge/cache）+ Playwright + `tools/bench_long.py` | 单测 + E2E + 基准记录 |
| 视觉差异修复或解释 | ✅ | — | `docs/reports/2026-11-07-visual-diff.md` |

## 一键验收结果

`python tools/final_acceptance.py`（先退出常驻 HUD）：

```json
{"ok": false, "blocked": ["multi_monitor: only 1 display(s)"], "failed_gates": []}
```

18/18 门禁 rc=0；双屏实机按用户指示**搁置**（本机无第二块显示器，门禁与代码保留，不删除）。按规则 14 不以模拟数据替代，故不标记全目标完成。

## 本机替换与修复记录

- 旧 tkinter（`cchud/`、`verify.py`、旧入口）已删除；设置 `hud-state.json` → `hud-next-state.json`；快捷方式 `E:\DeskBox\编程工具\CC Switch HUD.lnk` 指向 `start-hud.bat`。
- 单实例闸门、CC Switch 跟随退出、`final_acceptance` 互斥体预检已补。
- 托盘三个真实问题：`HWND_MESSAGE` → 隐藏顶层工具窗；`uID=0` → 1；`RegisterWindowMessageW` 补 `argtypes`。Windows 提升项 `NotifyIconSettings\...\IsPromoted` 置 1 后像素可见。
- `tray_pixel` 改为色相判定 + 重试取样 + 等待互斥体释放；“no hwnd” 连发回归已定位并修复。

## 剩余动作（换环境即可闭环）

1. 接入第二块显示器（或让 ACER S271HL 通电/接线），确认 Windows 显示设置出现两块屏。
2. 退出常驻 HUD 后运行：`python tools/final_acceptance.py`。
3. 返回 0 即全部完成；若仍只报 `multi_monitor`，说明系统仍只识别到一块屏，需查线与显示模式。
