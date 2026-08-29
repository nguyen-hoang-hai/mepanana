# -*- coding: utf-8 -*-
__title__ = "Unlock"
__doc__   = "Unlock or Lock mepanana tools for the current Revit session."

import traceback
from py.auth import (
    is_authenticated, show_login_dialog, show_session_status_dialog,
    update_ribbon_state, get_current_user, set_authenticated
)
from py.ui import show_info, show_error

try:
    if is_authenticated():
        action = show_session_status_dialog()
        if action == "LOCK":
            set_authenticated(False)
            update_ribbon_state(False)
            show_info(u"All mepanana tools have been LOCKED (grayed out).", "Session Locked")
        else:
            user = get_current_user() or "User"
            update_ribbon_state(True, user)
    else:
        update_ribbon_state(False)
        success = show_login_dialog()
        if success:
            user = get_current_user() or "User"
            update_ribbon_state(True, user)
            show_info(
                u"Unlock successful!\n\n"
                u"👤 Welcome: {}\n\n"
                u"All mepanana tools are activated for this Revit session.".format(user),
                "Success"
            )
        else:
            update_ribbon_state(False)
except Exception as ex:
    show_error(u"Unlock Error:\n{}\n\n{}".format(str(ex), traceback.format_exc()), "Error")