# -*- coding: utf-8 -*-
"""
Upright Sprinkler Connector - Under Development
Part of mepanana.extension.
"""
import os
import sys

# 1. Dynamic Lib Resolution
cur_dir = os.path.dirname(__file__)
while cur_dir and not os.path.exists(os.path.join(cur_dir, "lib", "py", "auth.py")):
    parent = os.path.dirname(cur_dir)
    if parent == cur_dir:
        break
    cur_dir = parent
lib_path = os.path.join(cur_dir, "lib")
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from py.auth import require_auth, update_ribbon_state, is_authenticated

# 2. Security Gatekeeper
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()

from py.ui import show_info

def run():
    show_info(
        u"🚧 Upright Sprinkler is currently under development!\n\nThis feature is scheduled for an upcoming update.",
        "Under Development"
    )

run()