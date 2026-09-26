# -*- coding: utf-8 -*-
"""
Update.pushbutton - MEPANANA Extension In-App Auto-Updater
Synchronizes the extension with the latest GitHub repository releases.
"""
__title__ = "Update"
__doc__   = "Check for updates and synchronize MEPANANA with the latest GitHub release."

# ── 6-LINE GATEKEEPER BOILERPLATE (MANDATORY) ─────────────────────────────
from py.auth import require_auth, update_ribbon_state, is_authenticated
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        import sys
        sys.exit()
# ──────────────────────────────────────────────────────────────────────────

import os
import sys
import clr
clr.AddReference("System")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
import System
from System.Windows import Visibility
from System.Windows.Media import SolidColorBrush, Color
from System.Threading import ThreadPool, WaitCallback

from pyrevit import forms, script
from py.core import safe_unicode
from py.ui import setup_modern_window, is_dark_theme, show_info, show_success, show_warning, show_error, show_confirm, do_events, RunningModeManager

import py.updater_engine
try:
    reload(py.updater_engine)
except Exception:
    pass
from py.updater_engine import get_local_version, check_cloud_version, download_and_install_update, set_ribbon_update_badge


class MepananaUpdateWindow(forms.WPFWindow):
    def __init__(self, dark_mode=False):
        self.dark_mode = dark_mode
        xaml_file = "ui_dark.xaml" if dark_mode else "ui_light.xaml"
        xaml_path = os.path.join(os.path.dirname(__file__), xaml_file)
        forms.WPFWindow.__init__(self, xaml_path)
        setup_modern_window(self, dark_mode=dark_mode, set_revit_owner=True)
        self.rmm = RunningModeManager(self, dark_mode=dark_mode)

        self.local_info = get_local_version()
        self.cloud_info = None
        self._is_updating = False

        if hasattr(self, 'btnCheck'):
            self.btnCheck.Click += self.OnCheckUpdatesClick
        if hasattr(self, 'btnUpdate'):
            self.btnUpdate.Click += self.OnUpdateClick
        if hasattr(self, 'btnClose'):
            self.btnClose.Click += self.OnCloseClick
        if hasattr(self, 'btnFooterClose'):
            self.btnFooterClose.Click += self.OnCloseClick

        self.InitDisplay()
        self.CheckUpdatesAsync()

    def InitDisplay(self):
        """Populates initial local version information."""
        formatted_date = str(self.local_info.get("date", "Unknown"))
        if hasattr(self, 'txtLocalCommit'):
            self.txtLocalCommit.Text = u"Commit: {}".format(self.local_info.get("commit", "Unknown"))
        if hasattr(self, 'txtLocalDate'):
            self.txtLocalDate.Text = u"Installed: {}".format(formatted_date)

    def CheckUpdatesAsync(self):
        """Asynchronously checks GitHub for the latest commit on main branch."""
        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = Visibility.Visible
            self.progressBar.IsIndeterminate = True

        if hasattr(self, 'btnCheck'):
            self.btnCheck.IsEnabled = False

        if hasattr(self, 'btnUpdate'):
            self.btnUpdate.IsEnabled = False

        if hasattr(self, 'txtStatus'):
            self.txtStatus.Text = u"Connecting to GitHub and checking for updates..."

        dispatcher = self.Dispatcher

        def bg_worker(state):
            res = check_cloud_version()

            def on_check_done():
                try:
                    self.cloud_info = res
                    if res.get("success"):
                        sha = res.get("sha", "Unknown")
                        readable_date = str(res.get("date", "Unknown"))
                        msg = res.get("message", "No release notes provided.")

                        if hasattr(self, 'txtCloudCommit'):
                            self.txtCloudCommit.Text = u"Commit: {}".format(sha)
                        if hasattr(self, 'txtCloudDate'):
                            self.txtCloudDate.Text = u"Released: {}".format(readable_date)
                        if hasattr(self, 'txtChangelog'):
                            self.txtChangelog.Text = msg

                        is_new_update = (sha.lower() != str(self.local_info.get("commit", "")).lower())

                        try:
                            set_ribbon_update_badge(is_new_update, res)
                        except Exception:
                            pass

                        if hasattr(self, 'badgeCloud') and hasattr(self, 'txtCloudBadge'):
                            if is_new_update:
                                if self.dark_mode:
                                    self.badgeCloud.Background = SolidColorBrush(Color.FromRgb(6, 78, 59))
                                    self.txtCloudBadge.Text = u"NEW UPDATE READY"
                                    self.txtCloudBadge.Foreground = SolidColorBrush(Color.FromRgb(110, 231, 183))
                                else:
                                    self.badgeCloud.Background = SolidColorBrush(Color.FromRgb(220, 252, 231))
                                    self.txtCloudBadge.Text = u"NEW UPDATE READY"
                                    self.txtCloudBadge.Foreground = SolidColorBrush(Color.FromRgb(21, 128, 61))
                            else:
                                if self.dark_mode:
                                    self.badgeCloud.Background = SolidColorBrush(Color.FromRgb(15, 23, 42))
                                    self.txtCloudBadge.Text = u"UP TO DATE"
                                    self.txtCloudBadge.Foreground = SolidColorBrush(Color.FromRgb(148, 163, 184))
                                else:
                                    self.badgeCloud.Background = SolidColorBrush(Color.FromRgb(241, 245, 249))
                                    self.txtCloudBadge.Text = u"UP TO DATE"
                                    self.txtCloudBadge.Foreground = SolidColorBrush(Color.FromRgb(71, 85, 105))

                        if hasattr(self, 'btnUpdate'):
                            self.btnUpdate.IsEnabled = True
                            if is_new_update:
                                self.btnUpdate.Content = u"🚀 Update Now"
                            else:
                                self.btnUpdate.Content = u"🔄 Reinstall / Repair"

                        if hasattr(self, 'txtStatus'):
                            if is_new_update:
                                self.txtStatus.Text = u"✨ New update ({}) ready to install.".format(sha)
                            else:
                                self.txtStatus.Text = u"✅ Extension is up to date."
                    else:
                        err_msg = res.get("error", "Unknown error")
                        if hasattr(self, 'txtStatus'):
                            self.txtStatus.Text = u"❌ Failed to check GitHub: {}".format(err_msg)
                        if hasattr(self, 'txtChangelog'):
                            self.txtChangelog.Text = u"Could not connect to GitHub. Please check your internet connection."
                finally:
                    if hasattr(self, 'progressBar'):
                        self.progressBar.IsIndeterminate = False
                        self.progressBar.Visibility = Visibility.Collapsed
                    if hasattr(self, 'btnCheck'):
                        self.btnCheck.IsEnabled = True

            if dispatcher:
                dispatcher.Invoke(System.Action(on_check_done))

        ThreadPool.QueueUserWorkItem(WaitCallback(bg_worker))

    def OnCheckUpdatesClick(self, sender, args):
        """User manually clicks 'Check Updates'."""
        self.CheckUpdatesAsync()

    def OnUpdateClick(self, sender, args):
        """Downloads latest package and updates the extension."""
        if not self.cloud_info or not self.cloud_info.get("success"):
            show_warning(u"Please wait for GitHub update check to complete.", title="Update Notice")
            return

        sha = self.cloud_info.get("sha", "")
        msg = self.cloud_info.get("message", "")
        confirm_text = u"Do you want to download and install the latest MEPANANA update (Commit: {})?\n\nChangelog:\n{}".format(
            sha, msg[:200] + ("..." if len(msg) > 200 else "")
        )
        if not show_confirm(confirm_text, title="Confirm MEPANANA Update"):
            return

        self._is_updating = True
        self.rmm.start(title=u"Updating MEPANANA\u2026", detail=u"Downloading release archive from GitHub\u2026")

        def update_progress(percent, message):
            self.rmm.update(percent, detail=message)

        try:
            download_and_install_update(progress_callback=update_progress)

            self.rmm.finish(
                title=u"\u2713 Update Complete!",
                detail=u"Updated to commit {}. Reloading pyRevit\u2026".format(sha),
                auto_return_delay_ms=1200
            )

            show_success(
                u"🎉 MEPANANA has been updated successfully to latest release (Commit: {})!\n\nRevit will now reload the pyRevit ribbon.".format(sha),
                title="Update Complete"
            )

            self.Close()

            # Reload pyRevit
            try:
                from pyrevit.loader import sessionmgr
                sessionmgr.reload_pyrevit()
            except Exception:
                pass

        except Exception as ex:
            self.rmm.restore_form(status_text=u"Update failed")
            show_error(u"Failed to update MEPANANA:\n{}".format(safe_unicode(ex)), title="Update Error")
            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"❌ Update failed: {}".format(safe_unicode(ex))
        finally:
            self._is_updating = False
            if hasattr(self, 'btnUpdate'):
                self.btnUpdate.IsEnabled = True
            if hasattr(self, 'btnCheck'):
                self.btnCheck.IsEnabled = True

    def OnCloseClick(self, sender, args):
        self.Close()


if __name__ == "__main__":
    current_dark = is_dark_theme()
    try:
        if __shiftclick__:
            current_dark = not current_dark
    except Exception:
        pass

    while True:
        win = MepananaUpdateWindow(dark_mode=current_dark)
        win.ShowDialog()
        if getattr(win, 'switch_requested', False):
            current_dark = not current_dark
            continue
        break
