# -*- coding: utf-8 -*-
"""
script.py - Batch Export Controller Window
Automated batch sheet export to Native Revit 2022+ PDF & DWG formats with:
- Auto paper size (A0-A4) & orientation detection from TitleBlock.
- Dynamic token-based filename builder.
- Progress reporting & smooth Dispatcher message pumping.

Part of mepanana.extension.
Author: Hai Nguyen
"""
import os
import sys
import tempfile
import shutil
import subprocess
import traceback

import clr
clr.AddReference("System")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from System.Windows import Visibility
from System.Collections.ObjectModel import ObservableCollection

from pyrevit import forms
# ── 6-Line Security Gatekeeper Boilerplate ───────────────────────────────────
from py.auth import require_auth, update_ribbon_state, is_authenticated
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()

from py.core import get_doc, get_uidoc, safe_unicode
from py.ui import setup_window, do_events, show_error, show_warning, _show_custom_dialog
from py.sheet_export_engine import (
    get_all_sheets, build_sheet_filename, export_sheets_to_pdf, export_sheets_to_dwg,
    NATIVE_PDF_SUPPORTED, DWG_SUPPORTED
)
from py.dwg_combine_engine import (
    combine_dwgs_to_multilayout, find_accoreconsole, is_accoreconsole_available
)

try:
    from Autodesk.Revit.DB import ExportPaperFormat
except Exception:
    pass


class BatchExportWindow(forms.WPFWindow):
    """Main UI Controller for MEPANANA Batch Sheet Exporter."""

    def __init__(self, doc, uidoc):
        xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        setup_window(self)

        self.doc = doc
        self.uidoc = uidoc

        # Output Folder Setup (Default to Desktop/MEPANANA_Exports or user home)
        default_dir = os.path.join(os.path.expanduser("~"), "Desktop", "MEPANANA_Exports")
        self.txtOutputPath.Text = default_dir

        # Load All Sheets from Document
        self._all_sheet_vms = []
        self._displayed_vms = ObservableCollection[object]()
        self.dgSheets.ItemsSource = self._displayed_vms

        self._load_sheets()

        # Wire UI Events
        self.txtSearch.TextChanged += lambda s, e: self._apply_filter()
        self.btnClearSearch.Click += lambda s, e: self._clear_search()

        self.btnSelectAll.Click += lambda s, e: self._set_selection_all(True)
        self.btnSelectNone.Click += lambda s, e: self._set_selection_all(False)
        self.btnInvertSelect.Click += lambda s, e: self._invert_selection()

        self.btnBrowseFolder.Click += self._on_browse_folder

        # Quick Token Pill Buttons
        self.btnTokenSheetNum.Click += lambda s, e: self._insert_token("[Sheet Number]")
        self.btnTokenSheetName.Click += lambda s, e: self._insert_token("[Sheet Name]")
        self.btnTokenRev.Click += lambda s, e: self._insert_token("Rev[Current Revision]")
        self.btnTokenDate.Click += lambda s, e: self._insert_token("[Date]")
        self.btnTokenProjNum.Click += lambda s, e: self._insert_token("[Project Number]")

        self.txtNamingTemplate.TextChanged += lambda s, e: self._update_live_preview()
        self.dgSheets.SelectionChanged += lambda s, e: self._update_live_preview()

        # Export Mode Switching (PDF & DWG)
        self.rbPdfSeparate.Checked += self._on_export_mode_changed
        self.rbPdfCombine.Checked += self._on_export_mode_changed
        self.rbDwgSeparate.Checked += self._on_export_mode_changed
        self.rbDwgCombine.Checked += self._on_export_mode_changed
        self.chkFormatPdf.Checked += self._on_export_mode_changed
        self.chkFormatPdf.Unchecked += self._on_export_mode_changed
        self.chkFormatDwg.Checked += self._on_export_mode_changed
        self.chkFormatDwg.Unchecked += self._on_export_mode_changed

        self.btnExport.Click += self._on_export_clicked
        self.btnClose.Click += lambda s, e: self.Close()

        # Prevent ScrollViewer from auto-scrolling down on control focus
        if hasattr(self, 'scrollRightOptions') and self.scrollRightOptions:
            self.scrollRightOptions.ScrollToTop()
            self.scrollRightOptions.RequestBringIntoView += lambda s, e: setattr(e, 'Handled', True)

        if hasattr(self, 'txtNamingTemplate') and self.txtNamingTemplate:
            self.txtNamingTemplate.CaretIndex = 0

        self._saved_indiv_template = self.txtNamingTemplate.Text if hasattr(self, 'txtNamingTemplate') else "[Sheet Number] - [Sheet Name]"
        self._saved_combined_name = "Combined_Drawing_Set"

        self._on_export_mode_changed(None, None)
        self._update_live_preview()
        self._update_counts()

    # -------------------------------------------------------------------------
    # Sheet Loading & Filtering
    # -------------------------------------------------------------------------

    def _load_sheets(self):
        try:
            self._all_sheet_vms = get_all_sheets(self.doc, include_placeholders=False)
            self._apply_filter()
            self.txtSheetCountBadge.Text = "{} Sheets in Project".format(len(self._all_sheet_vms))
        except Exception as ex:
            self.txtStatus.Text = u"Error loading sheets: {}".format(safe_unicode(ex))

    def _apply_filter(self):
        query = (self.txtSearch.Text or "").strip().lower()
        self._displayed_vms.Clear()

        for item in self._all_sheet_vms:
            if not query:
                self._displayed_vms.Add(item)
            else:
                num = (item.SheetNumber or "").lower()
                name = (item.SheetName or "").lower()
                if query in num or query in name:
                    self._displayed_vms.Add(item)

        self._update_counts()

    def _clear_search(self):
        self.txtSearch.Text = ""
        self._apply_filter()

    def _set_selection_all(self, select_state):
        for item in self._displayed_vms:
            item.IsSelected = select_state
        self._refresh_grid()
        self._update_counts()

    def _invert_selection(self):
        for item in self._displayed_vms:
            item.IsSelected = not item.IsSelected
        self._refresh_grid()
        self._update_counts()

    def _refresh_grid(self):
        # Refresh DataGrid visually
        self.dgSheets.Items.Refresh()

    def _update_counts(self):
        selected_count = sum(1 for item in self._all_sheet_vms if item.IsSelected)
        displayed_count = len(self._displayed_vms)
        self.txtSelectionCount.Text = "Selected: {} / {}".format(selected_count, displayed_count)

    # -------------------------------------------------------------------------
    # Filename Builder & Live Preview
    # -------------------------------------------------------------------------

    def _insert_token(self, token):
        template = self.txtNamingTemplate.Text or ""
        caret_idx = self.txtNamingTemplate.CaretIndex
        if caret_idx < 0:
            caret_idx = len(template)

        # Add space separator if needed
        prefix = " " if (caret_idx > 0 and template[caret_idx - 1] not in [" ", "_", "-"]) else ""
        insert_str = prefix + token

        new_text = template[:caret_idx] + insert_str + template[caret_idx:]
        self.txtNamingTemplate.Text = new_text
        self.txtNamingTemplate.CaretIndex = caret_idx + len(insert_str)
        self.txtNamingTemplate.Focus()

    def _update_live_preview(self):
        try:
            template = self.txtNamingTemplate.Text or ""
            export_pdf = bool(self.chkFormatPdf.IsChecked)
            export_dwg = bool(self.chkFormatDwg.IsChecked)
            pdf_comb = bool(export_pdf and self.rbPdfCombine.IsChecked)
            dwg_comb = bool(export_dwg and self.rbDwgCombine.IsChecked)

            if pdf_comb or dwg_comb:
                sample_item = self._all_sheet_vms[0] if len(self._all_sheet_vms) > 0 else None
                sheet_obj = sample_item.Sheet if sample_item else None
                combined_name = build_sheet_filename(self.doc, sheet_obj, template or "Combined_Drawing_Set")
                clean_name = (combined_name or "Combined_Drawing_Set").replace(".pdf", "").replace(".dwg", "")

                parts = []
                if export_pdf:
                    parts.append(clean_name + ".pdf" if pdf_comb else "Individual PDFs")
                if export_dwg:
                    parts.append(clean_name + ".dwg (Layouts)" if dwg_comb else "Individual DWGs")

                self.txtLivePreview.Text = "  •  ".join(parts) if parts else (clean_name + ".pdf")
            else:
                sample_item = self.dgSheets.SelectedItem
                if not sample_item and len(self._all_sheet_vms) > 0:
                    sample_item = self._all_sheet_vms[0]

                if sample_item:
                    base_name = build_sheet_filename(self.doc, sample_item.Sheet, template or "[Sheet Number] - [Sheet Name]")
                    parts = []
                    if export_pdf:
                        parts.append(base_name + ".pdf")
                    if export_dwg:
                        parts.append(base_name + ".dwg")
                    self.txtLivePreview.Text = "  •  ".join(parts) if parts else (base_name + ".pdf")
                else:
                    self.txtLivePreview.Text = "No sample sheet available."
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Options & Folder Browsing
    # -------------------------------------------------------------------------

    def _on_export_mode_changed(self, sender, e):
        if not hasattr(self, 'txtNamingSectionTitle'):
            return

        export_pdf = bool(self.chkFormatPdf.IsChecked)
        export_dwg = bool(self.chkFormatDwg.IsChecked)
        pdf_comb = bool(export_pdf and self.rbPdfCombine.IsChecked)
        dwg_comb = bool(export_dwg and self.rbDwgCombine.IsChecked)

        # Toggle visibility of format config panels based on checkbox state
        if hasattr(self, 'borderPdfConfig') and self.borderPdfConfig:
            self.borderPdfConfig.Visibility = Visibility.Visible if export_pdf else Visibility.Collapsed

        if hasattr(self, 'borderDwgConfig') and self.borderDwgConfig:
            self.borderDwgConfig.Visibility = Visibility.Visible if export_dwg else Visibility.Collapsed

        if pdf_comb or dwg_comb:
            # Switch to Combine Mode UI
            if not getattr(self, '_in_combine_mode', False):
                self._saved_indiv_template = self.txtNamingTemplate.Text
                self._in_combine_mode = True
                self.txtNamingTemplate.Text = getattr(self, '_saved_combined_name', "Combined_Drawing_Set")

            if pdf_comb and dwg_comb:
                self.txtNamingSectionTitle.Text = "3. COMBINED EXPORT FILENAME"
            elif pdf_comb:
                self.txtNamingSectionTitle.Text = "3. COMBINED PDF FILENAME"
            else:
                self.txtNamingSectionTitle.Text = "3. COMBINED DWG FILENAME"

            self.lblNamingPattern.Text = "Output Combined File Name:"
            self.lblLivePreviewTitle.Text = "Combined File Output Preview:"

            # Sheet-specific tokens don't apply to the whole combined set
            self.btnTokenSheetNum.Visibility = Visibility.Collapsed
            self.btnTokenSheetName.Visibility = Visibility.Collapsed
            self.btnTokenRev.Visibility = Visibility.Collapsed
        else:
            # Switch to Separate Files Mode UI
            if getattr(self, '_in_combine_mode', False):
                self._saved_combined_name = self.txtNamingTemplate.Text
                self._in_combine_mode = False
                self.txtNamingTemplate.Text = getattr(self, '_saved_indiv_template', "[Sheet Number] - [Sheet Name]")

            self.txtNamingSectionTitle.Text = "3. DYNAMIC FILENAME BUILDER"
            self.lblNamingPattern.Text = "Template Pattern:"
            self.lblLivePreviewTitle.Text = "Live Filename Preview:"

            self.btnTokenSheetNum.Visibility = Visibility.Visible
            self.btnTokenSheetName.Visibility = Visibility.Visible
            self.btnTokenRev.Visibility = Visibility.Visible

        self._update_live_preview()

    def _on_browse_folder(self, sender, e):
        folder = forms.pick_folder(title="Select Output Export Directory")
        if folder:
            self.txtOutputPath.Text = folder

    # -------------------------------------------------------------------------
    # Batch Export Execution
    # -------------------------------------------------------------------------

    def _on_export_clicked(self, sender, e):
        selected_items = [item for item in self._all_sheet_vms if item.IsSelected]

        if not selected_items:
            show_warning("Please select at least one sheet from the list to export.",
                         title="No Sheets Selected", owner=self, topmost=True)
            return

        export_pdf = bool(self.chkFormatPdf.IsChecked)
        export_dwg = bool(self.chkFormatDwg.IsChecked)

        if not export_pdf and not export_dwg:
            show_warning("Please check at least one output format (PDF or DWG).",
                         title="No Format Selected", owner=self, topmost=True)
            return

        output_dir = (self.txtOutputPath.Text or "").strip()
        if not output_dir:
            show_warning("Please specify an output destination folder.",
                         title="Invalid Path", owner=self, topmost=True)
            return

        # Prepare UI for background batch processing
        self.btnExport.IsEnabled = False
        self.btnClose.IsEnabled = False
        self.progressBar.Visibility = Visibility.Visible
        self.progressBar.Value = 0

        naming_template = self.txtNamingTemplate.Text or "[Sheet Number] - [Sheet Name]"
        combine_pdf = bool(self.rbPdfCombine.IsChecked)

        sample_sheet = self._all_sheet_vms[0].Sheet if self._all_sheet_vms else None
        combined_filename = build_sheet_filename(self.doc, sample_sheet, naming_template) or "Combined_Drawing_Set"
        combined_filename = combined_filename.replace(".pdf", "")

        # Color Mode
        color_mode = "Color"
        if self.cmbColorMode.SelectedIndex == 1:
            color_mode = "Grayscale"
        elif self.cmbColorMode.SelectedIndex == 2:
            color_mode = "Black & White"

        # Force Paper Size
        force_format = None
        if self.cmbPaperRule.SelectedIndex == 1:
            force_format = getattr(ExportPaperFormat, "ISO_A3", None)
        elif self.cmbPaperRule.SelectedIndex == 2:
            force_format = getattr(ExportPaperFormat, "ISO_A1", None)
        elif self.cmbPaperRule.SelectedIndex == 3:
            force_format = getattr(ExportPaperFormat, "ISO_A0", None)

        def progress_cb(current, total, msg):
            pct = int((float(current) / float(total if total > 0 else 1)) * 100)
            self.progressBar.Value = pct
            self.txtStatus.Text = u"[{}/{}] {}".format(current, total, msg)
            do_events()

        total_exported = 0
        all_errors = []

        try:
            # 1. Export PDF
            if export_pdf:
                self.txtStatus.Text = "Initiating Native PDF Export..."
                do_events()

                count, errs = export_sheets_to_pdf(
                    self.doc, selected_items, output_dir,
                    naming_template=naming_template,
                    combine=combine_pdf,
                    combined_filename=combined_filename,
                    color_mode=color_mode,
                    force_paper_format=force_format,
                    progress_callback=progress_cb
                )
                total_exported += count
                all_errors.extend(errs)

            # 2. Export DWG
            if export_dwg:
                combine_dwg = bool(self.rbDwgCombine.IsChecked)
                if combine_dwg and not find_accoreconsole():
                    show_warning(
                        "AutoCAD Core Console (accoreconsole.exe) was not found on this computer.\n"
                        "DWG export will proceed as Separate Files.",
                        title="AutoCAD Not Found", owner=self, topmost=True
                    )
                    combine_dwg = False

                if combine_dwg:
                    self.txtStatus.Text = "Initiating Multi-Layout DWG Combine..."
                    do_events()

                    # Use output_dir as base for temp folder — more reliable than tempfile.gettempdir()
                    # which returns unpredictable paths in IronPython / Revit process context.
                    temp_dwg_dir = os.path.join(output_dir, "._mep_tmp_{}".format(os.getpid()))

                    # Pre-clean to avoid "file already in use" from a previous crashed session
                    if os.path.exists(temp_dwg_dir):
                        shutil.rmtree(temp_dwg_dir, ignore_errors=True)
                    try:
                        os.makedirs(temp_dwg_dir)
                    except Exception as ex:
                        all_errors.append(u"Cannot create temp directory: {}".format(safe_unicode(ex)))
                        temp_dwg_dir = None

                    if temp_dwg_dir:
                      try:
                        # Export individual sheets to temp directory
                        dwg_temp_template = "mep_[Sheet Number]"
                        t_count, t_errs = export_sheets_to_dwg(
                            self.doc, selected_items, temp_dwg_dir,
                            naming_template=dwg_temp_template,
                            progress_callback=lambda cur, tot, msg: progress_cb(
                                cur, tot * 2, u"Revit DWG: {}".format(msg)
                            )
                        )
                        all_errors.extend(t_errs)

                        # Match exported files with sheets in order.
                        # Revit with MergedViews=True sometimes writes "_<name>.dwg" (underscore prefix)
                        # instead of "<name>.dwg" — check both variants, then fallback to dir scan.
                        dwg_files = []
                        sheet_labels = []
                        for item in selected_items:
                            expected_name = build_sheet_filename(self.doc, item.Sheet, dwg_temp_template)
                            candidate     = os.path.join(temp_dwg_dir, expected_name + ".dwg")
                            candidate_alt = os.path.join(temp_dwg_dir, "_" + expected_name + ".dwg")

                            found = None
                            if os.path.isfile(candidate):
                                found = candidate
                            elif os.path.isfile(candidate_alt):
                                found = candidate_alt
                            else:
                                # Last resort: scan temp dir for any .dwg file matching sheet number
                                sheet_num = (item.SheetNumber or "").replace("/", "_").replace("\\", "_")
                                try:
                                    for f in os.listdir(temp_dwg_dir):
                                        if f.lower().endswith(".dwg") and sheet_num.lower() in f.lower():
                                            found = os.path.join(temp_dwg_dir, f)
                                            break
                                except Exception:
                                    pass

                            if found:
                                dwg_files.append(found)
                                sheet_lbl = item.SheetNumber or item.SheetName or "Sheet"
                                sheet_labels.append(sheet_lbl)

                        if dwg_files:
                            out_dwg_path = os.path.join(output_dir, combined_filename + ".dwg")
                            self.txtStatus.Text = "Merging layouts into master DWG..."
                            do_events()

                            def merge_cb(pct, m_msg):
                                progress_cb(len(selected_items) + int(len(selected_items) * (pct / 100.0)),
                                            len(selected_items) * 2, m_msg)

                            ok, m_res = combine_dwgs_to_multilayout(
                                dwg_files, sheet_labels, out_dwg_path,
                                progress_callback=merge_cb
                            )
                            if ok:
                                total_exported += 1
                            else:
                                all_errors.append(u"DWG Combine Failed: {}".format(safe_unicode(m_res)))
                        else:
                            all_errors.append(
                                u"No intermediate DWG files found in temp dir: {}. "
                                u"Revit may have written files to a different path.".format(temp_dwg_dir)
                            )
                      finally:
                        shutil.rmtree(temp_dwg_dir, ignore_errors=True)

                else:
                    # Separate Files Mode
                    self.txtStatus.Text = "Initiating Separate DWG Export..."
                    do_events()

                    dwg_template = self._saved_indiv_template if (combine_pdf or getattr(self, '_in_combine_mode', False)) else naming_template
                    if "[Sheet Number]" not in dwg_template and "[Number]" not in dwg_template:
                        dwg_template = "[Sheet Number] - " + dwg_template

                    count, errs = export_sheets_to_dwg(
                        self.doc, selected_items, output_dir,
                        naming_template=dwg_template,
                        progress_callback=progress_cb
                    )
                    total_exported += count
                    all_errors.extend(errs)

            self.progressBar.Value = 100
            if all_errors:
                self.txtStatus.Text = u"Export finished with warnings: {}/{} processed.".format(total_exported, len(selected_items))
            else:
                self.txtStatus.Text = u"Export finished: Successfully processed {} item(s).".format(total_exported)

            # Report completion via MEPANANA Modern Alert Dialog
            if all_errors:
                msg = u"Export completed with warnings/errors:\n\n" + u"\n".join(all_errors[:5])
                if len(all_errors) > 5:
                    msg += u"\n...and {} more errors.".format(len(all_errors) - 5)
                _show_custom_dialog(msg, title="Export Warning", dialog_type="WARNING", owner=self, topmost=True)
            else:
                msg = u"Successfully exported {} drawing files to:\n\n{}".format(total_exported, output_dir)
                _show_custom_dialog(msg, title="Export Complete", dialog_type="SUCCESS", owner=self, topmost=True)

            # Open folder in Windows Explorer
            try:
                if os.path.exists(output_dir):
                    subprocess.Popen(['explorer', os.path.normpath(output_dir)])
            except Exception:
                pass

        except Exception as ex:
            err_str = safe_unicode(ex)
            self.txtStatus.Text = u"Fatal export error: {}".format(err_str)
            show_error(u"An unexpected error occurred during export:\n\n{}".format(err_str),
                       title="Export Error", owner=self, topmost=True)
        finally:
            self.progressBar.Visibility = Visibility.Collapsed
            self.btnExport.IsEnabled = True
            self.btnClose.IsEnabled = True


# -- Tool Entry Point ---------------------------------------------------------

if __name__ == "__main__":
    doc = get_doc()
    uidoc = get_uidoc()

    if not doc:
        show_error("Please open a Revit project first.", title="No Document", exitscript=True)

    win = BatchExportWindow(doc, uidoc)
    win.ShowDialog()
