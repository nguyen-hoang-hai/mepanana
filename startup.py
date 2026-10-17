# -*- coding: utf-8 -*-
"""
Startup script for mepanana.extension.
Runs when pyRevit initializes this extension.
[STATUS: UNLOCKED BY DEFAULT]
Ensures all tools are enabled on the ribbon upon launch.
"""
try:
    from py.auth import update_ribbon_state
    update_ribbon_state(True)
except Exception:
    pass