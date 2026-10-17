# -*- coding: utf-8 -*-
"""
auth.py — MEPANANA Authentication & Ribbon State Manager
[STATUS: ARCHIVED & UNLOCKED BY DEFAULT]

Theo chỉ đạo của tác giả, toàn bộ extension MEPANANA hoạt động ở chế độ mở khóa tự do.
Mọi hàm xác thực (is_authenticated, require_auth) luôn trả về True.
Hệ thống xác thực đầy đủ được lưu trữ an toàn tại archive/security_system/.
"""
import os
import sys

SESSION_KEY      = "MEPANANA_SESSION_AUTH_STATE"
SESSION_USER_KEY = "MEPANANA_SESSION_AUTH_USER"
MAX_FAILED_ATTEMPTS = 5

from py.core import safe_unicode


# ── Session Helpers (Always Authenticated Mode) ───────────────────────────────

def is_authenticated():
    """Luôn trả về True trong chế độ Unlocked (mở khóa toàn bộ tool)."""
    return True


def get_current_user():
    """Trả về tên người dùng hiện hành."""
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "User"


def set_authenticated(state=True, user=u"User"):
    """Thiết lập trạng thái phiên làm việc."""
    try:
        from System import AppDomain
        AppDomain.CurrentDomain.SetData("MEPANANA_AUTH_STATE", True)
        AppDomain.CurrentDomain.SetData("MEPANANA_AUTH_USER", user or "User")
    except Exception:
        pass
    update_ribbon_state(True, user)


def is_locked_out():
    """Luôn False trong chế độ Unlocked."""
    return False


def get_lockout_remaining_seconds():
    """Luôn 0 trong chế độ Unlocked."""
    return 0


def verify_password(plain_password):
    """Luôn hợp lệ trong chế độ Unlocked."""
    return True, get_current_user(), MAX_FAILED_ATTEMPTS, False


# ── Ribbon Traversal & State ──────────────────────────────────────────────────

def _recurse_ribbon_items(obj, callback):
    """Duyệt đệ quy tất cả các control trong Ribbon để kích hoạt."""
    if obj is None:
        return
    try:
        callback(obj)
    except Exception:
        pass

    for attr in ('Items', 'Panels', 'Children', 'SubItems'):
        try:
            val = getattr(obj, attr, None)
            if val is not None and not isinstance(val, (str, unicode)):
                for child in val:
                    _recurse_ribbon_items(child, callback)
        except Exception:
            pass

    try:
        from System.Collections import IEnumerable
        if isinstance(obj, IEnumerable) and not isinstance(obj, (str, unicode)):
            for child in obj:
                _recurse_ribbon_items(child, callback)
    except Exception:
        pass


def update_ribbon_state(enable=True, user=None):
    """
    Đảm bảo toàn bộ các Panel và Pushbutton trên Ribbon MEPANANA luôn hoạt động (IsEnabled = True).
    """
    try:
        import clr
        clr.AddReference("AdWindows")
        from Autodesk.Windows import ComponentManager

        ribbon = ComponentManager.Ribbon
        if ribbon and ribbon.Tabs:
            for tab in ribbon.Tabs:
                tab_id    = str(getattr(tab, 'Id', '') or '').lower()
                tab_title = str(getattr(tab, 'Title', '') or '').lower()

                if "mepanana" in tab_id or "mepanana" in tab_title:
                    for panel in (tab.Panels or []):
                        if not panel or not panel.Source:
                            continue
                        panel.IsEnabled = True

                        def _enable_btn(b):
                            if hasattr(b, 'IsEnabled'):
                                try:
                                    b.IsEnabled = True
                                except Exception:
                                    pass

                        _recurse_ribbon_items(panel.Source.Items, _enable_btn)
                        if hasattr(panel.Source, 'SlideOutPanelItemsView') and panel.Source.SlideOutPanelItemsView:
                            _recurse_ribbon_items(panel.Source.SlideOutPanelItemsView, _enable_btn)

            try:
                ribbon.UpdateLayout()
            except Exception:
                pass
    except Exception:
        pass
    return 0


# ── Gatekeeper & Dialog Stubs ─────────────────────────────────────────────────

def require_auth():
    """Gatekeeper: luôn trả về True để cho phép khởi chạy tool ngay lập tức."""
    return True


def show_login_dialog():
    """Không cần hiển thị hộp thoại đăng nhập trong chế độ Unlocked."""
    return True


def show_session_status_dialog():
    """Stub cho trạng thái session."""
    return "KEEP"