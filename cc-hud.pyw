# -*- coding: utf-8 -*-
"""cc-hud 入口：pywebview + Edge WebView2（React 前端）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cchud_next.host import main


if __name__ == "__main__":
    main()
