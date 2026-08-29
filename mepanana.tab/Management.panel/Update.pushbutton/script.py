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
from py.ui import setup_window, show_info, show_success, show_warning, show_error, show_confirm, do_events

import py.updater_engine
try:
    reload(py.updater_engine)
except Exception:
    pass
from py.updater_engine import get_local_version, check_cloud_version, download_and_install_update


class MepananaUpdateWindow(forms.WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        setup_window(self)

        self.local_info = get_local_version()
        self.cloud_info = None
        self._is_updating = False

        self.InitDisplay()
        self.CheckUpdatesAsync()

    def InitDisplay(self):
        """Populates initial local version information."""
        raw_date = str(self.local_info.get("date", "Unknown"))
        if "T" in raw_date:
            parts = raw_date.split("T")
            raw_date = parts[0] + " · " + parts[1].replace("Z", "")[:5] + " UTC"

        if hasattr(self, 'txtLocalCommit'):
            self.txtLocalCommit.Text = u"Commit: {}".format(self.local_info.get("commit", "Unknown"))
        if hasattr(self, 'txtLocalDate'):
            self.txtLocalDate.Text = u"Installed: {}".format(raw_date)

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
                        raw_date = str(res.get("raw_date", res.get("date", "Unknown")))
                        if "T" in raw_date:
                            parts = raw_date.split("T")
                            readable_date = parts[0] + " · " + parts[1].replace("Z", "")[:5] + " UTC"
                        else:
                            readable_date = raw_date

                        msg = res.get("message", "No release notes provided.")

                        if hasattr(self, 'txtCloudCommit'):
                            self.txtCloudCommit.Text = u"Commit: {}".format(sha)
                        if hasattr(self, 'txtCloudDate'):
                            self.txtCloudDate.Text = u"Released: {}".format(readable_date)
                        if hasattr(self, 'txtChangelog'):
                            self.txtChangelog.Text = msg

                        is_new_update = (sha.lower() != str(self.local_info.get("commit", "")).lower())

                        if hasattr(self, 'badgeCloud') and hasattr(self, 'txtCloudBadge'):
                            if is_new_update:
                                self.badgeCloud.Background = SolidColorBrush(Color.FromRgb(220, 252, 231))
                                self.txtCloudBadge.Text = u"NEW UPDATE READY"
                                self.txtCloudBadge.Foreground = SolidColorBrush(Color.FromRgb(21, 128, 61))
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
                                self.txtStatus.Text = u"✨ A new version ({}) is available to install!".format(sha)
                            else:
                                self.txtStatus.Text = u"✅ MEPANANA is currently up to date."
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

        # Setup Progress Bar
        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = Visibility.Visible
            self.progressBar.IsIndeterminate = False
            self.progressBar.Minimum = 0
            self.progressBar.Maximum = 100
            self.progressBar.Value = 0

        if hasattr(self, 'btnUpdate'):
            self.btnUpdate.IsEnabled = False
        if hasattr(self, 'btnCheck'):
            self.btnCheck.IsEnabled = False

        self._is_updating = True

        def update_progress(percent, message):
            if hasattr(self, 'progressBar'):
                self.progressBar.Value = percent
            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = message
            do_events()

        try:
            download_and_install_update(progress_callback=update_progress)

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
            show_error(u"Failed to update MEPANANA:\n{}".format(str(ex)), title="Update Error")
            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"❌ Update failed: {}".format(str(ex))
        finally:
            self._is_updating = False
            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = Visibility.Collapsed
            if hasattr(self, 'btnUpdate'):
                self.btnUpdate.IsEnabled = True
            if hasattr(self, 'btnCheck'):
                self.btnCheck.IsEnabled = True

    def OnCloseClick(self, sender, args):
        self.Close()


if __name__ == "__main__":
    win = MepananaUpdateWindow()
    win.ShowDialog()
