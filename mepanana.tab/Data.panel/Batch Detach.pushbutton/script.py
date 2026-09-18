# -*- coding: utf-8 -*-
"""
script.py - Batch Detach & Workset Relinquish Controller Window
Interactive tool to batch detach Revit models, make worksets non-editable, and save clean transmission files.

Part of mepanana.extension.
Author: Hai Nguyen
"""
# ── GATEKEEPER BOILERPLATE (MANDATORY) ───────────────────────────────────────
import sys
from py.auth import require_auth, update_ribbon_state, is_authenticated
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()
# ─────────────────────────────────────────────────────────────────────────────

import os
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")

from System.Windows import Visibility
from Microsoft.Win32 import OpenFileDialog
from System.Windows.Forms import FolderBrowserDialog, DialogResult

from pyrevit import script, forms
from py.core import get_doc, get_uidoc, get_app, safe_unicode
from py.ui import setup_window, show_warning, show_error, show_info, show_success, do_events
from py.batch_detach_engine import (
    get_file_size_display,
    detach_and_clean_model,
    log_batch_detach
)

from Autodesk.Revit.DB import FailureSeverity, FailureProcessingResult

doc = get_doc()
uidoc = get_uidoc()
app = get_app()
if not app and doc:
    app = doc.Application
if not app:
    try:
        app = __revit__.Application
    except Exception:
        pass


def _on_failures_processing(sender, e):
    """Auto-dismisses warnings and non-blocking failures during batch processing."""
    try:
        fa = e.GetFailuresAccessor()
        fail_list = fa.GetFailureMessages()
        for f in fail_list:
            if f.GetSeverity() == FailureSeverity.Warning:
                fa.DeleteWarning(f)
            elif fa.CanCommit():
                fa.ResolveFailure(f)
        e.SetProcessingResult(FailureProcessingResult.Continue)
    except Exception:
        pass


class FileItem(object):
    """Data binding item for the file list."""
    def __init__(self, full_path):
        self.Path = full_path
        self.Name = os.path.basename(full_path)
        self.SizeDisplay = get_file_size_display(full_path)


class BatchDetachWindow(forms.WPFWindow):
    """Batch Detach Controller Window."""

    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        setup_window(self)

        self.file_items = []
        self._is_processing = False

        # Wire event handlers dynamically (Zero inline events in XAML rule)
        self.btnAddFiles.Click += self.OnAddFiles
        self.btnAddFolder.Click += self.OnAddFolder
        self.btnClear.Click += self.OnClear
        self.btnBrowse.Click += self.OnBrowseFolder
        self.btnCancel.Click += self.OnCancel
        self.btnRun.Click += self.OnRun
        self.rbFolder.Checked += self.OnDestModeChanged
        self.rbSuffix.Checked += self.OnDestModeChanged

        # Set default output folder to Desktop\MEPANANA_Detached
        desktop = os.path.join(os.environ.get("USERPROFILE", "C:"), "Desktop", "MEPANANA_Detached")
        self.txtFolder.Text = desktop

        self.UpdateFileCountBadge()

    def OnDestModeChanged(self, sender, args):
        """Toggles enabling of destination inputs based on selected radio button."""
        use_folder = bool(self.rbFolder.IsChecked)
        self.txtFolder.IsEnabled = use_folder
        self.btnBrowse.IsEnabled = use_folder
        self.txtSuffix.IsEnabled = not use_folder

    def OnAddFiles(self, sender, args):
        """Opens file dialog allowing multi-selection of .rvt files."""
        try:
            dlg = OpenFileDialog()
            dlg.Filter = "Revit Project (*.rvt)|*.rvt"
            dlg.Multiselect = True
            dlg.Title = "Select Revit Project Files to Detach"

            if dlg.ShowDialog():
                existing_paths = set(item.Path.lower() for item in self.file_items)
                for f_path in dlg.FileNames:
                    if f_path.lower() not in existing_paths:
                        self.file_items.append(FileItem(f_path))
                        existing_paths.add(f_path.lower())

                self.RefreshFileList()
        except Exception as ex:
            show_error(u"Error selecting files:\n{}".format(safe_unicode(ex)))

    def OnAddFolder(self, sender, args):
        """Scans a selected directory for all .rvt files."""
        try:
            dlg = FolderBrowserDialog()
            dlg.Description = "Select Folder Containing Revit Models"
            dlg.ShowNewFolderButton = False

            if dlg.ShowDialog() == DialogResult.OK:
                folder_path = dlg.SelectedPath
                existing_paths = set(item.Path.lower() for item in self.file_items)

                for root, dirs, files in os.walk(folder_path):
                    for f in files:
                        if f.lower().endswith(".rvt") and not f.startswith("~"):
                            full_path = os.path.join(root, f)
                            if full_path.lower() not in existing_paths:
                                self.file_items.append(FileItem(full_path))
                                existing_paths.add(full_path.lower())

                self.RefreshFileList()
        except Exception as ex:
            show_error(u"Error scanning folder:\n{}".format(safe_unicode(ex)))

    def OnClear(self, sender, args):
        """Clears all files from the list."""
        self.file_items = []
        self.RefreshFileList()

    def RefreshFileList(self):
        """Updates ListBox source and file count badge."""
        self.lstFiles.ItemsSource = None
        self.lstFiles.ItemsSource = self.file_items
        self.UpdateFileCountBadge()

    def UpdateFileCountBadge(self):
        """Updates badge text showing number of selected models."""
        count = len(self.file_items)
        if count == 1:
            self.txtFileCount.Text = "1 model selected"
        else:
            self.txtFileCount.Text = "{} models selected".format(count)

    def OnBrowseFolder(self, sender, args):
        """Browses for a destination output directory."""
        try:
            dlg = FolderBrowserDialog()
            dlg.Description = "Select Destination Folder for Detached Models"
            dlg.ShowNewFolderButton = True

            if dlg.ShowDialog() == DialogResult.OK:
                self.txtFolder.Text = dlg.SelectedPath
        except Exception as ex:
            show_error(u"Error browsing folder:\n{}".format(safe_unicode(ex)))

    def OnCancel(self, sender, args):
        """Closes the dialog."""
        self.Close()

    def OnRun(self, sender, args):
        """Top-level action handler wrapped to prevent any unhandled crashes."""
        try:
            self._ExecuteDetachProcess()
        except Exception as ex:
            log_batch_detach(u"OnRun Exception: {}".format(safe_unicode(ex)))
            show_error(u"An error occurred during batch detach execution:\n\n{}".format(safe_unicode(ex)))
        except:
            import sys
            fatal_err = safe_unicode(sys.exc_info()[1])
            log_batch_detach(u"OnRun Fatal CLR Error: {}".format(fatal_err))
            show_error(u"A fatal system error occurred during execution.")

    def _ExecuteDetachProcess(self):
        """Internal worker executing the batch detach workflow."""
        if self._is_processing:
            return

        if not self.file_items:
            show_warning("Please select at least one Revit (.rvt) model to detach.")
            return

        if not app:
            show_error("Could not obtain Revit Application reference.")
            return

        is_folder_mode = bool(self.rbFolder.IsChecked)
        out_folder = safe_unicode(self.txtFolder.Text.strip())
        suffix = safe_unicode(self.txtSuffix.Text.strip())

        if is_folder_mode:
            if not out_folder:
                show_warning("Please specify a valid destination folder.")
                return
            if not os.path.exists(out_folder):
                try:
                    os.makedirs(out_folder)
                except Exception as ex:
                    show_error(u"Could not create destination folder:\n{}".format(safe_unicode(ex)))
                    return
        else:
            if not suffix:
                show_warning("Please specify a suffix for the detached files (e.g. _detached).")
                return

        relinquish_all = bool(self.chkRelinquish.IsChecked)
        unload_links = bool(self.chkUnloadLinks.IsChecked)
        audit_models = bool(self.chkAudit.IsChecked)

        total = len(self.file_items)
        success_count = 0
        fail_count = 0
        failed_files = []

        # Tier 3 Progress Bar setup
        self._is_processing = True
        self.progressBar.Visibility = Visibility.Visible
        self.progressBar.Minimum = 0
        self.progressBar.Maximum = total
        self.progressBar.Value = 0

        self.btnRun.IsEnabled = False
        self.btnAddFiles.IsEnabled = False
        self.btnAddFolder.IsEnabled = False
        self.btnClear.IsEnabled = False

        # Attach failure handler to auto-resolve warnings during batch opening
        failures_attached = False
        try:
            app.FailuresProcessing += _on_failures_processing
            failures_attached = True
        except Exception:
            pass

        try:
            for idx, item in enumerate(self.file_items):
                src_path = safe_unicode(item.Path)
                filename = safe_unicode(item.Name)

                # Determine destination path
                if is_folder_mode:
                    dst_path = os.path.join(out_folder, filename)
                else:
                    base, ext = os.path.splitext(src_path)
                    dst_path = base + suffix + ext

                self.txtStatus.Text = u"Detaching {} ({}/{})...".format(filename, idx + 1, total)
                self.progressBar.Value = idx
                do_events()

                ok, msg = detach_and_clean_model(
                    app=app,
                    source_path=src_path,
                    dest_path=dst_path,
                    relinquish_all=relinquish_all,
                    unload_links=unload_links,
                    audit=audit_models,
                    preserve_worksets=True
                )

                if ok:
                    success_count += 1
                else:
                    fail_count += 1
                    failed_files.append(u"{}: {}".format(filename, safe_unicode(msg)))

                self.progressBar.Value = idx + 1
                do_events()

            self.progressBar.Value = total
            self.txtStatus.Text = u"Completed: {} successful, {} failed.".format(success_count, fail_count)

            # Build final report
            if fail_count == 0:
                show_success(
                    u"🎉 Successfully detached and processed all {} model(s)!\n\n"
                    u"- Worksets: Non-Editable (Relinquished)\n"
                    u"- Links: {}\n"
                    u"- Destination: {}".format(
                        success_count,
                        "Unloaded" if unload_links else "Preserved",
                        out_folder if is_folder_mode else u"Alongside original files with suffix '{}'".format(suffix)
                    ),
                    title="Batch Detach Complete"
                )
            else:
                err_summary = u"\n".join(failed_files[:5])
                if len(failed_files) > 5:
                    err_summary += u"\n...and {} more.".format(len(failed_files) - 5)

                show_warning(
                    u"Batch detach completed with issues:\n\n"
                    u"✅ Succeeded: {}\n"
                    u"❌ Failed: {}\n\n"
                    u"Errors:\n{}".format(success_count, fail_count, err_summary),
                    title="Batch Detach Results"
                )

        finally:
            if failures_attached:
                try:
                    app.FailuresProcessing -= _on_failures_processing
                except Exception:
                    pass

            self._is_processing = False
            self.progressBar.Visibility = Visibility.Collapsed
            self.btnRun.IsEnabled = True
            self.btnAddFiles.IsEnabled = True
            self.btnAddFolder.IsEnabled = True
            self.btnClear.IsEnabled = True


if __name__ == "__main__":
    try:
        xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
        if os.path.exists(xaml_path):
            win = BatchDetachWindow(xaml_path)
            win.ShowDialog()
        else:
            show_error(u"UI file 'ui.xaml' not found.")
    except Exception as ex:
        log_batch_detach(u"Startup Error: {}".format(safe_unicode(ex)))
        show_error(u"Failed to open Batch Detach:\n\n{}".format(safe_unicode(ex)))
    except:
        import sys
        show_error(u"Failed to open Batch Detach.")
