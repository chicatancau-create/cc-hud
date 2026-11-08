# 视觉差异报告（cc-hud 重构版 vs dsh-context）

对照素材：

- 参考：`dsh-context` @ `6d55c2f`，截图 `artifacts/reference/dsh-context-dashboard.png`（仓库 `docs/context-dashboard.png`）
- 实现：`artifacts/windows/FINAL2-insights.png`、`FINAL2-sessions2.png`、`FINAL6-tools.png`、`FINAL7-30d.png`（WebView2 实机，真实本机数据）
- 并排图：`artifacts/visual-diff.png`（左参考、右实现）
- 前端整页截图：`artifacts/web/insights.png`（Playwright，1440×900）

## 1. 结构对照

| 区块 | 参考 dsh-context | 本实现 | 判定 |
|---|---|---|---|
| 页头 | 标题 + 设置胶囊 + 余额 + 时间范围（今日/近7天/近30天/全部/自定义） | 标题 + 范围胶囊（今日/7天/30天/全部）+ 刷新/导出/设置 | 同结构；无余额（本机无云端余额） |
| KPI 带 | 6 个（会话、Token、预估费用、缓存命中、请求、时长） | 6 个（会话、tokens、成本、缓存命中、活跃日、credits） | 同结构；后两项按本机可得维度替换（无时长采集） |
| 用量图 | “近 7 天用量”分组柱（token/成本双轴） | “每日 token”柱 + 24 小时请求条 | 简化：无双轴成本柱（见 §3） |
| Token 构成 | 环形图 + 6 色分项列表（含百分比/字节） | 环形图 + 4 色分项（新增/输出/缓存读/缓存写）+ 数值 | 同结构；分项按 cc-hud 四桶口径 |
| 耗时统计 | 环形 + TTFT/生成/工具等 | 「耗时」卡：TTFT 占时环 + 请求 P50/P95 + 首 token P50 + 样本数 | 已实现（CC Switch 代理真实 `latency_ms/first_token_ms`）；无生成/推理/工具分项 |
| 活跃热力图 | 12 周日历格 | 8 周热力格 | 同结构，周数较少 |
| 技能/工具/命令 tally | 3 张排行卡 | 「工具调用」排行（cc-haha transcript 的 `tool_use` 真实计数） | 工具已实现；命令 tally 未做（未解析命令） |
| 会话网格 | 搜索、分组 chips、覆盖筛选、排序、12/页分页、会话卡（上下文构成） | 搜索、来源 chips、12/页分页、会话卡（id/模型/tokens/请求/成本或 credits/最后请求） | 同结构；上下文构成不可得 |
| 来源/诊断 | 无 | 11 路来源卡 + 守恒校验表 | 本实现新增 |

## 2. 视觉语言

| 维度 | 参考 | 本实现 | 说明 |
|---|---|---|---|
| 底色 | `#151517`/`#232324`（宿主令牌） | `#0b0e14` + 卡片 `#10131d` | 取自 cc-hud 既有配色，深色更冷 |
| 卡片 | 圆角 10/12px、1px 细边 | 圆角 12px、`#262b36` 边 | 一致 |
| 字号 | 13px 基准，KPI 20/600，刻度 9px | 13px 基准，KPI 20/600，刻度 9px | 一致 |
| 数字 | tabular-nums | tabular-nums | 一致 |
| 图表 | 手写 SVG/CSS | 手写 SVG/CSS | 一致（不引图表库） |
| 分类色 | indigo/amber/green/purple/… | 蓝/绿/紫/橙四桶 + 来源稳定色 | 语义色按 cc-hud 四桶 |

主色统计（缩略图众数）：参考 `#232324`/`#151517`；实现 `#10131d`/`#0b0e14`。
差异为**刻意保留 cc-hud 品牌色**，不是渲染错误。

## 3. 明确解释的差异（非缺陷）

1. **耗时只有两段**：CC Switch 有逐请求 `latency_ms/first_token_ms`，但没有“生成/推理/读工具”分段，
   因此只展示 TTFT 占比与 P50/P95，不编造参考页的六段环。
2. **只有工具 tally，没有命令 tally**：已从 cc-haha transcript 的 `tool_use` 统计真实工具名；
   命令（Bash 内的子命令）未解析，故不展示“命令”排行。
   1d/7d 无工具记录是因为 cc-haha 在范围内没有消息（真实空，非假 0）。
3. **会话卡无“上下文构成条”**：参考页展示每个会话的系统/工具/用户/注入 token 占比；
   本机只有 token 用量与模型，故只显示真实可得字段。
4. **无余额胶囊**：本机不读云端账户，不展示金额余额。
5. **KPI 第 5/6 项替换**：时长与“预估费用”在本机口径下不可得，改为活跃日与 credits。

## 4. 已修复的视觉缺陷

- 125% DPI 下右侧 20% 被裁：根因是 pywebview 按物理像素建窗、WebView2 按系统缩放渲染；
  以 `zoom = 1/devicePixelRatio` 补偿，并按视图重设窗口，实机复查整页可见（`FINAL2-insights.png`）。
- 分层窗口截图带入桌面：改为取证前临时 alpha=100%，PrintWindow 后恢复。
- 小卡头部图标被挤出：卡片流式宽度 + 头部允许换行。

## 5. 复核命令

```bash
python tools/verify_windows.py --layout insights --wait 26 --shot vd-top
python tools/verify_windows.py --layout insights --wait 26 --scroll 1150 --shot vd-sessions
```

结论：结构与视觉语言高保真；三处内容差异均为**数据不可得**导致的有意省略，已在 §3 解释，未用假数据替代。
