# 窗口密度与布局切换改造报告（2026-11-08）

基线：`48ffe481f505d088f91707ed0dcf3e9bbaa9a85c`。工作区为未提交修改，未执行 commit / push / merge，未执行真实电源动作。九路统计公式、数据源、快照、聚合未改动。

## 一、根因与修法（本次新发现）

运行时 `SetWindowPos` 把大面板设成目标尺寸后 **约 0.6–1.0 秒**，pywebview/WinForms 会再走一遍框架布局：
把窗口改成 2202×1340，并按这个“旧尺寸”重新居中（实测序列 1475×1000 @542,270 → 2202×1340 → 219,119 → 179,100）。

定位过程（证据链）：
1. 宿主 `status.rect` 一直是 1475×1000（SetWindowPos 返回值也正确），但 `GetWindowRect` 变成 2202×1340。
2. 在 GUI 线程挂了 `Form.SizeChanged`：跳变发生时 **没有任何 Python 调用栈**（只到 `Application.Run`），`WindowState` 仍为 Normal、`MaximumSize=(0,0)`、`MaxWindowTrackSize=2582×1622`，说明不是最大化、不是最大跟踪尺寸夹取。
3. 启动时用 `CC_HUD_LAYOUT=insights` 直接进大面板 **不跳**；只有“点击触发”的 resize 才跳。
4. 外部在跳变后再设一次目标矩形，窗口稳定不再跳（一次性事件，不是无限对抗）。

修法（`cchud_next/host.py`）：
- `apply_settings` 的全部原生窗口操作经 `_run_on_gui()` 编组到 WinForms GUI 线程（跨线程改窗口属性会被框架事后改写）。
- `_pin_native_size()`：每次布局切换把 `MinimumSize=MaximumSize=该布局物理尺寸`，并把 `StartPosition` 改为 `Manual`；框架那次重排被夹回目标尺寸。
- `_start_rect_guard()`：切换后 1.6 秒内每 40ms 校验一次真实矩形，漂移立刻纠回（实测 0.83s 被改、0.93s 已回位），计数写入 `status.rect_guard_fixes`。
- 小卡圆角区域改为按 **真实窗口矩形** 生成（`CC_HUD_SIZE` 覆盖尺寸时也不会裁掉下半截）。
- `apply_settings` 失败路径仍整体回滚并抛可读异常；`status.layout/rect` 只在成功后写入。

## 二、修改清单

后端
- `cchud_next/settings.py`：`LAYOUT_SIZES`（card 424×330 / insights 1180×800 / diagnostics 1080×760 / settings 760×640）与 `use_colorkey()` 策略。
- `cchud_next/bridge.py`：设置事务——`validate` 生成候选 → `window.apply_settings(candidate)` → 成功才落盘；异常不再吞掉。
- `cchud_next/host.py`：布局比较 + 统一 `_apply_layout_size`；非布局设置不再 `place()`；GUI 线程编组；Min/Max 钉死；矩形守卫；小卡回位 `_card_pos`；最小尺寸 360×300；`hollow` 与小卡共用策略；selftest 固定目标上报；区域按真实矩形。
- `cchud_next/win32.py`：`place` 支持居中；`rect/move/client_origin`；`set_round_region/clear_region/region_state`；`set_topmost` 补 argtypes（修复 -1 句柄截断）。

前端
- `web/src/App.tsx`：布局失败保留原视图 + 错误提示；`navigate` 不产生 unhandled rejection；串行 latest-wins；selftest 目标在 **滚动/缩放后重新上报**（用真实滚轮验证页内滚动目标）。
- `web/src/state/useSnapshot.ts`：范围切换保留旧快照，消除透明空窗。
- `web/src/views/InsightsView.tsx`：KPI 6 项固定 3×2；tiles 顺序 热力/工具/模型(wide)/耗时/守恒；稳定 `data-testid`。
- `web/src/views/DiagnosticsView.tsx`：新增“设置”入口（`nav-settings`），使 card→…→diagnostics→settings 链路可走。
- `web/src/views/CardView.tsx`、`SettingsView.tsx`：selftest 目标 id；文案“小卡圆角镂空”。
- `web/src/styles/app.css`：`.app` 100% 宽高；`.page` min-height:0、底 padding 24/20；KPI 3 列（640 两列、460 单列）；tiles 2 列（560 单列）；小卡铺满；大面板不透明。
- `web/src/types.ts`：`Bootstrap.selftest_layout`。

测试 / 工具
- `tests_py/test_layout_switch.py`：resize 失败不落盘、范围变化不重定位、card→insights 立即 resize、失败回滚、居中/回位、区域镂空策略、桥接事务。
- `tests_py/test_environment.py`：删除 `... or True` 恒真断言。
- `web/src/app.test.tsx`：真实点击“展开洞察”；失败保留小卡 + 提示 + `unhandledrejection=0`。
- `web/src/views/views.test.tsx`：tiles 顺序与 wide。
- `web/e2e/insights.spec.ts`：KPI 3×2、热力/工具同行、模型跨列、耗时/守恒同行、无横向溢出。
- `tools/verify_layout_switch.py`：固定目标 + `SendInput` 真实点击全链路；目标在页内滚动区下方时先发 **真实滚轮**；三档 DPI；每步校验 layout / 状态矩形=实机矩形 / HWND 尺寸 / `WindowFromPoint` 命中 / 截图 / 透明策略。
- `tools/verify_windows.py`：镂空判定改为“颜色键 **或** 圆角窗口区域”（见偏差说明）。
- `tools/final_acceptance.py`：接入 `verify_layout_switch`。

## 三、实测命令与退出码

| 命令 | 结果 |
|---|---|
| `.venv\Scripts\python.exe -m pytest tests_py -q` | **72 passed**，rc=0 |
| `python tools/reconcile.py` | 四范围 `bad=none`，rc=0 |
| `npm --prefix web run lint` | rc=0 |
| `npm --prefix web run typecheck` | rc=0 |
| `npm --prefix web test` | **19 passed**，rc=0 |
| `npm --prefix web run build` | rc=0 |
| `npm --prefix web run e2e`（= `playwright test`，在 `web/` 下执行） | **11 passed**，rc=0 |
| `python tools/verify_layout_switch.py` | **ok=true**，三档全过（见下表） |
| `.venv\Scripts\python.exe tools/final_acceptance.py` | 19 个门禁 **全部 rc=0**；`failed_gates=[]`；仅 `blocked=["multi_monitor: only 1 display(s)"]`，因 blocked 非空脚本 rc=1 |

> 注：在仓库根执行 `npm --prefix web exec -- playwright test` 不会加载 `web/playwright.config.ts`，会把 `src/*.test.tsx` 当 Playwright 用例跑并报 vitest 内部错误；正确入口是在 `web/` 下跑 `playwright test`，即 `npm --prefix web run e2e`。

## 四、真实鼠标切换链与窗口尺寸

`tools/verify_layout_switch.py`（清空 `CC_HUD_SIZE`、`CC_HUD_FAKE_POWER=1`、唯一互斥体、临时配置），
每一步都先做 `WindowFromPoint` 命中校验再发真实左键 down/up：

card → 点击“展开洞察” → insights → 点击“7天” → 点击“诊断” → 点击“设置” → 点击“回洞察” → 点击“收起为小卡”。

| 档位 | card | insights | diagnostics | settings | 回卡 |
|---|---|---|---|---|---|
| 系统 125% | 530×412 | 1475×1000 | 1350×950 | 950×800 | 530×412 |
| 100%（强制换算） | **424×330** | 1180×800 | 1080×760 | 760×640 | 424×330 |
| 150%（强制换算） | 636×495 | 1770×1200 | 1620×1140 | 1140×960 | 636×495 |

- 每步 `WindowFromPoint` 均命中主窗（无鼠标穿透），`hollow_mode`：card=`region`、大面板=`alpha`。
- 每步 `status.rect` 与 `GetWindowRect` 完全一致（脚本逐项断言）。
- 截图逐张按目标尺寸校验：`artifacts/windows/layout-{sys,dpi96,dpi144}-*.png`。
- 小卡收起后回到展开前的右上角位置（`2014,16` @125%，`2120,16` @100%）。

## 五、前后对比截图

- 小卡：`artifacts/windows/layout-sys-card.png`（现为 530×412@125%，仅圆角外透明；旧基线小卡按规格为 424×420 逻辑尺寸，本轮未保留旧构建截图做像素对照，尺寸差异以本节表格为准）
- 洞察：`artifacts/windows/layout-sys-insights.png`（KPI 3×2、tiles 两列 + 模型跨列，无 4+2 空洞）
- 诊断：`artifacts/windows/layout-sys-diagnostics.png`
- 设置：`artifacts/windows/layout-sys-settings.png`
- 7 天档：`artifacts/windows/layout-sys-insights-7d.png`
- 回卡：`artifacts/windows/layout-sys-card-back.png`
- 独立门禁抓图：`artifacts/windows/ACCEPT-{card,insights,diagnostics,settings,peek,hollow,export,power}.png`
  （`verify_windows.py` 已改为 DPI-aware 且不再用 `CC_HUD_SIZE` 覆盖，抓图尺寸即生产尺寸：
  card 530×412、insights 1475×1000、diagnostics 1350×950、settings 950×800、hollow/peek 530×412）
- 网页几何：`artifacts/web/insights-density.png`

## 六、九路数据未受影响的证据

`python tools/reconcile.py`（本轮实际输出）：

```
1d    9.68s  tokens=1,067,480,171  reqs=  4,468  cost=$124.35  sessions=   31  checks=11  bad=none
7d    4.40s  tokens=1,983,839,268  reqs= 14,937  cost=$257.87  sessions=   87  checks=20  bad=none
30d   1.84s  tokens=3,590,869,811  reqs= 26,427  cost=$488.36  sessions= 1092  checks=26  bad=none
all   3.34s  tokens=4,268,034,214  reqs= 59,978  cost=$526.23  sessions= 1333  checks=29  bad=none
```

本次改动只在窗口宿主/设置事务/前端布局与测试工具，没有触碰 `sources/`、快照与聚合代码。

## 七、偏差与说明

1. **透明实现**：颜色键（`LWA_COLORKEY`）+ WebView2 子窗会让整窗（含按钮）不可点（实测点击穿透，`WindowFromPoint` 落到下层窗口）。因此 `use_colorkey()` 仍是策略函数，但应用阶段改为 **圆角窗口区域**（`SetWindowRgn`）+ 整窗 alpha：视觉同为“圆角外透明”，且按钮可点。`verify_layout_switch` 与 `verify_windows` 都按这一策略判定。
2. **矩形守卫与点击重试**：`verify_layout_switch` 在“点击后 5 秒布局未变”时会重发一次真实点击，并把重试写进 `artifacts/layout-switch.json`（本轮三次运行均无重试）。守卫纠偏次数写在 `status.rect_guard_fixes`，不隐藏。
3. **100% / 150% 是强制换算档**：本机系统 DPI 固定 125%，未改系统设置；`CC_HUD_FORCE_DPI` 只影响宿主换算。三档全部按同一套真实鼠标链路验证，尺寸/命中/截图逐项断言。

## 八、阻塞 / 未验证

- **多显示器**：本机仅 `\\.\DISPLAY21` 一块屏，无法实测跨屏 DPI 与定位，按用户要求搁置，不写通过。
- **真实 100%/150% 系统 DPI**：需改系统缩放并注销，本轮未做；上表 100%/150% 是强制换算结果，已如实标注。
- **托盘像素**：`tray_pixel` / `tray_click` 门禁本轮 rc=0（沿用既有判据），未在本报告中重复展开。

## 产物

- `artifacts/layout-switch.json`：三档 DPI 的逐步矩形、命中方式、截图尺寸。
- `artifacts/final-acceptance.json`：19 个门禁 rc 与 tail。
- `artifacts/windows/`、`artifacts/web/`：上述截图。
