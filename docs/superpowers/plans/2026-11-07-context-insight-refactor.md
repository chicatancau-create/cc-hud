# Context Insight Refactor — 17-Task Plan

- 日期：2026-11-07
- 依据：`docs/superpowers/specs/2026-11-07-context-insight-refactor-design.md`
- 状态：**重建版**。两份原始文档在本地与远端均不存在，取证见 §0。用户授权「遇到阻碍按最合理方式继续」。

## 0. 文档缺失取证（2026-11-07 13:43–13:59 UTC+8）

| 检查 | 结果 |
|---|---|
| `ls G:\cc-hud\docs` | 不存在 |
| `git ls-files | grep docs` | 空 |
| `git fetch atomgit` + `rev-list --left-right --count main...atomgit/main` | `0 0`（同为 `991521d`） |
| `git ls-remote https://atomgit.com/zhoumoyukuai/cc-hud.git` | 仅 `refs/heads/main = 991521d…` |
| `raw.gitcode.com/.../docs/superpowers/...` | HTTP 404 |
| 全盘文件名搜索 `*context-insight-refactor*` | 0 命中 |
| 全盘 `.md` 内容搜索 `Context Insights` | 0 命中 |

## 1. 执行约定

- 每个 Task 先写失败测试 → 确认失败原因 → 实现 → 跑窄测试 → 跑受影响回归。
- 测试命令统一：
  - Python：`python -m pytest tests_py -q`
  - 前端：`cd web && npm run lint && npm run typecheck && npm test -- --run`
  - 构建：`cd web && npm run build`
  - E2E：`cd web && npx playwright test`
  - 实机：`python tools/verify_windows.py`
- 任一 Task 门禁不绿不得进入下一 Task。允许记录阻塞，但不得以降低断言过关。

---

## Task 1 — 环境与骨架

文件：`pyproject.toml`、`cchud_next/__init__.py`、`cc-hud-next.pyw`、`web/package.json`、`web/vite.config.ts`、`web/tsconfig*.json`
测试：`tests_py/test_environment.py`（Python ≥3.14、pywebview 可导入、web/dist 约定路径、无 `transparent=True` 字面量）
门禁：`python -V`、`node -v`、`python -c "import webview"`、`npm ci`、`npm run build` 成功。

## Task 2 — 数据模型 / 范围 / 状态

文件：`cchud_next/model.py`、`cchud_next/ranges.py`、`tests_py/test_model.py`
要点：`DayUsage`、`SourceSnapshot`、`Snapshot`；状态 `ok/empty/unsupported/error`；`1d/7d/30d/all` 以本地日 00:00 为界。
测试：范围边界、序列化、`totals==Σdays` 辅助函数、`cost=None` 与 0 区分。

## Task 3 — SQLite 只读层

文件：`cchud_next/sqlite_ro.py`、`tests_py/test_sqlite_ro.py`
要点：`mode=ro` URI、`PRAGMA query_only=ON`、`busy_timeout`、`finally close`；写入抛错；缺库 → `unsupported`。
门禁：用临时库验证「写被拒」「句柄在异常路径也关闭」。

## Task 4 — CC Switch 适配器（基准路）

文件：`cchud_next/sources/ccswitch.py`、`tests_py/test_ccswitch.py`
要点：逐请求表；`fresh_in=input-codex_read`；分项成本；`providers`/`apps`/`models`/`daily`/`hourly`；会话 id 集合。
测试：合成库断言四桶守恒、codex 回填不双计、只 SELECT。

## Task 5 — cc-haha 适配器

文件：`cchud_next/sources/cchaha.py`、`tests_py/test_cchaha.py`
要点：索引库取成本，transcript 取本地日四项；跨文件按 message id 全局去重；配置目录自动发现（`.claude` / `E:\cc-haha`）；按份额摊成本。
测试：fork 抄写不双计、UTC/本地日错位、无目录 → `unsupported`。

## Task 6 — Qoder / Qoder CN 适配器

文件：`cchud_next/sources/qoder.py`、`tests_py/test_qoder.py`
要点：只出 `reqs + credits`；token 恒 0 不并；mtime 预筛；跨文件去重；两目录各自独立。
测试：credits 汇总、重复 id 去重、范围过滤。

## Task 7 — ZCode / 牧羊人适配器

文件：`cchud_next/sources/zcode.py`、`cchud_next/sources/herdsman.py`、`tests_py/test_zcode_herdsman.py`
要点：ZCode `input-rd`、`out+reasoning`、**finally close**；牧羊人 ISO/秒时间戳兼容、无缓存分项。
测试：净输入、异常路径关库、无 token 行跳过。

## Task 8 — Codex 适配器

文件：`cchud_next/sources/codex.py`、`tests_py/test_codex.py`
要点：最后一条 `total_token_usage`；`have_sids` 过滤；`input-cached`；会话 id 从文件名尾 5 段；坏行跳过。
测试：已回填会话不并、净输入、小时守恒。

## Task 9 — WorkBuddy 双版适配器

文件：`cchud_next/sources/workbuddy.py`、`tests_py/test_workbuddy.py`
要点：毫秒字符串时间戳；`prompt - hit - write`；写缓存两版字段名；国外版 credits 不并；子 agent sessionId 也入 sids。
测试：四桶相加 == `total_tokens`（合成）、credits 规则、路径归属。

## Task 10 — DSH（projcache + V4）

文件：`cchud_next/sources/dsh.py`、`tests_py/test_dsh.py`
要点：
- projcache：`record.rows.tokenUsage.val.totals`，`uncachedInputTokens` 即净输入；`turns` 为请求；按 `createdAt` 归日；
- V4：`~/.dsh/sessions/**/session.v4.jsonl.zstd`，用 `compression.zstd` 解码；有结构化 usage 才计 token，否则 `unsupported`（附原因），**不伪造**；
- 两路 `have_sids` 只补缺口。
测试：V4 压缩样例解析、无 usage → unsupported、空会话不计请求。

## Task 11 — 合并 / 双计 / 守恒 / 模型

文件：`cchud_next/accounting.py`、`tests_py/test_accounting.py`
要点：整路拒绝（交集）、只补缺口、`suppressed` 标记、`kpis`、模型聚合、守恒断言列表。
测试：交集整路拒绝、模型 tokens ≤ 总量、hit 分母 0 → null、四范围一致。

## Task 12 — 设置 / 导出

文件：`cchud_next/settings.py`、`cchud_next/export.py`、`tests_py/test_settings_export.py`
要点：原子写、夹取、未知键丢弃；导出带 `revision` 且脱敏（userinfo/query/token/Bearer）。
测试：损坏文件回退默认、越界夹取、脱敏正则。

## Task 13 — 桥接

文件：`cchud_next/bridge.py`、`tests_py/test_bridge.py`
要点：`bootstrap/snapshot/detail/settings/export/power/window`；`seq` 回显；`revision` 单调；快照缓存容量 ≤ 8；电源必须 `confirmed=True` 且注入 `PowerPort`。
测试：latest-wins 语义（旧 seq 返回 `stale`）、缓存淘汰、电源未确认拒绝、假电源零真实调用。

## Task 14 — 前端脚手架与状态层

文件：`web/src/api/*`、`web/src/state/*`、`web/src/types.ts`、测试
要点：`window.pywebview.api` 客户端 + stub；latest-wins reducer；缓存上限；四状态渲染。
门禁：lint + typecheck + vitest。

## Task 15 — 视图（小卡 / Insights / 诊断 / 设置）

文件：`web/src/views/*`、`web/src/components/*`、`web/src/styles/*`
要点：小卡、KPI 带、环形图、日柱、热力图、模型/应用表、九路来源卡、诊断、设置；容器查询响应式。
门禁：vitest（组件行为）+ 构建。

## Task 16 — Playwright 交互 / 视觉

文件：`web/e2e/*.spec.ts`、`web/playwright.config.ts`
要点：视图切换、范围切换 latest-wins、空/零/不支持/错误文案、设置持久化、导出 revision；截图存 `artifacts/` 供差异报告。
门禁：`npx playwright test`（chromium channel=msedge，避免额外下载）。

## Task 17 — Windows 宿主与实机验收

文件：`cchud_next/win32.py`、`cchud_next/host.py`、`tools/verify_windows.py`、`start-hud-next.bat`
要点：`PER_MONITOR_AWARE_V2`、`WS_EX_LAYERED` alpha、颜色键镂空（单列）、置顶、圆点、托盘、多屏工作区与夹取、PrintWindow/BitBlt 取证。
门禁：`python tools/verify_windows.py` 输出 JSON 证据（窗口存在、DPI、alpha、置顶、托盘、圆点、截图非全黑、多屏坐标）。
非 Windows/无法起窗时必须报告阻塞，不伪造。

---

## 最终交付清单

- 源码：`cchud_next/`、`web/`、`cc-hud-next.pyw`、`start-hud-next.bat`
- 测试：`tests_py/`、`web/src/**/*.test.*`、`web/e2e/`
- 文档：本文件 + spec + `docs/reports/2026-11-07-refactor-verification.md`
- 证据：`artifacts/` 下前后对比截图、实机取证 JSON、视觉差异说明
