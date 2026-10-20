# -*- coding: utf-8 -*-
r"""CC Switch 悬浮统计 HUD · 只读两份库 (mode=ro): %USERPROFILE%\.cc-switch\cc-switch.db
 与 cc-haha 的会话索引库(路径自动发现, 见 haha_db)。

口径(八路数据源合并后的总量, 单看 CC Switch 那一路仍与它界面逐位对账过):
  新增输入 = sum(input_tokens) - sum(cache_read_tokens where data_source='codex_session')
             ^ codex 回填行的 input_tokens 本身已含缓存读, 不减就是重复计(全库 20.0亿 vs 净 14.1亿)
  真实消耗 = 新增输入 + 输出 + 缓存创建 + 缓存命中
  缓存命中率 = 命中 / (命中 + 新增输入 + 创建)
  第二路 cc-haha(直连 Claude Code, 不经过 CC Switch 代理)按**本地日**并进上面每一个维度:
  成本/四项token/请求数/小时分布/模型表/应用表/今日·昨日·近1小时 全部一起并 —— 并一半就会
  出现「总请求 272 而应用行相加 34」这种各说各话, verify S 段按四个范围逐项钉住。
  能并的前提是两个源的会话 id 不相交(双计保险在 merge_haha, R 段断言)。
  只有**状态码与延迟**仍是 CC Switch 口径 —— cc-haha 的 transcript 里没有这两维, 面板上写明了。
  第三路起都是"不走代理的客户端各自的本地账": Qoder / Qoder CN(只有响应数与 credits, token
  四项本机恒为 0)、ZCode、牧羊人、Codex 未被 CC Switch 回填的会话, 以及第七八路 **WorkBuddy
  国内版与国外版**(各自 `~/.workbuddy*/projects/**/*.jsonl` 的逐调用账)。
  WorkBuddy 这一路的坑比 cc-haha 还深一层: `prompt_tokens` 同时含**缓存读与缓存写**, 实测
  `prompt = 命中 + 未命中 + 写` 对 1432/1432 行成立 —— 只减命中会把写缓存(国内 29 万 / 国外 34 万)
  重复算一次。拆完三桶后四桶相加恰好等于应用自己记的 `total_tokens`, verify Y 段按这条对账。
  它只记官方积分不记美元, 所以成本记 0; 而积分**只有国内版给得出**(逐调用覆盖 96.2%),
  国外版 1182 条里只有 20 条带值、且与它自己的 workbuddy.db 差 5 倍 -> 国外版一个积分都不并。
计时只存在于 data_source='proxy' 的行(代理转发实测), 会话日志回填的行和 cc-haha 那一路都没有计时。
只读取用量与配置字段, 绝不读取 providers.settings_config / universal_providers / cc-haha 的
providers.json —— 那三处存明文 API key。两份库一律 mode=ro。
刷新只就地改文字/坐标/颜色, 不销毁重建 -> 无闪烁。

启动机制: 跟随器就是进程本身 —— 每 3s 用 Toolhelp32 快照查一次 cc-switch.exe,
CC Switch 起来就显示, 退出就跟着退出(隐藏期间零 SQL)。
启动方式: 启动文件夹里放的是 **follow-probe.pyw**(不是本程序)。它在开机时只判定一回
—— CC Switch 在跑才拉起本程序, 没跑就永久退出, 不常驻也不按计划重复。
本程序运行中若发现 CC Switch 退出, 就跟着退出(除非还挂着定时电源, 见 _tick)。
命名互斥体保证只有一份。
隐藏后从系统托盘找回: 左键/双击 = 显示·隐藏互切, 右键 = 弹同一个菜单。
托盘图标默认被 Windows 收在任务栏溢出菜单里, 要常驻需在
「设置 → 个性化 → 任务栏 → 其他系统托盘图标」打开本项。
"""
import ctypes
import json
import math
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import datetime as dt
from urllib.parse import urlsplit, urlunsplit
from ctypes import wintypes as wt

import tkinter as tk
from tkinter import font as tkfont
import sys

import cchud
from cchud.const import *
from cchud.util import *
from cchud.render import *
from cchud.power import *
from cchud.data import *
from cchud.sysw import *
from cchud.pop import *
from cchud.hud import *

# 各子模块都写了 __all__(含 _ 开头的内部名), 所以上面星导入后 m._dpi_aware /
# m._work_area / m._hicon / m._glyph_img / m._parse_qoder 这些 verify.py 直接
# 取的下划线名字同样在。
# verify.py / shot.py / test_data.py 加载本文件后会对模块属性直接赋值打桩。
# 这个转发器让赋值同时落到 cchud 子模块里, 与拆分前是同一个语义。
cchud.install_patch_forwarder(sys.modules[__name__])


if __name__ == '__main__':
    _dpi_aware()
    if already_running():
        os._exit(0)                              # 开机自启已有一份在跑, 不再叠第二张卡片
    HUD().run()
