# -*- coding: utf-8 -*-
"""
Startup script for mepanana.extension.
Runs when pyRevit initializes this extension.
Uses Revit Idling event to guarantee that all tools are locked/grayed out
as soon as the ribbon becomes visible.
"""
from pyrevit import HOST_APP

_max_retries = 30
_success_count = 0
_attempt = 0

def _lock_on_idling(sender, args):
    global _attempt, _success_count
    _attempt += 1
    try:
        from py.auth import update_ribbon_state, is_authenticated
        if not is_authenticated():
            count = update_ribbon_state(False)
            if count > 0:
                _success_count += 1
            # Maintain lock across 5 Idling ticks so Revit finish all UI loading passes
            if _success_count >= 5 or _attempt >= _max_retries:
                try:
                    HOST_APP.app.Idling -= _lock_on_idling
                except Exception:
                    pass
        else:
            try:
                HOST_APP.app.Idling -= _lock_on_idling
            except Exception:
                pass
    except Exception:
        if _attempt >= _max_retries:
            try:
                HOST_APP.app.Idling -= _lock_on_idling
            except Exception:
                pass

try:
    from py.auth import set_authenticated, update_ribbon_state
    set_authenticated(False)
    update_ribbon_state(False)
    HOST_APP.app.Idling += _lock_on_idling
except Exception:
    pass