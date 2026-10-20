# -*- coding: utf-8 -*-
"""cc-hud 模块化包。

对外只暴露 cc-hud.pyw 需要的两个东西: 全部名字(星导入) 与 install_patch_forwarder。
测试器(verify.py / shot.py / test_data.py)通过对根模块赋值来打桩,
转发器保证桩能穿透到子模块 —— 拆分前后 m.X = v 的语义完全等价。
"""
import types

from . import const, util, render, power, data, sysw, pop, hud
from .const import *
from .util import *
from .render import *
from .power import *
from .data import *
from .sysw import *
from .pop import *
from .hud import *

_SUBMODULES = (const, util, render, power, data, sysw, pop, hud)


def install_patch_forwarder(root):
    """让 root.X = v 同时写进所有已有 X 的子模块。

    verify.py 的打桩语义因此与拆分前完全等价: 根模块上赋值, 子模块里那份由
    `from .const import *` 拷贝出来的同名全局也跟着换掉, 于是 HUD 的方法体
    (其 __globals__ 是 cchud.hud)读到的就是桩。
    """
    if getattr(root, "_patch_forwarder_installed", False):
        return

    class _ForwardingModule(types.ModuleType):
        def __setattr__(self, name, value):
            super().__setattr__(name, value)
            for mod in _SUBMODULES:
                if name in mod.__dict__:
                    mod.__dict__[name] = value

    root.__class__ = _ForwardingModule
    root._patch_forwarder_installed = True
