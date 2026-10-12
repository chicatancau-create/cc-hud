# cc-hud

Windows 桌面的 CC Switch 用量悬浮统计 HUD：单文件 tkinter 自绘面板，只读地把**本机六个 AI 客户端**的用量账合并成一个总量，并自带一套 A–X 取证门禁（`verify.py`，112 条判据，退出码 0 才算绿）。

本仓库面向代码审计者，因此下面「数据口径与守恒不变量」「已知未决」两节是重点——它们就是 bug 的藏身处和判定标准。

## ✨ 功能特性

- **六路合并**：CC Switch 代理库 + cc-haha(Claude Code 壳) + Qoder + Qoder CN + ZCode + 牧羊人(Herdsman) + Codex 未被 CC Switch 回填的会话
- **口径一致**：净 token 一路到底（回填类数据源的 `input_tokens` 含缓存读，先减再算），任何视图相加都等于总量
- **双计保险**：每一路都按会话 id 与 CC Switch 求交集，一旦相交**整路拒绝并入**，宁可少计不双计
- **今日档按小时条形图**：范围内只有一天时画不出跨天曲线，改为 24 根柱（柱=净 token，折线=成本）
- **完全跟随 CC Switch 启停**：开机只判定一回（不常驻、不轮询），CC Switch 退出则 HUD 跟着退出
- **定时电源**：到点关屏/睡眠/休眠/注销/重启/关机，带可撤销的系统级宽限，且跨 HUD 重启续用

## 🖥️ 演示

| 文件 | 内容 |
|---|---|
| `shot-today-bars.png` | 宽版 + 今日档小时条形图 |
| `shot-wide.png` | 宽版（7 天档，趋势曲线 + 两排 4 卡 + 两条全宽横幅） |
| `shot-expanded.png` | 展开竖版长条 |
| `shot-collapsed.png` | 收起态小卡 |
| `shot-solid.png` | 关掉键色镂空的对照图 |
| `menu-flyout.png` / `menu-flyout-hover.png` | 自绘右键菜单与二级子菜单 |
| `peek-dot.png` / `corner-zoom.png` | 隐藏后的角落呼出点、锚点对齐放大 |
| `live-*.png` | 活体窗口 PrintWindow 取证 |

## 🛠 技术栈

- Python 3.14.2 + 自带 tkinter（**实测版本**；其他版本未验证，唯一硬性要求是标准库 `tkinter` 可用）
- Pillow 12.3.0 —— 唯一第三方依赖（曲线/条形/圆角卡片的 4× 超采样位图，Tk canvas 不做抗锯齿）
- 其余全为标准库：`tkinter`、`ctypes`（托盘 / Toolhelp32 / PrintWindow / SendInput）、`sqlite3`、`json`、`re`
- 无框架、无构建步骤、无网络请求

## 🚀 快速开始（以下命令均已实测）

```bash
# 0) 依赖：Python 3.14 + Pillow
python -c "import tkinter, sqlite3, ctypes; from PIL import Image, ImageDraw, ImageTk"

# 1) 数据层单测（3 项，不碰界面）
python -X utf8 -m unittest test_data -v

# 2) 全量取证门禁（A–X，112 条判据，跑数分钟；退出码 0 = 全绿）
python -X utf8 verify.py

# 3) 跑起来（无控制台窗口）
pythonw cc-hud.pyw

# 4) 重拍三条版式的实拍证据
python -X utf8 shot.py
```

必须带 `-X utf8`：本机 stdout 默认 GBK，中文断言与逐字比对会截断/错判。

`verify.py` 会真的创建一个 HUD 窗口并驱动它（含真点击、真托盘消息、真子进程），**运行期间不要动鼠标**；它把电源动作全部打桩，不会真关机。

## 📁 目录结构

```
cc-hud.pyw          主程序（单文件）：数据层 fetch/merge_* → 版式 _layout/_cX → 绘制 paint
follow-probe.pyw    开机一次性判定器（决定"要不要拉起 HUD"，判完即退）
verify.py           A–X 取证门禁套件
test_data.py        数据层单元测试（缓存失效、重复响应取末次、导出 URL 脱敏）
shot.py             三条版式 + 镂空对照的 PrintWindow 实拍取证
start-hud.bat       手动启动入口（pythonw + 无控制台）
hud-state.json      运行时用户偏好（已 gitignore，不入库）
```

## 🔌 数据源与口径

面板上的每一个数字都来自下表，**没有任何估算列**。

| 路 | 本机位置 | 能给出 | 给不出（因此不并） |
|---|---|---|---|
| CC Switch 代理库 | `~\.cc-switch\cc-switch.db` → `proxy_request_logs` | 请求数、成本、四项 token、状态码、延迟、小时 | —— |
| cc-haha | 自动发现配置目录（实测 `E:\cc-haha`）的 `index-v1.sqlite` + transcripts | 成本、四项 token、消息数、工具调用、活跃时长 | 状态码、延迟 |
| Qoder / Qoder CN | `~\.qoder\projects\**\*.jsonl`、`~\.qoder-cn\...` | 请求数、credits | **token 四项实测恒为 0**、成本 |
| ZCode | `~\.zcode\cli\db\db.sqlite` → `model_usage` | 逐请求四项 token、模型、耗时 | 成本（本机不记钱） |
| 牧羊人 Herdsman | `~\.herdsman\model_stats\events.jsonl` | 输入/输出 token、http_status、ttft | 缓存分项、成本 |
| Codex 未回填 | `~\.codex\sessions` + `archived_sessions` | 会话级四项 token | 逐请求小时归属（只有会话级时间戳） |

### 净 token 口径（最容易出错的地方）

```
新增输入 = sum(input_tokens) - sum(cache_read_tokens where 该行的 input 已含缓存)
真实消耗 = 新增输入 + 输出 + 缓存创建 + 缓存命中
命中率   = 缓存命中 / (缓存命中 + 新增输入 + 缓存创建)
```

哪些行的 `input_tokens` 含缓存读，是**实测出来的**，不是猜的：

- `data_source='codex_session'`：含（全库 20.0 亿裸加 vs 净 14.1 亿）→ 减
- ZCode `model_usage`：含（`raw_usage_json.totalTokens = inputTokens + outputTokens`）→ 减
- `session_log`（Claude 回填）：2872 行里 2803 行 `input < cache_read` → **不含，不减**
- `proxy`：1093 行里 0 行 `input < cache_read` → 疑似也含，**当前未减**（见「已知未决」）

### 守恒不变量（`verify.py` S/W 段逐范围硬断言）

```
Σ应用请求 == Σ按天请求 == Σ小时请求 == 总请求
Σ按天净tok == Σ应用净tok == 四项相加 == 真实消耗
Σ四项成本 == Σ按天成本 == Σ应用成本 == 总成本
Σ每小时(请求|净tok|成本) == 对应总量        # 今日档条形图的依据
横幅"并入成本/token" == 真的并进去的那份     # 本地日口径, 不是索引全量
```

**"并了一半"是这个项目历史上最严重的 bug 类**：总量并了新源、某个视图忘了并，于是同一张卡里出现「总请求 272 / 今日 34」。新增任何一路，必须同时落到：总量、按天、按小时、今日、昨日、近 1 小时、应用表、（若给得出）模型表。

### 双计保险

每路带一个会话/请求 id 集合，与 CC Switch 的 `all_sids` 求交集；非空则**整路拒绝并入**并在面板写明。实测当前交集为 0（Qoder 243 个会话 vs CC Switch 1185 个）。

## 🔒 硬约束（改代码前必读）

1. 两个 SQLite 库**必须** `mode=ro` 只读打开（`cc-haha` 在跑、WAL 活跃时也能读，已实测）
2. **绝不读取** `providers.settings_config`、`universal_providers`、cc-haha 的 `providers.json` —— 里面是明文 API key
3. 测试**绝不能真执行电源动作**：`verify.py` 顶部用假 `subprocess.Popen/run` 全程记录，R 段断言"没有真的调用过 shutdown"
4. 自绘菜单浮层**禁止 grab**（一 grab 子浮层就收不到事件）
5. 面板锚点是**圆点的右上角**，不是左上角；任何改尺寸的分支都必须重锚
6. 位图引用必须一直被持有（`ImageTk` 丢引用即被回收）；且**不能**存在会被 `_layout()` 清空的 `imgs` 里（圆点踩过这个坑）

## 🧪 verify.py 各段含义

| 段 | 验什么 |
|---|---|
| A | 一次刷新里图元删/建数量（无闪烁判据） |
| B / B2 / B3 | 窗口越界、文字互撞、**卡内越界**（宽版单列仅 482 物理px，越界会压到隔壁列） |
| C | 键色镂空的设置/还原 |
| D / E | 数值正确性；4 范围 × 2 状态跑遍，抓"注册了从不赋值"的死槽位 |
| F | 显示/隐藏边沿判定 + 隐藏期间零读库（不跟随模式） |
| G / H | 托盘（含**图标像素级取证**：`GetIconInfo`→数不透明像素）；角落呼出点可点可拖 |
| I | 空范围不崩、红字会被成功绘制清掉、悬停读数 |
| J / K / K2 | 定时电源到点与取消；自绘菜单几何/子菜单存活/外点关闭；连着点 |
| N | 按应用对账：HUD 的 app 维度 == **原始 SQL 独立基线**（含各并入量） |
| O | 双击卡片大小互切 |
| P / Q | 宽版行制版式（权重排布、间隙统一、每排底边齐平）；面板落点 == 圆点右上角 |
| R | cc-haha：路径自动发现、本地日分桶、并入守恒、双计保险、缺库不崩 |
| S | 四范围 × 14 项口径守恒（防"并了一半"） |
| T | 电源真实参数（假 subprocess 调真函数）、定时跨重启续用、**坏状态文件不许让程序起不来**、托盘事件合并、位图引用存活、文案与取数对齐 |
| U | Qoder 路：解析可复现、会话不相交、"token 恒 0"哨兵、缺目录不崩 |
| V | ZCode / 牧羊人 / Codex 漏项 / Qoder CN 的口径与双计 |
| W | 今日档小时条形：六路逐小时守恒、画法切换、悬停、无残留图元 |
| X | 跟随启停：启动文件夹解析、判定真值表 8 组、退出标记联动 |

## 🐞 已知未决（审计起点）

1. **`proxy` 行的 `input_tokens` 疑似也含缓存读**（实测 1093 行里 0 行 `input < cache_read`），但当前只对 `codex_session` 做减法。改成按语义统一减会让命中率从 88.29% 移到约 90.54%，且与 CC Switch 自己界面不再一致 —— 未决，等产品拍。注意库里那列 `input_token_semantics`（proxy=1、三种回填=0）**不是**包含性标志，别拿它当依据。
2. **Codex「同一会话内部回填不全」只报不并**：某会话 rollout 有 94 次响应、CC Switch 只回填 13 行。CC 的 `request_id` 尾号（261..273）不是 rollout 行号（1286,1293…），拿不到逐请求对应关系，所以宁少不双计。
3. **`follow-probe.pyw` 的"HUD 是否已在跑"查询不可靠**：`CreateMutexW` 判存在有副作用（自己把互斥体建出来），改成 `OpenMutexW` 后实测仍查不到。目前靠 HUD 自身 `__main__` 的互斥体闸门兜底（多拉起的实例会自杀），已实测最终只剩一个进程。
4. **多显示器下 `_work_area()` 仍按主屏算**（`SPI_GETWORKAREA` 只回主屏），拖到副屏后可能被拽回。本机单屏，未实测。
5. **`fetch_haha` / `fetch_zcode` / `fetch_herdsman` 把"库损坏"吞成"这一路缺席"**（`except Exception: return None`），静默少计与"没装这个软件"在界面上无法区分。
6. **每次刷新在后台线程整份重读活动 transcript**：缓存键是 `(size, mtime)`，追加即 miss；成本随当日用量线性增长且无上限。已移到后台线程（不冻 UI），但没做增量读。
7. `verify.py` 的 K 段（菜单几何）**偶发** `bad window path name`：真游标/点击会触发 `Pop._watch` 的"点外面就关"。判为环境抖动，重跑即过；不要为此改产品代码。

## 📄 许可证

未指定。默认保留所有权利。
