# -*- coding: utf-8 -*-
"""
Check Clash - Interactive 3D Clash Inspector & Resolution Navigator
Modeless Architecture: Allows engineers to freely interact with Revit elements
outside the tool while keeping the 3D Navigator floating on top.
Uses Revit ExternalEvent to safely dispatch all API operations.

REQUIRES bundle.yaml: engine: {clean: true, persistent: true, full_frame: true}

Part of mepanana.extension.
Author: Hai Nguyen
"""
import os
import sys
import traceback
import clr

from pyrevit import forms
from pyrevit import script as _script
import py.auth as _auth

# -- 6-Line Security Gatekeeper -----------------------------------------------
if not _auth.is_authenticated():
    _auth.show_locked_dialog()
    sys.exit(0)

clr.AddReference("System")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from System import Uri, UriKind
from System.Windows import Visibility, ResourceDictionary, FontWeights
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Input import Key
from System.Collections.ObjectModel import ObservableCollection

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import BuiltInCategory

from py.core import get_doc, get_uidoc, get_id_value, safe_unicode
from py.ui import setup_window
from py.clash_analysis_engine import (
    scan_clashes, recheck_single_clash, focus_clash_3d, export_clash_report, import_clash_report
)


# -- Module-Level Modeless ExternalEvent Handlers (Persistent) ----------------
# ExternalEvent.Create() is valid inside IExternalCommand.Execute() context.
# With persistent:true engine, this module runs ONCE per session. The handler
# objects and ExternalEvent instances become session-wide singletons -- exactly
# the pattern used by pyRevit ColorSplasher tool.

class ClashScanHandler(IExternalEventHandler):
    """Executes full clash scan on Revit UI thread."""
    _wndw = None

    def Execute(self, uiapp):
        try:
            wndw = ClashScanHandler._wndw
            if not wndw:
                return
            doc = uiapp.ActiveUIDocument.Document
            uidoc = uiapp.ActiveUIDocument
            wndw._do_scan(doc, uidoc)
        except Exception:
            print("ClashScanHandler Error:\n" + traceback.format_exc())

    def GetName(self):
        return "MEPANANA ClashScanHandler"


class ClashFocus3DHandler(IExternalEventHandler):
    """Focuses 3D view Section Box on Revit UI thread."""
    _wndw = None
    _clash_item = None

    def Execute(self, uiapp):
        try:
            wndw = ClashFocus3DHandler._wndw
            item = ClashFocus3DHandler._clash_item
            if not wndw or not item:
                return
            doc = uiapp.ActiveUIDocument.Document
            uidoc = uiapp.ActiveUIDocument
            wndw._do_focus_3d(doc, uidoc, item)
        except Exception:
            print("ClashFocus3DHandler Error:\n" + traceback.format_exc())

    def GetName(self):
        return "MEPANANA ClashFocus3DHandler"


class ClashRecheckHandler(IExternalEventHandler):
    """Rechecks single clash status on Revit UI thread."""
    _wndw = None

    def Execute(self, uiapp):
        try:
            wndw = ClashRecheckHandler._wndw
            if not wndw:
                return
            doc = uiapp.ActiveUIDocument.Document
            uidoc = uiapp.ActiveUIDocument
            wndw._do_recheck(doc, uidoc)
        except Exception:
            print("ClashRecheckHandler Error:\n" + traceback.format_exc())

    def GetName(self):
        return "MEPANANA ClashRecheckHandler"


# Session-wide singleton ExternalEvent instances
_SCAN_HANDLER = ClashScanHandler()
_EXT_EVENT_SCAN = ExternalEvent.Create(_SCAN_HANDLER)

_FOCUS_HANDLER = ClashFocus3DHandler()
_EXT_EVENT_FOCUS = ExternalEvent.Create(_FOCUS_HANDLER)

_RECHECK_HANDLER = ClashRecheckHandler()
_EXT_EVENT_RECHECK = ExternalEvent.Create(_RECHECK_HANDLER)


# -- DataGrid Row ViewModel (plain Python object) -----------------------------
# Using plain object instead of INotifyPropertyChanged is intentional:
# IronPython 2.7 requires full C# interface implementation (add/remove event +
# PropertyChanged delegate) which can cause CLR interop crashes if incomplete.
# Instead we use ObservableCollection.Clear() + re-populate to trigger a full
# DataGrid refresh whenever displayed data changes -- safe and correct.

def _hex_brush(hex_str):
    h = hex_str.lstrip('#')
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return SolidColorBrush(Color.FromRgb(r, g, b))


class ClashRowVM(object):
    """Plain Python view-model for WPF DataGrid binding. IronPython 2.7 safe."""

    def __init__(self, raw_item):
        self.RawItem = raw_item

        el1 = raw_item.Element1
        el2 = raw_item.Element2
        cat1 = (el1.Category.Name if el1.Category else "Element") if el1 else "Element"
        cat2 = (el2.Category.Name if el2.Category else "Element") if el2 else "Element"
        id1 = get_id_value(el1) if el1 else 0
        id2 = get_id_value(el2) if el2 else 0

        self.Elem1Info = u"{} [{}]".format(cat1, id1)
        self.Elem2Info = u"{} [{}]".format(cat2, id2)
        self.ElevDiffDisplay = u"{:.0f} mm".format(raw_item.ElevDiffMm)
        self.ModelSource = raw_item.LinkName if raw_item.IsLink else u"Host Model"

        self._refresh_status()

    def _refresh_status(self):
        resolved = getattr(self.RawItem, "Status", "ACTIVE") == "RESOLVED"
        self.IsResolved = resolved
        if resolved:
            self.StatusDisplay = u"✅ Resolved"
            self.StatusColor = "#059669"
            self.StatusBg = "#D1FAE5"
        else:
            self.StatusDisplay = u"🔴 Active"
            self.StatusColor = "#DC2626"
            self.StatusBg = "#FEE2E2"
        self.OverlapDisplay = u"{:.0f} mm".format(self.RawItem.OverlapMm)

    def mark_resolved(self):
        self.RawItem.Status = "RESOLVED"
        self.RawItem.OverlapMm = 0.0
        self._refresh_status()

    def update_overlap(self, new_overlap_mm):
        self.RawItem.OverlapMm = new_overlap_mm
        self._refresh_status()


# -- Main Controller Window ---------------------------------------------------

class CheckClashWindow(forms.WPFWindow):
    _current_wndw = None

    def __init__(self, doc, uidoc):
        xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
        forms.WPFWindow.__init__(self, xaml_path)

        # Load theme WITHOUT Owner=MainWindowHandle so Revit canvas stays modelessly interactive
        setup_window(self, set_revit_owner=False)

        self.doc = doc
        self.uidoc = uidoc

        self._all_clash_vms = []
        self._displayed_vms = ObservableCollection[object]()
        self.dgClashes.ItemsSource = self._displayed_vms
        self._current_tab = "ACTIVE"

        # Wire UI events
        self.btnScan.Click += self._on_scan_clicked
        self.btnFocus3D.Click += self._on_focus3d_clicked
        self.btnRecheck.Click += self._on_recheck_clicked
        self.btnPrev.Click += self._on_prev_clash
        self.btnNext.Click += self._on_next_clash
        self.btnImportExcel.Click += self._on_import_excel
        self.btnExportExcel.Click += self._on_export_excel
        self.btnClose.Click += lambda s, e: self.Close()

        # Category checkbox events (master group toggles + sub-items + persistence)
        self._updating_mep_group = False
        self.chkGroupMep.Checked   += self._on_mep_group_changed
        self.chkGroupMep.Unchecked += self._on_mep_group_changed
        self.chkCatPipe.Checked      += self._on_mep_sub_changed
        self.chkCatPipe.Unchecked    += self._on_mep_sub_changed
        self.chkCatDuct.Checked      += self._on_mep_sub_changed
        self.chkCatDuct.Unchecked    += self._on_mep_sub_changed
        self.chkCatCableTray.Checked   += self._on_mep_sub_changed
        self.chkCatCableTray.Unchecked += self._on_mep_sub_changed
        self.chkCatConduit.Checked   += self._on_mep_sub_changed
        self.chkCatConduit.Unchecked += self._on_mep_sub_changed
        self.chkGroupStructural.Checked   += self._on_cat_changed
        self.chkGroupStructural.Unchecked += self._on_cat_changed
        self.chkGroupArch.Checked   += self._on_cat_changed
        self.chkGroupArch.Unchecked += self._on_cat_changed
        self.btnCatReset.Click += self._on_cat_reset
        self._load_cat_prefs()

        # Tab Switching
        self.btnTabActive.Click += lambda s, e: self._switch_tab("ACTIVE")
        self.btnTabResolved.Click += lambda s, e: self._switch_tab("RESOLVED")
        self.btnTabAll.Click += lambda s, e: self._switch_tab("ALL")

        self.dgClashes.MouseDoubleClick += self._on_grid_double_click
        self.txtSearch.TextChanged += self._on_filter_changed

        self.PreviewKeyDown += self._on_key_down
        self.Closed += self._on_closed

        # Initialize view state & pill styles
        self._apply_filter()

    def _on_closed(self, sender, e):
        CheckClashWindow._current_wndw = None
        ClashScanHandler._wndw = None
        ClashFocus3DHandler._wndw = None
        ClashFocus3DHandler._clash_item = None
        ClashRecheckHandler._wndw = None

    # -------------------------------------------------------------------------
    # Category Selection Handlers
    # -------------------------------------------------------------------------

    def _on_mep_group_changed(self, sender, e):
        """Master MEP checkbox → toggle all MEP sub-checkboxes."""
        if self._updating_mep_group:
            return
        self._updating_mep_group = True
        try:
            state = bool(self.chkGroupMep.IsChecked)
            self.chkCatPipe.IsChecked      = state
            self.chkCatDuct.IsChecked      = state
            self.chkCatCableTray.IsChecked = state
            self.chkCatConduit.IsChecked   = state
        finally:
            self._updating_mep_group = False
        self._save_cat_prefs()

    def _on_mep_sub_changed(self, sender, e):
        """Any MEP sub-checkbox changed → sync master MEP checkbox state."""
        if self._updating_mep_group:
            return
        self._updating_mep_group = True
        try:
            any_on = (
                bool(self.chkCatPipe.IsChecked) or
                bool(self.chkCatDuct.IsChecked) or
                bool(self.chkCatCableTray.IsChecked) or
                bool(self.chkCatConduit.IsChecked)
            )
            self.chkGroupMep.IsChecked = any_on
        finally:
            self._updating_mep_group = False
        self._save_cat_prefs()

    def _on_cat_changed(self, sender, e):
        """Structural / Architectural group changed → persist."""
        self._save_cat_prefs()

    def _on_cat_reset(self, sender, e):
        """Reset categories to MEP-only defaults."""
        self._updating_mep_group = True
        try:
            self.chkGroupMep.IsChecked       = True
            self.chkCatPipe.IsChecked        = True
            self.chkCatDuct.IsChecked        = True
            self.chkCatCableTray.IsChecked   = True
            self.chkCatConduit.IsChecked     = True
            self.chkGroupStructural.IsChecked = False
            self.chkGroupArch.IsChecked       = False
        finally:
            self._updating_mep_group = False
        self._save_cat_prefs()

    def _build_selected_categories(self):
        """Return list of BuiltInCategory based on current checkbox state."""
        cats = []
        if bool(self.chkCatPipe.IsChecked):
            cats += [
                BuiltInCategory.OST_PipeCurves,
                BuiltInCategory.OST_PipeFitting,
                BuiltInCategory.OST_PipeAccessory,
            ]
        if bool(self.chkCatDuct.IsChecked):
            cats += [
                BuiltInCategory.OST_DuctCurves,
                BuiltInCategory.OST_DuctFitting,
                BuiltInCategory.OST_DuctAccessory,
            ]
        if bool(self.chkCatCableTray.IsChecked):
            cats += [
                BuiltInCategory.OST_CableTray,
                BuiltInCategory.OST_CableTrayFitting,
            ]
        if bool(self.chkCatConduit.IsChecked):
            cats += [
                BuiltInCategory.OST_Conduit,
                BuiltInCategory.OST_ConduitFitting,
            ]
        if bool(self.chkGroupStructural.IsChecked):
            cats += [
                BuiltInCategory.OST_StructuralFraming,
                BuiltInCategory.OST_StructuralColumns,
                BuiltInCategory.OST_StructuralFoundation,
            ]
        if bool(self.chkGroupArch.IsChecked):
            cats += [
                BuiltInCategory.OST_Walls,
                BuiltInCategory.OST_Floors,
                BuiltInCategory.OST_Ceilings,
                BuiltInCategory.OST_Doors,
                BuiltInCategory.OST_Windows,
                BuiltInCategory.OST_Roofs,
            ]
        return cats

    def _save_cat_prefs(self):
        """Persist category checkbox states via pyrevit config."""
        try:
            cfg = _script.get_config()
            cfg.cat_pipe        = bool(self.chkCatPipe.IsChecked)
            cfg.cat_duct        = bool(self.chkCatDuct.IsChecked)
            cfg.cat_cable_tray  = bool(self.chkCatCableTray.IsChecked)
            cfg.cat_conduit     = bool(self.chkCatConduit.IsChecked)
            cfg.cat_structural  = bool(self.chkGroupStructural.IsChecked)
            cfg.cat_arch        = bool(self.chkGroupArch.IsChecked)
            _script.save_config()
        except Exception:
            pass

    def _load_cat_prefs(self):
        """Restore category checkbox states from pyrevit config (safe defaults: MEP on)."""
        try:
            cfg = _script.get_config()
            self._updating_mep_group = True
            try:
                self.chkCatPipe.IsChecked        = getattr(cfg, 'cat_pipe', True)
                self.chkCatDuct.IsChecked        = getattr(cfg, 'cat_duct', True)
                self.chkCatCableTray.IsChecked   = getattr(cfg, 'cat_cable_tray', True)
                self.chkCatConduit.IsChecked     = getattr(cfg, 'cat_conduit', True)
                self.chkGroupStructural.IsChecked = getattr(cfg, 'cat_structural', False)
                self.chkGroupArch.IsChecked       = getattr(cfg, 'cat_arch', False)
                # Sync MEP master checkbox
                any_mep = (
                    bool(self.chkCatPipe.IsChecked) or
                    bool(self.chkCatDuct.IsChecked) or
                    bool(self.chkCatCableTray.IsChecked) or
                    bool(self.chkCatConduit.IsChecked)
                )
                self.chkGroupMep.IsChecked = any_mep
            finally:
                self._updating_mep_group = False
        except Exception:
            pass

    def _on_key_down(self, sender, e):
        if e.Key == Key.Escape:
            self.Close()
            e.Handled = True
        elif e.Key == Key.F5:
            self._on_recheck_clicked(sender, e)
            e.Handled = True
        elif e.Key == Key.Space:
            self._on_focus3d_clicked(sender, e)
            e.Handled = True

    def _show_topmost_dialog(self, message, title="Notification", dialog_type=None, is_error=False):
        """Displays modern branded MEPANANA alert dialog properly parented to this window."""
        if dialog_type is None:
            dialog_type = "ERROR" if is_error else "SUCCESS"
        try:
            from py.ui import _show_custom_dialog
            return _show_custom_dialog(message, title=title, dialog_type=dialog_type, owner=self, topmost=True)
        except Exception:
            was_topmost = self.Topmost
            try:
                self.Topmost = False
                return forms.alert(message, title=title, warn_icon=(dialog_type == "ERROR"))
            finally:
                self.Topmost = was_topmost

    # -------------------------------------------------------------------------
    # 1. Scan
    # -------------------------------------------------------------------------

    def _on_scan_clicked(self, sender, e):
        self.btnScan.IsEnabled = False
        self.progressBar.Visibility = Visibility.Visible
        self.progressBar.IsIndeterminate = True
        self.txtStatus.Text = "Scanning for clashes..."
        ClashScanHandler._wndw = self
        _EXT_EVENT_SCAN.Raise()

    def _do_scan(self, doc, uidoc):
        """Called by ClashScanHandler on Revit UI thread. NO do_events() here."""
        try:
            selected_ids = []
            if self.cmbScope.SelectedIndex == 1:
                sel = uidoc.Selection.GetElementIds()
                if not sel or len(sel) == 0:
                    self.txtStatus.Text = "⚠️ No elements selected. Please select elements in Revit first."
                    return
                selected_ids = list(sel)

            cats = self._build_selected_categories()
            if not cats:
                self.txtStatus.Text = u"⚠️ No categories selected. Please check at least one category in the left panel."
                return

            clashes = scan_clashes(
                doc, uidoc.ActiveView,
                categories=cats,
                selected_ids=selected_ids,
                progress_callback=None,
            )

            tol_mm = 0.0
            try:
                tol_mm = float(self.txtTolerance.Text.strip())
            except Exception:
                pass

            if tol_mm > 0:
                clashes = [c for c in clashes if c.OverlapMm > tol_mm]

            self._all_clash_vms = [ClashRowVM(c) for c in clashes]
            self._apply_filter()

            if clashes:
                self.dgClashes.SelectedIndex = 0
                self.txtStatus.Text = "Found {} hard clashes. Double-click row to inspect in 3D.".format(len(clashes))
            else:
                self.txtStatus.Text = "Zero clashes detected! All inspected MEP systems are clear."

        except Exception as ex:
            err_msg = safe_unicode(ex)
            self.txtStatus.Text = u"❌ Clash scan failed: {}".format(err_msg)
            self._show_topmost_dialog(u"Clash scan failed:\n\n{}".format(err_msg), title="Scan Error", dialog_type="ERROR")
        finally:
            self.progressBar.IsIndeterminate = False
            self.progressBar.Visibility = Visibility.Collapsed
            self.btnScan.IsEnabled = True

    # -------------------------------------------------------------------------
    # 2. Focus 3D
    # -------------------------------------------------------------------------

    def _on_grid_double_click(self, sender, e):
        self._on_focus3d_clicked(sender, e)

    def _on_focus3d_clicked(self, sender, e):
        selected = self.dgClashes.SelectedItem
        if not selected or not isinstance(selected, ClashRowVM):
            return
        ClashFocus3DHandler._wndw = self
        ClashFocus3DHandler._clash_item = selected.RawItem
        _EXT_EVENT_FOCUS.Raise()

    def _do_focus_3d(self, doc, uidoc, clash_item):
        """Called by ClashFocus3DHandler on Revit UI thread."""
        success = focus_clash_3d(doc, uidoc, clash_item)
        el1 = clash_item.Element1
        el2 = clash_item.Element2
        if success and el1 and el2:
            cat1 = el1.Category.Name if el1.Category else "Element"
            cat2 = el2.Category.Name if el2.Category else "Element"
            vname = getattr(clash_item, "LastViewName", None) or (uidoc.ActiveView.Name if uidoc and uidoc.ActiveView else "3D")
            self.txtStatus.Text = u"Focus [{}]: {} [{}] vs {} [{}]".format(
                vname, cat1, get_id_value(el1), cat2, get_id_value(el2)
            )
        elif not success:
            self.txtStatus.Text = "Could not open 3D Section Box for this clash."

    # -------------------------------------------------------------------------
    # 3. Recheck
    # -------------------------------------------------------------------------

    def _on_recheck_clicked(self, sender, e):
        selected = self.dgClashes.SelectedItem
        if not selected or not isinstance(selected, ClashRowVM):
            self.txtStatus.Text = "⚠️ Please select a clash row from the table to recheck."
            return
        self.txtStatus.Text = "Rechecking..."
        ClashRecheckHandler._wndw = self
        _EXT_EVENT_RECHECK.Raise()

    def _do_recheck(self, doc, uidoc):
        """Called by ClashRecheckHandler on Revit UI thread."""
        selected = self.dgClashes.SelectedItem
        if not selected or not isinstance(selected, ClashRowVM):
            return

        tol_mm = 0.0
        try:
            tol_mm = float(self.txtTolerance.Text.strip())
        except Exception:
            pass

        still_clashing, overlap_mm, _ = recheck_single_clash(
            doc, selected.RawItem, tolerance_mm=tol_mm
        )

        if not still_clashing:
            selected.mark_resolved()
            self._apply_filter()
            self.txtStatus.Text = u"✅ Resolved! Clash moved to Resolved tab."
            self._auto_advance(doc, uidoc)
        else:
            selected.update_overlap(overlap_mm)
            self._apply_filter()
            self.txtStatus.Text = u"⚠️ Still clashing: {:.0f} mm overlap.".format(overlap_mm)

    def _auto_advance(self, doc, uidoc):
        """Selects next active clash in view and focuses it. Already inside ExternalEvent context."""
        total = self.dgClashes.Items.Count
        if total == 0:
            if self._current_tab == "ACTIVE":
                self.txtStatus.Text = "🎉 All active clashes resolved! Check Resolved tab to review."
            else:
                self.txtStatus.Text = "🎉 All displayed clashes have been resolved! Excellent work!"
            return

        cur_idx = min(self.dgClashes.SelectedIndex, total - 1)
        if cur_idx < 0:
            cur_idx = 0

        for i in list(range(cur_idx, total)) + list(range(0, cur_idx)):
            candidate = self.dgClashes.Items[i]
            if isinstance(candidate, ClashRowVM) and not candidate.IsResolved:
                self.dgClashes.SelectedIndex = i
                self.dgClashes.ScrollIntoView(candidate)
                focus_clash_3d(doc, uidoc, candidate.RawItem)
                return

        candidate = self.dgClashes.Items[cur_idx]
        if isinstance(candidate, ClashRowVM):
            self.dgClashes.SelectedIndex = cur_idx
            self.dgClashes.ScrollIntoView(candidate)
            focus_clash_3d(doc, uidoc, candidate.RawItem)

    # -------------------------------------------------------------------------
    # 4. Prev / Next Navigation
    # -------------------------------------------------------------------------

    def _on_prev_clash(self, sender, e):
        if self.dgClashes.Items.Count == 0:
            return
        idx = max(0, self.dgClashes.SelectedIndex - 1)
        self.dgClashes.SelectedIndex = idx
        item = self.dgClashes.SelectedItem
        if item:
            self.dgClashes.ScrollIntoView(item)
        self._on_focus3d_clicked(sender, e)

    def _on_next_clash(self, sender, e):
        if self.dgClashes.Items.Count == 0:
            return
        idx = min(self.dgClashes.Items.Count - 1, self.dgClashes.SelectedIndex + 1)
        self.dgClashes.SelectedIndex = idx
        item = self.dgClashes.SelectedItem
        if item:
            self.dgClashes.ScrollIntoView(item)
        self._on_focus3d_clicked(sender, e)

    # -------------------------------------------------------------------------
    # 5. Filter, Search & Tabs
    # -------------------------------------------------------------------------

    def _switch_tab(self, tab_mode):
        self._current_tab = tab_mode
        self._apply_filter()
        if self.dgClashes.Items.Count > 0:
            self.dgClashes.SelectedIndex = 0
            self.dgClashes.ScrollIntoView(self.dgClashes.SelectedItem)

    def _on_filter_changed(self, sender, e):
        self._apply_filter()

    def _apply_filter(self):
        query = ""
        try:
            query = self.txtSearch.Text.strip().lower()
        except Exception:
            pass

        self._displayed_vms.Clear()
        total = len(self._all_clash_vms)
        active_count = sum(1 for vm in self._all_clash_vms if not vm.IsResolved)
        resolved_count = total - active_count

        for vm in self._all_clash_vms:
            if self._current_tab == "ACTIVE" and vm.IsResolved:
                continue
            if self._current_tab == "RESOLVED" and not vm.IsResolved:
                continue
            if query:
                haystack = (vm.Elem1Info + " " + vm.Elem2Info + " " + vm.ModelSource).lower()
                if query not in haystack:
                    continue
            self._displayed_vms.Add(vm)

        # Update Tab Header Counts & Colors (Modern Segmented Pill style)
        try:
            self.btnTabActive.Content = u"🔴 Active ({})".format(active_count)
            self.btnTabResolved.Content = u"✅ Resolved ({})".format(resolved_count)
            self.btnTabAll.Content = u"All ({})".format(total)

            transparent_brush = SolidColorBrush(Color.FromArgb(0, 0, 0, 0))
            white_brush = _hex_brush("#FFFFFF")
            text_muted = _hex_brush("#64748B")

            if self._current_tab == "ACTIVE":
                self.btnTabActive.Background = white_brush
                self.btnTabActive.Foreground = _hex_brush("#DC2626")
                self.btnTabActive.FontWeight = FontWeights.Bold

                self.btnTabResolved.Background = transparent_brush
                self.btnTabResolved.Foreground = text_muted
                self.btnTabResolved.FontWeight = FontWeights.SemiBold

                self.btnTabAll.Background = transparent_brush
                self.btnTabAll.Foreground = text_muted
                self.btnTabAll.FontWeight = FontWeights.SemiBold

            elif self._current_tab == "RESOLVED":
                self.btnTabActive.Background = transparent_brush
                self.btnTabActive.Foreground = text_muted
                self.btnTabActive.FontWeight = FontWeights.SemiBold

                self.btnTabResolved.Background = white_brush
                self.btnTabResolved.Foreground = _hex_brush("#059669")
                self.btnTabResolved.FontWeight = FontWeights.Bold

                self.btnTabAll.Background = transparent_brush
                self.btnTabAll.Foreground = text_muted
                self.btnTabAll.FontWeight = FontWeights.SemiBold

            else:  # "ALL"
                self.btnTabActive.Background = transparent_brush
                self.btnTabActive.Foreground = text_muted
                self.btnTabActive.FontWeight = FontWeights.SemiBold

                self.btnTabResolved.Background = transparent_brush
                self.btnTabResolved.Foreground = text_muted
                self.btnTabResolved.FontWeight = FontWeights.SemiBold

                self.btnTabAll.Background = white_brush
                self.btnTabAll.Foreground = _hex_brush("#2563EB")
                self.btnTabAll.FontWeight = FontWeights.Bold
        except Exception:
            pass

        # Toggle Empty State Notice
        try:
            if hasattr(self, 'borderEmptyState'):
                if len(self._displayed_vms) == 0:
                    self.borderEmptyState.Visibility = Visibility.Visible
                    if self._current_tab == "ACTIVE":
                        self.txtEmptyTitle.Text = "No active clashes in this view"
                        self.txtEmptySubtitle.Text = "All clashes may be resolved or none detected yet."
                    elif self._current_tab == "RESOLVED":
                        self.txtEmptyTitle.Text = "No resolved clashes yet"
                        self.txtEmptySubtitle.Text = "Inspect active clashes and press Recheck (F5) to resolve."
                    else:
                        self.txtEmptyTitle.Text = "No clashes displayed"
                        self.txtEmptySubtitle.Text = "Click 'Scan Clashes' above or 'Import' from Excel to begin."
                else:
                    self.borderEmptyState.Visibility = Visibility.Collapsed
        except Exception:
            pass

        # Update Mini Dashboard (Resolution Progress & Big Metrics)
        try:
            pct = int(round((float(resolved_count) / total * 100.0))) if total > 0 else 0
            if hasattr(self, 'txtResolutionPercent'):
                self.txtResolutionPercent.Text = "{}%".format(pct)
            if hasattr(self, 'progResolution'):
                self.progResolution.Value = pct
            if hasattr(self, 'txtActiveMetric'):
                self.txtActiveMetric.Text = str(active_count)
            if hasattr(self, 'txtResolvedMetric'):
                self.txtResolvedMetric.Text = str(resolved_count)
            if hasattr(self, 'txtTotalMetric'):
                self.txtTotalMetric.Text = "Total: {} clashes inspected".format(total)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 6. Import & Export Excel
    # -------------------------------------------------------------------------

    def _on_import_excel(self, sender, e):
        was_topmost = self.Topmost
        try:
            self.Topmost = False
            file_path = forms.pick_file(
                file_ext='xlsx',
                title='Select Clash Report Excel File'
            )
        finally:
            self.Topmost = was_topmost

        if not file_path or not os.path.exists(file_path):
            return

        self.txtStatus.Text = "Importing clashes from Excel..."
        try:
            clashes = import_clash_report(self.doc, file_path)
            if not clashes:
                self.txtStatus.Text = "⚠️ No matching clash items found in selected Excel file."
                self._show_topmost_dialog(
                    "No valid clash records found in Excel file that match elements in current Revit model.\n\n"
                    "Make sure the report was exported from this project or linked models are loaded.",
                    title="Import Result",
                    dialog_type="WARNING"
                )
                return

            self._all_clash_vms = [ClashRowVM(c) for c in clashes]
            self._apply_filter()
            if self.dgClashes.Items.Count > 0:
                self.dgClashes.SelectedIndex = 0
                self.dgClashes.ScrollIntoView(self.dgClashes.SelectedItem)

            self.txtStatus.Text = u"✅ Loaded {} clash items from Excel.".format(len(clashes))
            self._show_topmost_dialog(
                u"Successfully loaded {} clash records from:\n\n{}\n\n"
                "You can now inspect 3D boxes and recheck them!".format(len(clashes), file_path),
                title="Import Complete",
                dialog_type="SUCCESS"
            )
        except Exception as ex:
            err_msg = safe_unicode(ex)
            self.txtStatus.Text = u"❌ Import failed: {}".format(err_msg)
            self._show_topmost_dialog(u"Failed to import Excel file:\n\n{}".format(err_msg), title="Import Error", dialog_type="ERROR")

    def _on_export_excel(self, sender, e):
        if not self._all_clash_vms:
            self.txtStatus.Text = "⚠️ No clash data available to export."
            return

        was_topmost = self.Topmost
        try:
            self.Topmost = False
            dest_path = forms.save_file(
                file_ext='xlsx',
                default_name='MEPANANA_Clash_Report.xlsx',
                title='Save Clash Report'
            )
        finally:
            self.Topmost = was_topmost

        if not dest_path:
            return

        try:
            clashes = [vm.RawItem for vm in self._all_clash_vms]
            ok = export_clash_report(clashes, dest_path)
            if ok:
                self.txtStatus.Text = u"✅ Exported to: {}".format(dest_path)
                self._show_topmost_dialog(u"Clash report exported successfully to:\n\n{}".format(dest_path), title="Export Complete", dialog_type="SUCCESS")
            else:
                self.txtStatus.Text = "❌ Failed to generate Excel file."
                self._show_topmost_dialog("Failed to generate Excel file.", title="Export Error", dialog_type="ERROR")
        except Exception as ex:
            err_msg = safe_unicode(ex)
            self.txtStatus.Text = u"❌ Export error: {}".format(err_msg)
            self._show_topmost_dialog(u"Excel export failed:\n\n{}".format(err_msg), title="Export Error", dialog_type="ERROR")


# -- Tool Entry Point ---------------------------------------------------------

if __name__ == "__main__":
    doc = get_doc()
    uidoc = get_uidoc()

    if not doc:
        from py.ui import show_error
        show_error("Please open a Revit project first.", title="No Document", exitscript=True)

    existing = getattr(CheckClashWindow, "_current_wndw", None)
    if existing:
        try:
            existing.Activate()
            sys.exit(0)
        except Exception:
            CheckClashWindow._current_wndw = None

    win = CheckClashWindow(doc, uidoc)
    CheckClashWindow._current_wndw = win
    ClashScanHandler._wndw = win
    ClashFocus3DHandler._wndw = win
    ClashRecheckHandler._wndw = win
    win.show(modal=False)