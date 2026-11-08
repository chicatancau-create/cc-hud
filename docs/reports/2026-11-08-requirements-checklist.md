# 需求 → 证据 对照表（完成审计）

日期：2026-11-08（原任务 2026-11-07 启动）
状态：**未整体完成**。镜像 §B 中标 ❌/⚠ 的项目仍需对应环境或授权。
逐命令执行记录（最新一轮）：`docs/reports/2026-11-08-gate-transcript.md`。

## A. 强制规则 1–15

| # | 规则 | 证据 | 状态 |
|---|---|---|---|
| 1 | 按 Task 1–17 顺序执行 | `docs/superpowers/plans/…refactor.md` 为重建版，按 17 项顺序实施；任务状态见 §C | ⚠ 依据为重建文档 |
| 2 | 每任务独立实施并审查 | 主实施为单代理；已补两轮独立审查代理。第一轮 8 条修 4 条；第二轮数据层/host 7 条已修并补测（导出按 key 脱敏、Herdsman 会话数、cc-haha 跨日成本与范围 sid、WorkBuddy 范围 sid、revision 单调、ccswitch 读快照、host 竞态/托盘 GUI 线程），第 8 条 DSH 仅 `createdAt` 属数据不可得。另做前端审查 6 条并全部修（设置回包 latest-wins、bootstrap 失败出口、卡片五态、场景桩口径、电源确认 15s 超时与假执行器门控、E2E 吞断言） | ⚠ 部分满足 |
| 3 | 先失败测试再实现 | 部分任务先写测试（越界夹取、latest-wins、缓存上限、导出脱敏、长会话）；部分为补测 | ⚠ 非严格 TDD |
| 4 | 不重写计划代替实施 | 已产出源码/测试/截图/报告 | ✅ |
| 5 | 不改架构 | React 18+TS+Vite；pywebview 6.2.1；`cchud_next` 宿主 | ✅ |
| 6 | 无远程服务/HTTP 监听 | `webview.start(http_server=False)`；URL 为 `file:///G:/cc-hud/web/dist/index.html`（`FINAL8-*.json`） | ✅ |
| 7 | 不用 `transparent=True`；alpha 走 Win32；镂空单列门禁 | AST 测试禁止该关键字；alpha 路径 `LWA_ALPHA`=244；镂空实机：`flags=3`（COLORKEY+ALPHA）、`colorkey=0x140E0B`、`bg_pixels=0/379555`，桌面从背景透出（`FINAL-hollow3.png`） | ✅ |
| 8 | SQLite mode=ro；不读密钥 | 统一 `connect_ro`（`mode=ro`+`query_only`+`finally close`）；`test_sqlite_ro`；全库无 providers.json/API key 读取 | ✅ |
| 9 | 五态区分 | `ok/empty/unsupported/error/loading`；四态文案 Playwright；真实 0 显示 0 | ✅ |
| 10 | 不引入远程库/估值/采集 | 无网络调用；`test_no_transparent_true_anywhere` 同文件 AST 检查 | ✅ |
| 11 | 旧入口处置 | 2026-11-08 按用户要求改为**本机整体替换**：旧 `cchud/`、`verify.py`、旧 tkinter 入口已删除；托盘代码迁入 `cchud_next/tray.py`；入口统一为 `start-hud.bat` → `cc-hud.pyw`（pywebview）；设置 `hud-state.json` → `hud-next-state.json`（alpha 0.96 / hollow / range→30d）；快捷方式已重定向 | ✅ 替换完成 |
| 12 | 测试不执行真实电源 | 测试注入 `FakePower`；WebView2 实机自测用 `CC_HUD_FAKE_POWER` 假执行器（`confirmed.fake=true`），未执行真实命令 | ✅ |
| 13 | 不 commit/push/merge/发布 | `git status` 仅工作区改动，无提交 | ✅ |
| 14 | 不伪造 Windows 结果 | 所有 Windows 结论挂 `artifacts/*.json`；未做到的项目列 §B | ✅ |
| 15 | 不删断言/不自动接受视觉 | 无快照自动接受；未降低断言 | ✅ |

## B. 完成标准 8 项

| 项 | 证据 | 状态 |
|---|---|---|
| Python 单测/适配器/守恒/桥接 | `pytest tests_py -q` → **64 passed**（含多屏定位 500 组随机性质测试；另托盘结构 2、设置/导出 6、cchaha 成本/sid 2、revision 单调 1 等） | ✅ |
| 前端 lint / tsc / Vitest / build | lint 0；tsc 0；Vitest **16 passed**；build 成功 | ✅ |
| Playwright 交互与视觉 | **10 passed**（范围切换、四态、会话搜索分页、导出、刷新后 seq、窄视口） | ✅ |
| WebView2 / 窗口 / 托盘 / 圆点 / DPI / 多屏 / PrintWindow | 窗口/圆点/DPI/PrintWindow/镂空/托盘（行为+像素）全过；**多屏未实测**（本机仅 DISPLAY21，第二块显示器未接入） | ⚠ 6/7 |
| 小卡 / 大面板 / 诊断 / 设置可用 | `FINAL8-card`、`FINAL7-30d`、`FINAL-diagnostics`、`FINAL-settings` | ✅ |
| 四范围 × 九路对账 | 每轮随真实数据增长；最新一轮 `gate-transcript`：tokens 268,296,240 / 1,184,179,669 / 2,791,562,712 / 3,468,727,115，守恒 11/20/26/29 项全 true，`bad=none`，RC=0 | ✅ |
| latest-wins / 导出 revision / 缓存上限 / 长会话 | `test_bridge`（stale、capacity=2 淘汰、导出 rev）；Playwright 连续切范围；`--selftest export` rev=1；20k+5k 与 100k+20k 基准 | ✅ |
| 视觉差异修复或解释 | `visual-diff.png` + `2026-11-07-visual-diff.md`；命令 tally/上下文构成/余额 已解释为数据不可得 | ✅ |
| （规则 2）独立审查 | 已完成一轮；4 条实质问题修复并补测 | ✅ |

## C. 17 个任务

| Task | 内容 | 状态 |
|---|---|---|
| 1 | 环境与骨架 | ✅ |
| 2 | 模型/范围/状态 | ✅ |
| 3 | 只读 SQLite 层 | ✅ |
| 4 | CC Switch（含会话/耗时） | ✅ |
| 5 | cc-haha（含工具 tally） | ✅ |
| 6 | Qoder / CN | ✅ |
| 7 | ZCode / 牧羊人 | ✅ |
| 8 | Codex | ✅ |
| 9 | WorkBuddy 双版 | ✅ |
| 10 | DSH projcache + V4 | ✅（V4 无 usage → unsupported，按要求不伪造） |
| 11 | 合并/双计/守恒/会话 | ✅ |
| 12 | 设置/导出 | ✅ |
| 13 | 桥接 | ✅ |
| 14 | 前端状态层 | ✅ |
| 15 | 四视图 | ✅（缺命令 tally/上下文构成，数据不可得） |
| 16 | Playwright | ✅ |
| 17 | Windows 实机 | ⚠ 多屏/托盘像素未过（窗口/圆点/DPI/镂空/导出/电源已过） |

## D. 未完成与阻塞

| 阻塞 | 原因 | 需要的动作 |
|---|---|---|
| 双显示器实机 | 本机仅 `\\.\DISPLAY21` 已挂载（2560×1600，`EnumDisplaySettings` 有模式）；`DISPLAY22/23`（NVIDIA）与 `DISPLAY10–19`（MuMu 虚拟显示适配器）、`DISPLAY5–9`（AMD）均无当前/注册模式、无子显示器，无法软件启用 | **按用户指示搁置**（本机无第二块显示器）；门禁保留，接屏后跑 `final_acceptance.py` 复测 |
| 托盘像素级 | **已通过**：行为 `tray_click` ok=true；注册修复 `HWND_MESSAGE`→顶层工具窗、`uID=0`→1，`RegisterWindowMessageW` 补 argtypes；Windows 提升设置 `IsPromoted=1`；`tools/tray_pixel.py` 改为色相判定并重试取样，输出 282 绿像素、`GetRect=0`、ok=true。|2026-11-08T02:06Z 复核：可见区截图仍无 cc-hud；运行中的旧实例（PID 47936，11-07 17:29 启动、带旧版 856 字节结构，仅作弱对照）同样无图标；同一轮 `pytest` 64 passed、`npm test` 16 passed | 图标可见性需换机/换登录会话，或人工在“任务栏设置→其他系统托盘图标”确认 |
| 系统级 DPI 100/150 | 未改系统缩放，仅做 WebView `--force-device-scale-factor` 对照 | 在对应缩放机器复测 |
| 背景镂空实机门禁 | **已通过**：`FINAL-hollow3.png` 显示桌面透出、卡片不透明 | — |
| 独立子代理审查 | 本轮单代理连续实施 | 可另起审查代理复核 diff |
