# -*- coding: utf-8 -*-
__title__ = "Schedule Link"
__doc__   = "Export and Import Revit Schedules to/from Excel (.xlsx)."

import os
import sys
import traceback

try:
    import clr
    clr.AddReference("System")
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    clr.AddReference("System.Windows.Forms")

    import System
    import System.Windows
    from System.Windows import Thickness, Visibility
    from System.Windows.Controls import CheckBox
    from Microsoft.Win32 import OpenFileDialog
    from System.Windows.Forms import FolderBrowserDialog, DialogResult

    from pyrevit import forms
    from py.auth import require_auth, update_ribbon_state, is_authenticated
    from py.core import get_doc
    from py.ui   import show_info, show_warning, show_error, setup_window
    from py.schedule_io import get_all_schedules, extract_schedule_data, preview_schedule_diff, apply_schedule_import
    from py.excel_io import export_schedules_to_excel, read_excel_workbook

    # ── Authentication Gatekeeper ─────────────────────────────────────────────────
    if not is_authenticated():
        update_ribbon_state(False)
        if not require_auth():
            sys.exit()

    doc = get_doc()
    if not doc:
        show_warning(u"Please open a Revit project before using Schedule Link.", "Warning")
        sys.exit()

    class DiffRow(object):
        def __init__(self, sheet, element_id, field, old_val, new_val, status):
            self.Sheet = sheet
            self.ElementId = element_id
            self.Field = field
            self.OldVal = old_val
            self.NewVal = new_val
            if status == "CHANGED":
                self.StatusDisplay = u"🟡 Changed"
            elif status == "READONLY":
                self.StatusDisplay = u"🔒 Read-Only"
            elif status == "NOT_FOUND":
                self.StatusDisplay = u"❌ Not Found"
            else:
                self.StatusDisplay = status

    class ScheduleLinkWindow(forms.WPFWindow):
        def __init__(self):
            xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
            forms.WPFWindow.__init__(self, xaml_path)
            setup_window(self)

            self.all_schedules = []
            self.current_excel_data = None

            # Load Schedules from Revit doc
            raw_schedules = get_all_schedules(doc)
            for s in raw_schedules:
                self.all_schedules.append({
                    "id": s["id"],
                    "name": s["name"],
                    "view": s["view"],
                    "selected": True
                })

            # Default export folder on Desktop
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            self.txtExportFolder.Text = desktop

            # Tab Switching Events
            self.rbTabExport.Checked += self.on_tab_changed
            self.rbTabImport.Checked += self.on_tab_changed

            # Export Controls Events
            self.txtSearchExport.TextChanged += self.on_search_export
            self.btnSelectAll.Click += self.on_select_all
            self.btnDeselectAll.Click += self.on_deselect_all
            self.btnBrowseFolder.Click += self.on_browse_folder
            self.btnExport.Click += self.on_export

            # Import Controls Events
            self.btnBrowseImport.Click += self.on_browse_import
            self.btnPreviewDiff.Click += self.on_preview_diff
            self.btnApplyImport.Click += self.on_apply_import

            self.refresh_export_list()

        def on_tab_changed(self, sender, args):
            if self.rbTabExport.IsChecked:
                self.panelExport.Visibility = Visibility.Visible
                self.panelImport.Visibility = Visibility.Collapsed
            else:
                self.panelExport.Visibility = Visibility.Collapsed
                self.panelImport.Visibility = Visibility.Visible

        def refresh_export_list(self):
            query = (self.txtSearchExport.Text or "").strip().lower()
            self.lstExportSchedules.Items.Clear()

            for s in self.all_schedules:
                if not query or query in s["name"].lower():
                    chk = CheckBox()
                    chk.Content = s["name"]
                    chk.IsChecked = s["selected"]
                    chk.Tag = s
                    chk.Margin = Thickness(4, 4, 4, 4)
                    chk.FontSize = 13
                    chk.Checked += self.on_item_checked
                    chk.Unchecked += self.on_item_unchecked
                    self.lstExportSchedules.Items.Add(chk)

            self.update_selected_count()

        def on_item_checked(self, sender, args):
            if sender and hasattr(sender, "Tag") and sender.Tag:
                sender.Tag["selected"] = True
            self.update_selected_count()

        def on_item_unchecked(self, sender, args):
            if sender and hasattr(sender, "Tag") and sender.Tag:
                sender.Tag["selected"] = False
            self.update_selected_count()

        def update_selected_count(self):
            count = sum(1 for s in self.all_schedules if s["selected"])
            self.txtSelectedCount.Text = u"{} of {} selected".format(count, len(self.all_schedules))

        def on_search_export(self, sender, args):
            self.refresh_export_list()

        def on_select_all(self, sender, args):
            for s in self.all_schedules:
                s["selected"] = True
            self.refresh_export_list()

        def on_deselect_all(self, sender, args):
            for s in self.all_schedules:
                s["selected"] = False
            self.refresh_export_list()

        def on_browse_folder(self, sender, args):
            dlg = FolderBrowserDialog()
            dlg.Description = "Select Destination Folder for Exported Schedules"
            if os.path.exists(self.txtExportFolder.Text):
                dlg.SelectedPath = self.txtExportFolder.Text
            if dlg.ShowDialog() == DialogResult.OK:
                self.txtExportFolder.Text = dlg.SelectedPath

        def on_export(self, sender, args):
            selected = [s for s in self.all_schedules if s["selected"]]
            if not selected:
                show_warning(u"Please select at least 1 schedule to export.", "Warning")
                return

            export_folder = self.txtExportFolder.Text.strip()
            if not export_folder or not os.path.exists(export_folder):
                show_warning(u"Please choose a valid destination folder.", "Warning")
                return

            visible_only = bool(self.chkVisibleOnly.IsChecked)

            try:
                exported_files = []
                for item in selected:
                    sched_name = item["name"]
                    # Clean filename
                    clean_name = sched_name
                    for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
                        clean_name = clean_name.replace(ch, '_')
                    clean_name = clean_name.strip()
                    if not clean_name:
                        clean_name = "Schedule_{}".format(item["id"])

                    file_path = os.path.join(export_folder, "{}.xlsx".format(clean_name))

                    # Extract and write single schedule Excel file
                    data = extract_schedule_data(doc, item["view"], visible_only=visible_only)
                    export_schedules_to_excel(file_path, [data])
                    exported_files.append(file_path)

                msg = u"Successfully exported {} schedule(s) to folder:\n\n📁 Folder:\n{}".format(
                    len(exported_files), export_folder
                )
                show_info(msg, "Success")

                if self.chkOpenAfter.IsChecked:
                    try:
                        import System.Diagnostics
                        if len(exported_files) == 1 and os.path.exists(exported_files[0]):
                            psi = System.Diagnostics.ProcessStartInfo()
                            psi.FileName = exported_files[0]
                            psi.UseShellExecute = True
                            System.Diagnostics.Process.Start(psi)
                        else:
                            psi = System.Diagnostics.ProcessStartInfo()
                            psi.FileName = "explorer.exe"
                            psi.Arguments = u'"{}"'.format(export_folder)
                            psi.UseShellExecute = True
                            System.Diagnostics.Process.Start(psi)
                    except Exception:
                        try:
                            if len(exported_files) == 1 and os.path.exists(exported_files[0]):
                                os.startfile(exported_files[0])
                            else:
                                os.startfile(export_folder)
                        except Exception:
                            pass

            except Exception as ex:
                show_error(u"Error exporting Excel files:\n{}".format(str(ex)), "Error")

        def on_browse_import(self, sender, args):
            dlg = OpenFileDialog()
            dlg.Filter = "Excel Workbook (*.xlsx)|*.xlsx"
            if dlg.ShowDialog() is True:
                self.txtImportPath.Text = dlg.FileName
                self.on_preview_diff(None, None)

        def on_preview_diff(self, sender, args):
            import_path = self.txtImportPath.Text.strip()
            if not import_path or not os.path.exists(import_path):
                show_warning(u"Please select a valid Excel file to preview.", "Warning")
                return

            try:
                self.current_excel_data = read_excel_workbook(import_path)
                diff_res = preview_schedule_diff(doc, self.current_excel_data)

                self.txtChangesBadge.Text = u"🟡 {} Changes".format(diff_res["total_changes"])
                self.txtUnchangedBadge.Text = u"🟢 {} Unchanged".format(diff_res["total_unchanged"])
                self.txtReadonlyBadge.Text = u"🔒 {} Read-Only".format(diff_res["total_readonly"])

                diff_items = []
                for d in diff_res["details"]:
                    row = DiffRow(
                        d.get("sheet", ""),
                        d.get("element_id", ""),
                        d.get("field", ""),
                        d.get("old_val", ""),
                        d.get("new_val", ""),
                        d.get("status", "")
                    )
                    diff_items.append(row)

                self.lvDiff.ItemsSource = None
                self.lvDiff.ItemsSource = diff_items

                self.btnApplyImport.IsEnabled = (diff_res["total_changes"] > 0)

                if diff_res["total_changes"] == 0:
                    show_info(u"No changes detected between Excel file and Revit elements.", "Info")

            except Exception as ex:
                show_error(u"Error reading Excel file:\n{}".format(str(ex)), "Error")

        def on_apply_import(self, sender, args):
            if not self.current_excel_data:
                return

            try:
                res = apply_schedule_import(doc, self.current_excel_data)
                updated = res["updated_count"]
                readonly = res["readonly_count"]
                errors = res["error_count"]

                msg = u"Import completed successfully!\n\n" \
                      u"✓ Updated: {} parameter(s)\n" \
                      u"🔒 Skipped (Read-Only): {}\n" \
                      u"⚠ Errors: {}".format(updated, readonly, errors)

                show_info(msg, "Complete")
                self.on_preview_diff(None, None)

            except Exception as ex:
                show_error(u"Error updating parameters in Revit:\n{}".format(str(ex)), "Error")

    win = ScheduleLinkWindow()
    win.ShowDialog()

except Exception as ex:
    err_msg = "Schedule Link Error:\n{}\n\n{}".format(str(ex), traceback.format_exc())
    try:
        from py.ui import show_error
        show_error(err_msg, "Schedule Link Error")
    except:
        print(err_msg)