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


# ── Cloud Auth Configuration (100% Online Real-Time from Google Sheet) ───────
AUTH_WEBHOOK_URL    = "https://script.google.com/macros/s/AKfycbw2la7kIP5AbVW8NHkDb4fOzf2pWxvREebzHF_QiVdlZssdEaEMWWaBOMRE_Kla6s31/exec"
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
    """Sets session state in C# DLL, updates ribbon, and triggers background update check."""
    if _DLL_LOADED:
        try:
            AuthManager.SetLockState(bool(state), user if state else "")
        except Exception:
            pass
    update_ribbon_state(bool(state), user if state else "")

    # Trigger automatic background GitHub update check upon unlock
    if state:
        try:
            from py.updater_engine import check_updates_in_background
            check_updates_in_background(force=True)
        except Exception:
            pass


LOCKOUT_DURATION_SECONDS = 900  # 15 minutes lockout

def _get_lock_file_path():
    """Returns path to persistent lockout file in %APPDATA% or %TEMP%."""
    try:
        appdata = os.environ.get('APPDATA', '')
        if appdata:
            p = os.path.join(appdata, "pyRevit", ".mpn_auth_lock.dat")
            dir_p = os.path.dirname(p)
            if not os.path.exists(dir_p):
                try: os.makedirs(dir_p)
                except Exception: pass
            return p
    except Exception:
        pass
    import tempfile
    return os.path.join(tempfile.gettempdir(), ".mpn_auth_lock.dat")


def _read_lock_state():
    """Reads persistent lock state from disk. Auto-resets if 15-minute lock has expired."""
    try:
        p = _get_lock_file_path()
        if os.path.exists(p):
            with open(p, 'r') as f:
                content = f.read().strip()
            if content:
                import json, base64, time
                try:
                    raw_json = base64.b64decode(content).decode('utf-8')
                except Exception:
                    raw_json = content
                data = json.loads(raw_json)
                fail_count = int(data.get("fail_count", 0))
                locked_until = float(data.get("locked_until", 0.0))
                now = time.time()
                
                # If a 15-minute lock was active AND it has now expired:
                if locked_until > 0 and now >= locked_until:
                    _reset_fail_count()
                    return {"fail_count": 0, "locked_until": 0.0}

                return {
                    "fail_count": fail_count,
                    "locked_until": locked_until
                }
    except Exception:
        pass
    return {"fail_count": 0, "locked_until": 0.0}


def _write_lock_state(fail_count, locked_until=0.0):
    """Writes persistent lock state to disk encoded with Base64."""
    try:
        import json, base64, time
        data = {
            "fail_count": int(fail_count),
            "locked_until": float(locked_until),
            "updated_at": time.time()
        }
        payload = base64.b64encode(json.dumps(data).encode('utf-8')).decode('ascii')
        p = _get_lock_file_path()
        with open(p, 'w') as f:
            f.write(payload)
    except Exception:
        pass


def get_lockout_remaining_seconds():
    """Returns remaining lockout seconds (> 0 if currently locked out for 15 mins)."""
    import time
    state = _read_lock_state()
    locked_until = state.get("locked_until", 0.0)
    now = time.time()
    if locked_until > now:
        return int(locked_until - now)
    return 0


def _get_fail_count():
    """Returns number of failed attempts stored persistently on disk."""
    state = _read_lock_state()
    return state.get("fail_count", 0)


def _increment_fail_count():
    """
    Increments fail counter persistently on disk and enforces 15-minute lock on 5 fails.
    Applies progressive anti-bot throttling delay.
    """
    import time
    state = _read_lock_state()
    new_count = state.get("fail_count", 0) + 1
    locked_until = 0.0

    if new_count >= MAX_FAILED_ATTEMPTS:
        locked_until = time.time() + LOCKOUT_DURATION_SECONDS

    _write_lock_state(new_count, locked_until)

    try:
        delay = min(3.0, new_count * 0.6)
        time.sleep(delay)
    except Exception:
        pass


def _reset_fail_count():
    """Resets fail counter on disk upon successful login or timer expiration."""
    _write_lock_state(0, 0.0)


def is_locked_out():
    """
    Returns True ONLY if currently within the active 15-minute lockout cooldown.
    Automatically unlocks when the 15 minutes have passed!
    """
    return get_lockout_remaining_seconds() > 0


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

    _increment_fail_count()
    rem = max(0, MAX_FAILED_ATTEMPTS - _get_fail_count())
    return False, "", rem, is_locked_out()

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
    rem_secs = get_lockout_remaining_seconds()
    if rem_secs > 0:
        mins = max(1, (rem_secs + 59) // 60)
        try:
            from py.ui import show_error
            show_error(
                u"Access locked!\n\nToo many failed attempts ({} max).\n"
                u"Security cooldown active. Please wait ~{} minute(s) to retry.".format(MAX_FAILED_ATTEMPTS, mins),
                "Access Locked"
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
                    rem_s = get_lockout_remaining_seconds()
                    mins = max(1, (rem_s + 59) // 60)
                    self.txtError.Text = u"⛔ Access locked! Please wait ~{} min(s) to retry.".format(mins)
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