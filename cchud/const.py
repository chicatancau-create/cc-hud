# -*- coding: utf-8 -*-
"""cc-hud 常量与模块级共享缓存。最底层, 无包内依赖。"""
import os


# cc-hud.pyw 所在的目录(包目录的上一级)。原文件里 STATE 与导出文件都用
# os.path.dirname(os.path.abspath(__file__)) 定位; 搬进 cchud/ 后 __file__
# 变成了包内文件, 所以这里显式算一次, 保证落盘位置一字不差。
ROOTDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

__all__ = [
    'DB', 'QDIR', 'QDIR_CN', 'ZCODE_DB', 'HERD_LOG', 'CODEX_DIRS', 'WB_SOURCES', 'HDB_SUB',
    'DSH_DIR',
    '_QODER_FILES', '_HAHA_FILES', '_WB_FILES', 'NEWDAY', 'ROOTDIR', 'STATE', 'QUIT_MARK', 'REFRESH_MS',
    'POLL_MS', 'CC_TICKS', 'RANGES', 'ALPHAS', 'CARD_W', 'WIDE_W', 'CHIP_BLOCK_W', 'PAD', 'PEEK',
    'CARD_LBL_DY', 'CARD_VAL_DY', 'BG', 'CARD', 'CARD2', 'EDGE', 'TRACK', 'FG', 'DIM', 'FAINT',
    'MUTED', 'CY', 'GR', 'VI', 'AM', 'PK', 'TE', 'MA', 'IN', 'CH_IN', 'CH_OUT', 'CH_CW', 'CH_RD',
    'CH_COST', 'PROV_ALIAS', 'APP_ALIAS',
]


DB = os.path.join(os.path.expanduser('~'), '.cc-switch', 'cc-switch.db')


# Qoder 的 agent 会话目录(第三路)。它不走 CC Switch 代理, 所以那 943 条代理行里根本没有它;
# 与 cc-haha 一样按候选位置找, 找不到就整路缺席(不报错)。
QDIR = os.path.join(os.path.expanduser('~'), '.qoder', 'projects')


# Qoder CN 是**另一个**目录(国际版 .qoder / CN 版 .qoder-cn), 两套会话账互不相干。
QDIR_CN = os.path.join(os.path.expanduser('~'), '.qoder-cn', 'projects')


ZCODE_DB = os.path.join(os.path.expanduser('~'), '.zcode', 'cli', 'db', 'db.sqlite')


HERD_LOG = os.path.join(os.path.expanduser('~'), '.herdsman', 'model_stats', 'events.jsonl')


CODEX_DIRS = [os.path.join(os.path.expanduser('~'), '.codex', 'sessions'),
              os.path.join(os.path.expanduser('~'), '.codex', 'archived_sessions')]


# WorkBuddy 两个版本的会话账(第七、八路)。目录名不是猜的 —— 来自各自安装目录 resources/app.asar.unpacked/
# cli/product.json 的 dataFolderName: 国内版 WorkBuddy.exe(5.8.2) -> `.workbuddy`,
# 国外版 WorkBuddyAI.exe(5.7.6) -> `.workbuddy-ai`(endpoint 也分别是 workbuddy.cn / workbuddy.ai)。
# 第三个对得上的信号: 各自 ~/.workbuddy*/last-launch.json 里的 version+build == product.json 的
# FileVersion+commit。最后一位 with_credit 是**国外版给不了成本基线**的开关, 见 fetch_workbuddy。
WB_SOURCES = [(os.path.join(os.path.expanduser('~'), '.workbuddy', 'projects'),
               'workbuddy', True),
              (os.path.join(os.path.expanduser('~'), '.workbuddy-ai', 'projects'),
               'workbuddy-ai', False)]


# cc-haha(Claude Code 桌面壳)的索引库。它的配置目录**会被整机搬走**(实测: 先 C:\Users\Admin\.claude,
# 10-08 之后搬到 E:\cc-haha), 写死任一路径都会静默读到一份不再更新的旧索引 —— 所以这里按候选位置
# 逐个找、取 mtime 最新的那个。找法与 cc-haha 自己的扫描根一致: <配置目录>\cc-haha\db\index-v1.sqlite。
HDB_SUB = os.path.join('cc-haha', 'db', 'index-v1.sqlite')


# DSH(DeepSeek Harness)的会话用量缓存(第九路)。一个会话一份 json, 里面只有
# `record.rows.tokenUsage.val.totals` 这个**会话级累计值**, 没有逐次调用的时间戳 ——
# 所以这一路只能按 `record.identity.createdAt` 归到"会话创建那天", 给不出小时分布。
DSH_DIR = os.path.join(os.path.expanduser('~'), '.dsh', 'storages', 'session_projcache',
                       'sessions')


_QODER_FILES = {}         # Qoder 会话 jsonl 的按文件解析缓存(同 _HAHA_FILES 一套做法)


_HAHA_FILES = {}          # transcript -> ((size, mtime_ns, file_id), {message id: ...})


_WB_FILES = {}            # WorkBuddy 会话 jsonl -> ((size, mtime_ns), 逐调用账)


NEWDAY = lambda: {'in': 0, 'out': 0, 'rd': 0, 'cc': 0, 'cost': 0.0, 'msgs': 0}


STATE = os.path.join(ROOTDIR, 'hud-state.json')


# 「我在这个 CC Switch 生命周期里主动退过 HUD」的标记。判定器看到它就不要再拉起,
# 否则用户点了退出、下一次判定又把它叫回来, 就成了流氓行为。
QUIT_MARK = os.path.join(os.environ.get('TEMP', '.'), 'cc-hud-quit.marker')


REFRESH_MS = 30_000


POLL_MS = 150                                          # 界面心跳: 收托盘事件


CC_TICKS = 20                                          # 每 20 拍(≈3s)查一次 CC Switch


RANGES = [('今日', 1), ('7 天', 7), ('30 天', 30), ('全部', 0)]


ALPHAS = (1.0, 0.96, 0.92, 0.86, 0.78)


CARD_W = 424                                   # 逻辑像素


WIDE_W = 1560                                  # 宽版总宽: 1560 逻辑px = 1950 物理px @125% (4 列 × 2 排 + 趋势一整行)


CHIP_BLOCK_W = 380                             # 范围胶囊那一块的最大宽度(宽版下不跟着拉长)


PAD = 13


PEEK = 34                                      # 隐藏后留在角落的呼出圆点直径


# 卡片内纵向基线(逻辑px, 相对卡片顶) —— 全卡统一, 保证宽版同一排的四张卡横向严格对齐。
# 此前是各卡各写: c2 用 47/63、c3 用 46/61、c4 用 45/61、haha/qoder 用 47/63、表格列头 47、
# 代理与配置 46 —— 同排相差 1~2 逻辑px(125% 下 1.25~2.5 物理px), 看上去就是"没对齐"。
CARD_LBL_DY = 46                               # 指标名 / 表格列头


CARD_VAL_DY = 61                               # 指标值 / 表格首行


# 下面每一档都是从用户参考图实测出来的占比最高色, 不是眼睛估的:
#   页面底 #0b0e14(21%) 卡片 #10131d(27%) 卡片亮档 #171a24 描边 #22262e~#2a2d36
#   轨道 #1c1f2a 琥珀 #fbbf24 靛底 #1d2040 青底 #122937 绿底 #102a2b
BG, CARD, CARD2 = '#0b0e14', '#10131d', '#171a24'


EDGE, TRACK = '#262b36', '#1c1f2a'


# 次级文字四档的对比度按 WCAG 2.1 公式在卡片底 #10131d 上实算:
#   FG #e8edf5 = 15.8:1   DIM #8a97a8 = 6.24:1   FAINT #7f8b9e = 5.38:1   MUTED #757f93 = 4.60:1
# 旧值 FAINT #5c6878(3.27:1) / MUTED #454f63(2.25:1) 两档都低于 AA 的 4.5:1。而 MUTED 并不是
# 装饰色 —— 它画的是**真实数据**(表格里的命中率/TOKEN 数值、趋势坐标刻度、四色图例文字、
# 24小时时刻刻度), 3.27:1 在小号字下就是"发糊"。现在四档全部 ≥4.5:1, 层次与色相族不变。
FG, DIM, FAINT, MUTED = '#e8edf5', '#8a97a8', '#7f8b9e', '#757f93'


CY, GR, VI, AM, PK, TE, MA, IN = ('#38bdf8', '#34d399', '#a78bfa', '#fbbf24',
                                  '#f472b6', '#2dd4bf', '#c084fc', '#6366f1')


# CC Switch 原版「使用统计」曲线配色(从其界面截图实测的色桶): 输入蓝/输出绿/创建橙/命中紫/成本红
CH_IN, CH_OUT, CH_CW, CH_RD, CH_COST = '#3b82f6', '#10b981', '#f97316', '#a855f7', '#ef4444'


# CC Switch 对「非代理来源」的请求记的是合成 provider_id, 这里只做显示别名;
# 导出的 JSON 里仍是原始 id。
PROV_ALIAS = {'_codex_session': 'Codex会话回填', '_session': 'Claude会话回填',
              '_opencode_session': 'OpenCode回填'}


# app_type → CC Switch 侧边栏显示名(库里目前只出现过 codex/claude/opencode, 其余按官方列表补齐)
APP_ALIAS = {'codex': 'Codex', 'claude': 'Claude Code', 'claude-desktop': 'Claude Desktop',
             'gemini': 'Gemini CLI', 'grok': 'Grok Build', 'opencode': 'OpenCode',
             'openclaw': 'OpenClaw', 'hermes': 'Hermes', 'pi': 'Pi', 'minimax': 'MiniMax Code',
             'qoder': 'Qoder', 'qoder-cn': 'Qoder CN', 'zcode': 'ZCode',
             'workbuddy': 'WorkBuddy 国内', 'workbuddy-ai': 'WorkBuddy 国外',
             'herdsman': '牧羊人(本地)', 'dsh': 'DSH'}
# ^ 不走代理的直连客户端, 见 fetch_qoder/fetch_zcode/fetch_dsh
