# 2026-11-10 托盘 / 布局 / 启动 设计

状态：已实现（本地）
基线：`main` @ `2f96309`，改造在本地工作区，未 push。

## 1. 目标与边界

| 目标 | 落地方式 |
|---|---|
| 桌面不再出现绿色 cc 小圆点 | 删除 `webview.create_window("cc-hud-dot", …)` 整个第二窗口，`show()/hide()` 不再引用 `self.dot` |
| 旧配置仍带 `peek` 能正常启动 | `cchud_next/settings.py` 保留 `peek` 键（`DEFAULTS` 与 `BOOL_KEYS`），仅 UI 不再提供开关 |
| 托盘是隐藏后唯一入口 | 托盘注册失败/不可见时 `hide()` 直接拒绝并回写错误，保持面板可见 |
| 点击托盘只切一次 | `Tray._accept()` 对同类事件做 300ms 去抖，Shell 的多条消息只认第一条 |
| 右键只弹菜单 | 托盘右键走 `TrackPopupMenu`，与显隐切换完全分离 |
| 两处菜单同源 | 新增 `cchud_next/menu.py` 作为唯一命令模型，托盘与主面板都消费它 |
| 洞察页检测区下沉 | DOM 重排：会话 → 数据来源 → `checks-zone` → 页脚 |
| 守恒列表宽屏两列 | `.checks-2col`，`max-width:780px` 回落单列 |
| 启动去掉重复导入 | `start-hud.bat` 删除 `pythonw -c "import webview"` 预检；依赖缺失由 `cc-hud.pyw` 用 MessageBox 报错 |

不改动的部分：九路统计公式、去重/守恒规则、导出格式、数据源、原生窗口尺寸接口。

## 2. 命令模型（`cchud_next/menu.py`）

节点：`{id, title, kind, enabled, checked, danger, children}`，
`kind ∈ {command, check, radio, submenu, separator}`。

```
panel.toggle                       显示/隐藏主面板（托盘不可用时禁用）
submenu.view      → view.{card,insights,diagnostics,settings}       radio
submenu.range     → range.{1d,7d,30d,all}                           radio
action.refresh / action.export / action.open_settings
submenu.settings  → setting.alpha.{100,96,92,86,78} radio
                    setting.topmost / setting.hollow              check
                    submenu.theme → setting.theme.{dark,light}    radio
submenu.power（危险） → power.{lock,sleep,hibernate,shutdown,restart,logoff}
app.quit
```

- `patch_for(cmd_id)` 把视图/范围/透明度/主题翻译成设置补丁；`setting.topmost|hollow` 由宿主按当前值取反。
- 开发/取证命令（capture / dpi / place / selftest）**不进菜单**；`is_known()` 只放行 7 个前缀白名单。

## 3. 分发链路（唯一）

```
托盘右键 ──> Host._on_tray("menu")
              ├─ status["tray_menu_shown"] += 1（先记账，模态循环可被验收观测）
              ├─ Tray.popup(menu_items())  → TrackPopupMenu（DestroyMenu + PostMessage 收尾）
              └─ 选中 id
                   ├─ 前端在 ⇒ evaluate_js window.__cchudTrayMenu(id)  → App.runMenu
                   └─ 前端没了 ⇒ Host.run_menu(id) 兜底

主面板右键 ─> ContextMenu（React） ─> App.runMenu(id) ─> api.menu_command(id)
                                                        └─ Bridge.menu_command
                                                             ├─ power.*  → power(action, confirmed)
                                                             ├─ action.export → export_json
                                                             ├─ action.* / app.* → Host.run_menu
                                                             └─ 视图/范围/设置 → set_settings(patch) 事务
```

所有设置写入仍走 `Bridge.set_settings`（原生应用成功才落盘，失败窗口回滚），业务逻辑没有第二份实现。

## 4. 托盘建窗的两个既有缺陷（本次修掉）

1. **WndProc 早于字段初始化**：`RegisterClassExW` 后 `CreateWindowExW` 会同步派发 `WM_NCCREATE/WM_CREATE`，
   而 `_wnd` 里要读 `self._taskbar_created`、`self._last`、`self.added` 等。字段尚未赋值 → 回调抛
   `AttributeError` → 返回 0 → **建窗静默失败**（`err=0`）。修法：把所有回调会用到的字段在 `__init__` 开头初始化。
2. **`RegisterClassExW` 缺 argtypes**：64 位 `hInstance` 会被按 `c_int` 截断，类注册与建窗用的不是同一个模块句柄。
   修法：`restype=ATOM`、`argtypes=[POINTER(_WCX)]`，并把 `hInstance` 显式包成 `c_void_p`，
   父窗口/菜单传 `None`。

## 5. 隐藏兜底

`Host._tray_ok()` = `tray.added and tray.getrect_rc == 0`（NIM_ADD 成功 **且** Shell 能给出图标矩形）。
`hide()` 前置检查失败时：

- 不隐藏窗口；
- 写 `status["hide_blocked"]="托盘不可用或不可见"`、`status["last_error"]="托盘不可用，已保持主面板可见"`；
- 调 `show()` 确保可见。

`panel.toggle` 菜单项在 `tray_ok=False` 时也被置灰（已隐藏时例外，仍允许“显示主面板”）。

## 6. 启动耗时打点

`cchud_next/bench.py`：进程内 `perf_counter` 相对毫秒，`Host._ensure_window_ready()` 结束时把
`status["bench"]` 写进 `runtime.json`。测量脚本 `tools/bench_startup.py` 另测：

- `Popen → ready=true` 墙钟（冷：删 profile 目录；热：复用 profile）
- 整棵进程树私有内存（沿 `ParentProcessId` 递归求和）
- 进程树规模与 `msedgewebview2.exe` 数量（第二窗口的直接可量化证据）

## 7. 布局

`.checks-zone` 是**局部**容器，只压缩自己与检测卡的 `gap/padding/line-height`，不动全局 spacing token。
`.checks-2col` 用 `repeat(2, minmax(0,1fr))`，`<780px` 回单列。检测项仍保留两行结构（状态图标+名称 / 详情），
失败项不隐藏，数量取 `snap.conservation.length`。
