# 2026-11-10 托盘 / 布局 / 启动 验收报告

日期：2026-11-11（按目标日期命名）
基线：`main` @ `2f96309`；改造在本地工作区，**未 push / 未操作远端**。
机器：单显示器 `\\.\DISPLAY1` 2560×1600（工作区 2560×1540），系统 DPI 120（125%）。

## 1. 修改文件清单

| 文件 | 作用 |
|---|---|
| `cchud_next/menu.py`（新增） | 唯一命令模型：`build/walk/leaves/resolve/is_known/patch_for`；托盘与主面板共用 |
| `cchud_next/bench.py`（新增） | 启动耗时打点（进程内相对毫秒） |
| `cchud_next/host.py` | 删第二窗口与 `_place_dot`；`show/hide` 去 dot；`_tray_ok()` + 拒绝隐藏兜底；`menu_items/run_menu`；托盘选中优先交前端；托盘在 `ready` 前落账 |
| `cchud_next/tray.py` | 左右键事件分组 + 300ms 去抖；`popup()` 原生菜单（DestroyMenu 释放）；修两处既有建窗缺陷（字段早于 WndProc、`RegisterClassExW` 缺 argtypes） |
| `cchud_next/bridge.py` | `menu_model()` / `menu_command()`，设置类仍走 `set_settings` 事务，电源仍走 `power(action, confirmed)` |
| `cchud_next/settings.py` | `peek` 保留读取（兼容旧配置），注释标废弃 |
| `start-hud.bat` | 删除第二个 `pythonw -c "import webview"` 预检进程 |
| `cc-hud.pyw` | 启动失败/缺依赖 → MessageBox + `artifacts/startup-error.log` |
| `web/src/components/ContextMenu.tsx`（新增） | 主面板右键菜单（Esc / 点外部关闭 / 子菜单 / 危险项样式） |
| `web/src/App.tsx` | 阻止默认右键、`openMenu`、`runMenu`（菜单命令统一分发）、`window.__cchudTrayMenu` |
| `web/src/views/InsightsView.tsx` | 检测区下沉到会话与数据来源之后、页脚之前；守恒宽屏两列 |
| `web/src/styles/app.css` | `.checks-zone/.timing-wide/.checks-2col` 与右键菜单局部样式（不动全局 token） |
| `web/src/views/SettingsView.tsx` / `DiagnosticsView.tsx` | 移除 peek 开关与“呼出圆点”行 |
| `web/src/types.ts` / `web/src/api/bridge.ts` | `MenuNode/MenuModel` 与 `menu_model/menu_command`（native + stub） |
| `web/peek.html`（删除） | 圆点页面 |
| `tests_py/test_menu_tray.py`（新增） | 菜单模型/分发/托盘语义/去抖/旧配置兼容 共 20 条 |
| `tests_py/test_host_lifecycle.py` / `hostfakes.py` | 改为守“无 dot”；新增托盘不可用兜底、dot 不存在 |
| `tools/bench_startup.py`（新增） | 冷/热多轮、进程树、常驻内存；支持 `--root` 对比改造前 worktree |
| `tools/tray_click.py` | 改写：左键只切一次（含重复消息）/ 右键只弹菜单 / ESC 收起 / 无小圆点 |
| `tools/verify_windows.py` | `dot_window` → `no_dot_window`+`single_window_only`；hidden 分支查“无圆点+托盘可用”；等托盘落账 |
| `tools/verify_settings_persist.py` | 旧 peek 配置可读 + 无 dot + 托盘存在 |
| `tools/final_acceptance.py` | `verify_peek` → `verify_hidden_tray`；新增 `bench_startup` 门禁 |
| `web/src/views/views.test.tsx` / `web/src/app.test.tsx` / `web/e2e/insights.spec.ts` | 新的布局与菜单断言 |
| `README.md` | 启动方式、托盘/右键交互、测试命令与实测数字 |
| `docs/superpowers/specs|plans/2026-11-10-*`、本报告 | 设计与计划、验收证据 |

## 2. 托盘 / 主面板右键菜单最终结构

```
隐藏主面板 / 显示主面板        （托盘不可用时置灰）
────────
视图 ›      小卡 / 洞察 / 诊断 / 设置              （radio，选中打勾）
统计范围 ›  今日 / 7 天 / 30 天 / 全部             （radio）
────────
刷新数据
导出 JSON
────────
显示设置 ›  透明度 › 100/96/92/86/78%              （radio）
            窗口置顶 / 小卡圆角镂空               （check）
            主题 › 深色 / 浅色                    （radio）
            打开设置页…
────────
电源（危险操作）›  锁定/睡眠/休眠/关机/重启/注销   （仍需二次确认）
────────
退出程序                                       （danger）
```

capture / dpi / place / selftest 不进菜单（`menu.is_known()` 白名单也不放行）。

## 3. 洞察页内容顺序（自上而下）

KPI（3×2）与每日 token → token 构成 / 按应用 → 活跃热力图 / 工具调用 / 模型（整行）
→ 会话网格 → 数据来源 → **底部检测区（耗时宽卡 → 守恒校验，宽屏两列）** → 页脚。

## 4. 删除的悬浮窗口 / 死代码 / 冗余步骤

- `webview.create_window("cc-hud-dot", …)` 整个第二窗口、`Host.dot`、`_place_dot()`、`startup step "dot"`、
  `status["dot_hwnd"|"dot_placed"|"peek_visible"|"dot_created"]` 的实际含义（前者删除，`dot_created` 固定 False）。
- `web/peek.html`；`host.py` 的 `PEEK`、`BG_COLORREF`（圆点颜色键专用）。
- `start-hud.bat` 里第二个 pythonw 预检进程（`import webview` 只导一次）。
- 设置页 peek 开关、诊断页“呼出圆点”行。

## 5. 实际执行命令与结果

`artifacts/final-acceptance.json`（本次运行，20 个门禁）：

| 门禁 | rc | 耗时 |
|---|---|---|
| pytest | 0 | 2.1s |
| reconcile | 0 | 23.4s |
| lint | 0 | 2.1s |
| typecheck | 0 | 3.0s |
| vitest | 0 | 5.9s |
| build | 0 | 3.8s |
| playwright | 0 | 46.6s |
| verify_layout_switch | 0 | 62.4s |
| bench_startup | 0 | 72.1s |
| verify_card / insights / diagnostics / settings | 0 | 各 ~34s |
| verify_hidden_tray | 0 | 15.4s |
| verify_hollow | 0 | 35.6s |
| verify_export | 0 | 52.2s |
| verify_power | 0 | 38.5s |
| tray_pixel | 0 | 4.7s |
| tray_click | 0 | 7.9s |
| settings_persist | 0 | 4.5s |

结论：`failed_gates: []`；`blocked: ["multi_monitor: only 1 display(s)"]` → 脚本 rc=1 **仅因多屏阻塞**（本机只有一台显示器，按约定标注 blocked）。
测试数量：pytest **114 passed**、vitest **29 passed**、playwright **13 passed**、reconcile 四段 `bad=none`。

`tools/tray_click.py` 实测（全 true）：
`ready / tray_added / tray_hwnd / initial_visible / no_dot_window / dot_created_false /
hidden_after_click / stays_hidden_on_duplicate_message / right_click_opened_menu /
right_click_keeps_hidden / menu_closed_after_escape / shown_after_second_click`

`tools/verify_windows.py --hidden`：`visible=false`、`tray_available_when_hidden=true`、`no_dot_when_hidden=true`。

## 6. 启动速度前后实测

方法：`tools/bench_startup.py --rounds 5`；冷启动每轮先结束 HUD 并删除 profile 目录，
热启动复用同一 profile；指标 = `Popen → runtime.json 中 ready=true`，取 5 轮中位数。
改造前数据来自 `git worktree add ../cc-hud-baseline 2f96309`（`web/dist` 用同一份构建产物）。

| 指标 | 改造前 | 改造后 | 变化 |
|---|---|---|---|
| 冷启动 ready 中位数 | **2283.0 ms** | **2028.1 ms** | −255 ms（−11.2%） |
| 冷启动区间 | 2075.8 – 2536.7 | 1978.2 – 2333.9 | — |
| 热启动 ready 中位数 | **2638.4 ms** | **1799.4 ms** | −839 ms（−31.8%） |
| 热启动区间 | 2331.1 – 2839.4 | 1521.6 – 1976.8 | — |
| 进程树进程数（冷） | 9 | 8 | −1 |
| `msedgewebview2.exe` 数 | 7 | 6 | **−1（第二个 WebView2 窗口）** |
| 整树私有内存（冷） | 248.2 MB | 239.4 MB | −8.8 MB |
| `dot_created_seen` | `["True"]` | `["False"]` | 第二窗口确认消失 |

确定有效的两项：① 删除第二窗口（进程树 9→8、WebView2 7→6，内存 −9MB）；
② 启动器少一次 `import webview` + 少一个进程。耗时数字同机同服务波动较大（±200~400ms），
故以中位数与区间共同呈现，不宣称单轮极值。

## 7. 截图与证据位置

`artifacts/windows/`：`ACCEPT-card.png`(530×412)、`ACCEPT-insights.png`(1475×1000)、
`ACCEPT-diagnostics.png`(1350×950)、`ACCEPT-settings.png`(950×800)、
`ACCEPT-hidden.png`（隐藏态：无圆点）、`ACCEPT-hollow.png`、`ACCEPT-power.png`、`ACCEPT-export.png`；
`web/` Playwright 截图 `insights-density.png`（宽屏两列）、`narrow-checks.png`（窄屏单列）。
JSON：`artifacts/final-acceptance.json`、`artifacts/windows-verify-*.json`、
`artifacts/windows-verify-tray-click.json`、`artifacts/startup-bench-{before,after}.json`。

## 8. 仍未解决 / 未验证

1. **多显示器**：本机只有 1 屏，`verify_layout_switch` 的 `multi_monitor` 记为 **blocked**，未验证。
2. **100% / 150% DPI**：系统固定 125%，`dpi96/dpi144` 是强制倍率模拟（通过），非真实系统缩放。
3. **托盘菜单点击项选择**：`tray_click` 只验证“右键弹菜单且不改显隐 + ESC 收起”；
   菜单项本身被点中的路径由单测（`test_tray_menu_pick_*`）与前端
   `__cchudTrayMenu` 单测覆盖，未做真实鼠标点菜单项取证。
4. **托盘图标在溢出面板中的可见性**：仍用 `tray_pixel.py` 的既有门禁（本次 rc=0），
   未额外验证“Win11 折叠后在箭头面板内”的可见性。
5. 启动耗时属本机同服务测量，不等于 CI 环境；波动大，仅报中位数与区间。

## 9. git status 与本地提交

改造前工作区干净（HEAD `2f96309`）。本次改动全部留在本地工作区，
**未 commit、未 push**，符合目标中“可以在本地创建清晰 commit，但不要 push”的约束（本轮选择不提交）。
`git status` 见交付时输出。
