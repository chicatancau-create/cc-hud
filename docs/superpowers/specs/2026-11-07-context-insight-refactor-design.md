# Context Insight Refactor — Design Spec

- 日期：2026-11-07
- 主项目：`G:\cc-hud`（atomgit: zhoumoyukuai/cc-hud, main）
- UI 参考：`bowenliang123/dsh-context` @ `6d55c2f26066610ff419b8cb7713bef865fb1093`
- 状态：**重建版**。原 `docs/superpowers/specs/2026-11-07-context-insight-refactor-design.md`
  在本地工作区、`atomgit`/`origin` 两个远端与全盘搜索中均不存在（见 `docs/superpowers/plans/…` 的取证记录）。
  用户已授权：遇到阻碍按最合理方式继续。本文件由现有 `cchud/` 实现、`verify.py` 判据与本机真实数据
  格式反推写成，不改变用户已确认的架构与约束。

## 1. 目标

把 Python/tkinter 的 `cc-hud` 重构为「React 18 + TypeScript + Vite 前端 + Python 3.14 + pywebview 6.2.1
+ Edge WebView2 宿主」，同时保留并强化原有能力：

1. 小卡（常驻悬浮窗）沿用新视觉系统；
2. 大面板高保真复刻 dsh-context 的 Context Insights 页面；
3. 九路只读统计、统计守恒、双计防护；
4. 托盘、呼出圆点、置顶、整窗透明度、DPI、多显示器、导出、电源动作；
5. 修复 Codex 未回填、WorkBuddy 双版口径、模型统计与 SQLite 生命周期缺陷；
6. 新增 DSH V4、cc-haha、Codex、WorkBuddy 本机只读会话适配器；
7. 自动化测试 + Windows 实机验收 + 视觉差异报告。

## 2. 非目标

- 不改变「本地只读」性质：不联网取数、不上报、不读 API Key / `providers.json` / `settings_config`；
- 不引入远程数据库、联网估价、远程采集、Harness 业务；
- 不删除 `cc-hud.pyw` 回退入口，不删除 `cchud/` 既有功能；
- 不做多用户、不做安装包签名分发。

## 3. 架构

```
cc-hud-next.pyw                 # 新入口（pywebview 宿主）
cchud_next/
  paths.py                      # 所有数据源路径 + CC_HUD_HOME 覆盖（测试/沙箱）
  model.py                      # DayUsage / SourceSnapshot / Snapshot 数据结构与序列化
  ranges.py                     # 1d / 7d / 30d / all 的窗口计算（本地时区）
  sqlite_ro.py                  # 只读连接上下文管理器（mode=ro + query_only + finally close）
  sources/
    base.py                     # Adapter 协议与状态枚举
    ccswitch.py                 # 第 1 路：~/.cc-switch/cc-switch.db
    cchaha.py                   # 第 2 路：索引库 + transcripts（本地日 + 全局去重）
    qoder.py                    # 第 3/4 路：.qoder / .qoder-cn（credits-only）
    zcode.py                    # 第 5 路：~/.zcode/cli/db/db.sqlite
    herdsman.py                 # 第 6 路：~/.herdsman/model_stats/events.jsonl
    codex.py                    # 第 7 路：~/.codex/sessions + archived_sessions
    workbuddy.py                # 第 8 路：.workbuddy / .workbuddy-ai
    dsh.py                      # 第 9 路：projcache totals + V4 zstd 会话
  accounting.py                 # 合并、双计防护、守恒校验、模型聚合
  settings.py                   # hud-next-state.json（校验/夹取/原子写）
  bridge.py                     # pywebview js_api：快照/设置/导出/电源/窗口
  win32.py                      # DPI、整窗 alpha、颜色键镂空、工作区/多屏
  host.py                       # 窗口、托盘、圆点、刷新循环
web/                            # React 18 + TS + Vite（file:// 加载 dist）
  src/{api,state,views,components,styles}
tests_py/                       # pytest
web/src/**/*.test.ts(x)         # Vitest
web/e2e/*.spec.ts               # Playwright（stub bridge）
tools/verify_windows.py         # WebView2/窗口/托盘/圆点/DPI/多屏/PrintWindow 实机取证
```

### 3.1 运行方式

- 生产：`pywebview.create_window(url=file:///<repo>/web/dist/index.html)`，`webview.start(http_server=False)`。
- 禁止 `transparent=True`；整窗 alpha 走 Win32 `WS_EX_LAYERED + SetLayeredWindowAttributes(LWA_ALPHA)`。
- 背景镂空（hollow）用 `LWA_COLORKEY`，单独列实机门禁，失败即回退为实色背景并记录。
- DPI：进程启动即 `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`；前端用 `devicePixelRatio` 自适应。

## 4. 数据契约

### 4.1 状态枚举（必须区分）

| 状态 | 含义 | 前端显示 |
|---|---|---|
| `loading` | 请求在途（前端状态） | 骨架/“读取中” |
| `ok` | 读取成功且有数据（允许真实 0 值） | 数值，0 就是 0 |
| `empty` | 数据源存在，但当前范围无记录 | “本期无记录”，不画 0 |
| `unsupported` | 来源存在但其格式不提供该维度（如 DSH V4 无结构化 usage）、或未安装 | “来源不支持/未安装” |
| `error` | 读取失败（权限/损坏/被占用） | 错误原因，不冒充 0 |

**禁止**：把 `empty`/`unsupported`/`error` 统一填 0。

### 4.2 SourceSnapshot

```json
{
  "key": "workbuddy",
  "name": "WorkBuddy 国内",
  "kind": "session",
  "status": "ok",
  "reason": null,
  "note": "prompt 含缓存读写（均已拆出） · 本机不记钱",
  "totals": {"reqs":0,"credits":0.0,"fresh_in":0,"out":0,"cache_read":0,
             "cache_write":0,"cost":0.0,"tokens":0},
  "days": {"2026-11-07": {"reqs":0,"credits":0.0,"fresh_in":0,"out":0,
            "cache_read":0,"cache_write":0,"cost":0.0,"hours":[0,...24],
            "models":{"m":{"reqs":0,"fresh_in":0,"out":0,"cache_read":0,"cache_write":0,"cost":0.0}}}},
  "sessions": 0,
  "last_seen": null,
  "warnings": [],
  "suppressed": null
}
```

`suppressed` 非空表示该路因会话 id 与已计入来源交集而被整路拒绝并入：
`{"by":"ccswitch","clash":3}`。此时 `totals` 仍报告该路自身读数，但**不进入合计**。

### 4.3 Snapshot（桥接返回）

```json
{
  "schema": 1,
  "revision": 12,
  "seq": 7,
  "range": "7d",
  "generated_at": 1792590000.0,
  "status": "ok",
  "totals": { ...同上... },
  "kpis": {"sessions":0,"active_days":0,"cost":null,"tokens":0,
           "cache_hit":null,"credits":0.0},
  "daily": [{"date":"2026-11-07","tokens":0,"reqs":0,"cost":0.0,"fresh_in":0,
             "out":0,"cache_read":0,"cache_write":0}],
  "hourly": [{"hour":0,"reqs":0,"tokens":0,"cost":0.0}],
  "models": [{"name":"...","reqs":0,"tokens":0,"cost":0.0,"sources":["ccswitch"]}],
  "apps": [{"key":"claude","name":"Claude Code","reqs":0,"tokens":0,"cost":0.0}],
  "sources": [SourceSnapshot...],
  "conservation": [{"name":"totals_eq_days","ok":true,"detail":"..."}],
  "cache": {"hits":0,"misses":0,"entries":1,"capacity":8}
}
```

`cost: null` 表示来源不支持成本（≠ 0）。`cache_hit: null` 表示分母为 0。

### 4.4 桥接方法（pywebview js_api）

| 方法 | 入参 | 出参 |
|---|---|---|
| `bootstrap()` | — | `{version, ranges, settings, sources_meta, dpi, platform}` |
| `snapshot(range, seq)` | `1d/7d/30d/all`, 递增序号 | Snapshot（`seq` 回显） |
| `detail(source_key, range)` | | `{source, days, models}` |
| `get_settings()` / `set_settings(patch)` | | 校验后的设置 |
| `export_json(range)` | | `{path, bytes, revision}` |
| `power(action, confirmed)` | `sleep/shutdown/restart/...` | `{ok, scheduled, action}`；`confirmed!=true` 拒绝 |
| `window(action, value)` | `alpha/topmost/peek/layout` | `{ok, value}` |
| `open_debug()` | | `{ok, log_path}` |

## 5. 记账规则（守恒与双计防护）

1. **基础路**：CC Switch 代理日志是基准。`fresh_in = input - codex_session.cache_read`；
   `tokens = fresh_in + out + cache_read + cache_write`。
2. **整路拒绝**：cc-haha / Qoder / Qoder CN / ZCode / 牧羊人 / WorkBuddy（国内、国外）在并入前，
   若其会话 id 与「已计入来源」的会话 id 有交集，则整路不并入，记 `suppressed`。
3. **只补缺口**：Codex 与 DSH 只并入 CC Switch 未记录的会话（`have_sids`）；同一会话内部不补。
4. **全局去重**：cc-haha / Qoder 的 transcript 可能被 fork 抄写，按 message id 跨文件全局去重；
   WorkBuddy 每行 `rawUsage` 唯一。
5. **WorkBuddy 口径**：`prompt_tokens` 含缓存读与缓存写，净输入 = `prompt - cache_read - cache_write`；
   国外版 `credits` 两本账矛盾 → 不并入。
6. **ZCode**：`input` 含缓存读，净输入需减；`out` 含 reasoning。
7. **Codex**：取每个 rollout 最后一条 `total_token_usage`；`input` 含 `cached_input_tokens`，需减。
8. **DSH projcache**：`uncachedInputTokens` 已是净输入；`turns` 为请求数；按 `createdAt` 归日（近似）。
9. **守恒断言**（每范围、每来源）：
   - `totals == Σdays`（四项、请求、成本、credits）；
   - `Σhours == totals.reqs`（按来源）；
   - `daily.tokens == fresh_in + out + cache_read + cache_write`；
   - `cache_hit = cache_read / (cache_read + fresh_in + cache_write)`，分母 0 → `null`；
   - 模型表 `Σmodel.tokens` ≤ 总量（CC Switch 只列前 4 时允许小于，但**不得大于**）。
10. **成本**：只有 CC Switch 与 cc-haha 有真实美元成本；其余记 `cost=0` 且 source 标注“本机不记钱/无定价”，
    面板不得把“无成本”显示成“$0.00 已计价”。

## 6. UI 规格（Context Insights 高保真）

参考 `6d55c2f` 的实现，取其结构与视觉，不取其运行时。

- 页面骨架：`header`（标题 + 范围胶囊 + 刷新/导出）→ `first`（6 KPI + 用量卡）→ `stats`（token 环形图 + 模型/应用拆分）
  → `tiles`（热力图 / 技能或工具计数 / 来源状态 / 会话数）→ `grid`（来源卡片：九路各一张，含状态与守恒结果）。
- 布局：容器查询；`>=932px` 两列首带；`>=640px` 四列 tiles；`<=560px` 单列；卡片半径 10–12px，间距 8–10px。
- 颜色：深色底 `#0b0e14`，卡片 `#10131d`/`#171a24`，描边 `#262b36`，文字 `#e8edf5/#8a97a8/#7f8b9e/#757f93`；
  分类色：系统 indigo、工具 amber、用户 green、注入 purple、技能 orange、助手 blue、工具调用 teal；
  来源色按 key 稳定哈希。
- 字体：13px 基准，KPI 20/600，标签 11/600，刻度 9px，数字 `tabular-nums`；等宽仅用于路径/模型 id。
- 图表：手写 SVG/CSS（环形图、柱状、热力图），不引第三方图表库。
- 状态：加载骨架；`empty` 文案“本期无记录”；`unsupported` 文案“来源不支持/未安装”+ 原因；
  `error` 文案“读取失败”+ 原因；真实 0 正常显示 0。
- 小卡：范围胶囊、今日成本/请求/真实 token/命中率、1 小时、按应用条形、状态底栏；点击展开大面板。
- 诊断视图：每路状态、路径、原因、`suppressed`、守恒逐条、revision、缓存命中/容量、SQLite 打开方式。
- 设置：透明度（5 档）、置顶、圆点、主题、导出、电源动作（二次确认，测试用注入器）。

## 7. 安全与生命周期

- SQLite 一律 `mode=ro` URI + `PRAGMA query_only=ON` + `busy_timeout` + `finally close()`（ZCode 旧实现缺 finally，本版修复）。
- 不打开：`providers.settings_config`、`universal_providers`、`providers.json`、`auth.json`、`.credentials.yaml`、API Key 字段。
- 导出 JSON 复用 `cchud.util` 的脱敏（userinfo/query/token/Bearer）。
- 电源动作只经 `PowerController`；测试注入 `FakePower`，断言从不调用真实命令。
- `hud-next-state.json` 原子写（tmp + `os.replace`），读取时校验并夹取。

## 8. 验收

见 `docs/superpowers/plans/2026-11-07-context-insight-refactor.md` 的 17 个任务门禁；最终报告必须逐条附真实命令与输出。
