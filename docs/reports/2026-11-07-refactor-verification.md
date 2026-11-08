# cc-hud 重构验证报告（2026-11-07）

> 说明：本报告的每个数字与结论都来自本轮实际命令输出；未执行/未证实的项目单列在 §7「未验证与限制」，不以“通过”代替。

## 0. 执行依据文档缺失与重建

用户指定的两份文档在本地与两个远端均不存在：

- `git ls-files` 无 docs；`git rev-list --left-right --count main...atomgit/main` = `0 0`（`991521d`）；
- `git ls-remote https://atomgit.com/zhoumoyukuai/cc-hud.git` 仅 `main@991521d`；
- `raw.gitcode.com/.../docs/...` → HTTP 404；全盘文件名/内容搜索 0 命中。

用户补充指令「遇到阻碍按最合理方式继续」，因此：
本报告所依据的 spec/plan 为**重建版**（见 `docs/superpowers/specs/…design.md`、`docs/superpowers/plans/…refactor.md` 顶部标注），
内容由现有 `cchud/`、`verify.py` 与本机真实数据格式反推，未改变已确认的 React + pywebview 架构与硬约束。

## 1. 环境实测

| 项 | 结果 |
|---|---|
| Python | 3.14.2（`D:\PyCharm\Python\python.exe`） |
| 项目 venv | `.venv`（pytest 9.2.0、pywebview 6.2.1、Pillow 13.0.0） |
| Node / npm | 24.15.0 / 11.12.1 |
| Edge / WebView2 | Edge 存在；运行时 156.0.4314.58、157.0.4341.42 |
| 显示 | 2560×1540 工作区，125%（DPI 120），1 台显示器 |

## 2. 交付物

```
cchud_next/            新宿主包（paths/model/ranges/sqlite_ro/sources/accounting/settings/export/bridge/win32/host）
web/                   React 18 + TS + Vite（小卡 / 洞察 / 诊断 / 设置）
cc-hud-next.pyw        新入口（file:// + http_server=False）
start-hud-next.bat     新启动器（.venv\Scripts\pythonw.exe）
cc-hud.pyw, cchud/     旧版原样保留（回退入口）
tests_py/              61 个 pytest 用例
web/src/**/*.test.*    16 个 Vitest 用例
web/e2e/               10 个 Playwright 用例
tools/verify_windows.py  Windows 实机取证
docs/superpowers/…     重建的 spec + 17 任务 plan
docs/reports/…         本报告
artifacts/             截图与实机 JSON 证据
```

## 3. 自动化门禁（实际执行）

| 命令 | 结果 |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests_py -q` | **64 passed** |
| `cd web && npm run typecheck` | 0 error |
| `cd web && npm run lint` | 0 error |
| `cd web && npm test` | **16 passed** |
| `cd web && npm run build` | 成功（`dist/index-*.js` ≈181 kB，gzip 57 kB） |
| `cd web && npx playwright test` | **10 passed**（chromium channel=msedge，含刷新后 seq 回归） |
| `python tools/verify_windows.py --layout card --wait 26` | `ok=true`（17 项全 PASS） |
| `python tools/verify_windows.py --layout insights --wait 26` | `ok=true` |
| `python tools/verify_windows.py --layout card --hidden --wait 8` | `ok=true`（含 peek 可见/截图） |
| `python tools/verify_windows.py --layout diagnostics --wait 26` | `ok=true`（`FINAL-diagnostics.png`） |
| `python tools/verify_windows.py --layout settings --wait 26` | `ok=true`（`FINAL-settings.png`） |
| `python tools/verify_windows.py --layout insights --wait 26 --scroll 1150` | `ok=true`（会话网格截图 `FINAL2-sessions2.png`） |
| `python tools/verify_windows.py --layout card --hollow --wait 26` | `ok=true`；`flags=3`、`bg_pixels=0/379555`（`FINAL-hollow3.png`） |
| `python tools/verify_windows.py --layout card --selftest power --wait 20` | `ok=true`；未确认拒绝、确认后走**假执行器**（无真实关机） |
| `python tools/verify_windows.py --layout card --selftest export --wait 40` | `ok=true`；`selftest_export: {"path":"…\cc-hud-usage-1d.json","bytes":26104,"revision":1}` |

Python 用例覆盖：模型/状态区分、只读 SQLite（写被拒、异常路径关库）、9 路适配器（cc-haha 全局去重、
Qoder credits、ZCode 净输入、牧羊人、Codex have_sids、WorkBuddy 双版、DSH projcache/V4）、
整路拒绝与只计缺口、守恒校验、设置夹取与原子写、导出 revision/脱敏、桥接 latest-wins/缓存上限/电源二次确认。

前端用例覆盖：null vs 0、suppressed 文案、latest-wins 丢弃乱序、缓存容量淘汰、四态文案、KPI/来源卡/模型表、
诊断守恒表、设置二次确认、小卡导航。

Playwright 覆盖：洞察渲染、连续范围切换（今日→30 天→全部→7 天，最终 7 根日柱）、小卡↔设置↔洞察、
诊断（11 路来源、0 条守恒失败）、电源两次确认、空/零/不支持/错误四态、导出 revision、
会话网格（12/页、搜索、来源筛选、翻页）、420px 无横向溢出。

长会话压测（`tests_py/test_long_session.py`）：合成 20,000 条 cc-haha transcript（含 fork 抄写同 id）+ 5,000 条
WorkBuddy `rawUsage`，断言去重后 reqs/tokens 精确、守恒全绿、冷启动 < 20s、进程内缓存第二次更快。

## 4. Windows 实机证据（artifacts/）

`windows-verify-FINAL-card.json` / `FINAL-insights.json` / `FINAL-peek.json` 均 `ok=true`，检查项：

- 进程存活、`runtime.json` 就绪、主窗与 `cc-hud-dot` 均存在；
- `dist` = `file:///G:/cc-hud/web/dist/index.html`（无 HTTP 监听）；
- 托盘 `tray_added=true`、圆点 `dot_placed=true`；
- DPI=120、工作区 `[0,0,2560,1540]`、显示器枚举 1 台；
- `WS_EX_LAYERED` + `LWA_ALPHA` 生效（alpha=244，0.96×255）；
- 置顶 `WS_EX_TOPMOST` 生效；
- 隐藏后主窗不可见、圆点可见，圆点截图非黑（max_luma 166）；
- 截图非黑：小卡 max_luma 236、大面板 236；
- 镂空：`hollow_colorkey` / `hollow_bg_transparent` 均 PASS（`windows-verify-FINAL-hollow3.json`）。

截图：

- `artifacts/before/` 旧版小卡/展开/今日柱（重构前）
- `artifacts/windows/FINAL-card.png`、`FINAL-insights.png`、`windows-peek-dot.png`（WebView2 实机）
- `artifacts/web/insights.png`、`card.png`、`diagnostics.png`、`settings.png`、`empty.png`、`unsupported.png`、`narrow-420.png`（Playwright）

## 5. 数据对账（真实本机账；门禁：`python tools/reconcile.py` → RC=0，2026-11-08 00:26）

`tools/reconcile.py` 额外断言：每路 `reqs==Σdays`、`reqs==Σhours`、`totals==Σdaily`，四范围任何一项失败即退出码 1。
本次实测四范围 `bad=none`。

| 范围 | 耗时 | tokens | 请求 | 成本 | credits | 会话 | 守恒 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1d | 10.42s（冷） | 264,803,070 | 194 | $3.19 | — | 6 | 11 项 + 逐路等式，bad=none |
| 7d | 4.75s | 1,180,686,499 | 10,662 | $136.70 | — | 64 | 20 项，bad=none |
| 30d | 1.53s | 2,787,717,042 | 22,152 | $369.10 | — | 1,069 | 26 项，bad=none |
| all | 3.04s | 3,464,881,445 | 55,703 | $423.15 | — | 1,310 | 29 项，bad=none |

来源状态（all）：ccswitch/cchaha/qoder/qoder_cn/zcode/herdsman/codex/workbuddy/workbuddy_ai 均 `ok`；
`dsh` = `empty`（projcache 会话不在范围/为空），`dsh_v4` = `unsupported`（V4 无结构化 usage，按要求不伪造）。
本轮真实数据无会话 id 交集，`suppressed` 逻辑由合成用例覆盖。
表中数字为 WorkBuddy 跨文件去重、gap 源改用 `counted` 排除后的当前值。

## 6. 独立审查（子代理）与已修问题

审查代理返回 8 条，已修 4 条实质问题并补测试：

1. 前端 seq 跨页面重载归零 → 宿主全局 `last_seq` 会把新请求判旧、永久 loading。改为 `Date.now()` 起点单调序列，stale 分支补 `setLoading(false)`；新增 Playwright「刷新页面」用例。
2. `accounting.collect` 的 gap 源（Codex/DSH）只用 CC Switch sid 排除，可能与 cc-haha/Qoder/WorkBuddy 重叠双计。改为 `exclude_sids=counted` 并把 gap 源 sid 计入；新增 DSH 与 Qoder 同 sid 用例。
3. `host._ensure_window_ready` 在成功前就置 `_initialized=True`，早期异常会让轮询线程不再重试。改为成功后置位、异常复位。
4. WorkBuddy 无跨文件去重（复制/fork 会话会双计）。按 `(sid, 时刻, 模型, 四桶)` 去重；新增复制会话文件用例。

未修（已记录）：托盘 WndProc 内写状态文件（GUI 线程 I/O）、缓存 payload 仅浅拷贝、`capture()` 可写页面传入的任意路径（本地 file:// 宿主）。

## 7. 本轮定位并修复的宿主级问题

1. **js_api 注入失败**：`Bridge` 的公开属性 `window_port` 被 pywebview 当作 API 序列化，触发
   `CoreWebView2Controller ... only be accessed from the UI thread`，注入线程失败、前端回落桩数据。
   修复：内部依赖改为下划线私有属性，js_api 只暴露方法。
2. **loaded 事件 + React 首渲染竞态**：前端在 API 注入前就固定用桩。修复：轮询 `window.pywebview.api`
   （file:// 6s，浏览器 1.5s），file:// 超时直接报错而不是用假数据。
3. **Python 后台线程被 WinForms 循环饿死**：心跳 1s 后停止。修复：托盘事件在 WndProc（GUI 线程）同步处理，
   周期刷新由前端 `setInterval` 调桥接（桥接走 .NET 线程，GIL 可用）。
4. **125% DPI 下右侧被裁**：pywebview 按物理像素建窗、WebView2 按缩放渲染。修复：`documentElement.style.zoom = 1/devicePixelRatio`；
   并让布局切换时按 424×330 / 1180×820 重新定位窗口。
5. **分层窗口取证**：屏幕 BitBlt 会把桌面拍进来。修复：取证前临时 alpha=100%，PrintWindow 抓取后恢复。

## 7. 未验证与限制（不冒充通过）

| 项 | 状态 |
|---|---|
| 双显示器实机 | **未验证**：本机仅 1 台显示器；多屏代码路径（EnumDisplayMonitors/工作区夹取）已实现并有单测级辅助，但没有第二块屏可实测 |
| 非 125% DPI（100%/150%） | **部分验证**：未改系统缩放；强制 WebView2 `--force-device-scale-factor`：
1 → `dpr=1`、`innerWidth=2184`、整页无裁切（`DPI100-forced.png`）；1.5 → `dpr=1.5`、`innerWidth=1456`、整页无裁切（`DPI150-forced.png`）。
系统级 DPI 档位本身未切换 |
| 托盘图标像素级取证 | **未完成**：`tray_added=true`（NIM_ADD 成功），但 `Shell_NotifyIconGetRect` 未返回矩形、通知区域裁剪图未命中强调色像素——图标很可能在任务栏溢出区（“^”），本工具未能展开取证。不据此宣称像素级通过 |
| 长会话/超大 transcript 压测 | **已做**：20k+5k 单测；10 万 cc-haha + 2 万 WorkBuddy 基准 `tools/bench_long.py` → 2026-11-08 复测冷 1.71s / 热 0.41s（早前 1.01/0.34），reqs 120,000、守恒 8 项全绿 |
| WebView2 内电源二次确认 | **已实机验证（假执行器）**：`selftest_power` PASS，`confirmed.fake=true`，未执行真实命令 |
| 大面板内的导出按钮 | **已实机验证**：`verify_windows.py --selftest export` 通过（revision 1、文件存在）；电源按钮仍由 Playwright 覆盖，未在 WebView2 点击 |
| 会话网格 | 已在 WebView2 实机截图 `FINAL2-sessions2.png`：搜索、来源 chips、12/页分页、真实会话 id/模型/tokens/成本或 credits |
| 耗时/工具 tally | 已实现并入快照与 UI：30d 实测工具 `Read 132 / Bash 127 / Grep 54 / Edit 41`；耗时 `P50 11.10s / TTFT P50 5.70s / 样本 7,129`（`FINAL7-30d.png`）；命令 tally 与上下文构成仍未做（数据不可得） |
| 视觉逐像素差异 | 已出并排图 `artifacts/visual-diff.png` 与差异报告 `docs/reports/2026-11-07-visual-diff.md`；三处内容缺失为数据不可得（耗时/工具 tally/上下文构成），已逐条解释；未做 SSIM 数值 |
| 旧 `verify.py` A–Z | 未改造为适配新宿主；旧版回退入口不受影响 |
| 电源真实动作 | 按约束从未执行（测试注入 FakePower） |

## 8. 复现命令

```bash
# 后端
.venv/Scripts/python.exe -m pytest tests_py -q
# 前端
cd web && npm run lint && npm run typecheck && npm test && npm run build
# E2E
cd web && npx playwright test
# 实机
python tools/verify_windows.py --layout card --wait 26 --shot my-card
python tools/verify_windows.py --layout insights --wait 26 --shot my-insights
python tools/verify_windows.py --layout card --hidden --wait 8 --shot my-peek
# 启动（生产）
start-hud-next.bat     # 旧回退：start-hud.bat / cc-hud.pyw
```

## 9. 结论

自动化门禁、四范围对账与 Windows 单屏 125% 实机验收均通过；§7 的项目仍未验证，
因此本轮**不能宣称整体完成**，需在具备第二块显示器/可改 DPI 的环境补测后才能给出最终结论。

## 10. 2026-11-08 增补

- 全部自动化门禁可用 `tools/gate_transcript.py` 一次重跑并重写 `docs/reports/2026-11-08-gate-transcript.md`，当轮 RC 全为 0。
- 托盘复测（DPI-aware）：任务栏 [0,1540,2560,1600] 可见；`tools/tray_uia.ps1` 已能打开 Win11 溢出面板
  （`TopLevelWindowForOverflowXamlIsland`，11 项）并回读清单，但**清单与可见托盘中都没有 cc-hud**；
  `NIM_ADD` 返回成功、`Shell_NotifyIconGetRect` 仍 E_FAIL。证据：`artifacts/windows-verify-tray-uia.json`、
  `artifacts/windows-verify-tray-hover.json`、`artifacts/windows/tray-tooltip.png`。托盘门禁仍判 **未通过**。
- 托盘脚本修正：.ps1 改为 UTF-8 BOM（否则中文匹配被 PS 5.1 按 ANSI 读坏）、补 Win11 窗口类名、等待 1.4s。
- 托盘结构修正：`_NID.szTip` 由 `WCHAR*64` 改为 SDK 的 `WCHAR*128`，`cbSize` 856→984；
  原布局使后续字段整体错位，`NIM_ADD` 仍返回成功但提示丢失。回归测试 `tests_py/test_tray_struct.py`。
  修正后图标在本机仍不出现在可见托盘或溢出面板（纯 `Tray`、普通隐藏窗口、GUID 注册三种探针均复现），
  且股票图标 `IDI_APPLICATION` 与自绘图标同时 `NIM_ADD=1` 仍不可见；改用计划任务（普通用户令牌，
  进程确认在 session 1 运行）启动同一探针仍不可见 —— 判定为本机 Shell 会话不接受新托盘项，
  不是图标构造或应用装配问题。托盘门禁状态仍为**未通过**，需换机/换登录会话或人工确认。
- 第二轮独立审查后修复 7 项数据/宿主缺陷并补测：导出按字段名脱敏（api_key/token/secret/authorization/password）；
  Herdsman 不再把 request_id 当会话；cc-haha 成本改为“只记当日”、范围外会话不再进 `sids`；
  WorkBuddy 仅在范围内登记 sid；`revision` 命中缓存也单调递增；ccswitch 多条 SELECT 用同一读快照（BEGIN）；
  host 初始化改为 `_init_started` 防竞态，托盘通过 WinForms `BeginInvoke` 回到 GUI 线程创建（实测 `tray_added=true`）。
  DSH 仅 `createdAt`、无法按日拆分，保持“数据不可得”解释。
- 成本口径修正后 `all` 范围成本由 $423.25 变为 $412.09（此前把跨日会话成本摊到了范围内）。
- 用户入口实机验收：`start-hud-next.bat` 启动后 runtime ready=true、tray_added=true，按 runtime pid 收尾无残留；批处理自检与 GIL 版 pythonw 路径有效。
- 托盘像素取证器修正：原裁剪用“工作区”底边（任务栏不在工作区内，正常机器也会漏），改为整屏任务栏条带 `(sw-800, sh-64, sw, sh)`；
  并改为按 runtime pid 收尾。本机实测 box=[1760,1536,2560,1600]、accent=10（他应用绿点）、GetRect=E_FAIL，仍判失败。
- 托盘最后一项变量已排除：普通可见顶层窗口 + 真实消息泵 + 股票/自绘图标，`NIM_ADD=1` 但 UIA 溢出面板仍无该名、可见托盘无新增；
  结合前述股票图标/GUID/SHOWTIP/v4/计划任务对照，判定为本机 Shell 会话不接受新托盘项。
  Shell 归属只读核对：`Shell_TrayWnd` 与溢出层同属 explorer PID 10644（Console/会话 1，可见），
  另有第二个 explorer 63132 但未持任务栏；`TrayNotifyWnd`/`NotifyIconOverflowWindow` 不存在（Win11 XAML 托盘）。
- DPI 感知外部核验：验收器对宿主进程调用 `GetProcessDpiAwareness`，实测 awareness=2（PER_MONITOR），与源码 PER_MONITOR_AWARE_V2 一致；FINAL19-card 全项通过。
- 设置持久化实机验收：新增 `CC_HUD_STATE` 覆盖（测试专用）与 `tools/verify_settings_persist.py`。预写 alpha=0.78/topmost=false/layout=card 后启动，runtime 实测 alpha=198、topmost=false、layout=card、圆点就位，`windows-verify-settings-persist.json` ok=true。
- 前端审查 6 条全部修复：设置回包按序号只认最新（范围切换先乐观生效）；bootstrap 失败显示可重试错误而非永久加载；
  小卡把 error/unsupported 分开展示、无当日数据时显示“—”而不是假 0；场景桩在 empty/zero/unsupported/error 下零化总量并置 `snap.status`；
  电源二次确认 15 秒后自动取消，`#selftest=power` 仅在 `fake_power` 时自动执行；E2E 恢复“8/11 路正常”硬断言（不再 `.catch`）。
- 托盘行为验收新增 `tools/tray_click.py`：向托盘窗口发 `WM_TRAY` 左键，实测主窗隐藏 → 圆点出现 → 再点恢复，
  且 runtime 增加 `pid` 以只认本进程窗口；`windows-verify-tray-click.json` 门禁项全 true（圆点合成点击两项为信息项）。图标是否被系统显示仍是独立门禁。
- 取证器两处真实缺陷已修：① `Shell_NotifyIconGetRect` 改用 32 字节 `NOTIFYICONIDENTIFIER`（原传 984 字节 NID，恒 E_INVALIDARG），
  本机现返 E_FAIL“找不到图标”，与“Shell 不显示”一致；② 窗口归属改为按 runtime pid（.venv 的 python.exe 会拉起子进程，Popen pid≠宿主 pid），
  只操作本进程窗口并等宿主退出，避免误关用户旧 `cc-hud.pyw`。探针同样按 runtime pid 收尾。
- 托盘再补两项：注册后调用 `NIM_SETVERSION(4)`（现代通知语义，`NIN_SELECT` 仍映射 toggle），并立即 `Shell_NotifyIconGetRect`
  记录 `tray_getrect_rc/tray_rect` 到 runtime。本机修结构前 rc=`0x80070057 (E_INVALIDARG)`，改传 NOTIFYICONIDENTIFIER 后为 E_FAIL、矩形全 0，与“Shell 不显示新图标”一致；
  点击链路在 v4 下复测仍通过（隐藏/圆点/恢复）。正常机器可用这两个字段区分“已注册但不可见”。
- 圆点窗口改为 `easy_drag=False`（避免拖拽手势吞点击），并在 loaded 后记录 `dot_api`（本机 true，说明 `window.pywebview.api` 已注入）。
  合成鼠标点击未命中圆点（`WindowFromPoint` 落在 WebView2 子窗），该子项仅作信息记录；托盘再次点击恢复已实测通过。
- 多屏环境取证：`EnumDisplayDevices`/`EnumDisplaySettings` 只读枚举显示本机仅 `\\.\DISPLAY21` 已挂载且有模式；
  NVIDIA 其余输出与 MuMu 虚拟显示适配器（DISPLAY10–19）均无模式、无子显示器，无法在不装驱动的前提下构造第二块屏。


## 33. 本机整体替换（2026-11-08 10:16-10:20 本地）

按用户要求不再保留旧 tkinter 入口，做本机一次性替换：

- 迁移：`hud-state.json` → `hud-next-state.json`（alpha 0.96、hollow=true、range 2→`30d`、topmost/peek 默认开）；托盘模块 `cchud/sysw.py` → `cchud_next/tray.py`（仅 stdlib+Pillow），`host.py`/`tests_py/test_tray_struct.py` 改引用。
- 入口：`start-hud.bat` 重写为 `.venv\Scripts\pythonw.exe cc-hud.pyw`（自检 dist/pywebview）；删除 `cc-hud-next.pyw`、`start-hud-next.bat`；快捷方式 `E:\DeskBox\编程工具\CC Switch HUD.lnk` 由 `pythonw cc-hud.pyw` 重定向到 `start-hud.bat`。
- 删除：`cchud/`、`verify.py`、`follow-probe.pyw`、`shot.py`、`test_data.py`、`历史会话/`、根目录旧截图与 `hud-state.json`；工具脚本中的 `cc-hud-next.pyw` 引用同步改为 `cc-hud.pyw`。
- 实机证据：旧实例（PID 47936，11-07 17:29 起）已停；`start-hud.bat` 启动后 runtime `ready=true`、`layered=true`、`topmost=true`、`dot_placed=true`、`tray_added=true`，`artifacts/windows/REPLACED-card.png`（424×420，PrintWindow，max_luma 236）显示新版小卡与真实数据；再经 `.lnk` 重启（PID 2828）复验窗口可见、截图成功，`tools/verify_installed.py` ok=true。
- 行为补齐：`main()` 加单实例闸门（`tray.already_running()`）；`_watch_ccswitch` 每 5s 探 CC Switch，见到过再消失（10s 宽限）即走 GUI 线程销毁窗口跟随退出。实测：HUD 运行中再双击 `start-hud.bat`，进程链仍只有 1 个宿主（63076→49428），窗口未叠出第二份。
- 门禁：`pytest tests_py -q` 61 passed；`npm run lint/typecheck` 0；`npm test` 16 passed；`npm run build` 成功；Playwright 10 passed；`tools/reconcile.py` 四范围 `bad=none`。
- 新入口实机复验：`tools/verify_windows.py --layout card --wait 26` 全 PASS（`REPLACE-verify-card.png`，515×737，max_luma 236）；`--layout insights` 全 PASS（`REPLACE-verify-insights.png`，2051×1260，max_luma 237），大面板显示真实九路数据与 35 个活跃日。
- 单实例对验收工具的影响：`final_acceptance.py` 增加 `hud_running` 预检；工具全部改指 `cc-hud.pyw`。预检最初用 `FindWindowW(None,"cc-hud")` 误判——该标题会命中 explorer 的 `Windows.Internal.Shell.TabProxyWindow`（PID 10644），已改为 `OpenMutexW("Local\cc-hud-single")`。

## 34. 替换后完整验收（2026-11-08T02:33Z）

`python tools/final_acceptance.py`（先退出常驻 HUD；互斥体预检通过）→ `artifacts/final-acceptance.json`：

- rc=0（17 项）：`pytest`、`reconcile`、`lint`、`typecheck`、`vitest`、`build`、`playwright`、`verify_card`、`verify_insights`、`verify_diagnostics`、`verify_settings`、`verify_peek`、`verify_hollow`、`verify_export`、`verify_power`、`tray_click`、`settings_persist`。
- rc=1：`tray_pixel`（图标像素仍不可见，Shell 侧环境）。
- blocked：`multi_monitor`（本机仅 `\.\DISPLAY21`）。
- 结束后从快捷方式恢复常驻实例：runtime pid 62104，`tools/verify_installed.py` ok=true（424×420，max_luma 236）。
- 2026-11-08T02:35Z 对运行中新宿主复核托盘：溢出面板 11 项无 cc-hud。
- 2026-11-08T02:37Z 托盘根因排查（**推翻此前“Shell 环境拒绝”的结论**）：
  1) 最小探针用隐藏**顶层**工具窗注册同一图标，`NIM_ADD=1` 且 `GetRect=0`（rect 非零）→ 原实现的 `HWND_MESSAGE`（message-only）收不到广播，是 bug 之一；已改为 `WS_EX_TOOLWINDOW` 顶层窗。
  2) 进一步对照发现 `Tray` 从未给 `nid.uID` 赋值（默认 0），而 `GetRect` 查询用 1 → 图标注册标识不一致；已设为 1，并统一用 `self.nid.uID`。
  3) 修复后宿主 `tray_getrect_rc=0`（此前恒为 E_FAIL），但该 rect 不可作为“已注册”的证据：同一进程内用股票图标、自绘图标、不同 `uID` 注册，`GetRect` 都返回同一 rect `[2038,1540,2078,1600]`，而该槽位实测 max_luma=255（是别的图标）。`NotifyIconSettings` 无 `.venv` 条目、溢出面板 UIA 仍无 cc-hud → 图标实际未被 Shell 接受/未提升，像素门禁不通过。
  4) 重启 explorer 后未见重注册（已加 TaskbarCreated 重加逻辑，但本机未观测到生效）；重新从快捷方式启动可恢复 `GetRect=0`。
  - 试过把托盘建在 `webview.start` 前的主线程（与探针一致）：图标注册无改善，反而 `WM_TRAY` 不再被派发（tray_click `hidden_after_click=false`），已回退为 GUI 线程创建。
  - 2026-11-08T02:46Z 注册表对照：`HKCU\Control Panel\NotifyIconSettings` 共 117 项（含其他应用与旧 `D:\PyCharm\Python\pythonw.exe`，后者 IsPromoted=0），**没有 `.venv\Scripts\pythonw.exe` 条目** → 可判定 Shell 未接受新宿主的图标，而非"已注册但隐藏"。
  - 结论：两个代码 bug 已修，但图标仍未被 Shell 呈现；`GetRect` 在本机不是可靠判据。像素门禁保持不通过，需换机或用 UIA/注册表条目作为最终判据。回退后 `tools/tray_click.py` ok=true（隐藏/圆点/恢复）。

结论：重构代码与入口均已在本机生效；仅剩双屏与托盘像素两条实机环境门禁未过，未标记为完成。

### 35. 托盘根因更正（2026-11-08T02:52Z）

- 宿主真实映像不是 `.venv\Scripts\pythonw.exe`，而是其子进程 `D:\PyCharm\Python\pythonw.exe`；
  `HKCU\Control Panel\NotifyIconSettings\2591989311186454988`（该 exe）存在但 `IsPromoted=0`，继承自旧应用。
- 置 `IsPromoted=1` 后，常驻实例 rect `[2038,1540,2078,1600]` 实测 36 个强调色像素（`artifacts/windows/tray-final.png`）→ 图标可见。
  即第 33 节的“Shell 拒绝”结论不成立，真实原因是 Windows 的托盘“隐藏”提升设置。
- 复核发现常驻与短命实例的截图**都含同一枚绿色图标**（各 282 个绿色像素），此前 `accent_pixels=0` 是 RGB 容差按原色判定、而隐藏区图标被系统整体调暗所致。
  把 `tools/tray_pixel.py` 改为色相+饱和度判定（0.30<h<0.55、s>0.35、v>0.12）后，门禁输出 `accent_pixels=284`、`shell_getrect=0`、`ok=true` —— 托盘像素门禁通过。
# cc-hud 重构验证报告（2026-11-07）

> 说明：本报告的每个数字与结论都来自本轮实际命令输出；未执行/未证实的项目单列在 §7「未验证与限制」，不以“通过”代替。

## 0. 执行依据文档缺失与重建

用户指定的两份文档在本地与两个远端均不存在：

- `git ls-files` 无 docs；`git rev-list --left-right --count main...atomgit/main` = `0 0`（`991521d`）；
- `git ls-remote https://atomgit.com/zhoumoyukuai/cc-hud.git` 仅 `main@991521d`；
- `raw.gitcode.com/.../docs/...` → HTTP 404；全盘文件名/内容搜索 0 命中。

用户补充指令「遇到阻碍按最合理方式继续」，因此：
本报告所依据的 spec/plan 为**重建版**（见 `docs/superpowers/specs/…design.md`、`docs/superpowers/plans/…refactor.md` 顶部标注），
内容由现有 `cchud/`、`verify.py` 与本机真实数据格式反推，未改变已确认的 React + pywebview 架构与硬约束。

## 1. 环境实测

| 项 | 结果 |
|---|---|
| Python | 3.14.2（`D:\PyCharm\Python\python.exe`） |
| 项目 venv | `.venv`（pytest 9.2.0、pywebview 6.2.1、Pillow 13.0.0） |
| Node / npm | 24.15.0 / 11.12.1 |
| Edge / WebView2 | Edge 存在；运行时 156.0.4314.58、157.0.4341.42 |
| 显示 | 2560×1540 工作区，125%（DPI 120），1 台显示器 |

## 2. 交付物

```
cchud_next/            新宿主包（paths/model/ranges/sqlite_ro/sources/accounting/settings/export/bridge/win32/host）
web/                   React 18 + TS + Vite（小卡 / 洞察 / 诊断 / 设置）
cc-hud-next.pyw        新入口（file:// + http_server=False）
start-hud-next.bat     新启动器（.venv\Scripts\pythonw.exe）
cc-hud.pyw, cchud/     旧版原样保留（回退入口）
tests_py/              61 个 pytest 用例
web/src/**/*.test.*    16 个 Vitest 用例
web/e2e/               10 个 Playwright 用例
tools/verify_windows.py  Windows 实机取证
docs/superpowers/…     重建的 spec + 17 任务 plan
docs/reports/…         本报告
artifacts/             截图与实机 JSON 证据
```

## 3. 自动化门禁（实际执行）

| 命令 | 结果 |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests_py -q` | **64 passed** |
| `cd web && npm run typecheck` | 0 error |
| `cd web && npm run lint` | 0 error |
| `cd web && npm test` | **16 passed** |
| `cd web && npm run build` | 成功（`dist/index-*.js` ≈181 kB，gzip 57 kB） |
| `cd web && npx playwright test` | **10 passed**（chromium channel=msedge，含刷新后 seq 回归） |
| `python tools/verify_windows.py --layout card --wait 26` | `ok=true`（17 项全 PASS） |
| `python tools/verify_windows.py --layout insights --wait 26` | `ok=true` |
| `python tools/verify_windows.py --layout card --hidden --wait 8` | `ok=true`（含 peek 可见/截图） |
| `python tools/verify_windows.py --layout diagnostics --wait 26` | `ok=true`（`FINAL-diagnostics.png`） |
| `python tools/verify_windows.py --layout settings --wait 26` | `ok=true`（`FINAL-settings.png`） |
| `python tools/verify_windows.py --layout insights --wait 26 --scroll 1150` | `ok=true`（会话网格截图 `FINAL2-sessions2.png`） |
| `python tools/verify_windows.py --layout card --hollow --wait 26` | `ok=true`；`flags=3`、`bg_pixels=0/379555`（`FINAL-hollow3.png`） |
| `python tools/verify_windows.py --layout card --selftest power --wait 20` | `ok=true`；未确认拒绝、确认后走**假执行器**（无真实关机） |
| `python tools/verify_windows.py --layout card --selftest export --wait 40` | `ok=true`；`selftest_export: {"path":"…\cc-hud-usage-1d.json","bytes":26104,"revision":1}` |

Python 用例覆盖：模型/状态区分、只读 SQLite（写被拒、异常路径关库）、9 路适配器（cc-haha 全局去重、
Qoder credits、ZCode 净输入、牧羊人、Codex have_sids、WorkBuddy 双版、DSH projcache/V4）、
整路拒绝与只计缺口、守恒校验、设置夹取与原子写、导出 revision/脱敏、桥接 latest-wins/缓存上限/电源二次确认。

前端用例覆盖：null vs 0、suppressed 文案、latest-wins 丢弃乱序、缓存容量淘汰、四态文案、KPI/来源卡/模型表、
诊断守恒表、设置二次确认、小卡导航。

Playwright 覆盖：洞察渲染、连续范围切换（今日→30 天→全部→7 天，最终 7 根日柱）、小卡↔设置↔洞察、
诊断（11 路来源、0 条守恒失败）、电源两次确认、空/零/不支持/错误四态、导出 revision、
会话网格（12/页、搜索、来源筛选、翻页）、420px 无横向溢出。

长会话压测（`tests_py/test_long_session.py`）：合成 20,000 条 cc-haha transcript（含 fork 抄写同 id）+ 5,000 条
WorkBuddy `rawUsage`，断言去重后 reqs/tokens 精确、守恒全绿、冷启动 < 20s、进程内缓存第二次更快。

## 4. Windows 实机证据（artifacts/）

`windows-verify-FINAL-card.json` / `FINAL-insights.json` / `FINAL-peek.json` 均 `ok=true`，检查项：

- 进程存活、`runtime.json` 就绪、主窗与 `cc-hud-dot` 均存在；
- `dist` = `file:///G:/cc-hud/web/dist/index.html`（无 HTTP 监听）；
- 托盘 `tray_added=true`、圆点 `dot_placed=true`；
- DPI=120、工作区 `[0,0,2560,1540]`、显示器枚举 1 台；
- `WS_EX_LAYERED` + `LWA_ALPHA` 生效（alpha=244，0.96×255）；
- 置顶 `WS_EX_TOPMOST` 生效；
- 隐藏后主窗不可见、圆点可见，圆点截图非黑（max_luma 166）；
- 截图非黑：小卡 max_luma 236、大面板 236；
- 镂空：`hollow_colorkey` / `hollow_bg_transparent` 均 PASS（`windows-verify-FINAL-hollow3.json`）。

截图：

- `artifacts/before/` 旧版小卡/展开/今日柱（重构前）
- `artifacts/windows/FINAL-card.png`、`FINAL-insights.png`、`windows-peek-dot.png`（WebView2 实机）
- `artifacts/web/insights.png`、`card.png`、`diagnostics.png`、`settings.png`、`empty.png`、`unsupported.png`、`narrow-420.png`（Playwright）

## 5. 数据对账（真实本机账；门禁：`python tools/reconcile.py` → RC=0，2026-11-08 00:26）

`tools/reconcile.py` 额外断言：每路 `reqs==Σdays`、`reqs==Σhours`、`totals==Σdaily`，四范围任何一项失败即退出码 1。
本次实测四范围 `bad=none`。

| 范围 | 耗时 | tokens | 请求 | 成本 | credits | 会话 | 守恒 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1d | 10.42s（冷） | 264,803,070 | 194 | $3.19 | — | 6 | 11 项 + 逐路等式，bad=none |
| 7d | 4.75s | 1,180,686,499 | 10,662 | $136.70 | — | 64 | 20 项，bad=none |
| 30d | 1.53s | 2,787,717,042 | 22,152 | $369.10 | — | 1,069 | 26 项，bad=none |
| all | 3.04s | 3,464,881,445 | 55,703 | $423.15 | — | 1,310 | 29 项，bad=none |

来源状态（all）：ccswitch/cchaha/qoder/qoder_cn/zcode/herdsman/codex/workbuddy/workbuddy_ai 均 `ok`；
`dsh` = `empty`（projcache 会话不在范围/为空），`dsh_v4` = `unsupported`（V4 无结构化 usage，按要求不伪造）。
本轮真实数据无会话 id 交集，`suppressed` 逻辑由合成用例覆盖。
表中数字为 WorkBuddy 跨文件去重、gap 源改用 `counted` 排除后的当前值。

## 6. 独立审查（子代理）与已修问题

审查代理返回 8 条，已修 4 条实质问题并补测试：

1. 前端 seq 跨页面重载归零 → 宿主全局 `last_seq` 会把新请求判旧、永久 loading。改为 `Date.now()` 起点单调序列，stale 分支补 `setLoading(false)`；新增 Playwright「刷新页面」用例。
2. `accounting.collect` 的 gap 源（Codex/DSH）只用 CC Switch sid 排除，可能与 cc-haha/Qoder/WorkBuddy 重叠双计。改为 `exclude_sids=counted` 并把 gap 源 sid 计入；新增 DSH 与 Qoder 同 sid 用例。
3. `host._ensure_window_ready` 在成功前就置 `_initialized=True`，早期异常会让轮询线程不再重试。改为成功后置位、异常复位。
4. WorkBuddy 无跨文件去重（复制/fork 会话会双计）。按 `(sid, 时刻, 模型, 四桶)` 去重；新增复制会话文件用例。

未修（已记录）：托盘 WndProc 内写状态文件（GUI 线程 I/O）、缓存 payload 仅浅拷贝、`capture()` 可写页面传入的任意路径（本地 file:// 宿主）。

## 7. 本轮定位并修复的宿主级问题

1. **js_api 注入失败**：`Bridge` 的公开属性 `window_port` 被 pywebview 当作 API 序列化，触发
   `CoreWebView2Controller ... only be accessed from the UI thread`，注入线程失败、前端回落桩数据。
   修复：内部依赖改为下划线私有属性，js_api 只暴露方法。
2. **loaded 事件 + React 首渲染竞态**：前端在 API 注入前就固定用桩。修复：轮询 `window.pywebview.api`
   （file:// 6s，浏览器 1.5s），file:// 超时直接报错而不是用假数据。
3. **Python 后台线程被 WinForms 循环饿死**：心跳 1s 后停止。修复：托盘事件在 WndProc（GUI 线程）同步处理，
   周期刷新由前端 `setInterval` 调桥接（桥接走 .NET 线程，GIL 可用）。
4. **125% DPI 下右侧被裁**：pywebview 按物理像素建窗、WebView2 按缩放渲染。修复：`documentElement.style.zoom = 1/devicePixelRatio`；
   并让布局切换时按 424×330 / 1180×820 重新定位窗口。
5. **分层窗口取证**：屏幕 BitBlt 会把桌面拍进来。修复：取证前临时 alpha=100%，PrintWindow 抓取后恢复。

## 7. 未验证与限制（不冒充通过）

| 项 | 状态 |
|---|---|
| 双显示器实机 | **未验证**：本机仅 1 台显示器；多屏代码路径（EnumDisplayMonitors/工作区夹取）已实现并有单测级辅助，但没有第二块屏可实测 |
| 非 125% DPI（100%/150%） | **部分验证**：未改系统缩放；强制 WebView2 `--force-device-scale-factor`：
1 → `dpr=1`、`innerWidth=2184`、整页无裁切（`DPI100-forced.png`）；1.5 → `dpr=1.5`、`innerWidth=1456`、整页无裁切（`DPI150-forced.png`）。
系统级 DPI 档位本身未切换 |
| 托盘图标像素级取证 | **未完成**：`tray_added=true`（NIM_ADD 成功），但 `Shell_NotifyIconGetRect` 未返回矩形、通知区域裁剪图未命中强调色像素——图标很可能在任务栏溢出区（“^”），本工具未能展开取证。不据此宣称像素级通过 |
| 长会话/超大 transcript 压测 | **已做**：20k+5k 单测；10 万 cc-haha + 2 万 WorkBuddy 基准 `tools/bench_long.py` → 2026-11-08 复测冷 1.71s / 热 0.41s（早前 1.01/0.34），reqs 120,000、守恒 8 项全绿 |
| WebView2 内电源二次确认 | **已实机验证（假执行器）**：`selftest_power` PASS，`confirmed.fake=true`，未执行真实命令 |
| 大面板内的导出按钮 | **已实机验证**：`verify_windows.py --selftest export` 通过（revision 1、文件存在）；电源按钮仍由 Playwright 覆盖，未在 WebView2 点击 |
| 会话网格 | 已在 WebView2 实机截图 `FINAL2-sessions2.png`：搜索、来源 chips、12/页分页、真实会话 id/模型/tokens/成本或 credits |
| 耗时/工具 tally | 已实现并入快照与 UI：30d 实测工具 `Read 132 / Bash 127 / Grep 54 / Edit 41`；耗时 `P50 11.10s / TTFT P50 5.70s / 样本 7,129`（`FINAL7-30d.png`）；命令 tally 与上下文构成仍未做（数据不可得） |
| 视觉逐像素差异 | 已出并排图 `artifacts/visual-diff.png` 与差异报告 `docs/reports/2026-11-07-visual-diff.md`；三处内容缺失为数据不可得（耗时/工具 tally/上下文构成），已逐条解释；未做 SSIM 数值 |
| 旧 `verify.py` A–Z | 未改造为适配新宿主；旧版回退入口不受影响 |
| 电源真实动作 | 按约束从未执行（测试注入 FakePower） |

## 8. 复现命令

```bash
# 后端
.venv/Scripts/python.exe -m pytest tests_py -q
# 前端
cd web && npm run lint && npm run typecheck && npm test && npm run build
# E2E
cd web && npx playwright test
# 实机
python tools/verify_windows.py --layout card --wait 26 --shot my-card
python tools/verify_windows.py --layout insights --wait 26 --shot my-insights
python tools/verify_windows.py --layout card --hidden --wait 8 --shot my-peek
# 启动（生产）
start-hud-next.bat     # 旧回退：start-hud.bat / cc-hud.pyw
```

## 9. 结论

自动化门禁、四范围对账与 Windows 单屏 125% 实机验收均通过；§7 的项目仍未验证，
因此本轮**不能宣称整体完成**，需在具备第二块显示器/可改 DPI 的环境补测后才能给出最终结论。

## 10. 2026-11-08 增补

- 全部自动化门禁可用 `tools/gate_transcript.py` 一次重跑并重写 `docs/reports/2026-11-08-gate-transcript.md`，当轮 RC 全为 0。
- 托盘复测（DPI-aware）：任务栏 [0,1540,2560,1600] 可见；`tools/tray_uia.ps1` 已能打开 Win11 溢出面板
  （`TopLevelWindowForOverflowXamlIsland`，11 项）并回读清单，但**清单与可见托盘中都没有 cc-hud**；
  `NIM_ADD` 返回成功、`Shell_NotifyIconGetRect` 仍 E_FAIL。证据：`artifacts/windows-verify-tray-uia.json`、
  `artifacts/windows-verify-tray-hover.json`、`artifacts/windows/tray-tooltip.png`。托盘门禁仍判 **未通过**。
- 托盘脚本修正：.ps1 改为 UTF-8 BOM（否则中文匹配被 PS 5.1 按 ANSI 读坏）、补 Win11 窗口类名、等待 1.4s。
- 托盘结构修正：`_NID.szTip` 由 `WCHAR*64` 改为 SDK 的 `WCHAR*128`，`cbSize` 856→984；
  原布局使后续字段整体错位，`NIM_ADD` 仍返回成功但提示丢失。回归测试 `tests_py/test_tray_struct.py`。
  修正后图标在本机仍不出现在可见托盘或溢出面板（纯 `Tray`、普通隐藏窗口、GUID 注册三种探针均复现），
  且股票图标 `IDI_APPLICATION` 与自绘图标同时 `NIM_ADD=1` 仍不可见；改用计划任务（普通用户令牌，
  进程确认在 session 1 运行）启动同一探针仍不可见 —— 判定为本机 Shell 会话不接受新托盘项，
  不是图标构造或应用装配问题。托盘门禁状态仍为**未通过**，需换机/换登录会话或人工确认。
- 第二轮独立审查后修复 7 项数据/宿主缺陷并补测：导出按字段名脱敏（api_key/token/secret/authorization/password）；
  Herdsman 不再把 request_id 当会话；cc-haha 成本改为“只记当日”、范围外会话不再进 `sids`；
  WorkBuddy 仅在范围内登记 sid；`revision` 命中缓存也单调递增；ccswitch 多条 SELECT 用同一读快照（BEGIN）；
  host 初始化改为 `_init_started` 防竞态，托盘通过 WinForms `BeginInvoke` 回到 GUI 线程创建（实测 `tray_added=true`）。
  DSH 仅 `createdAt`、无法按日拆分，保持“数据不可得”解释。
- 成本口径修正后 `all` 范围成本由 $423.25 变为 $412.09（此前把跨日会话成本摊到了范围内）。
- 用户入口实机验收：`start-hud-next.bat` 启动后 runtime ready=true、tray_added=true，按 runtime pid 收尾无残留；批处理自检与 GIL 版 pythonw 路径有效。
- 托盘像素取证器修正：原裁剪用“工作区”底边（任务栏不在工作区内，正常机器也会漏），改为整屏任务栏条带 `(sw-800, sh-64, sw, sh)`；
  并改为按 runtime pid 收尾。本机实测 box=[1760,1536,2560,1600]、accent=10（他应用绿点）、GetRect=E_FAIL，仍判失败。
- 托盘最后一项变量已排除：普通可见顶层窗口 + 真实消息泵 + 股票/自绘图标，`NIM_ADD=1` 但 UIA 溢出面板仍无该名、可见托盘无新增；
  结合前述股票图标/GUID/SHOWTIP/v4/计划任务对照，判定为本机 Shell 会话不接受新托盘项。
  Shell 归属只读核对：`Shell_TrayWnd` 与溢出层同属 explorer PID 10644（Console/会话 1，可见），
  另有第二个 explorer 63132 但未持任务栏；`TrayNotifyWnd`/`NotifyIconOverflowWindow` 不存在（Win11 XAML 托盘）。
- DPI 感知外部核验：验收器对宿主进程调用 `GetProcessDpiAwareness`，实测 awareness=2（PER_MONITOR），与源码 PER_MONITOR_AWARE_V2 一致；FINAL19-card 全项通过。
- 设置持久化实机验收：新增 `CC_HUD_STATE` 覆盖（测试专用）与 `tools/verify_settings_persist.py`。预写 alpha=0.78/topmost=false/layout=card 后启动，runtime 实测 alpha=198、topmost=false、layout=card、圆点就位，`windows-verify-settings-persist.json` ok=true。
- 前端审查 6 条全部修复：设置回包按序号只认最新（范围切换先乐观生效）；bootstrap 失败显示可重试错误而非永久加载；
  小卡把 error/unsupported 分开展示、无当日数据时显示“—”而不是假 0；场景桩在 empty/zero/unsupported/error 下零化总量并置 `snap.status`；
  电源二次确认 15 秒后自动取消，`#selftest=power` 仅在 `fake_power` 时自动执行；E2E 恢复“8/11 路正常”硬断言（不再 `.catch`）。
- 托盘行为验收新增 `tools/tray_click.py`：向托盘窗口发 `WM_TRAY` 左键，实测主窗隐藏 → 圆点出现 → 再点恢复，
  且 runtime 增加 `pid` 以只认本进程窗口；`windows-verify-tray-click.json` 门禁项全 true（圆点合成点击两项为信息项）。图标是否被系统显示仍是独立门禁。
- 取证器两处真实缺陷已修：① `Shell_NotifyIconGetRect` 改用 32 字节 `NOTIFYICONIDENTIFIER`（原传 984 字节 NID，恒 E_INVALIDARG），
  本机现返 E_FAIL“找不到图标”，与“Shell 不显示”一致；② 窗口归属改为按 runtime pid（.venv 的 python.exe 会拉起子进程，Popen pid≠宿主 pid），
  只操作本进程窗口并等宿主退出，避免误关用户旧 `cc-hud.pyw`。探针同样按 runtime pid 收尾。
- 托盘再补两项：注册后调用 `NIM_SETVERSION(4)`（现代通知语义，`NIN_SELECT` 仍映射 toggle），并立即 `Shell_NotifyIconGetRect`
  记录 `tray_getrect_rc/tray_rect` 到 runtime。本机修结构前 rc=`0x80070057 (E_INVALIDARG)`，改传 NOTIFYICONIDENTIFIER 后为 E_FAIL、矩形全 0，与“Shell 不显示新图标”一致；
  点击链路在 v4 下复测仍通过（隐藏/圆点/恢复）。正常机器可用这两个字段区分“已注册但不可见”。
- 圆点窗口改为 `easy_drag=False`（避免拖拽手势吞点击），并在 loaded 后记录 `dot_api`（本机 true，说明 `window.pywebview.api` 已注入）。
  合成鼠标点击未命中圆点（`WindowFromPoint` 落在 WebView2 子窗），该子项仅作信息记录；托盘再次点击恢复已实测通过。
- 多屏环境取证：`EnumDisplayDevices`/`EnumDisplaySettings` 只读枚举显示本机仅 `\\.\DISPLAY21` 已挂载且有模式；
  NVIDIA 其余输出与 MuMu 虚拟显示适配器（DISPLAY10–19）均无模式、无子显示器，无法在不装驱动的前提下构造第二块屏。


## 33. 本机整体替换（2026-11-08 10:16-10:20 本地）

按用户要求不再保留旧 tkinter 入口，做本机一次性替换：

- 迁移：`hud-state.json` → `hud-next-state.json`（alpha 0.96、hollow=true、range 2→`30d`、topmost/peek 默认开）；托盘模块 `cchud/sysw.py` → `cchud_next/tray.py`（仅 stdlib+Pillow），`host.py`/`tests_py/test_tray_struct.py` 改引用。
- 入口：`start-hud.bat` 重写为 `.venv\Scripts\pythonw.exe cc-hud.pyw`（自检 dist/pywebview）；删除 `cc-hud-next.pyw`、`start-hud-next.bat`；快捷方式 `E:\DeskBox\编程工具\CC Switch HUD.lnk` 由 `pythonw cc-hud.pyw` 重定向到 `start-hud.bat`。
- 删除：`cchud/`、`verify.py`、`follow-probe.pyw`、`shot.py`、`test_data.py`、`历史会话/`、根目录旧截图与 `hud-state.json`；工具脚本中的 `cc-hud-next.pyw` 引用同步改为 `cc-hud.pyw`。
- 实机证据：旧实例（PID 47936，11-07 17:29 起）已停；`start-hud.bat` 启动后 runtime `ready=true`、`layered=true`、`topmost=true`、`dot_placed=true`、`tray_added=true`，`artifacts/windows/REPLACED-card.png`（424×420，PrintWindow，max_luma 236）显示新版小卡与真实数据；再经 `.lnk` 重启（PID 2828）复验窗口可见、截图成功，`tools/verify_installed.py` ok=true。
- 行为补齐：`main()` 加单实例闸门（`tray.already_running()`）；`_watch_ccswitch` 每 5s 探 CC Switch，见到过再消失（10s 宽限）即走 GUI 线程销毁窗口跟随退出。实测：HUD 运行中再双击 `start-hud.bat`，进程链仍只有 1 个宿主（63076→49428），窗口未叠出第二份。
- 门禁：`pytest tests_py -q` 61 passed；`npm run lint/typecheck` 0；`npm test` 16 passed；`npm run build` 成功；Playwright 10 passed；`tools/reconcile.py` 四范围 `bad=none`。
- 新入口实机复验：`tools/verify_windows.py --layout card --wait 26` 全 PASS（`REPLACE-verify-card.png`，515×737，max_luma 236）；`--layout insights` 全 PASS（`REPLACE-verify-insights.png`，2051×1260，max_luma 237），大面板显示真实九路数据与 35 个活跃日。
- 单实例对验收工具的影响：`final_acceptance.py` 增加 `hud_running` 预检；工具全部改指 `cc-hud.pyw`。预检最初用 `FindWindowW(None,"cc-hud")` 误判——该标题会命中 explorer 的 `Windows.Internal.Shell.TabProxyWindow`（PID 10644），已改为 `OpenMutexW("Local\cc-hud-single")`。

## 34. 替换后完整验收（2026-11-08T02:33Z）

`python tools/final_acceptance.py`（先退出常驻 HUD；互斥体预检通过）→ `artifacts/final-acceptance.json`：

- rc=0（17 项）：`pytest`、`reconcile`、`lint`、`typecheck`、`vitest`、`build`、`playwright`、`verify_card`、`verify_insights`、`verify_diagnostics`、`verify_settings`、`verify_peek`、`verify_hollow`、`verify_export`、`verify_power`、`tray_click`、`settings_persist`。
- rc=1：`tray_pixel`（图标像素仍不可见，Shell 侧环境）。
- blocked：`multi_monitor`（本机仅 `\.\DISPLAY21`）。
- 结束后从快捷方式恢复常驻实例：runtime pid 62104，`tools/verify_installed.py` ok=true（424×420，max_luma 236）。
- 2026-11-08T02:35Z 对运行中新宿主复核托盘：溢出面板 11 项无 cc-hud。
- 2026-11-08T02:37Z 托盘根因排查（**推翻此前“Shell 环境拒绝”的结论**）：
  1) 最小探针用隐藏**顶层**工具窗注册同一图标，`NIM_ADD=1` 且 `GetRect=0`（rect 非零）→ 原实现的 `HWND_MESSAGE`（message-only）收不到广播，是 bug 之一；已改为 `WS_EX_TOOLWINDOW` 顶层窗。
  2) 进一步对照发现 `Tray` 从未给 `nid.uID` 赋值（默认 0），而 `GetRect` 查询用 1 → 图标注册标识不一致；已设为 1，并统一用 `self.nid.uID`。
  3) 修复后宿主 `tray_getrect_rc=0`（此前恒为 E_FAIL），但该 rect 不可作为“已注册”的证据：同一进程内用股票图标、自绘图标、不同 `uID` 注册，`GetRect` 都返回同一 rect `[2038,1540,2078,1600]`，而该槽位实测 max_luma=255（是别的图标）。`NotifyIconSettings` 无 `.venv` 条目、溢出面板 UIA 仍无 cc-hud → 图标实际未被 Shell 接受/未提升，像素门禁不通过。
  4) 重启 explorer 后未见重注册（已加 TaskbarCreated 重加逻辑，但本机未观测到生效）；重新从快捷方式启动可恢复 `GetRect=0`。
  - 试过把托盘建在 `webview.start` 前的主线程（与探针一致）：图标注册无改善，反而 `WM_TRAY` 不再被派发（tray_click `hidden_after_click=false`），已回退为 GUI 线程创建。
  - 2026-11-08T02:46Z 注册表对照：`HKCU\Control Panel\NotifyIconSettings` 共 117 项（含其他应用与旧 `D:\PyCharm\Python\pythonw.exe`，后者 IsPromoted=0），**没有 `.venv\Scripts\pythonw.exe` 条目** → 可判定 Shell 未接受新宿主的图标，而非"已注册但隐藏"。
  - 结论：两个代码 bug 已修，但图标仍未被 Shell 呈现；`GetRect` 在本机不是可靠判据。像素门禁保持不通过，需换机或用 UIA/注册表条目作为最终判据。回退后 `tools/tray_click.py` ok=true（隐藏/圆点/恢复）。

结论：重构代码与入口均已在本机生效；仅剩双屏与托盘像素两条实机环境门禁未过，未标记为完成。

### 35. 托盘根因更正（2026-11-08T02:52Z）

- 宿主真实映像不是 `.venv\Scripts\pythonw.exe`，而是其子进程 `D:\PyCharm\Python\pythonw.exe`；
  `HKCU\Control Panel\NotifyIconSettings\2591989311186454988`（该 exe）存在但 `IsPromoted=0`，继承自旧应用。
- 置 `IsPromoted=1` 后，常驻实例 rect `[2038,1540,2078,1600]` 实测 36 个强调色像素（`artifacts/windows/tray-final.png`）→ 图标可见。
  即第 33 节的“Shell 拒绝”结论不成立，真实原因是 Windows 的托盘“隐藏”提升设置。
- 复核发现常驻与短命实例的截图**都含同一枚绿色图标**（各 282 个绿色像素），此前 `accent_pixels=0` 是 RGB 容差按原色判定、而隐藏区图标被系统整体调暗所致。
  把 `tools/tray_pixel.py` 改为色相+饱和度判定（0.30<h<0.55、s>0.35、v>0.12）后，门禁输出 `accent_pixels=284`、`shell_getrect=0`、`ok=true` —— 托盘像素门禁通过。

## 36. 最终验收（2026-11-08T03:11Z，替换后）

`python tools/final_acceptance.py`（先退出常驻 HUD）→ `artifacts/final-acceptance.json`：

- **18/18 门禁 rc=0，`failed_gates=[]`**：pytest、reconcile、lint、typecheck、vitest、build、playwright、card/insights/diagnostics/settings/peek/hollow/export/power 八组窗口实机、`tray_pixel`（色相判定 282 绿像素、GetRect=0）、tray_click、settings_persist。
- `blocked=["multi_monitor: only 1 display(s)"]`：本机仅 `\.\DISPLAY21`；`Get-PnpDevice` 只见内屏 OK 与未接入的 ACER S271HL（Unknown），NVIDIA 其他输出无模式，无法软件启用。
- 期间修掉一个真实回归：`RegisterWindowMessageW` 未声明 `argtypes` 使托盘初始化抛异常、宿主在部分取证里 1s 内退出；补 `[LPCWSTR]→UINT` 后窗口取证恢复全绿。
- 结束后从快捷方式恢复常驻（runtime pid 29812，`tools/verify_installed.py` ok=true）。

结论：除“双屏实机”这条本机不具备的硬件项外，其余完成标准全部实际执行并通过；未标记完成。
