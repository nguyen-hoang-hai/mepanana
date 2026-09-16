# -*- coding: utf-8 -*-
"""
Check Clash - Interactive 3D Clash Inspector & Resolution Navigator
Features:
- Instant 3D Section Box auto-focus on clash zone.
- Live single-clash recheck (F5) with automatic status transition.
- Comprehensive Document Model Categories (VV) with discipline presets.
- Excel Clash Report Import and Export.
- Seamless keyboard navigation (F2: Prev, F3: Next, F4: Focus, F5: Recheck, ESC: Close).
- Clean modal dialog architecture: runs natively on Revit UI thread without engine locks.

Part of mepanana.extension.
Author: Hai Nguyen
"""
import os
import sys
import traceback

# ── Dynamic Lib Resolution (Mandatory per Playbook) ──────────────────────────
lib_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)


def _fatal_alert(err_str):
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("Check Clash Error", err_str)
    except Exception:
        pass


# ── 6-Line Security Gatekeeper Boilerplate ───────────────────────────────────
from py.auth import require_auth, update_ribbon_state, is_authenticated
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()


# ── Root Execution Wrapper ───────────────────────────────────────────────────
try:
    import clr
    clr.AddReference("System")
    clr.AddReference("PresentationCore")
    clr.AddReference("PresentationFramework")
    clr.AddReference("WindowsBase")
    clr.AddReference("RevitAPI")
    clr.AddReference("RevitAPIUI")

    import System
    from System import Uri, UriKind, Action
    from System.Windows import Visibility, ResourceDictionary, FontWeights
    from System.Windows.Interop import WindowInteropHelper
    from System.Windows.Threading import Dispatcher, DispatcherFrame, DispatcherPriority
    from System.Windows.Media import SolidColorBrush, Color, VisualTreeHelper
    from System.Windows.Controls import DataGridRow
    from System.Windows.Controls.Primitives import DataGridColumnHeader
    from System.Windows.Input import Key
    from System.Collections.ObjectModel import ObservableCollection

    from Autodesk.Revit.DB import BuiltInCategory, CategoryType, ElementId

    from pyrevit import forms
    from py.core import get_doc, get_uidoc, get_id_value, safe_unicode
    from py.ui import setup_window, do_events
    from py.clash_analysis_engine import (
        scan_clashes, recheck_single_clash, focus_clash_3d, focus_element_3d, check_element_exists,
        export_clash_report, import_clash_report
    )

    # ── Color Helpers ────────────────────────────────────────────────────────
    def _hex_brush(hex_str):
        h = hex_str.lstrip('#')
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return SolidColorBrush(Color.FromRgb(r, g, b))

    # ── Plain Python ViewModels (IronPython 2.7 Safe) ─────────────────────────
    class ClashRowVM(object):
        """Plain Python view-model for WPF DataGrid binding. IronPython 2.7 safe."""

        def __init__(self, raw_item):
            self.RawItem = raw_item

            el1 = getattr(raw_item, "Element1", None)
            el2 = getattr(raw_item, "Element2", None)
            cat1 = (el1.Category.Name if el1 and el1.Category else getattr(raw_item, "Elem1CatName", "Element"))
            cat2 = (el2.Category.Name if el2 and el2.Category else getattr(raw_item, "Elem2CatName", "Element"))
            id1 = getattr(raw_item, "Elem1IdInt", None) or (get_id_value(el1) if el1 else 0)
            id2 = getattr(raw_item, "Elem2IdInt", None) or (get_id_value(el2) if el2 else 0)

            self.Elem1Info = u"{} [{}]".format(cat1, id1)
            self.Elem2Info = u"{} [{}]".format(cat2, id2)
            self.ElevDiffDisplay = u"{:.0f} mm".format(getattr(raw_item, "ElevDiffMm", 0.0))
            self.ModelSource = raw_item.LinkName if getattr(raw_item, "IsLink", False) else u"Host Model"

            self._refresh_status()

        def _refresh_status(self):
            resolved = getattr(self.RawItem, "Status", "ACTIVE") == "RESOLVED"
            self.IsResolved = resolved
            if resolved:
                self.StatusDisplay = u"\u2705 Resolved"
                self.StatusColor = "#059669"
                self.StatusBg = "#D1FAE5"
            else:
                self.StatusDisplay = u"\U0001f534 Active"
                self.StatusColor = "#DC2626"
                self.StatusBg = "#FEE2E2"
            self.OverlapDisplay = u"{:.0f} mm".format(getattr(self.RawItem, "OverlapMm", 0.0))

        def mark_resolved(self):
            self.RawItem.Status = "RESOLVED"
            self.RawItem.OverlapMm = 0.0
            self._refresh_status()

        def update_overlap(self, new_overlap_mm):
            self.RawItem.OverlapMm = new_overlap_mm
            self._refresh_status()

    class CategoryItemVM(object):
        """Plain Python view-model for Model Category item matching Revit VV dialog."""

        def __init__(self, cat_id_int, name, discipline, is_checked=False):
            self.CatInt = int(cat_id_int)
            self.Name = name
            self.Discipline = discipline
            self.IsChecked = bool(is_checked)

            # Color coding for discipline pill badge
            if discipline == "Piping":
                self.DiscBg = "#DBEAFE"
                self.DiscColor = "#1E40AF"
            elif discipline == "Mechanical":
                self.DiscBg = "#E0E7FF"
                self.DiscColor = "#3730A3"
            elif discipline == "Electrical":
                self.DiscBg = "#FEF3C7"
                self.DiscColor = "#92400E"
            elif discipline == "Structural":
                self.DiscBg = "#FCE7F3"
                self.DiscColor = "#9D174D"
            elif discipline == "Architectural":
                self.DiscBg = "#D1FAE5"
                self.DiscColor = "#065F46"
            else:
                self.DiscBg = "#F1F5F9"
                self.DiscColor = "#475569"

    def _bip(name):
        try:
            val = getattr(BuiltInCategory, name, None)
            return int(val) if val is not None else None
        except Exception:
            return None

    # ── Category Discipline Sets ─────────────────────────────────────────────
    _MEP_PIPING_BIPS = {b for b in [
        _bip("OST_PipeCurves"),
        _bip("OST_PipeFitting"),
        _bip("OST_PipeAccessory"),
        _bip("OST_FlexPipeCurves"),
        _bip("OST_PipeInsulations"),
        _bip("OST_PlumbingFixtures"),
        _bip("OST_Sprinklers"),
    ] if b is not None}

    _MEP_MECH_BIPS = {b for b in [
        _bip("OST_DuctCurves"),
        _bip("OST_DuctFitting"),
        _bip("OST_DuctAccessory"),
        _bip("OST_DuctTerminal"),
        _bip("OST_FlexDuctCurves"),
        _bip("OST_DuctInsulations"),
        _bip("OST_DuctLinings"),
        _bip("OST_MechanicalEquipment"),
    ] if b is not None}

    _MEP_ELEC_BIPS = {b for b in [
        _bip("OST_CableTray"),
        _bip("OST_CableTrayFitting"),
        _bip("OST_Conduit"),
        _bip("OST_ConduitFitting"),
        _bip("OST_ElectricalEquipment"),
        _bip("OST_ElectricalFixtures"),
        _bip("OST_LightingFixtures"),
        _bip("OST_LightingDevices"),
        _bip("OST_FireAlarmDevices"),
        _bip("OST_DataDevices"),
        _bip("OST_CommunicationDevices"),
        _bip("OST_SecurityDevices"),
    ] if b is not None}

    _STRUCT_BIPS = {b for b in [
        _bip("OST_StructuralFraming"),
        _bip("OST_StructuralColumns"),
        _bip("OST_StructuralFoundation"),
        _bip("OST_Floors"),
        _bip("OST_Walls"),
    ] if b is not None}

    _ARCH_BIPS = {b for b in [
        _bip("OST_Walls"),
        _bip("OST_Floors"),
        _bip("OST_Ceilings"),
        _bip("OST_Roofs"),
        _bip("OST_Doors"),
        _bip("OST_Windows"),
        _bip("OST_Stairs"),
        _bip("OST_Ramps"),
        _bip("OST_Railings"),
        _bip("OST_CurtainWallPanels"),
        _bip("OST_CurtainWallMullions"),
        _bip("OST_Columns"),
        _bip("OST_GenericModel"),
        _bip("OST_SpecialityEquipment"),
        _bip("OST_Casework"),
        _bip("OST_Furniture"),
        _bip("OST_FurnitureSystems"),
    ] if b is not None}

    _DEFAULT_MEP_SET = _MEP_PIPING_BIPS | _MEP_MECH_BIPS | _MEP_ELEC_BIPS

    def _classify_discipline(cat_id_int, name):
        if cat_id_int in _MEP_PIPING_BIPS:
            return "Piping"
        if cat_id_int in _MEP_MECH_BIPS:
            return "Mechanical"
        if cat_id_int in _MEP_ELEC_BIPS:
            return "Electrical"
        if cat_id_int in _STRUCT_BIPS:
            return "Structural"
        if cat_id_int in _ARCH_BIPS:
            return "Architectural"

        nl = name.lower()
        if any(k in nl for k in ["pipe", "plumbing", "sprinkler"]):
            return "Piping"
        if any(k in nl for k in ["duct", "air", "mechanical", "hvac"]):
            return "Mechanical"
        if any(k in nl for k in ["cable", "conduit", "tray", "electric", "lighting", "device", "alarm", "data", "wire"]):
            return "Electrical"
        if any(k in nl for k in ["struct", "framing", "column", "foundation", "rebar"]):
            return "Structural"
        if any(k in nl for k in ["wall", "floor", "ceiling", "roof", "door", "window", "stair", "rail", "ramp", "curtain", "furniture", "panel", "mullion", "casework", "room"]):
            return "Architectural"
        return "General"

    _EXCLUDED_BIPS = {b for b in [
        _bip("OST_Views"),
        _bip("OST_Viewers"),
        _bip("OST_Sheets"),
        _bip("OST_ProjectInformation"),
        _bip("OST_Materials"),
        _bip("OST_Cameras"),
        _bip("OST_ScheduleGraphics"),
        _bip("OST_Schedules"),
        _bip("OST_RvtLinks"),
        _bip("OST_Massing"),
        _bip("OST_Phases"),
    ] if b is not None}

    _EXCLUDED_CAT_NAMES = {
        "views", "view", "sheets", "sheet", "project information",
        "materials", "cameras", "schedule graphics", "schedules",
        "rvt links", "revit links", "analysis results", "sun path",
        "raster images", "import in families", "phasing", "phases"
    }

    def _collect_document_model_categories(doc):
        """
        Extracts all top-level Model categories strictly matching Revit VV Model Categories.
        Completely view-independent and safely shielded against CLR exceptions.
        """
        if not doc:
            return []

        results = []
        try:
            categories = doc.Settings.Categories
        except Exception:
            return []

        for cat in categories:
            try:
                if not cat:
                    continue
                if cat.CategoryType != CategoryType.Model:
                    continue
                if cat.Parent is not None:
                    continue
                if not cat.AllowsBoundParameters:
                    continue
                if hasattr(cat, "IsVisibleInUI") and not cat.IsVisibleInUI:
                    continue
                cid = get_id_value(cat.Id)
                if cid in _EXCLUDED_BIPS:
                    continue
                name = cat.Name
                if not name:
                    continue
                if name.strip().lower() in _EXCLUDED_CAT_NAMES:
                    continue

                disc = _classify_discipline(cid, name)
                results.append((cid, name, disc))
            except Exception:
                pass

        results.sort(key=lambda x: x[1])
        return results

    # ── Main Controller Window ───────────────────────────────────────────────
    class CheckClashWindow(forms.WPFWindow):
        def __init__(self, doc, uidoc):
            xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
            forms.WPFWindow.__init__(self, xaml_path)

            # Apply theme and bind ESC key
            setup_window(self)

            self.doc = doc
            self.uidoc = uidoc

            self._all_clash_vms = []
            self._displayed_vms = ObservableCollection[object]()
            self.dgClashes.ItemsSource = self._displayed_vms
            self._current_tab = "ACTIVE"

            # Wire Action buttons
            self.btnScan.Click += self._on_scan_clicked
            self.btnFocus3D.Click += self._on_focus3d_clicked
            self.btnRecheck.Click += self._on_recheck_clicked
            self.btnPrev.Click += self._on_prev_clash
            self.btnNext.Click += self._on_next_clash
            self.btnImportExcel.Click += self._on_import_excel
            self.btnExportExcel.Click += self._on_export_excel
            self.btnClose.Click += lambda s, e: self.Close()

            # Categories (VV) Tab wiring & initialization
            self._all_cat_vms = []
            self._displayed_cat_vms = ObservableCollection[object]()
            self.dgCategories.ItemsSource = self._displayed_cat_vms

            self.txtCatSearch.TextChanged += self._on_cat_filter_changed
            self.cmbCatDiscipline.SelectionChanged += self._on_cat_filter_changed

            self.btnPresetMep.Click += self._on_preset_mep
            self.btnPresetAll.Click += self._on_preset_all
            self.btnPresetNone.Click += self._on_preset_none
            self.btnPresetStruct.Click += self._on_preset_struct
            self.btnPresetArch.Click += self._on_preset_arch

            self.dgCategories.PreviewMouseLeftButtonDown += self._on_cat_grid_click
            self.dgCategories.MouseDoubleClick += lambda s, e: self._toggle_selected_category_row()

            try:
                self._init_categories()
                self._load_category_prefs()
                self._apply_cat_filter()
                self._update_cat_summary()
            except Exception:
                pass

            # Tab Switching
            self.btnTabActive.Click += lambda s, e: self._switch_tab("ACTIVE")
            self.btnTabResolved.Click += lambda s, e: self._switch_tab("RESOLVED")
            self.btnTabAll.Click += lambda s, e: self._switch_tab("ALL")

            self.dgClashes.MouseDoubleClick += self._on_grid_double_click
            self.txtSearch.TextChanged += self._on_filter_changed

            self.PreviewKeyDown += self._on_key_down

            # Initialize view state & pill styles
            self._apply_filter()

        # ---------------------------------------------------------------------
        # Categories (VV) Tab Handlers
        # ---------------------------------------------------------------------
        def _init_categories(self):
            self._all_cat_vms = []
            try:
                raw_cats = _collect_document_model_categories(self.doc)
                for cid, name, disc in raw_cats:
                    vm = CategoryItemVM(cid, name, disc, is_checked=False)
                    self._all_cat_vms.append(vm)
            except Exception:
                pass

        def _on_cat_filter_changed(self, sender, e):
            self._apply_cat_filter()

        def _apply_cat_filter(self):
            q = ""
            try:
                q = self.txtCatSearch.Text.strip().lower()
            except Exception:
                pass

            disc_filter = "All"
            try:
                if self.cmbCatDiscipline.SelectedItem:
                    disc_filter = str(self.cmbCatDiscipline.SelectedItem.Content).strip()
            except Exception:
                pass

            self._displayed_cat_vms.Clear()
            for vm in self._all_cat_vms:
                # Discipline filter check
                if disc_filter in ("All", "All Disciplines", ""):
                    pass
                elif disc_filter == "MEP Only":
                    if vm.Discipline not in ("Piping", "Mechanical", "Electrical"):
                        continue
                elif disc_filter in ("Structure", "Structural"):
                    if vm.Discipline != "Structural":
                        continue
                elif disc_filter in ("Architecture", "Architectural"):
                    if vm.Discipline != "Architectural":
                        continue
                elif vm.Discipline.lower() != disc_filter.lower():
                    continue

                if q and q not in vm.Name.lower():
                    continue
                self._displayed_cat_vms.Add(vm)

        def _update_cat_summary(self):
            n_sel = sum(1 for vm in self._all_cat_vms if vm.IsChecked)
            n_tot = len(self._all_cat_vms)
            self.txtCatSummary.Text = "{} of {} categories selected".format(n_sel, n_tot)
            if hasattr(self, 'tabCategories'):
                self.tabCategories.Header = u"\U0001f4cb Categories ({})".format(n_sel)

        def _toggle_selected_category_row(self):
            item = self.dgCategories.SelectedItem
            if item and isinstance(item, CategoryItemVM):
                item.IsChecked = not item.IsChecked
                self.dgCategories.Items.Refresh()
                self._update_cat_summary()
                self._save_category_prefs()

        def _on_cat_grid_click(self, sender, e):
            dep = e.OriginalSource
            from System.Windows.Controls import DataGridCell, DataGridRow
            while dep is not None:
                if isinstance(dep, DataGridCell):
                    col = dep.Column
                    # Toggle when clicking on the Check checkbox column (index 0)
                    if col and getattr(col, "DisplayIndex", 1) == 0:
                        row = DataGridRow.GetRowContainingElement(dep)
                        item = row.Item if row else self.dgCategories.SelectedItem
                        if item and isinstance(item, CategoryItemVM):
                            item.IsChecked = not item.IsChecked
                            self.dgCategories.Items.Refresh()
                            self._update_cat_summary()
                            self._save_category_prefs()
                            e.Handled = True
                        return
                dep = VisualTreeHelper.GetParent(dep)

        def _on_preset_mep(self, sender, e):
            for vm in self._all_cat_vms:
                vm.IsChecked = (vm.Discipline in ("Piping", "Mechanical", "Electrical") or vm.CatInt in _DEFAULT_MEP_SET)
            self.dgCategories.Items.Refresh()
            self._update_cat_summary()
            self._save_category_prefs()

        def _on_preset_all(self, sender, e):
            for vm in self._all_cat_vms:
                vm.IsChecked = True
            self.dgCategories.Items.Refresh()
            self._update_cat_summary()
            self._save_category_prefs()

        def _on_preset_none(self, sender, e):
            for vm in self._all_cat_vms:
                vm.IsChecked = False
            self.dgCategories.Items.Refresh()
            self._update_cat_summary()
            self._save_category_prefs()

        def _on_preset_struct(self, sender, e):
            for vm in self._all_cat_vms:
                if vm.Discipline == "Structural" or vm.CatInt in _STRUCT_BIPS:
                    vm.IsChecked = True
            self.dgCategories.Items.Refresh()
            self._update_cat_summary()
            self._save_category_prefs()

        def _on_preset_arch(self, sender, e):
            for vm in self._all_cat_vms:
                if vm.Discipline == "Architectural" or vm.CatInt in _ARCH_BIPS:
                    vm.IsChecked = True
            self.dgCategories.Items.Refresh()
            self._update_cat_summary()
            self._save_category_prefs()

        def _get_active_category_ids(self):
            selected = [vm.CatInt for vm in self._all_cat_vms if vm.IsChecked]
            if not selected:
                mep_ids = [vm.CatInt for vm in self._all_cat_vms if vm.Discipline in ("Piping", "Mechanical", "Electrical") or vm.CatInt in _DEFAULT_MEP_SET]
                return mep_ids if mep_ids else [vm.CatInt for vm in self._all_cat_vms]
            return selected

        def _save_category_prefs(self):
            try:
                from pyrevit import script as _script
                cfg = _script.get_config("MEPANANA_CheckClash")
                cfg.selected_category_ids = [vm.CatInt for vm in self._all_cat_vms if vm.IsChecked]
                _script.save_config()
            except Exception:
                pass

        def _load_category_prefs(self):
            try:
                from pyrevit import script as _script
                cfg = _script.get_config("MEPANANA_CheckClash")
                saved_ids = getattr(cfg, 'selected_category_ids', None)
                if saved_ids and isinstance(saved_ids, (list, set)) and len(saved_ids) > 0:
                    saved_set = set(int(x) for x in saved_ids)
                    matched = False
                    for vm in self._all_cat_vms:
                        if vm.CatInt in saved_set:
                            vm.IsChecked = True
                            matched = True
                        else:
                            vm.IsChecked = False
                    if matched:
                        return
            except Exception:
                pass

            # Default to MEP categories
            for vm in self._all_cat_vms:
                vm.IsChecked = (vm.Discipline in ("Piping", "Mechanical", "Electrical") or vm.CatInt in _DEFAULT_MEP_SET)

            # If no MEP categories in current model, select all available model categories
            if not any(vm.IsChecked for vm in self._all_cat_vms):
                for vm in self._all_cat_vms:
                    vm.IsChecked = True

        # ---------------------------------------------------------------------
        # Keyboard Shortcuts
        # ---------------------------------------------------------------------
        def _on_key_down(self, sender, e):
            if e.Key == Key.F2:
                self._on_prev_clash(sender, e)
                e.Handled = True
            elif e.Key == Key.F3:
                self._on_next_clash(sender, e)
                e.Handled = True
            elif e.Key == Key.F4:
                self._on_focus3d_clicked(sender, e)
                e.Handled = True
            elif e.Key == Key.F5:
                self._on_recheck_clicked(sender, e)
                e.Handled = True
            elif e.Key == Key.Space and (self.dgCategories.IsKeyboardFocusWithin or self.dgCategories.IsFocused):
                self._toggle_selected_category_row()
                e.Handled = True
            elif e.Key == Key.Escape:
                self.Close()
                e.Handled = True

        def _show_dialog(self, message, title="Notification", dialog_type="INFO"):
            """Displays branded MEPANANA alert dialog properly parented to this window."""
            try:
                from py.ui import _show_custom_dialog
                is_topmost = bool(getattr(self, "Topmost", False))
                return _show_custom_dialog(message, title=title, dialog_type=dialog_type, owner=self, topmost=is_topmost)
            except Exception:
                return forms.alert(message, title=title, warn_icon=(dialog_type == "ERROR"))

        # ---------------------------------------------------------------------
        # 1. Scan Clashes
        # ---------------------------------------------------------------------
        def _on_scan_clicked(self, sender, e):
            self.btnScan.IsEnabled = False
            self.progressBar.Visibility = Visibility.Visible
            self.progressBar.Value = 0
            self.progressBar.IsIndeterminate = False
            self.txtStatus.Text = "Starting clash scan..."
            do_events()

            try:
                self._do_scan(self.doc, self.uidoc)
            finally:
                self.progressBar.IsIndeterminate = False
                self.progressBar.Visibility = Visibility.Collapsed
                self.btnScan.IsEnabled = True

        def _do_scan(self, doc, uidoc):
            try:
                selected_ids = []
                if self.cmbScope.SelectedIndex == 1:
                    sel = uidoc.Selection.GetElementIds()
                    if not sel or len(sel) == 0:
                        self.txtStatus.Text = "\u26a0\ufe0f No elements selected. Please select elements in Revit first."
                        self._show_dialog("No elements selected. Please select elements in Revit or switch to 'Active View'.", title="Empty Selection", dialog_type="WARNING")
                        return
                    selected_ids = list(sel)

                cats = self._get_active_category_ids()
                if not cats:
                    self.txtStatus.Text = u"\u26a0\ufe0f No categories selected. Please go to 'Categories' tab and select at least one."
                    self._show_dialog(
                        u"No categories selected for clash check!\n\n"
                        u"Please click the '\U0001f4cb Categories' tab and check the categories you want to inspect.",
                        title="No Categories Selected",
                        dialog_type="WARNING"
                    )
                    return

                def update_prog(pct, msg):
                    try:
                        self.progressBar.Value = pct
                        self.txtStatus.Text = msg
                        do_events()
                    except Exception:
                        pass

                check_same = bool(self.chkIncludeHost.IsChecked) if hasattr(self, 'chkIncludeHost') else True

                clashes = scan_clashes(
                    doc, uidoc.ActiveView,
                    categories=cats,
                    selected_ids=selected_ids,
                    check_same_model=check_same,
                    progress_callback=update_prog,
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

                # Automatically switch to Inspector tab to review results
                if hasattr(self, 'tabMain'):
                    self.tabMain.SelectedIndex = 0

                if clashes:
                    self.dgClashes.SelectedIndex = 0
                    mode_str = "" if check_same else " (Host vs Link only)"
                    self.txtStatus.Text = "Found {} hard clashes{}. Double-click row to inspect in 3D.".format(len(clashes), mode_str)
                else:
                    if not check_same:
                        msg = "Zero hard clashes detected between Host and Linked models in active view!"
                    else:
                        msg = "Zero hard clashes detected in active view! Everything is clear."
                    self.txtStatus.Text = msg
                    self._show_dialog(msg, title="No Clashes", dialog_type="INFO")

            except Exception as ex:
                err_msg = safe_unicode(ex)
                self.txtStatus.Text = u"\u274c Clash scan failed: {}".format(err_msg)
                self._show_dialog(u"Clash scan failed:\n\n{}".format(err_msg), title="Scan Error", dialog_type="ERROR")

        # ---------------------------------------------------------------------
        # 2. Focus 3D
        # ---------------------------------------------------------------------
        def _on_grid_double_click(self, sender, e):
            # Ignore double-clicks originating from column headers or scrollbars
            try:
                dep = e.OriginalSource
                while dep is not None:
                    if isinstance(dep, DataGridColumnHeader):
                        return
                    dep = VisualTreeHelper.GetParent(dep)
            except Exception:
                pass
            self._on_focus3d_clicked(sender, e)

        def _on_focus3d_clicked(self, sender, e):
            selected = self.dgClashes.SelectedItem
            if not selected or not isinstance(selected, ClashRowVM):
                return
            self._do_focus_3d(self.doc, self.uidoc, selected.RawItem, row_vm=selected)

        def _do_focus_3d(self, doc, uidoc, clash_item, row_vm=None):
            is_resolved = False
            if row_vm:
                is_resolved = bool(row_vm.IsResolved)
            elif getattr(clash_item, "Status", "ACTIVE") == "RESOLVED":
                is_resolved = True

            id1 = getattr(clash_item, "Elem1IdInt", None) or get_id_value(getattr(clash_item, "Element1", None))
            id2 = getattr(clash_item, "Elem2IdInt", None) or get_id_value(getattr(clash_item, "Element2", None))
            cat1 = getattr(clash_item, "Elem1CatName", "Element")
            cat2 = getattr(clash_item, "Elem2CatName", "Element")

            exists1, live_el1, tf1 = check_element_exists(
                doc, getattr(clash_item, "Element1", None),
                elem_id_int=id1,
                is_link=getattr(clash_item, "IsLink1", False),
                link_name=getattr(clash_item, "LinkName", "") if getattr(clash_item, "IsLink1", False) else ""
            )
            exists2, live_el2, tf2 = check_element_exists(
                doc, getattr(clash_item, "Element2", None),
                elem_id_int=id2,
                is_link=getattr(clash_item, "IsLink2", False),
                link_name=getattr(clash_item, "LinkName", "") if getattr(clash_item, "IsLink2", False) else ""
            )

            if exists1 and live_el1:
                clash_item.Element1 = live_el1
            if exists2 and live_el2:
                clash_item.Element2 = live_el2

            # ── Case 1: Neither element exists in model ───────────────────────
            if not exists1 and not exists2:
                if row_vm:
                    row_vm.mark_resolved()
                    row_vm.OverlapDisplay = "0 mm (Deleted)"
                    self._apply_filter()
                msg = (
                    "Elements not found in model:\n\n"
                    "Both elements in this clash have been deleted from the model:\n"
                    "\u2022 {} [{}]\n"
                    "\u2022 {} [{}]\n\n"
                    "This clash has been automatically marked as Resolved."
                ).format(cat1, id1, cat2, id2)
                self.txtStatus.Text = "\u26a0\ufe0f Both elements ({} [{}] & {} [{}]) were deleted from the model.".format(
                    cat1, id1, cat2, id2
                )
                self._show_dialog(msg, title="Elements Deleted", dialog_type="INFO")
                return

            # ── Case 2: Exactly one element survives (other was deleted) ──────
            if exists1 and not exists2:
                surviving_el = live_el1
                surv_is_link = getattr(clash_item, "IsLink1", False)
                surv_tf = tf1
                surv_info = "{} [{}]".format(cat1, id1)
                del_info = "{} [{}]".format(cat2, id2)

                success, vname = focus_element_3d(doc, uidoc, surviving_el, padding_mm=1000, transform=surv_tf, is_link=surv_is_link)
                if row_vm:
                    row_vm.mark_resolved()
                    row_vm.OverlapDisplay = "0 mm (1 Deleted)"
                    self._apply_filter()
                self.txtStatus.Text = "Focus [{}]: {} exists ({} deleted). Clash resolved.".format(
                    vname or "3D", surv_info, del_info
                )
                try:
                    uidoc.RefreshActiveView()
                except Exception:
                    pass
                return

            if exists2 and not exists1:
                surviving_el = live_el2
                surv_is_link = getattr(clash_item, "IsLink2", False)
                surv_tf = tf2
                surv_info = "{} [{}]".format(cat2, id2)
                del_info = "{} [{}]".format(cat1, id1)

                success, vname = focus_element_3d(doc, uidoc, surviving_el, padding_mm=1000, transform=surv_tf, is_link=surv_is_link)
                if row_vm:
                    row_vm.mark_resolved()
                    row_vm.OverlapDisplay = "0 mm (1 Deleted)"
                    self._apply_filter()
                self.txtStatus.Text = "Focus [{}]: {} exists ({} deleted). Clash resolved.".format(
                    vname or "3D", surv_info, del_info
                )
                try:
                    uidoc.RefreshActiveView()
                except Exception:
                    pass
                return

            # ── Case 3: Both elements exist in model ──────────────────────────
            success = focus_clash_3d(doc, uidoc, clash_item)
            vname = getattr(clash_item, "LastViewName", None) or (uidoc.ActiveView.Name if uidoc and uidoc.ActiveView else "3D")

            try:
                uidoc.RefreshActiveView()
            except Exception:
                pass

            # If clash was RESOLVED (recheck if recent edits reintroduced clash):
            if is_resolved:
                tol_mm = 0.0
                try:
                    tol_mm = float(self.txtTolerance.Text.strip())
                except Exception:
                    pass

                still_clashing, overlap_mm, _ = recheck_single_clash(doc, clash_item, tolerance_mm=tol_mm)
                if still_clashing:
                    if row_vm:
                        row_vm.update_overlap(overlap_mm)
                        row_vm.RawItem.Status = "ACTIVE"
                        row_vm._refresh_status()
                        self._apply_filter()
                    self.txtStatus.Text = "\u26a0\ufe0f Clash reappeared: {:.0f} mm overlap! Status changed back to ACTIVE.".format(overlap_mm)
                    warn_msg = (
                        "\u26a0\ufe0f Warning: Following model modifications, these 2 elements are CLASHING AGAIN!\n\n"
                        "\u2022 {} [{}] \u26a1 {} [{}]\n"
                        "\u2022 Overlap: {:.0f} mm\n\n"
                        "Clash status has been automatically reverted to 'Active' for further coordination."
                    ).format(cat1, id1, cat2, id2, overlap_mm)
                    self._show_dialog(warn_msg, title="Clash Reappeared", dialog_type="WARNING")
                else:
                    if row_vm:
                        row_vm.mark_resolved()
                        self._apply_filter()
                    self.txtStatus.Text = "Focus [{}]: {} [{}] vs {} [{}] - \u2705 Rechecked: No clash detected.".format(
                        vname, cat1, id1, cat2, id2
                    )
            else:
                if success:
                    self.txtStatus.Text = "Focus [{}]: {} [{}] vs {} [{}]".format(
                        vname, cat1, id1, cat2, id2
                    )
                elif not success:
                    self.txtStatus.Text = "Could not open 3D Section Box for this clash."

        # ---------------------------------------------------------------------
        # 3. Recheck Single Clash
        # ---------------------------------------------------------------------
        def _on_recheck_clicked(self, sender, e):
            selected = self.dgClashes.SelectedItem
            if not selected or not isinstance(selected, ClashRowVM):
                self.txtStatus.Text = "\u26a0\ufe0f Please select a clash row from the table to recheck."
                return
            self.txtStatus.Text = "Rechecking..."
            do_events()
            self._do_recheck(self.doc, self.uidoc)

        def _do_recheck(self, doc, uidoc):
            selected = self.dgClashes.SelectedItem
            if not selected or not isinstance(selected, ClashRowVM):
                return

            tol_mm = 0.0
            try:
                tol_mm = float(self.txtTolerance.Text.strip())
            except Exception:
                pass

            # Check existence first
            clash_item = selected.RawItem
            id1 = getattr(clash_item, "Elem1IdInt", None) or get_id_value(getattr(clash_item, "Element1", None))
            id2 = getattr(clash_item, "Elem2IdInt", None) or get_id_value(getattr(clash_item, "Element2", None))
            cat1 = getattr(clash_item, "Elem1CatName", "Element")
            cat2 = getattr(clash_item, "Elem2CatName", "Element")

            exists1, live_el1, _ = check_element_exists(
                doc, getattr(clash_item, "Element1", None),
                elem_id_int=id1,
                is_link=getattr(clash_item, "IsLink1", False),
                link_name=getattr(clash_item, "LinkName", "") if getattr(clash_item, "IsLink1", False) else ""
            )
            exists2, live_el2, _ = check_element_exists(
                doc, getattr(clash_item, "Element2", None),
                elem_id_int=id2,
                is_link=getattr(clash_item, "IsLink2", False),
                link_name=getattr(clash_item, "LinkName", "") if getattr(clash_item, "IsLink2", False) else ""
            )

            if not exists1 and not exists2:
                selected.mark_resolved()
                selected.OverlapDisplay = "0 mm (Deleted)"
                self._apply_filter()
                self.txtStatus.Text = "\u2705 Both elements deleted from model. Marked as Resolved."
                self._auto_advance(doc, uidoc)
                return

            if exists1 != exists2:
                selected.mark_resolved()
                selected.OverlapDisplay = "0 mm (1 Deleted)"
                self._apply_filter()
                surv_info = "{} [{}]".format(cat1, id1) if exists1 else "{} [{}]".format(cat2, id2)
                self.txtStatus.Text = "\u2705 Other element was deleted ({} still exists). Marked as Resolved.".format(surv_info)
                self._auto_advance(doc, uidoc)
                return

            if exists1 and live_el1:
                clash_item.Element1 = live_el1
            if exists2 and live_el2:
                clash_item.Element2 = live_el2

            still_clashing, overlap_mm, _ = recheck_single_clash(
                doc, selected.RawItem, tolerance_mm=tol_mm
            )

            if not still_clashing:
                selected.mark_resolved()
                self._apply_filter()
                self.txtStatus.Text = u"\u2705 Resolved! Clash moved to Resolved tab."
                self._auto_advance(doc, uidoc)
            else:
                selected.update_overlap(overlap_mm)
                self._apply_filter()
                self.txtStatus.Text = u"\u26a0\ufe0f Still clashing: {:.0f} mm overlap.".format(overlap_mm)

        def _auto_advance(self, doc, uidoc):
            total = self.dgClashes.Items.Count
            if total == 0:
                if self._current_tab == "ACTIVE":
                    self.txtStatus.Text = "\U0001f389 All active clashes resolved! Check Resolved tab to review."
                else:
                    self.txtStatus.Text = "\U0001f389 All displayed clashes have been resolved! Excellent work!"
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
                    try:
                        uidoc.RefreshActiveView()
                    except Exception:
                        pass
                    return

            candidate = self.dgClashes.Items[cur_idx]
            if isinstance(candidate, ClashRowVM):
                self.dgClashes.SelectedIndex = cur_idx
                self.dgClashes.ScrollIntoView(candidate)
                focus_clash_3d(doc, uidoc, candidate.RawItem)
                try:
                    uidoc.RefreshActiveView()
                except Exception:
                    pass

        # ---------------------------------------------------------------------
        # 4. Prev / Next Navigation
        # ---------------------------------------------------------------------
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

        # ---------------------------------------------------------------------
        # 5. Filter, Search & Tabs
        # ---------------------------------------------------------------------
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

            # Update Tab Header Counts & Colors
            try:
                self.btnTabActive.Content = u"\U0001f534 Active ({})".format(active_count)
                self.btnTabResolved.Content = u"\u2705 Resolved ({})".format(resolved_count)
                self.btnTabAll.Content = u"All ({})".format(total)

                transparent_brush = SolidColorBrush(Color.FromArgb(0, 0, 0, 0))
                white_brush = _hex_brush("#FFFFFF")
                text_muted = _hex_brush("#64748B")

                if self._current_tab == "ACTIVE":
                    self.btnTabActive.Background = white_brush
                    self.btnTabActive.Foreground = _hex_brush("#DC2626")
                    self.btnTabActive.FontWeight = FontWeights.Normal

                    self.btnTabResolved.Background = transparent_brush
                    self.btnTabResolved.Foreground = text_muted
                    self.btnTabResolved.FontWeight = FontWeights.Normal

                    self.btnTabAll.Background = transparent_brush
                    self.btnTabAll.Foreground = text_muted
                    self.btnTabAll.FontWeight = FontWeights.Normal

                elif self._current_tab == "RESOLVED":
                    self.btnTabActive.Background = transparent_brush
                    self.btnTabActive.Foreground = text_muted
                    self.btnTabActive.FontWeight = FontWeights.Normal

                    self.btnTabResolved.Background = white_brush
                    self.btnTabResolved.Foreground = _hex_brush("#059669")
                    self.btnTabResolved.FontWeight = FontWeights.Normal

                    self.btnTabAll.Background = transparent_brush
                    self.btnTabAll.Foreground = text_muted
                    self.btnTabAll.FontWeight = FontWeights.Normal

                else:  # "ALL"
                    self.btnTabActive.Background = transparent_brush
                    self.btnTabActive.Foreground = text_muted
                    self.btnTabActive.FontWeight = FontWeights.Normal

                    self.btnTabResolved.Background = transparent_brush
                    self.btnTabResolved.Foreground = text_muted
                    self.btnTabResolved.FontWeight = FontWeights.Normal

                    self.btnTabAll.Background = white_brush
                    self.btnTabAll.Foreground = _hex_brush("#2563EB")
                    self.btnTabAll.FontWeight = FontWeights.Normal
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

            # Update Mini Dashboard
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

        # ---------------------------------------------------------------------
        # 6. Import & Export Excel
        # ---------------------------------------------------------------------
        def _on_import_excel(self, sender, e):
            file_path = forms.pick_file(
                file_ext='xlsx',
                title='Select Clash Report Excel File'
            )
            if not file_path or not os.path.exists(file_path):
                return

            self.txtStatus.Text = "Importing clashes from Excel..."
            do_events()

            try:
                clashes = import_clash_report(self.doc, file_path)
                if not clashes:
                    self.txtStatus.Text = "\u26a0\ufe0f No matching clash items found in selected Excel file."
                    self._show_dialog(
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

                self.txtStatus.Text = u"\u2705 Loaded {} clash items from Excel.".format(len(clashes))
                self._show_dialog(
                    u"Successfully loaded {} clash records from:\n\n{}\n\n"
                    "You can now inspect 3D boxes and recheck them!".format(len(clashes), file_path),
                    title="Import Complete",
                    dialog_type="SUCCESS"
                )
            except Exception as ex:
                err_msg = safe_unicode(ex)
                self.txtStatus.Text = u"\u274c Import failed: {}".format(err_msg)
                self._show_dialog(u"Failed to import Excel file:\n\n{}".format(err_msg), title="Import Error", dialog_type="ERROR")

        def _on_export_excel(self, sender, e):
            if not self._all_clash_vms:
                self.txtStatus.Text = "\u26a0\ufe0f No clash data available to export."
                return

            dest_path = forms.save_file(
                file_ext='xlsx',
                default_name='MEPANANA_Clash_Report.xlsx',
                title='Save Clash Report'
            )
            if not dest_path:
                return

            try:
                clashes = [vm.RawItem for vm in self._all_clash_vms]
                ok = export_clash_report(clashes, dest_path)
                if ok:
                    self.txtStatus.Text = u"\u2705 Exported to: {}".format(dest_path)
                    self._show_dialog(u"Clash report exported successfully to:\n\n{}".format(dest_path), title="Export Complete", dialog_type="SUCCESS")
                else:
                    self.txtStatus.Text = "\u274c Failed to generate Excel file."
                    self._show_dialog("Failed to generate Excel file.", title="Export Error", dialog_type="ERROR")
            except Exception as ex:
                err_msg = safe_unicode(ex)
                self.txtStatus.Text = u"\u274c Export error: {}".format(err_msg)
                self._show_dialog(u"Excel export failed:\n\n{}".format(err_msg), title="Export Error", dialog_type="ERROR")


    # ── Launcher (Direct Synchronous Execution for pyRevit) ──────────────────
    doc = get_doc()
    uidoc = get_uidoc()

    if not doc:
        _fatal_alert("Please open a Revit project before launching Check Clash.")
        sys.exit()

    win = CheckClashWindow(doc, uidoc)

    # ── TRUE MODELESS WINDOW — pyRevit-compatible pattern ────────────────────
    # ShowDialog() = modal: disables ALL Revit interaction (ribbon + viewport)
    # Show() alone = crashes: script scope GC'd immediately → Python handlers lost
    #
    # Solution: Show() + Dispatcher.PushFrame()
    #   - Show()         → modeless, Revit stays fully interactive (ribbon + 3D view)
    #   - PushFrame()    → nested WPF message loop, keeps Python scope alive
    #   - frame.Continue → set to False on Closed → exits loop cleanly
    #
    # This is the same pattern pyRevit uses internally for its own modeless tools
    # (e.g. Section Box Navigator).
    # ─────────────────────────────────────────────────────────────────────────
    try:
        revit_handle = System.IntPtr(uidoc.Application.MainWindowHandle)
        helper = WindowInteropHelper(win)
        helper.Owner = revit_handle
    except Exception:
        pass

    frame = DispatcherFrame()

    def _on_win_closed(s, e):
        frame.Continue = False

    win.Closed += _on_win_closed
    win.Show()
    Dispatcher.PushFrame(frame)  # blocks here (keeps scope alive) but pumps all Windows msgs

except Exception as ex:
    err = traceback.format_exc()
    _fatal_alert(u"Check Clash Initialization Error:\n\n{}\n\n{}".format(safe_unicode(ex), err))
