# -*- coding: utf-8 -*-
"""CC Switch HUD 跟随启动判定器 —— 开机时跑**一次**, 决定"要不要拉起 HUD", 然后立刻退出。

为什么要有这个东西: CC Switch 自己没有任何外部命令/hooks 入口(实测它的库 21 张表里
没有 hook/script/command 类表), 所以"CC Switch 一起来 HUD 就跟"只能由第三方触发。
本判定器就是那个触发者, 而且**只判定一回**: 不常驻、不轮询、不按计划重复。

判定规则(与 cc-hud.pyw 里的 should_launch 同一份实现):
  CC Switch 没在跑            -> 不起(它开机没自启, HUD 也就不该存在)
  已经有一份 HUD 在跑         -> 不起(命名互斥体也会挡第二张卡片)
  用户在这个 CC Switch 生命周期里主动退过 HUD -> 不起(否则一分钟后爬回来=流氓)
  其余                        -> 拉起 HUD

开机时 CC Switch 可能比本进程晚起几秒, 所以给了一个**有界**的等待窗口(默认 25 秒):
窗口内每秒看一眼, 等到就起、等不到就永久退出 —— 这是一次判定, 不是常驻监听。
"""
import ctypes
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HUD = os.path.join(HERE, 'cc-hud.pyw')
MARKER = os.path.join(os.environ.get('LOCALAPPDATA', os.environ.get('TEMP', '.')),
                      'Temp', 'cc-hud-quit.marker')
if not os.path.isdir(os.path.dirname(MARKER)):
    MARKER = os.path.join(os.environ.get('TEMP', '.'), 'cc-hud-quit.marker')
WAIT_SEC = 25


def proc_pid(name_prefix):
    """Toolhelp32 快照找进程(与 cc-hud 同一套, 不派生 tasklist)。句柄必须按 64 位取。"""
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or ctypes.c_ssize_t(snap).value == -1:
        return None

    class PE(ctypes.Structure):
        _fields_ = [('dwSize', ctypes.c_uint32), ('cntUsage', ctypes.c_uint32),
                    ('th32ProcessID', ctypes.c_uint32), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', ctypes.c_uint32), ('cntThreads', ctypes.c_uint32),
                    ('th32ParentProcessID', ctypes.c_uint32), ('pcPriClassBase', ctypes.c_long),
                    ('dwFlags', ctypes.c_uint32), ('szExeFile', ctypes.c_wchar * 260)]

    pe = PE()
    pe.dwSize = ctypes.sizeof(PE)
    pid = None
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            if pe.szExeFile.lower().startswith(name_prefix):
                pid = int(pe.th32ProcessID)
                break
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return pid


def hud_running():
    """HUD 是否在跑 —— 只查询, 不创建。
    用 CreateMutexW 判存在有副作用: 探针自己会把互斥体建出来, 于是第二次调用永远返回
    True, 更糟的是刚被拉起的 HUD 会在 `already_running()` 上看到探针留下的互斥体而自杀。"""
    k = ctypes.windll.kernel32
    k.OpenMutexW.restype = ctypes.c_void_p
    h = k.OpenMutexW(0x1000, False, 'Local\\cc-hud-single')        # SYNCHRONIZE
    if not h:
        return False
    k.CloseHandle(h)
    return True


def marker_pid(path=None):
    path = path or MARKER        # 默认参数在 def 时就绑死, 换目录测试会读不到新位置
    try:
        with open(path, encoding='utf-8') as fh:
            return int((fh.read().strip() or '0'))
    except (OSError, ValueError):
        return None


def should_launch(cc_pid, hud_up, mark):
    if cc_pid is None:
        return False
    if hud_up:
        return False
    if mark is not None and mark == cc_pid:
        return False
    return True


def launch():
    py = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    if not os.path.exists(py):
        py = sys.executable
    DETACHED = 0x00000008 | 0x00000200 | 0x00000010   # DETACHED | NEW_PROCESS_GROUP | BYTES?
    flags = 0x00000008 | 0x00000200                   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    with open(os.devnull, 'wb') as dn:
        subprocess.Popen([py, HUD], stdin=dn, stdout=dn, stderr=dn, creationflags=flags,
                         close_fds=True, cwd=HERE)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    wait = WAIT_SEC
    if '--wait' in argv:
        wait = max(0, int(argv[argv.index('--wait') + 1]))
    end = time.time() + wait
    cc = None
    while True:
        cc = proc_pid('cc-switch')
        if cc or time.time() >= end:
            break
        time.sleep(1.0)
    go = should_launch(cc, hud_running(), marker_pid())
    try:                      # 判定结果留一行痕, 出问题时不至于完全无从查起
        with open(os.path.join(os.environ.get('TEMP', '.'), 'cc-hud-follow-probe.log'),
                  'a', encoding='utf-8') as fh:
            fh.write('%s cc=%s hud=%s mark=%s -> %s\n' % (
                time.strftime('%Y-%m-%d %H:%M:%S'), cc, hud_running(), marker_pid(),
                'LAUNCH' if go else 'skip'))
    except OSError:
        pass
    if go:
        launch()
    return 0 if go else 1


if __name__ == '__main__':
    sys.exit(main())
