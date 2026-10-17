# -*- coding: utf-8 -*-
try:
    from py.auth import update_ribbon_state, is_authenticated, get_current_user
    if not is_authenticated():
        update_ribbon_state(False)
    else:
        update_ribbon_state(True, get_current_user())
except Exception:
    pass