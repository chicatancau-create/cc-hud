# 视觉改造记录（2026-11-09）

> 起因：用户要求「把应用跑起来自己检测、把问题都找出来、自己判断修复」，并指出**先把视觉效果改好**，
> 不需要备份（代码已在 Git 上，可回滚）。
> 本文记录：改前逐张截图确认的缺陷、改了什么、怎么验的、以及仍然没解决的部分。
>
> 全部「改前 / 改后」结论都来自**真实运行的 HUD 窗口截图**（`artifacts/visual/`），不是看代码推断。

---

## 1. 取证方法

`tools/shoot_ui.py`：用隔离环境启动真实宿主并截图（产物落在 `artifacts/visual/`，该目录不入库）。

| 隔离手段 | 环境变量 | 作用 |
|---|---|---|
| 状态文件 | `CC_HUD_STATE` | 指向临时 state.json，不碰用户 `hud-next-state.json` |
| WebView2 存储 | `CC_HUD_PROFILE` | 独立 storage，不碰 `.webview` |
| 单实例互斥体 | `CC_HUD_MUTEX` | 独立互斥体，可与真实实例并存 |
| 透明度 | `CC_HUD_ALPHA=1` | 截图固定不透明，颜色不受桌面混合干扰 |
| 电源动作 | `CC_HUD_FAKE_POWER=1` | 禁止真实关机/休眠 |
| 窗口尺寸 | `CC_HUD_SIZE=WxH` | 验证窄窗重排 |

产出两份图：
- `<out>.png` —— `PrintWindow`，透明区域为黑，用于看布局骨架；
- `<out>-desk.png` —— `ImageGrab` 抓屏幕真实像素，**判断视觉效果以这份为准**。

> 坑：`--settle` 默认 2.2s 时四视图全部停在「读取中… 宿主：WebView2」，
> 截图里只有 loading 文案。必须 `--settle 10` 才能拍到有数据的界面。

---

## 2. 改前缺陷清单（逐张看图确认）

| # | 视图 | 缺陷 | 根因 |
|---|---|---|---|
| 1 | 小卡 | 内容到 y≈305 就结束，下方约 85 CSS px 全透明空带 | `.card-view` 没有 `height`，只按内容撑高，窗口固定 330 CSS 高 |
| 2 | 洞察 | 右侧一条明亮原生滚动条，与暗色 UI 割裂 | `.page` 有 `scrollbar-gutter: stable`，全站无自定义 `::-webkit-scrollbar` |
| 3 | 洞察 | 「每日 token」只有 1 根细柱居中，下方 24 根无标注小柱像条形码 | `.bar{max-width:22px}` 固定宽度 + `.hour-strip` 无刻度标注 |
| 4 | 洞察 | 热力图单元被拉成 70×14 长条，完全不是方格 | `.heat` 用 `grid-auto-rows:14px` + 8 列，格子高度被文字行高锁死 |
| 5 | 洞察 | donut 中心写 `76774.3万`，与全站 `fmtTokens` 的「7.68亿」口径不一致 | `pieces.tsx` 自己算 `(total/1e4).toFixed(1)+"万"` |
| 6 | 洞察 | 「按应用」用绿色条、「模型/热力图」用蓝色条，色语言分裂 | 各处直接写死颜色 |
| 7 | 洞察 | 工具调用空态用 `⌘` 字符，字体无此字形 → 渲染成豆腐块 | 用字符当图标 |
| 8 | 洞察/诊断/设置 | 「加载中…」土黄色全宽横幅，出现在 flex 列里会顶开内容、切范围时闪一下 | `.banner` 参与布局 + 用 warn 黄色 |
| 9 | 诊断 | 守恒表「详情」列被 `table-layout:fixed` 均分后 `…` 截断（`cache_read=10…`） | 无 `colgroup`，列宽均分 |
| 10 | 诊断 | 九路状态表「说明」列同样截断（`并只清…`） | 同上 |
| 11 | 设置 | 复选框是原生蓝方块，与整站胶囊风格不搭 | `.switch input{accent-color}` |
| 12 | 设置 | 内容到 y≈570 就结束，下方约 184 CSS px 空白 | 内容不足以填满 760×640 窗口 |
| 13 | 小卡 | 齿轮 `⚙` / 展开 `⤢` 字符渲染不正（`⚙` 形似太阳/星号） | 用字符当图标 |
| 14 | 全站 | 选中态分段按钮几乎看不出（用 `--card3` 做高亮，与底色差 4 级） | 对比度不足 |
| 15 | 小卡 | `range=1d` 时走势条渲染成一根占满全宽的蓝色大块 | 只有 1 个数据点时 `flex:1` 铺满 —— **这是我改造中自己引入又修掉的** |

---

## 3. 改了什么

### 3.1 新增 `web/src/components/charts.tsx`
把原先散落在 `InsightsView` / `pieces` 里的图表实现集中：

- `DailyBars`：柱宽自适应（`flex:1 1 0` + `max-width:44px`），数据点 ≤12 时柱顶显示数值，
  参考线用 `repeating-linear-gradient`（不额外占 DOM）；
- `HourSpark`：24 根柱 + `0/6/12/18/23` 刻度 + 峰值高亮；
- `Heatmap`：**近 26 周、7 行 × 26 列、`grid-auto-flow: column`、`.heat-cell{aspect-ratio:1}`**，
  真方格 + 周几标签 + 少→多图例；
- `TokenDonut`：SVG 环 + **HTML overlay 中心文字**（摆脱 SVG 字号缩放），中心改用 `fmtTokens`；
- `CardSpark`：小卡走势条，`flex:1` 吃满剩余高度，空槽用 `spark-ghost` 补齐。

### 3.2 `web/src/styles/tokens.css`
重写色板并新增**图表语义色 token**（深浅主题各一套）：
`--bar-from/--bar-to`、`--hour-on/--hour-off`、`--heat-1..4`；
加 `* { scrollbar-width: thin }` + 自定义 `::-webkit-scrollbar`（9px、透明轨道、`background-clip: content-box`）；
加 `:focus-visible` 键盘焦点环。

> 浅色主题最初 `--bar-to` 取 `.16`，实拍柱体近乎透明像悬空，改 `.52` 才实心。
> 浅色主题另外补了 `--ok/--warn/--err` 的深色版本（原值 `#3ddc97/#f7c948/#ff7a7a` 在白色背景上对比度不足，
> 尤其「成本」大字用 `--warn`，改成 `#a8630a`）。

### 3.3 四视图
- `CardView`：结构改为 header → (card-banner) → hero → **CardSpark** → mini-row → app-bars → foot，
  用一个真实数据区吃掉底部空带；图标全改内联 SVG；`mini-row` 第一格从 `今日请求` 改为 `请求`
  （与所选范围口径一致）。
- `InsightsView`：`HourSpark` 取代内联 hour-strip；守恒卡头显示「N 项全部通过 / N 项失败」。
- `DiagnosticsView`：两张表都加 `<colgroup>` 定宽 + `.num` 右对齐 + 长文本 `title`；
  运行参数增「快照时间」「范围起点」；`背景镂空` 文案改成「开（圆角区域 + alpha）」。
- `SettingsView`：新增「关于」卡片（版本/当前布局/状态文件/数据读取）填掉底部空白；
  开关改 CSS 胶囊（保留原生 `input[type=checkbox]`，不破坏可访问性与测试）。

### 3.4 `app.css` 全量重写
- `.banner` 改 `position: fixed` 浮动胶囊，不再参与布局；
- `.card-view{height:100%; display:flex; flex-direction:column; gap:9px; overflow:hidden}`；
- `.table{table-layout:fixed}` + `th{text-transform:uppercase}` + `td.num{text-align:right}` + hover 高亮；
- `.switch` 用 `appearance:none` + `::after` 做胶囊；
- 窄窗重排改用媒体查询（见 §4）。

---

## 4. 一个必须记下来的坑：`@container` 在 WebView2 上没生效

改造时我先用容器查询（`@container (max-width: 980px)`）做窄窗重排，把 `.page` 设成
`container-type: inline-size`。**实测没有匹配**：

- `--size 900x820` → `inner_width = 886` CSS px，886 明显小于 980，
  但 `.first` 仍是两列（KPI 左、图表右）；
- 本机 WebView2 版本实测 `157.0.4341.42`
  （`HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` 的 `pv`，
  `C:\Program Files (x86)\Microsoft\EdgeWebView\Application` 下有 156/157 两版），
  该版本理应支持容器查询。

改成**媒体查询**后同一尺寸立刻单列堆叠（`narrow900b`），886 与 700 两档都验证过。
本应用窗口宽 == 视口宽，媒体查询与容器查询等价，因此这是无损替换；
`.page` 上的 `container-type: inline-size` 已删除，避免留下无效声明。

断点：980（`.first` 单列）/ 780（`.stats`、`.tiles` 单列）/ 640（`.kpis` 两列）/ 470（`.kpis` 单列）。

---

## 5. 验证

### 5.1 截图
`artifacts/visual/`：

| 文件 | 内容 |
|---|---|
| `base-*-desk.png` | 改前四视图基线 |
| `v2..v6-*.png` | 逐轮迭代（含浅色主题） |
| `final-*-desk.png` | 改后四视图（深色，生产尺寸） |
| `light2-card-desk.png`、`light-insights-desk.png`、`light-settings-desk.png` | 改后浅色主题 |
| `narrow900b-desk.png`、`narrow700-desk.png` | 窄窗重排（886 / 700 CSS px） |

实测窗口尺寸（设备像素 @ dpr 1.25）：小卡 530×412、洞察 1475×1000、诊断 1350×950、设置 950×800。

### 5.2 门禁（全部真实 rc）

| 门禁 | 结果 |
|---|---|
| `pytest` | **95 passed**（`artifacts/audit/pytest-ui.xml`：tests=95 fail=0 err=0 skip=0） |
| `tools/reconcile.py` | rc=0，四范围 `bad=none`（1d 198,244,891/3,278；7d 1,779,197,202/18,912；30d 3,395,915,595/30,020；all 4,054,260,096/63,238） |
| `npm run lint` | rc=0 |
| `npm run typecheck` | rc=0 |
| `npm test` | **25 passed**（4 文件） |
| `npm run build` | 成功，`dist/assets/index-CWjhSTBw.css` 21.21 kB / `index-OHGIrBpj.js` 190.59 kB（gzip 59.67） |
| `tools/verify_windows.py --layout card` | 全 `[PASS]`（capture 530×412） |
| `tools/verify_layout_switch.py` | `{"ok": true}`，system / 96 / 144 三轮全 ok |

### 5.3 顺手修的非视觉 bug

`tools/verify_windows.py:105` 的 `CC_HUD_MUTEX=f"Local\cc-hud-verify-..."` 含无效转义 `\c`，
每次运行抛 `SyntaxWarning: "\c" is an invalid escape sequence`（`-W error` 下直接失败）。
改成 `rf"Local\cc-hud-verify-..."` 后同一命令 rc=0 且无警告。

### 5.4 首帧范围错位（截图才发现的真 bug）

拍「已提交构建」的四视图时拍到了自相矛盾的一幕：**分段控件高亮「7 天」，画面却是 1 天的数据**
（3,346 请求 / $28.48，与 `reconcile.py` 的 1d 行吻合）。

根因（`web/src/App.tsx:51` + `web/src/state/useSnapshot.ts:53`）：
`range` 初值是本地默认 `"1d"`，而 `useSnapshot` 一挂载就按它扫描账本 ——
一次全量账本读取要 5–8 秒。等 `bootstrap()` 回来把 `range` 改成服务端真值 `"7d"` 时，
那次 1d 的扫描往往已经返回并渲染到画面上了，于是出现「按钮 7 天 + 数据 1 天」，
并且白做一次 1d 全量扫描。

修法：给 `useSnapshot` 加 `enabled` 门，`boot === null` 时不发请求（`useSnapshot(api, range, boot !== null)`），
boot 回包（含服务端 range）到了才开始扫。

验证：`web/src/app.test.tsx` 新增用例「bootstrap 返回前不请求快照；只按服务端 range 请求一次」，
断言 `snapshot` 只被调用 1 次且参数是 `"7d"`。
**反证**：把 `if (!enabled) return;` 注释掉，该用例立刻红 ——
`expected "snapshot" to be called 1 times, but got 2 times`；恢复后 25 passed。
重拍小卡确认按钮与数据一致（$350 / 17.86亿 / 19,033 请求）。

---

## 6. 没做 / 判不了

1. **托盘图标可见性、圆点点击恢复**：仍未实机证实（沿用 `docs/reports/2026-11-09-doc-errata.md` 的 E4/E5 结论）。
2. **多显示器**：`multi_monitor: "blocked: only 1 display"`，本机只有一块屏，判不了。
3. **浅色主题在真实桌面混合下的观感**：截图固定 `CC_HUD_ALPHA=1`，与用户实际半透明叠桌面不同。
   截图只能证明「配色对比度够」，不能证明「叠在任意壁纸上都好看」。
4. **小卡 424×330 的高度余量**：仍是手算 + 截图目视确认，没有自动化的「内容不溢出」断言。
5. `@container` 为何在 WebView2 157 上不匹配 —— 只确认了现象并绕开，没有查到底。
