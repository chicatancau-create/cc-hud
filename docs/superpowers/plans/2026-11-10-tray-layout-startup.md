# 2026-11-10 托盘 / 布局 / 启动 实施计划

基线：`main` @ `2f96309`。改造全部在本地工作区，未 push。

## 阶段 0：基线取证（改代码之前）

1. `.venv\Scripts\python.exe -m pytest tests_py -q` → 期望 rc=0
2. `.venv\Scripts\python.exe tools/reconcile.py` → 四段 `bad=none`
3. 建改造前快照：`git worktree add ../cc-hud-baseline 2f96309`，把当前 `web/dist` 拷进去
4. `python tools/bench_startup.py --rounds 5 --root ../cc-hud-baseline --label before`
   → 记录冷/热 ready 中位数、进程树规模、`msedgewebview2.exe` 个数

## 阶段 1：删除第二窗口 + 旧配置兼容

- `cchud_next/host.py`
  - 删 `PEEK` 常量、`self.dot`、`_place_dot()`、`startup step "dot"`
  - `show()/hide()` 去 `dot` 引用；`_on_closed()` 只 destroy 主窗口
  - `_after_start()` 的 `dot_created` 固定 `False`（状态里仍可观测“没有第二窗口”）
- 删 `web/peek.html`
- `cchud_next/settings.py`：`peek` 保留在 `DEFAULTS`/`BOOL_KEYS`，注释标废弃
- 前端：`SettingsView` 去掉 peek 开关，`DiagnosticsView` 去掉“呼出圆点”行

验收：`pytest -q` 中 `test_host_never_creates_dot_window`、`test_show_hide_never_touch_dot`、
`test_legacy_settings_with_peek_still_load` 全绿。

## 阶段 2：统一命令模型与托盘

- 新增 `cchud_next/menu.py`：`build()/walk()/resolve()/leaves()/is_known()/patch_for()`
- `cchud_next/tray.py`
  - 左右键事件码分组；`_accept()` 300ms 同类去抖
  - `popup(items)` → `CreatePopupMenu/AppendMenuW/TrackPopupMenu(TPM_RETURNCMD)`，
    `finally: DestroyMenu` + `PostMessageW(0,0,0)` 让菜单真正收起
  - **修既有缺陷**：WndProc 会用到的字段在 `__init__` 开头初始化；`RegisterClassExW` 补 argtypes；
    `hInstance` 用 `c_void_p(hinst)`，父窗/菜单传 `None`
- `cchud_next/host.py`
  - `menu_items()` / `run_menu(id)` 作为唯一分发点
  - `_tray_ok()`；`hide()` 在托盘不可用时拒绝并 `show()`
  - `_on_tray("menu")` 先记 `tray_menu_shown`，再 popup；选中后优先交前端
    `window.__cchudTrayMenu(id)`，前端没了才 `run_menu()` 兜底
  - `_start_tray_now()`：非 GUI 线程用 `BeginInvoke` + `Event` 等结果（3s 超时），
    保证 `ready=true` 时 `tray_added` 已有确定值
- `cchud_next/bridge.py`：`menu_model()` / `menu_command()`；`power.*` 仍走 `power(action, confirmed)`

## 阶段 3：主面板右键菜单

- 新增 `web/src/components/ContextMenu.tsx`：按 model 渲染，`Esc`（capture 阶段拦截，避免触发旧的“Esc 收小卡”）、
  点击外部关闭、子菜单 hover/点击展开、执行后收起
- `web/src/App.tsx`
  - `onContextMenu` 一律 `preventDefault()` → `openMenu(x,y)`
  - `runMenu(id)`：`power.*` 二次确认后走 `api.power(action,true)`；其余 `api.menu_command(id)`，
    回包带 `settings` 就同步本地状态
  - 注册 `window.__cchudTrayMenu = runMenu`（托盘选中复用同一函数）
- `web/src/types.ts` + `web/src/api/bridge.ts`：`MenuNode/MenuModel`、`menu_model/menu_command`（native + stub）

## 阶段 4：洞察页布局

- `InsightsView.tsx`：`.tiles` 只留 热力 / 工具 / 模型(wide)；
  新增 `<section className="checks-zone">`（耗时宽卡 + 守恒校验），放在 `数据来源` 之后、`page-footer` 之前
- `app.css`：`.checks-zone/.timing-wide/.checks-2col` 局部间距；`<780px` 回单列
- 检测项保留两行结构，失败项不隐藏，数量来自 `snap.conservation.length`

## 阶段 5：启动

- `start-hud.bat`：删 `pythonw -c "import webview"` 预检
- `cc-hud.pyw`：`try: import cchud_next.host` / `run()`，异常 → 写 `artifacts/startup-error.log`
  + `MessageBoxW`（pythonw 无控制台也能看到原因）
- `cchud_next/bench.py` + `Host` 打点；`tools/bench_startup.py` 前后各 5 轮

## 阶段 6：测试与验收

| 覆盖点 | 位置 |
|---|---|
| 只建主窗口 / show-hide 不碰 dot / 旧 peek 兼容 | `tests_py/test_host_lifecycle.py`、`tests_py/test_menu_tray.py` |
| 托盘左键只切一次（含重复消息） | `test_menu_tray.py` + 实机 `tools/tray_click.py` |
| 右键只弹菜单不改显隐 | 同上 |
| 两处菜单同源 | `test_menu_tray.py`（`menu.build` 同函数 + `__cchudTrayMenu` 走同一 runMenu） |
| 视图/范围/刷新/导出/设置真的调用既有路径 | `test_menu_tray.py`、`web/src/app.test.tsx` |
| 托盘不可用兜底 | `test_hide_refused_when_tray_unavailable` |
| 检测区下沉 / 宽屏两列 / 窄屏单列 / 动态数量 | `views.test.tsx`、`web/e2e/insights.spec.ts` |
| 电源用假执行器 | `CC_HUD_FAKE_POWER=1` + `test_menu_tray.py` 断言 `needs_confirm` |
| 旧验收逻辑改写 | `tools/tray_click.py`、`tools/verify_windows.py`、`tools/final_acceptance.py`、`tools/verify_settings_persist.py` |

## 阶段 7：文档与交付

本文件 + 设计文档 + 验收报告 + README 更新；最后跑一遍完整门禁并记录真实输出。
