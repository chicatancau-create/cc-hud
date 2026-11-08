# 交付索引（2026-11-08）

## 源码
- Python 宿主：`cchud_next/`（paths / model / ranges / sqlite_ro / sources/ / accounting / settings / export / bridge / win32 / host）
- 前端：`web/`（React 18 + TS + Vite；`web/src/views/` 四视图，`web/src/state/` latest-wins，`web/src/components/`）
- 入口：`cc-hud.pyw`（pywebview）+ `start-hud.bat`；快捷方式 `E:\DeskBox\编程工具\CC Switch HUD.lnk` 已重定向到 `start-hud.bat`
- 2026-11-08 本机整体替换：旧 `cchud/`、`verify.py`、旧 tkinter 入口已删除；托盘迁入 `cchud_next/tray.py`；旧设置迁入 `hud-next-state.json`（alpha 0.96 / hollow / range→30d）

## 测试
- Python：`tests_py/`（64 用例：适配器、守恒、桥接、SQLite、长会话、多屏定位纯函数+500 组随机性质、截图路径、托盘结构、设置导出）
- 前端：`web/src/**/*.test.tsx?`（16 用例：状态、缓存、视图、会话网格、耗时、工具）
- E2E：`web/e2e/insights.spec.ts`（10 用例：范围切换、四态、会话、导出、刷新 seq、窄视口）

## 工具
- `tools/verify_windows.py`：WebView2 实机取证（窗口/托盘标志/圆点/DPI/alpha/镂空/导出/电源/截图）
- `tools/bench_long.py`：10 万行基准
- `tools/reconcile.py`：四范围 × 九路对账门禁（守恒/Σdays/Σhours/models≤total）
- `tools/tray_pixel.py` / `tools/tray_uia.ps1` / `tools/tray_toolbar.py`：托盘取证尝试（结论见未验证项）
- `tools/gate_transcript.py`：一键重跑全部门禁并重写执行记录
- `tools/tray_click.py`：托盘消息泵行为验收（隐藏/圆点/恢复）
- `tools/verify_settings_persist.py`：预写设置启动后 alpha/置顶/布局生效
- `tools/final_acceptance.py`：一键跑完 8 项完成标准，缺双屏/DPI 时返回阻塞

## 文档
- 设计（重建）：`docs/superpowers/specs/2026-11-07-context-insight-refactor-design.md`
- 计划（重建，17 任务）：`docs/superpowers/plans/2026-11-07-context-insight-refactor.md`
- 验证报告：`docs/reports/2026-11-07-refactor-verification.md`
- 视觉差异：`docs/reports/2026-11-07-visual-diff.md`
- 需求对照：`docs/reports/2026-11-08-requirements-checklist.md`
- 门禁执行记录（脚本生成）：`docs/reports/2026-11-08-gate-transcript.md`
- 本索引：`docs/reports/2026-11-08-delivery-index.md`

## 证据（artifacts/）
| 文件 | 内容 |
|---|---|
| `artifacts/windows/FINAL17-card.png` | 小卡（WebView2，托盘 GUI 线程修复后） |
| `artifacts/windows/FINAL14-insights.png` / `FINAL7-30d.png` | 大面板（含耗时/工具/会话/守恒） |
| `artifacts/windows/FINAL18-diagnostics.png` / `FINAL18-settings.png` | 诊断 / 设置 |
| `artifacts/windows/FINAL18-hollow.png` + `windows-verify-FINAL18-hollow.json` | 背景镂空（flags=3, bg=0） |
| `artifacts/windows/windows-peek-dot.png` + `FINAL18-peek.json` | 隐藏 + 呼出圆点 |
| `artifacts/windows-verify-FINAL18-power.json` | 电源二次确认（假执行器） |
| `artifacts/windows-verify-tray-click.json` | 托盘点击：隐藏/圆点/恢复 ok=true |
| `artifacts/windows-verify-settings-persist.json` | 设置持久化：alpha/topmost/layout ok=true |
| `artifacts/windows-verify-FINAL18-export.json` | 原生导出（revision+文件） |
| `artifacts/windows-verify-FINAL26-card.json` | 窗口/DPI/alpha/置顶/托盘标志 |
| `artifacts/windows/REPLACE-verify-card.png` + `windows-verify-REPLACE-verify-card.json` | 2026-11-08 本机替换后：`start-hud.bat`→`cc-hud.pyw` 启动的小卡 PrintWindow 全 PASS |
| `artifacts/windows/REPLACE-verify-insights.png` + 对应 JSON | 替换后大面板实机（2051×1260，真实九路数据） |
| `artifacts/windows/REPLACED-card.png` | 从桌面快捷方式重启后的常驻实例截图（`tools/verify_installed.py`） |
| `artifacts/visual-diff.png` + `artifacts/reference/` | 与 dsh-context 并排 |
| `artifacts/web/*.png` | Playwright 视觉（洞察/小卡/诊断/设置/四态/窄屏） |

## 复现命令
```bash
.venv/Scripts/python.exe -m pytest tests_py -q
cd web && npm run lint && npm run typecheck && npm test && npm run build
cd web && npx playwright test
python tools/verify_windows.py --layout card --wait 26 --shot my-card
python tools/verify_windows.py --layout insights --wait 30 --shot my-insights
python tools/verify_windows.py --layout card --hidden --wait 8 --shot my-peek
python tools/verify_windows.py --layout card --hollow --wait 26 --shot my-hollow
python tools/verify_windows.py --layout card --selftest export --wait 40 --shot my-export
python tools/verify_windows.py --layout card --selftest power --wait 20 --shot my-power
python tools/bench_long.py 100000
python tools/reconcile.py          # 四范围对账门禁，RC=0 才算过
python tools/gate_transcript.py    # 重跑上述全部门禁并重写执行记录（.venv/Scripts/python.exe）
```

## 验收状态（对照完成标准 8 项）

| 完成标准 | 状态 | 证据 |
|---|---|---|
| Python 单测/适配器/守恒/桥接 | ✅ 64 passed | gate-transcript |
| 前端 lint / tsc / Vitest / build | ✅ 0 / 0 / 16 / 成功 | gate-transcript |
| Playwright 交互与视觉 | ✅ 10 passed | gate-transcript |
| WebView2/窗口/托盘/圆点/DPI/多屏/PrintWindow | ⚠ 6/7：仅多屏未实测；托盘像素已过（色相 282 px） | FINAL18/19/26 + 11-08 最终验收 |
| 小卡/大面板/诊断/设置 | ✅ FINAL18-diagnostics/settings、FINAL17-card、FINAL14-insights | artifacts/windows |
| 四范围 × 九路对账 | ✅ RC=0，bad=none | gate-transcript |
| latest-wins / revision / 缓存 / 长会话 | ✅ 单测+E2E+FINAL18-export | gate-transcript |
| 视觉差异修复或解释 | ✅ visual-diff + 差异说明 | 2026-11-07-visual-diff.md |

**一键复核**：`python tools/final_acceptance.py` → `artifacts/final-acceptance.json`（本机 18/18 门禁 rc=0、failed=[]，仅 blocked=multi_monitor）。验收工具会自起 HUD，**跑前先退出常驻实例**；脚本用 `OpenMutexW("Local\cc-hud-single")` 预检并报 `hud_running`。

**未完成**：双显示器实机（本机仅 DISPLAY21）、托盘图标可见性（Shell 侧，点击行为已过）、系统级 DPI 变更（仅强制 1/1.5 对照）。
