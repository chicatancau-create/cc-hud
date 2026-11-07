# cc-hud

Windows 桌面的 CC Switch 用量悬浮统计 HUD：tkinter 自绘面板（主程序 `cc-hud.pyw` + `cchud/` 包），只读地把**本机九个 AI 客户端/会话账本**的用量合并成一个总量，并自带一套 A–Z 取证门禁（`verify.py`，27 段 167 条 assert，退出码 0 才算绿）。

本仓库面向代码审计者，因此下面「数据口径与守恒不变量」「已知未决」两节是重点——它们就是 bug 的藏身处和判定标准。

## ✨ 功能特性

- **九路合并**：CC Switch 代理库 + cc-haha(Claude Code 壳) + Qoder + Qoder CN + ZCode + 牧羊人(Herdsman) + Codex 未被 CC Switch 回填的会话 + **WorkBuddy 国内版与国外版** + DSH(DeepSeek Harness) 会话级累计账
- **口径一致**：净 token 一路到底（回填类数据源的 `input_tokens` 含缓存读、WorkBuddy 还含缓存写，先拆再算），任何视图相加都等于总量
- **双计保险**：每一路都按会话 id 与 CC Switch 求交集，一旦相交**整路拒绝并入**，宁可少计不双计
- **面板落位**：点圆球 → 小面板一定浮到最前，并沿圆球**向左下方**展开（面板右上角钉在圆球右上角）；点「展开大面板」→ 大面板落在**工作区正中**（让开任务栏）。居中只管"小→大那一次切换"，之后随便拖，刷新不会把它拽回去（`verify.py` Z 段逐条量像素）
- **今日档按小时条形图**：范围内只有一天时画不出跨天曲线，改为 24 根柱（柱=净 token，折线=成本）
- **不装开机自启，手动启动**（2026-11-07 按用户点名取消）：桌面上不留常驻进程。启动方式是快捷方式 `E:\DeskBox\编程工具\CC Switch HUD.lnk`（或 `start-hud.bat` / `pythonw cc-hud.pyw`）。**CC Switch 退出 → HUD 跟着退出**（唯一例外：定时电源还挂着时只隐藏，留撤销口）；反过来 CC Switch 重新启动**不会**自动拉起 HUD，需要自己点一下快捷方式。
- **定时电源**：到点关屏/睡眠/休眠/注销/重启/关机，带可撤销的系统级宽限，且跨 HUD 重启续用

## 🖥️ 演示

| 文件 | 内容 |
|---|---|
| `shot-today-bars.png` | 宽版 + 今日档小时条形图 |
| `shot-wide.png` | 宽版（7 天档，趋势曲线 + 两排 4 卡 + 三条全宽横幅） |
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

# 2) 全量取证门禁（A–Z，27 段 167 条 assert，跑数分钟；退出码 0 = 全绿）
python -X utf8 verify.py

# 3) 跑起来（无控制台窗口）—— 桌面快捷方式「CC Switch HUD.lnk」就是这一条命令
pythonw cc-hud.pyw

# 4) 重拍三条版式的实拍证据
python -X utf8 shot.py
```

必须带 `-X utf8`：本机 stdout 默认 GBK，中文断言与逐字比对会截断/错判。

`verify.py` 会真的创建一个 HUD 窗口并驱动它（含真点击、真托盘消息、真子进程），**运行期间不要动鼠标**；它把电源动作全部打桩，不会真关机。

## 📁 目录结构

```
cc-hud.pyw          入口 + 口径说明（薄壳：导入 cchud 包，`verify.py` 仍以它为模块打桩）
cchud/              实现包：const(常量/别名) data(九路取数与合并) hud(版式与交互) render(PIL 位图)
                    pop(自绘菜单) power(定时电源) sysw(托盘/进程/DPI/PrintWindow) util(格式化)
follow-probe.pyw    开机一次性判定器（**现已不装进启动文件夹**，保留给"以后想恢复自启"：把它的快捷方式放回 Startup 即可）
verify.py           A–Z 取证门禁套件
test_data.py        数据层单元测试（缓存失效、重复响应取末次、导出 URL 脱敏）
shot.py             三条版式 + 镂空对照的 PrintWindow 实拍取证
start-hud.bat       手动启动入口（钉死 D:\PyCharm\Python\pythonw.exe，先自检 tkinter/Pillow 再 start）
cc-hud.ico          桌面快捷方式的图标（7 帧 16–256px，全部无压缩 BMP 帧）
hud-state.json      运行时用户偏好（已 gitignore，不入库）
历史会话/           2026-11-07 从 AI 任务区(G:\AIrenwu)随项目搬来的旧会话档案（UI 优化轮次记录与
                    前后对照截图）。已 gitignore，只作历史证据，不参与构建。
```

启动入口（**不装开机自启**，2026-11-07 用户点名取消）：快捷方式 `E:\DeskBox\编程工具\CC Switch HUD.lnk` → `pythonw.exe "G:\cc-hud\cc-hud.pyw"`（隐藏窗口、带上面这个 ico）。也可以直接跑 `start-hud.bat` 或 `pythonw cc-hud.pyw`。程序有命名互斥体闸门，重复点击不会再叠一张卡片；CC Switch 退出时 HUD 跟着退出，之后重新打开 CC Switch **不会**自动拉起，需要自己点一下。

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
| WorkBuddy 国内版 | `~\.workbuddy\projects\**\*.jsonl` → `providerData.rawUsage` | 逐请求四项 token、模型、官方积分(credits) | 成本（本机不记美元）、状态码、延迟 |
| WorkBuddy 国外版 | `~\.workbuddy-ai\projects\**\*.jsonl`（含 `subagents/`，归父会话） | 逐请求四项 token、模型 | **credits**（两本账互相矛盾，见下）、成本、状态码、延迟 |
| DSH | `~\.dsh\storages\session_projcache\sessions\*.json` → `tokenUsage` 累计值 | 会话级四项 token、模型、轮次 | 逐请求小时归属（只有会话创建时刻）、成本（本机不记钱） |

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
- WorkBuddy `rawUsage.prompt_tokens`：**同时含缓存读与缓存写**，实测 `prompt = 命中 + 未命中 + 写`
  对 1432/1432 行成立 → 两项都要拆出去。只减命中会把写缓存重复算一次（国内 29 万 / 国外 34 万 tok）。
  拆完三桶后 `净输入 + 输出 + 命中 + 写` 恰好等于应用自己记的 `total_tokens`（国内 179,934,868 /
  国外 151,440,924）—— `verify.py` Y 段就钉这条等式，并用独立一遍 `os.walk` 解析做对照基线。
  注意两版的"写缓存"字段名不一样：国内版是 `cache_creation_input_tokens`，国外版只有
  `prompt_cache_write_tokens`。

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

每路带一个会话/请求 id 集合，与 CC Switch 的 `all_sids` 求交集；非空则**整路拒绝并入**并在面板写明。实测当前交集为 0（Qoder 263 个会话 vs CC Switch 1170 个；WorkBuddy 两版 29 个会话与 CC Switch、以及**两版彼此之间**也都是 0 交集）。

**DSH 是唯一"整路相交"的一路**：本机 DSH 就挂在 CC Switch 代理后面，库里 `app_type='dsh'` 的 3020 行 / $7.87 / 420,398,446 tok 与本地 26 个有账会话的累计值**逐位相等（26/26）**。所以它不能按上面的"相交就整路拒收"处理（那会把代理没记的会话一起丢掉），也不能整份并（那是把同一笔账数两遍）。收口办法：`fetch_dsh(start, have_sids)` 只补 **CC Switch 一行都没有**的会话；本机因此这一路贡献 0，DSH 的量全部以代理库自己的行为真值 —— V8 段同时断言"收口后不再含已记会话"与"HUD 的 DSH 应用行 == 原始 SQL 逐位一致"，另在合成视图里抹掉重叠会话来量并入守恒算术。

### credits 与成本：只有部分源给得出

- **成本(美元)**：只有 CC Switch 代理行与 cc-haha 有。其余各路本机都不记钱 → 记 0。这句声明挂在**底栏**（`foot.m`，`... · 额外源无本机定价`），不挂在应用卡的状态行上：状态行的真实余量只有"锚点 - 标题右沿 - 8"（宽版实测 248px），三个声明拼进去会被省略号截成 `额外…`，等于声明写了但用户看不到 —— V6 段现在同时断言"底栏有这句"与"状态行不含 `…`"。
- **credits**：Qoder 系与 **WorkBuddy 国内版**给得出（后者逐调用 `credit`，实测覆盖 96.2%、合计 678.64 分，与 `workbuddy.db::session_usage.credit_json` 同源）。
- **WorkBuddy 国外版故意不并 credits**：1182 条里只有 20 条带值（合计 647.55，均值 32.4/次），而它自己的 `workbuddy.db` 只记到 103.68 —— 两本账差 5 倍，说明这一版本机没有可信积分基线。Y 段用断言把"HUD 并进去的必须是 0"钉死，同时打印出原始 647.55 证明这个 0 是**有意不并**而不是漏读。

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
| V | ZCode / 牧羊人 / Codex 漏项 / Qoder CN 的口径与双计；**V8 第九路 DSH**：独立 glob 基线逐位对账、归日与 `createdAt` 一致、四视图守恒、**按 `have_sids` 收口**（代理已记的会话不补）、应用行 == 原始 SQL、缺目录降级不影响其它八路 |
| W | 今日档小时条形：九路逐小时守恒、画法切换、悬停、无残留图元 |
| X | 跟随启停：启动文件夹里 HUD 本体与判定器**都为 0**（自启已取消）、判定真值表 8 组、退出标记联动、"跟着退出/有定时不退"两条分支在位 |
| Z | 面板落位：展开大面板落在工作区正中（像素级）、拖完刷新不回弹、收起回到圆球右上角（向左下扩展）、点圆球一定映射出来且带 `WS_EX_TOPMOST` |
| Y | WorkBuddy 两版：独立 `os.walk` 基线对账、**缓存拆桶不多不少**（净输入+命中+写 == Σprompt、四桶 == 应用自记 `total_tokens`）、每路四视图齐并、积分只认国内版（国外版硬断言并 0）、人造相交整路拒绝、缺目录降级、横幅 8 个槽位无空值 |

## 🐞 已知未决（审计起点）

1. **`proxy` 行的 `input_tokens` 疑似也含缓存读**（实测 1093 行里 0 行 `input < cache_read`），但当前只对 `codex_session` 做减法。改成按语义统一减会让命中率从 88.29% 移到约 90.54%，且与 CC Switch 自己界面不再一致 —— 未决，等产品拍。注意库里那列 `input_token_semantics`（proxy=1、三种回填=0）**不是**包含性标志，别拿它当依据。
2. **Codex「同一会话内部回填不全」只报不并**：某会话 rollout 有 94 次响应、CC Switch 只回填 13 行。CC 的 `request_id` 尾号（261..273）不是 rollout 行号（1286,1293…），拿不到逐请求对应关系，所以宁少不双计。
3. **`follow-probe.pyw` 的"HUD 是否已在跑"查询不可靠**：`CreateMutexW` 判存在有副作用（自己把互斥体建出来），改成 `OpenMutexW` 后实测仍查不到。目前靠 HUD 自身 `__main__` 的互斥体闸门兜底（多拉起的实例会自杀），已实测最终只剩一个进程。
4. **多显示器下 `_work_area()` 仍按主屏算**（`SPI_GETWORKAREA` 只回主屏），拖到副屏后可能被拽回。本机单屏，未实测。
5. **`fetch_haha` / `fetch_zcode` / `fetch_herdsman` / `fetch_workbuddy` 把"库损坏"吞成"这一路缺席"**（`except Exception: return None` 或整文件跳过），静默少计与"没装这个软件"在界面上无法区分。
6. **每次刷新在后台线程整份重读活动 transcript**：缓存键是 `(size, mtime)`，追加即 miss；成本随当日用量线性增长且无上限。已移到后台线程（不冻 UI），但没做增量读。
7. `verify.py` 的 K 段（菜单几何）**偶发** `bad window path name`：真游标/点击会触发 `Pop._watch` 的"点外面就关"。判为环境抖动，重跑即过；不要为此改产品代码。
8. **WorkBuddy 数据目录写死为 `~\.workbuddy` / `~\.workbuddy-ai`**：这两个名字来自各自安装目录 `resources/app.asar.unpacked/cli/product.json` 的 `dataFolderName`（实测国内版 endpoint=workbuddy.cn / 国外版 =workbuddy.ai）。厂商改名或用户搬走配置目录时，这一路会**静默缺席**——cc-haha 那一路做了多盘自动发现，WorkBuddy 没有。
9. **WorkBuddy 只读 jsonl，不读它的 `workbuddy.db`**：逐调用账只在 `projects/**/*.jsonl`；`workbuddy.db::session_usage` 只有会话级 `used/size/credit_json`。实测两版"最新 jsonl 的 mtime == `session_usage` 最大 `updated_at`"（国内 09-19 15:17 / 国外 10-14 16:56），所以 jsonl 不是被 sqlite 取代的旧账，只是用户真的停了。若哪天某版只写 db 不写 jsonl，本路会停在最后一天而不报错。
10. **WorkBuddy 的缓存命中率极高（国内 98.46% / 国外 97.31%），会拉动全局命中率**：并入后 7 天档命中率 97.00%、全部档 86.40%。这不是 bug（各源如实报它自己的四项），但读数时要知道它已经不只是 CC Switch 那一路的命中率了。
11. **DSH 的小时归属是近似的**：会话 json 只有 `createdAt`（会话创建时刻），没有逐请求时间戳，所以 116 轮全记到"创建那一天的那一个钟点"，小时视图与"近 1 小时"对 DSH 只能算占位。且本机 DSH 全被代理记过，这一路在界面上**就是应用表里的 `DSH` 行**（不是独立横幅）；应用表只有 3 个应用槽位按成本排序，今日档 DSH 没有行时就看不见 —— V8 第 8 项因此把检查钉在「全部」档。
12. **卡片 `.rt` 状态行的宽度预算原来是写死的启发式**（`cardw - 74*s`）：宽版应用卡真实余量是"锚点(卡右沿-11) - 标题右沿 - 8"= **248px**，而启发式给了 281px —— 多算的 33px 就是文字压到标题上的量。现在 `prov.rt` 改按真实几何取预算（取两者较小），并带"长写法→短写法→整条不写"的降级梯子。仍留的口子：句子用的是精确数字，**总请求数进到 7 位数时基础句本身就会超 248px** 而被截断；届时应改用 `big()` 缩写或拆成两行，不要靠梯子硬扛。其它卡片的 `.rt` 还是统一减 74。
13. **`verify.py` 的 I 段悬停判据依赖"当前没有拖动"**：真鼠标在测试期间落到窗口上会设起 `self._drag`，而松开点在窗外时清不掉，`_hover` 第一句就早退 —— 原来表现为 `AttributeError: 'HUD' object has no attribute '_tip_lab'`，看着像产品坏了。现在段内显式回到 `_drag=None` 的前置态并带可读断言；根因（真实指针事件干扰测试）未消除，跑测试时不要动鼠标。

## 📄 许可证

未指定。默认保留所有权利。
