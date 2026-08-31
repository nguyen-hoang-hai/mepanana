# -*- coding: utf-8 -*-
import os
import sys

# ── Load C# MepananaAuth.dll ──────────────────────────────────────────────────
_DLL_LOADED = False
try:
    import clr
    dll_path = os.path.join(os.path.dirname(__file__), "MepananaAuth.dll")
    if os.path.exists(dll_path):
        clr.AddReferenceToFileAndPath(dll_path)
        from MepananaSecurity import AuthManager
        _DLL_LOADED = True
except Exception:
    _DLL_LOADED = False

SESSION_KEY      = "MEPANANA_SESSION_AUTH_STATE"
SESSION_USER_KEY = "MEPANANA_SESSION_AUTH_USER"
MAX_FAILED_ATTEMPTS = 5


# ── Cloud Auth Configuration (Zero-Exposure Webhook or Google Sheet) ─────────
AUTH_WEBHOOK_URL    = "" # Paste your deployed Google Apps Script /exec URL here
AUTH_SECRET_TOKEN   = "mepanana_auth_sec_2026"
GSHEET_ID           = "1xP1AwtlAMnY7kUJ-xpecB6TMS_g91UShTgFDaFO_bkg"

# Dynamic in-memory dictionary of synced credentials (populated 100% from Google Sheets)
CLOUD_CREDENTIALS = {}


from py.core import safe_unicode

def verify_password_via_webhook(pwd):
    """
    Sends password to private Google Apps Script Auth Webhook.
    Returns (success: bool, user: str, msg: str).
    NEVER downloads full credentials list to client, 100% zero-exposure.
    """
    if not AUTH_WEBHOOK_URL or not AUTH_WEBHOOK_URL.startswith("http"):
        return False, "", "No webhook configured"
    try:
        import json
        try:
            import urllib.request as urllib_req
        except ImportError:
            import urllib2 as urllib_req

        payload = json.dumps({
            "action": "verify",
            "password": pwd,
            "token": AUTH_SECRET_TOKEN
        })

        req = urllib_req.Request(
            AUTH_WEBHOOK_URL,
            data=payload.encode('utf-8') if hasattr(payload, 'encode') else payload,
            headers={'Content-Type': 'application/json', 'User-Agent': 'MEPANANA-Auth'}
        )
        resp = urllib_req.urlopen(req, timeout=5)
        resp_text = resp.read()
        if resp_text:
            if hasattr(resp_text, 'decode'):
                resp_text = resp_text.decode('utf-8', 'ignore')
            data = json.loads(resp_text)
            if data.get("status") == "success":
                return True, safe_unicode(data.get("user", "User")), "OK"
        return False, "", "Invalid password"
    except Exception as ex:
        return False, "", safe_unicode(ex)


def sync_from_gsheet(sheet_id=GSHEET_ID):
    """
    Fetches latest accounts and passwords in real-time from Google Sheets.
    Maps Column A (Họ và Tên) to Column B (Password / Key).
    Cross-compatible with IronPython 2.7 and Python 3.x.
    """
    url = "https://docs.google.com/spreadsheets/d/{}/gviz/tq?tqx=out:csv".format(sheet_id)
    try:
        try:
            import urllib.request as urllib_req
        except ImportError:
            import urllib2 as urllib_req

        req = urllib_req.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib_req.urlopen(req, timeout=4)
        csv_bytes = response.read()
        if not csv_bytes:
            return False

        try:
            csv_text = csv_bytes.decode('utf-8')
        except Exception:
            csv_text = str(csv_bytes)

        lines = [l.strip() for l in csv_text.splitlines() if l.strip()]
        if len(lines) <= 1:
            return False

        import csv
        try:
            import io
            reader = csv.reader(io.StringIO(csv_text))
        except Exception:
            import StringIO
            reader = csv.reader(StringIO.StringIO(csv_text.encode('utf-8')))

        header = next(reader, None)
        for row in reader:
            if len(row) >= 2:
                name = row[0].strip()
                key  = row[1].strip()
                name_u = safe_unicode(name)
                key_u  = safe_unicode(key)
                if name_u and key_u:
                    CLOUD_CREDENTIALS[key_u] = name_u
        return True
    except Exception:
        return False


# ── Session Helpers (Fail-Closed Architecture) ───────────────────────────────

def is_authenticated():
    """
    Checks if current Revit session is authenticated.
    Strictly Fail-Closed: Access is only granted if MepananaAuth.dll is verified and active.
    """
    if not _DLL_LOADED:
        return False
    try:
        return AuthManager.IsAuthenticated
    except Exception:
        return False


def get_current_user():
    """Gets authenticated username for current session."""
    if _DLL_LOADED:
        try:
            return AuthManager.CurrentUser or ""
        except Exception:
            pass
    return ""


def set_authenticated(state=True, user=u"User"):
    """Sets session state in C# DLL and updates ribbon accordingly."""
    if _DLL_LOADED:
        try:
            AuthManager.SetLockState(bool(state), user if state else "")
        except Exception:
            pass
    update_ribbon_state(bool(state), user if state else "")


def _get_fail_count():
    """Returns number of failed attempts this session."""
    try:
        from System import AppDomain
        val = AppDomain.CurrentDomain.GetData("MEPANANA_SESSION_FAIL_COUNT")
        return int(val) if val is not None else 0
    except Exception:
        return 0


def _increment_fail_count():
    """Increments the failed attempt counter."""
    try:
        from System import AppDomain
        AppDomain.CurrentDomain.SetData("MEPANANA_SESSION_FAIL_COUNT", _get_fail_count() + 1)
    except Exception:
        pass


def _reset_fail_count():
    """Resets fail counter after successful login."""
    try:
        from System import AppDomain
        AppDomain.CurrentDomain.SetData("MEPANANA_SESSION_FAIL_COUNT", 0)
    except Exception:
        pass


def is_locked_out():
    """Returns True if max failed attempts reached."""
    return _get_fail_count() >= MAX_FAILED_ATTEMPTS


def verify_password(plain_password):
    """
    Verifies input password against Webhook (zero-exposure), Google Sheets, and local C# DLL.
    Returns (is_valid: bool, username: str, remaining: int, is_locked: bool)
    """
    if is_locked_out():
        return False, "", 0, True

    if not plain_password:
        _increment_fail_count()
        rem = max(0, MAX_FAILED_ATTEMPTS - _get_fail_count())
        return False, "", rem, is_locked_out()

    pwd = plain_password.strip()

    # 1. Zero-Exposure: Try private Google Apps Script Webhook first (if configured)
    if AUTH_WEBHOOK_URL and AUTH_WEBHOOK_URL.startswith("http"):
        ok, user, msg = verify_password_via_webhook(pwd)
        if ok:
            _reset_fail_count()
            if _DLL_LOADED:
                try:
                    AuthManager.SetLockState(True, user)
                except Exception:
                    pass
            return True, user, MAX_FAILED_ATTEMPTS, False

    # 2. Try syncing latest accounts from Google Sheets
    try:
        sync_from_gsheet(GSHEET_ID)
    except Exception:
        pass

    # 3. Check against CLOUD_CREDENTIALS (synced from Google Sheet)
    matched_user = CLOUD_CREDENTIALS.get(pwd)
    if not matched_user:
        for k, v in CLOUD_CREDENTIALS.items():
            if k.lower() == pwd.lower():
                matched_user = v
                break

    if matched_user:
        _reset_fail_count()
        if _DLL_LOADED:
            try:
                AuthManager.SetLockState(True, matched_user)
            except Exception:
                pass
        return True, matched_user, MAX_FAILED_ATTEMPTS, False

    # 4. Check C# DLL as fallback
    if _DLL_LOADED:
        try:
            res = AuthManager.VerifyPassword(pwd)
            if res.IsValid:
                _reset_fail_count()
                return True, res.User, res.RemainingAttempts, res.IsLockedOut
        except Exception:
            pass

    _increment_fail_count()
    rem = max(0, MAX_FAILED_ATTEMPTS - _get_fail_count())
    return False, "", rem, is_locked_out()


def _recurse_ribbon_items(obj, callback):
    """Deeply traverses all WPF / AdWindows ribbon containers to find all RibbonButtons and RibbonItems."""
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


def update_ribbon_state(enable=None, user=None):
    """
    Updates Ribbon controls, panel title, and security button text.
    Relies 100% on pyRevit native icon loading and RibbonPanel.IsEnabled / RibbonItem.IsEnabled.
    """
    if enable is None:
        enable = is_authenticated()
    if user is None and enable:
        user = get_current_user()

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
                    for p_idx, panel in enumerate(tab.Panels or []):
                        if not panel or not panel.Source:
                            continue
                        panel_id    = str(getattr(panel.Source, 'Id', '') or '').lower()
                        panel_title = str(getattr(panel.Source, 'Title', '') or '').lower()

                        is_sec = (p_idx == 0) or ("security" in panel_id) or ("security" in panel_title)

                        if is_sec:
                            panel.IsEnabled = True
                            new_title = user if (enable and user) else "Security"
                            panel.Source.Title = new_title
                            try:
                                panel.Title = new_title
                            except Exception:
                                pass

                            def _update_sec_btn(b):
                                if hasattr(b, 'IsEnabled'):
                                    b.IsEnabled = True
                                    try:
                                        b.Text = "Lock" if enable else "Unlock"
                                    except Exception:
                                        pass
                                    try:
                                        b.ItemText = "Lock" if enable else "Unlock"
                                    except Exception:
                                        pass

                            _recurse_ribbon_items(panel.Source.Items, _update_sec_btn)
                        else:
                            panel.IsEnabled = bool(enable)

                            def _update_tool_btn(b):
                                if hasattr(b, 'IsEnabled'):
                                    try:
                                        b.IsEnabled = bool(enable)
                                    except Exception:
                                        pass

                            _recurse_ribbon_items(panel.Source.Items, _update_tool_btn)
                            if hasattr(panel.Source, 'SlideOutPanelItemsView') and panel.Source.SlideOutPanelItemsView:
                                _recurse_ribbon_items(panel.Source.SlideOutPanelItemsView, _update_tool_btn)

            try:
                ribbon.UpdateLayout()
            except Exception:
                pass
    except Exception:
        pass
    return 0


# ── Login Dialog ───────────────────────────────────────────────────────────────

def show_login_dialog():
    """
    Displays the password login dialog.
    Returns True if successfully unlocked, False otherwise.
    """
    from pyrevit import forms
    xaml_path = os.path.join(os.path.dirname(__file__), "auth_dialog.xaml")
    if not os.path.exists(xaml_path):
        return False

    # Pre-check lockout before even showing dialog
    if is_locked_out():
        try:
            from py.ui import show_error
            show_error(
                u"Access locked!\n\nToo many failed attempts ({} max).\n"
                u"Please restart Revit to try again.".format(MAX_FAILED_ATTEMPTS),
                "Locked Out"
            )
        except Exception:
            pass
        return False

    class AuthDialog(forms.WPFWindow):
        def __init__(self):
            forms.WPFWindow.__init__(self, xaml_path)
            from py.ui import setup_window
            setup_window(self)
            self.success = False
            self.user    = ""
            import System.Windows
            self.txtError.Visibility = System.Windows.Visibility.Collapsed
            self.btnUnlock.Click += self.on_unlock
            self.btnCancel.Click += self.on_cancel
            if hasattr(self, 'btnTogglePassword'):
                self.btnTogglePassword.Click += self.on_toggle_pwd
            self.txtPassword.Focus()

        def on_toggle_pwd(self, sender, args):
            import System.Windows
            if not hasattr(self, 'txtPasswordVisible'):
                return
            if self.txtPassword.Visibility == System.Windows.Visibility.Visible:
                self.txtPasswordVisible.Text = self.txtPassword.Password
                self.txtPasswordVisible.Visibility = System.Windows.Visibility.Visible
                self.txtPassword.Visibility = System.Windows.Visibility.Collapsed
                self.btnTogglePassword.Content = u"🔒"
                self.txtPasswordVisible.Focus()
                self.txtPasswordVisible.CaretIndex = len(self.txtPasswordVisible.Text)
            else:
                self.txtPassword.Password = self.txtPasswordVisible.Text
                self.txtPassword.Visibility = System.Windows.Visibility.Visible
                self.txtPasswordVisible.Visibility = System.Windows.Visibility.Collapsed
                self.btnTogglePassword.Content = u"👁"
                self.txtPassword.Focus()

        def on_unlock(self, sender, args):
            import System.Windows
            if is_locked_out():
                self.txtError.Text = u"Access locked! Restart Revit to try again."
                self.txtError.Visibility = System.Windows.Visibility.Visible
                self.btnUnlock.IsEnabled = False
                self.txtPassword.IsEnabled = False
                if hasattr(self, 'txtPasswordVisible'):
                    self.txtPasswordVisible.IsEnabled = False
                return

            pwd = self.txtPassword.Password if self.txtPassword.Visibility == System.Windows.Visibility.Visible else self.txtPasswordVisible.Text
            valid, user, remaining, is_locked = verify_password(pwd)
            if valid:
                self.success = True
                self.user    = user
                set_authenticated(True, user)
                update_ribbon_state(True, user)
                self.Close()
            else:
                if is_locked or remaining <= 0:
                    self.txtError.Text = u"Access locked! Restart Revit to try again."
                    self.btnUnlock.IsEnabled = False
                    self.txtPassword.IsEnabled = False
                    if hasattr(self, 'txtPasswordVisible'):
                        self.txtPasswordVisible.IsEnabled = False
                else:
                    self.txtError.Text = u"Incorrect password! {} attempt(s) remaining.".format(remaining)
                self.txtError.Visibility = System.Windows.Visibility.Visible
                self.txtPassword.Clear()
                if hasattr(self, 'txtPasswordVisible'):
                    self.txtPasswordVisible.Text = u""
                if self.txtPassword.Visibility == System.Windows.Visibility.Visible:
                    self.txtPassword.Focus()
                elif hasattr(self, 'txtPasswordVisible'):
                    self.txtPasswordVisible.Focus()

        def on_cancel(self, sender, args):
            self.Close()

    dialog = AuthDialog()
    dialog.ShowDialog()
    return dialog.success


def show_session_status_dialog():
    """
    Displays the modern WPF Session Status dialog when already authenticated.
    Allows the user to view status or click 'Lock Tools'.
    Returns 'LOCK' if user clicked Lock Tools, or 'KEEP' if user clicked Keep Active / closed.
    """
    from pyrevit import forms
    xaml_path = os.path.join(os.path.dirname(__file__), "session_dialog.xaml")
    if not os.path.exists(xaml_path):
        return "KEEP"

    class SessionDialog(forms.WPFWindow):
        def __init__(self):
            forms.WPFWindow.__init__(self, xaml_path)
            from py.ui import setup_window
            setup_window(self)
            self.action = "KEEP"
            self.txtUserName.Text = get_current_user() or "User"
            self.btnLock.Click += self.on_lock
            self.btnKeep.Click += self.on_keep

        def on_lock(self, sender, args):
            self.action = "LOCK"
            self.Close()

        def on_keep(self, sender, args):
            self.action = "KEEP"
            self.Close()

    dlg = SessionDialog()
    dlg.ShowDialog()
    return dlg.action


# ── Gatekeeper ─────────────────────────────────────────────────────────────────

def require_auth():
    """
    Gatekeeper: returns True if session is authenticated (or user logs in successfully).
    Returns False otherwise.
    """
    if is_authenticated():
        return True
    return show_login_dialog()