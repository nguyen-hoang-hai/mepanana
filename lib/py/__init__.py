# -*- coding: utf-8 -*-
"""
mepanana lib/py — Shared Library
"""
try:
    from py.tool_visibility_engine import init_startup_listener
    init_startup_listener()
except Exception:
    pass
