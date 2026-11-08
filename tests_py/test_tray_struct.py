"""NOTIFYICONDATAW 必须与 Windows SDK 布局一致。

szTip 是 WCHAR[128]；曾写成 64 导致 sizeof=856（应为 984），
NIM_ADD 仍返回成功，但外壳拿到的字段整体错位，托盘提示丢失。
"""
import ctypes
import sys

import pytest
from cchud_next.tray import _NID

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8,
    reason="Windows x64 only",
)


def test_nid_size_matches_sdk() -> None:
    assert ctypes.sizeof(_NID) == 984


def test_nid_tip_is_128_wchars() -> None:
    assert _NID.szTip.size == 256      # ctypes reports bytes: 128 WCHAR * 2
