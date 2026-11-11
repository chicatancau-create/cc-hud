# cc-hud

Windows 桌面用量悬浮统计 HUD（2026-11-08 已完成本机整体替换）：**React 18 + TypeScript + Vite 前端，Python 3.14 + pywebview 6.2.1 + Edge WebView2 宿主**。旧 tkinter 版本（`cchud/`、`verify.py`）已删除，原持久化设置已迁移到 `hud-next-state.json`。

只读地把**本机九个 AI 客户端/会话账本**的用量合并成一个总量；生产页面走 `file://` + `http_server=False`，不启 HTTP 监听，不读任何 API Key / providers 配置。

## 入口

| 入口 | 说明 |
|---|---|
| `start-hud.bat` | 推荐入口；只自检 `web/dist` 与 `.venv\Scripts\pythonw.exe` 后直接拉起 `cc-hud.pyw`（不再另起进程预检 `import webview`） |
| `cc-hud.pyw` | pywebview 宿主入口；依赖缺失/启动失败会弹 MessageBox 并写 `artifacts/startup-error.log`，pythonw 不会静默退出 |
| `E:\DeskBox\编程工具\CC Switch HUD.lnk` | 已重定向到 `G:\cc-hud\start-hud.bat` |

无开机自启；CC Switch 退出后 HUD 跟随退出，重新启动 CC Switch 不会自动拉起。

## 托盘与右键菜单

- 只创建一个窗口（主面板）。桌面不再有绿色小圆点，`web/peek.html` 已删除；旧配置里的 `peek` 字段仍能正常读取，只是不再生效。
- **左键单击托盘**：显示 ↔ 隐藏，一次单击只切一次（同类 Shell 消息 300ms 去抖）。
- **右键托盘**：只弹功能菜单，不改显隐。
- **主面板右键**：同一份命令树，浏览器默认菜单被阻止；`Esc` 或点外部关闭。
- 菜单内容：显示/隐藏主面板、视图（小卡/洞察/诊断/设置）、范围（今日/7天/30天/全部）、刷新、导出 JSON、显示设置（透明度/置顶/主题/圆角镂空/打开设置页）、电源（独立危险子菜单，仍需二次确认）、退出程序。
- 托盘注册失败或不可见时**拒绝隐藏**并保持面板可见（`runtime.json` 的 `hide_blocked` / `last_error` 会写明原因）。

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
- 置顶、Win32 整窗透明度、圆角窗口区域镂空（小卡）、托盘显隐 + 托盘/主面板同源右键菜单、电源计划（二次确认，测试用假执行器）。
- 五态区分：加载中 / 无数据 / 真实零值 / 来源不支持 / 读取失败。

## 数据口径要点

- 净 token 一路到底：Codex 回填行的 `input_tokens` 含缓存读，先减；WorkBuddy 的 `prompt_tokens` 同时含缓存读与缓存写，拆三桶后再算。
- 计时只存在于 CC Switch 代理转发的行；会话日志回填与 cc-haha 没有计时，面板上单独声明。
- 两个 SQLite 库一律 `mode=ro`；唯一写盘是设置文件（原子写）。

## 测试与取证

```bash
.venv/Scripts/python.exe -m pytest tests_py -q          # 114 passed
cd web && npm run lint && npm run typecheck && npm test && npm run build   # vitest 29 passed
cd web && npm run e2e                                  # 13 passed (Edge，:4179 vite preview)
python tools/gate_transcript.py                        # 重跑全部门禁并写 docs/reports/2026-11-08-gate-transcript.md
python tools/final_acceptance.py                       # 一键实机验收 → artifacts/final-acceptance.json
python tools/tray_click.py                             # 托盘：左键只切一次 / 右键只弹菜单 / 隐藏后靠托盘找回 / 无小圆点
python tools/bench_startup.py --rounds 5               # 冷/热启动中位数 + 进程树 + 常驻内存 → artifacts/startup-bench-after.json
```

实机窗口/DPI/镂空/PrintWindow 取证：`python tools/verify_windows.py --layout card --wait 20 --shot my-card`；隐藏态（无圆点、托盘可用）：加 `--hidden`；已安装实例截图：`python tools/verify_installed.py`。验收工具会各自起一份 HUD（单实例闸门），所以跑 `final_acceptance.py` 前要先退出正在运行的 HUD；脚本会预检并直接报 `hud_running`。

想对比改造前后启动耗时：`git worktree add ../cc-hud-baseline 2f96309` 后
`python tools/bench_startup.py --rounds 5 --root ../cc-hud-baseline --label before`。

## 目录

```
cc-hud.pyw            pywebview 入口
start-hud.bat         启动器（英文提示，GBK/CRLF）
cchud_next/           宿主、桥接、设置、导出、Win32、托盘、菜单模型、启动打点、九路 sources/
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
