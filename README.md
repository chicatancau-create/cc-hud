# cc-hud

Windows 桌面用量悬浮统计 HUD（2026-11-08 已完成本机整体替换）：**React 18 + TypeScript + Vite 前端，Python 3.14 + pywebview 6.2.1 + Edge WebView2 宿主**。旧 tkinter 版本（`cchud/`、`verify.py`）已删除，原持久化设置已迁移到 `hud-next-state.json`。

只读地把**本机九个 AI 客户端/会话账本**的用量合并成一个总量；生产页面走 `file://` + `http_server=False`，不启 HTTP 监听，不读任何 API Key / providers 配置。

## 入口

| 入口 | 说明 |
|---|---|
| `start-hud.bat` | 推荐入口；自检 `web/dist`、`.venv\Scripts\pythonw.exe`、`pywebview` 后拉起 `cc-hud.pyw` |
| `cc-hud.pyw` | pywebview 宿主入口 |
| `E:\DeskBox\编程工具\CC Switch HUD.lnk` | 已重定向到 `G:\cc-hud\start-hud.bat` |

无开机自启；CC Switch 退出后 HUD 跟随退出，重新启动 CC Switch 不会自动拉起。

## 构建与运行

```bat
cd web && npm install && npm run build
start-hud.bat
```

`.venv` 内固定 `pywebview==6.2.1` 与 Pillow；`web/dist` 不存在时启动器会直接报错并给出命令。

## 功能

- 四个视图：小卡、Context Insights 大面板、诊断、设置。
- 九路只读适配器：CC Switch、cc-haha、Qoder、Qoder CN、ZCode、牧羊人、Codex、WorkBuddy 国内/国外、DSH（含 V4 zstd 会话）。
- 统计守恒（总量 = Σ 日、Σ 小时 = 请求数、模型 ≤ 总量）；会话 id 交集整路拒绝、Codex+DSH 只补缺口。
- 四档范围（今日 / 7 天 / 30 天 / 全部）、latest-wins 切换、快照缓存 ≤ 8、导出带 `revision` 且按 key 脱敏。
- 置顶、Win32 整窗透明度、颜色键镂空、Win11 圆点呼出、托盘显隐、电源计划（二次确认，测试用假执行器）。
- 五态区分：加载中 / 无数据 / 真实零值 / 来源不支持 / 读取失败。

## 数据口径要点

- 净 token 一路到底：Codex 回填行的 `input_tokens` 含缓存读，先减；WorkBuddy 的 `prompt_tokens` 同时含缓存读与缓存写，拆三桶后再算。
- 计时只存在于 CC Switch 代理转发的行；会话日志回填与 cc-haha 没有计时，面板上单独声明。
- 两个 SQLite 库一律 `mode=ro`；唯一写盘是设置文件（原子写）。

## 测试与取证

```bash
.venv/Scripts/python.exe -m pytest tests_py -q          # 64 passed
cd web && npm run lint && npm run typecheck && npm test && npm run build
cd web && npx playwright test                          # 10 passed (Edge)
python tools/gate_transcript.py                        # 重跑全部门禁并写 docs/reports/2026-11-08-gate-transcript.md
python tools/final_acceptance.py                       # 一键实机验收 → artifacts/final-acceptance.json
python tools/tray_click.py                             # 托盘点击 → 隐藏 → 圆点 → 恢复（行为取证）
```

实机窗口/圆点/DPI/镂空/PrintWindow 取证：`python tools/verify_windows.py --layout card --wait 26 --shot my-card`；已安装实例截图：`python tools/verify_installed.py`。验收工具会各自起一份 HUD（单实例闸门），所以跑 `final_acceptance.py` 前要先退出正在运行的 HUD；脚本会预检并直接报 `hud_running`。

## 目录

```
cc-hud.pyw            pywebview 入口
start-hud.bat         启动器（英文提示，GBK/CRLF）
cchud_next/           宿主、桥接、设置、导出、Win32、托盘、九路 sources/
web/                  React 前端（src/、e2e/、dist/）
tests_py/             pytest（适配器/守恒/桥接/设置/托盘结构/窗口定位）
tools/                实机验收、对账、托盘与安装态取证
docs/superpowers/     设计 spec 与 17 任务计划
docs/reports/         验证报告、门禁执行记录、需求清单、交付索引
artifacts/            截图与 JSON 证据（gitignore）
```

## 已知环境阻塞（本机）

- 双显示器实机：本机仅 `\\.\DISPLAY21`（2560×1600）；其余输出/虚拟适配器无可用模式，无法软件启用。
- 系统级 DPI 100/150：仅做 WebView 强制 1/1.5 对照，未改系统缩放。

细节见 `docs/reports/2026-11-08-requirements-checklist.md`、`docs/reports/2026-11-08-delivery-index.md`、`docs/reports/2026-11-07-refactor-verification.md`。
