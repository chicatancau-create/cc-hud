# -*- coding: utf-8 -*-
"""cc-hud 定时电源动作。"""
import ctypes
import subprocess

from .const import *

__all__ = [
    'POWERS', 'PMINS', 'PMIN_LO', 'PMIN_HI', 'PROV_ROWS', 'GRACE', 'POWERSD', 'run_power',
    'abort_power',
]


POWERS = [('screen', '关闭显示器'), ('sleep', '睡眠'), ('hibernate', '休眠'),
          ('logout', '注销'),
          ('reboot', '重启'), ('off', '关机')]


PMINS = [(15, '15 分钟'), (30, '30 分钟'), (60, '1 小时'), (120, '2 小时')]


PMIN_LO, PMIN_HI = 1, 720        # 自定义步进的钳位范围(分钟)


PROV_ROWS = 8                    # 应用与供应商合表行数: 3 行应用 + 5 行供应商/回填


GRACE = 15                                       # 到点后留给 shutdown 自己的反悔窗口(秒)


POWERSD = dict(POWERS)


def run_power(kind):
    """执行电源动作, 返回 True 只代表"确实下发出去了"。
    关屏/睡眠/休眠走 API, 关机/重启走 shutdown 并带 /t 宽限, 注销走 shutdown /l(无宽限、不可撤)。"""
    u = ctypes.windll.user32
    if kind == 'screen':
        # SC_MONITORPOWER + 2 = 关屏; 动一下鼠标就回来, 不影响任何程序。
        # 必须是 Post: SendMessageW 对 0xFFFF(所有顶层窗口)是**同步广播**, 只要有一个
        # 不泵消息的窗口在, UI 线程就跟着一起卡死 —— 而这条链就挂在 _tick 里。
        return bool(u.PostMessageW(0xFFFF, 0x112, 0xF170, 2))
    if kind in ('sleep', 'hibernate'):
        # SetSuspendState(bHibernate, bForce, bWakeupEventsDisabled)。第一参才是关键:
        #   0 = 睡眠(本机实测只有 S0 低电量待机, S3 待机固件不支持)
        #   1 = 休眠(写 hiberfil.sys 后断电, powercfg /a 里"休眠"在可用列表)
        # 第二参一律 0 = 不强杀应用 —— 强杀会丢未保存的东西, 与关机不带 /f 同一个理由。
        return bool(ctypes.windll.powrprof.SetSuspendState(1 if kind == 'hibernate' else 0, 0, 0))
    flag = {'logout': '/l', 'reboot': '/r', 'off': '/s'}[kind]
    args = ['shutdown', flag] + ([] if kind == 'logout' else ['/t', str(GRACE)])
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=10, creationflags=0x08000000)   # 0x08000000 = 无窗口
    except Exception:
        return False
    return r.returncode == 0


def abort_power():
    """撤掉已经交给系统的关机/重启倒计时。返回 False = 系统那边本来就没有倒计时。"""
    try:
        return subprocess.run(['shutdown', '/a'], capture_output=True,
                              timeout=10).returncode == 0
    except Exception:
        return False
