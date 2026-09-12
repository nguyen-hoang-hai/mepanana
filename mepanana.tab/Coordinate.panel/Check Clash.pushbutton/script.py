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
from System.Windows.Media import SolidColorBrush, Color, VisualTreeHelper
from System.Windows.Controls import DataGridRow
from System.Windows.Input import Key
from System.Collections.ObjectModel import ObservableCollection

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import BuiltInCategory, CategoryType, FilteredElementCollector, ElementId

from py.core import get_doc, get_uidoc, get_id_value, safe_unicode
from py.ui import setup_window
from py.clash_analysis_engine import (
    scan_clashes, recheck_single_clash, focus_clash_3d, focus_element_3d, check_element_exists,
    export_clash_report, import_clash_report
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
    _row_vm = None

    def Execute(self, uiapp):
        try:
            wndw = ClashFocus3DHandler._wndw
            item = ClashFocus3DHandler._clash_item
            row_vm = ClashFocus3DHandler._row_vm
            if not wndw or not item:
                return
            doc = uiapp.ActiveUIDocument.Document
            uidoc = uiapp.ActiveUIDocument
            wndw._do_focus_3d(doc, uidoc, item, row_vm=row_vm)
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


# Grouping sets by BuiltInCategory integer ID
_MEP_PIPING_BIPS = {
    int(BuiltInCategory.OST_PipeCurves),
    int(BuiltInCategory.OST_PipeFitting),
    int(BuiltInCategory.OST_PipeAccessory),
    int(BuiltInCategory.OST_FlexPipeCurves),
    int(BuiltInCategory.OST_PipeInsulations),
    int(BuiltInCategory.OST_PlumbingFixtures),
    int(BuiltInCategory.OST_Sprinklers),
}

_MEP_MECH_BIPS = {
    int(BuiltInCategory.OST_DuctCurves),
    int(BuiltInCategory.OST_DuctFitting),
    int(BuiltInCategory.OST_DuctAccessory),
    int(BuiltInCategory.OST_DuctTerminal),
    int(BuiltInCategory.OST_FlexDuctCurves),
    int(BuiltInCategory.OST_DuctInsulations),
    int(BuiltInCategory.OST_DuctLinings),
    int(BuiltInCategory.OST_MechanicalEquipment),
}

_MEP_ELEC_BIPS = {
    int(BuiltInCategory.OST_CableTray),
    int(BuiltInCategory.OST_CableTrayFitting),
    int(BuiltInCategory.OST_Conduit),
    int(BuiltInCategory.OST_ConduitFitting),
    int(BuiltInCategory.OST_ElectricalEquipment),
    int(BuiltInCategory.OST_ElectricalFixtures),
    int(BuiltInCategory.OST_LightingFixtures),
    int(BuiltInCategory.OST_LightingDevices),
    int(BuiltInCategory.OST_FireAlarmDevices),
    int(BuiltInCategory.OST_DataDevices),
    int(BuiltInCategory.OST_CommunicationDevices),
    int(BuiltInCategory.OST_SecurityDevices),
    int(BuiltInCategory.OST_TelephoneDevices),
    int(BuiltInCategory.OST_NurseCallDevices),
}

_STRUCT_BIPS = {
    int(BuiltInCategory.OST_StructuralFraming),
    int(BuiltInCategory.OST_StructuralColumns),
    int(BuiltInCategory.OST_StructuralFoundation),
    int(BuiltInCategory.OST_StructuralFramingSystem),
    int(BuiltInCategory.OST_StructuralStiffener),
    int(BuiltInCategory.OST_StructConnections),
    int(BuiltInCategory.OST_Rebar),
}

_ARCH_BIPS = {
    int(BuiltInCategory.OST_Walls),
    int(BuiltInCategory.OST_Floors),
    int(BuiltInCategory.OST_Ceilings),
    int(BuiltInCategory.OST_Roofs),
    int(BuiltInCategory.OST_Doors),
    int(BuiltInCategory.OST_Windows),
    int(BuiltInCategory.OST_Stairs),
    int(BuiltInCategory.OST_StairsRailing),
    int(BuiltInCategory.OST_Ramps),
    int(BuiltInCategory.OST_CurtainWallPanels),
    int(BuiltInCategory.OST_CurtainWallMullions),
    int(BuiltInCategory.OST_Columns),
    int(BuiltInCategory.OST_GenericModel),
    int(BuiltInCategory.OST_SpecialityEquipment),
    int(BuiltInCategory.OST_Casework),
    int(BuiltInCategory.OST_Furniture),
    int(BuiltInCategory.OST_FurnitureSystems),
}

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


_EXCLUDED_BIPS = {
    int(BuiltInCategory.OST_Views),
    int(BuiltInCategory.OST_Viewers),
    int(BuiltInCategory.OST_Sheets),
    int(BuiltInCategory.OST_ProjectInformation),
    int(BuiltInCategory.OST_Materials),
    int(BuiltInCategory.OST_Cameras),
    int(BuiltInCategory.OST_ScheduleGraphics),
    int(BuiltInCategory.OST_Schedules),
    int(BuiltInCategory.OST_RvtLinks),
    int(BuiltInCategory.OST_Massing),
    int(BuiltInCategory.OST_Phasing),
}

_EXCLUDED_CAT_NAMES = {
    "views", "view", "sheets", "sheet", "project information",
    "materials", "cameras", "schedule graphics", "schedules",
    "rvt links", "revit links", "analysis results", "sun path",
    "raster images", "import in families"
}


def _collect_document_model_categories(doc, view=None):
    """Extracts all top-level Model categories strictly matching Revit VV Model Categories."""
    results = []
    for cat in doc.Settings.Categories:
        try:
            if cat.CategoryType != CategoryType.Model:
                continue
            if cat.Parent is not None:
                continue
            if hasattr(cat, "AllowsVisibilityControl") and not cat.AllowsVisibilityControl:
                continue
            if hasattr(cat, "IsVisibleInUI") and not cat.IsVisibleInUI:
                continue
            cid = cat.Id.IntegerValue
            if cid in _EXCLUDED_BIPS:
                continue
            name = cat.Name
            if not name or name.startswith("<") or name.startswith("{"):
                continue
            if name.strip().lower() in _EXCLUDED_CAT_NAMES:
                continue
            if view and hasattr(view, "CanCategoryBeHidden"):
                try:
                    if not view.CanCategoryBeHidden(cat.Id):
                        continue
                except Exception:
                    pass

            disc = _classify_discipline(cid, name)
            results.append((cid, name, disc))
        except Exception:
            pass

    results.sort(key=lambda x: x[1])
    return results


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

        self._init_categories()
        self._load_category_prefs()
        self._apply_cat_filter()
        self._update_cat_summary()

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
    # Categories (VV) Tab Handlers
    # -------------------------------------------------------------------------

    def _init_categories(self):
        self._all_cat_vms = []
        raw_cats = _collect_document_model_categories(self.doc, self.uidoc.ActiveView if self.uidoc else None)
        for cid, name, disc in raw_cats:
            vm = CategoryItemVM(cid, name, disc, is_checked=False)
            self._all_cat_vms.append(vm)

    def _on_cat_filter_changed(self, sender, e):
        self._apply_cat_filter()

    def _apply_cat_filter(self):
        q = self.txtCatSearch.Text.strip().lower() if (hasattr(self, 'txtCatSearch') and self.txtCatSearch.Text) else ""
        disc_idx = self.cmbCatDiscipline.SelectedIndex if hasattr(self, 'cmbCatDiscipline') else 0

        self._displayed_cat_vms.Clear()
        for vm in self._all_cat_vms:
            # Discipline dropdown filter
            if disc_idx == 1:  # MEP Only
                if vm.Discipline not in ["Mechanical", "Electrical", "Piping"]:
                    continue
            elif disc_idx == 2:  # Mechanical
                if vm.Discipline != "Mechanical":
                    continue
            elif disc_idx == 3:  # Electrical
                if vm.Discipline != "Electrical":
                    continue
            elif disc_idx == 4:  # Piping
                if vm.Discipline != "Piping":
                    continue
            elif disc_idx == 5:  # Structure
                if vm.Discipline != "Structural":
                    continue
            elif disc_idx == 6:  # Architecture
                if vm.Discipline != "Architectural":
                    continue

            # Search text query
            if q and (q not in vm.Name.lower()) and (q not in vm.Discipline.lower()):
                continue

            self._displayed_cat_vms.Add(vm)

        try:
            self.dgCategories.Items.Refresh()
        except Exception:
            pass

    def _on_cat_grid_click(self, sender, e):
        """Clicking on row in categories DataGrid toggles selection."""
        try:
            dep = e.OriginalSource
            while dep is not None and not isinstance(dep, DataGridRow):
                dep = VisualTreeHelper.GetParent(dep)
            if dep and isinstance(dep, DataGridRow):
                item = dep.Item
                if item and isinstance(item, CategoryItemVM):
                    item.IsChecked = not item.IsChecked
                    self.dgCategories.Items.Refresh()
                    self._update_cat_summary()
                    self._save_category_prefs()
        except Exception:
            pass

    def _toggle_selected_category_row(self):
        try:
            item = self.dgCategories.SelectedItem
            if item and isinstance(item, CategoryItemVM):
                item.IsChecked = not item.IsChecked
                self.dgCategories.Items.Refresh()
                self._update_cat_summary()
                self._save_category_prefs()
        except Exception:
            pass

    def _on_preset_mep(self, sender, e):
        for vm in self._all_cat_vms:
            vm.IsChecked = (vm.CatInt in _DEFAULT_MEP_SET)
        self.dgCategories.Items.Refresh()
        self._update_cat_summary()
        self._save_category_prefs()

    def _on_preset_all(self, sender, e):
        for vm in self._displayed_cat_vms:
            vm.IsChecked = True
        self.dgCategories.Items.Refresh()
        self._update_cat_summary()
        self._save_category_prefs()

    def _on_preset_none(self, sender, e):
        for vm in self._displayed_cat_vms:
            vm.IsChecked = False
        self.dgCategories.Items.Refresh()
        self._update_cat_summary()
        self._save_category_prefs()

    def _on_preset_struct(self, sender, e):
        for vm in self._all_cat_vms:
            if vm.Discipline == "Structural":
                vm.IsChecked = True
        self.dgCategories.Items.Refresh()
        self._update_cat_summary()
        self._save_category_prefs()

    def _on_preset_arch(self, sender, e):
        for vm in self._all_cat_vms:
            if vm.Discipline == "Architectural":
                vm.IsChecked = True
        self.dgCategories.Items.Refresh()
        self._update_cat_summary()
        self._save_category_prefs()

    def _update_cat_summary(self):
        checked_cats = [vm for vm in self._all_cat_vms if vm.IsChecked]
        n_sel = len(checked_cats)
        total_cats = len(self._all_cat_vms)
        if hasattr(self, 'txtCatSummary'):
            self.txtCatSummary.Text = u"Selected: {} / {} categories".format(n_sel, total_cats)
        if hasattr(self, 'tabCategories'):
            self.tabCategories.Header = u"📋 Categories ({})".format(n_sel)

    def _save_category_prefs(self):
        try:
            cfg = _script.get_config()
            checked_ids = [vm.CatInt for vm in self._all_cat_vms if vm.IsChecked]
            cfg.selected_category_ids = checked_ids
            _script.save_config()
        except Exception:
            pass

    def _load_category_prefs(self):
        try:
            cfg = _script.get_config()
            saved_ids = getattr(cfg, 'selected_category_ids', None)
            if saved_ids and isinstance(saved_ids, (list, set)):
                saved_set = set(int(x) for x in saved_ids)
                for vm in self._all_cat_vms:
                    vm.IsChecked = (vm.CatInt in saved_set)
                return
        except Exception:
            pass
        # Default to MEP categories
        for vm in self._all_cat_vms:
            vm.IsChecked = (vm.CatInt in _DEFAULT_MEP_SET)

    def _get_active_category_ids(self):
        return [vm.CatInt for vm in self._all_cat_vms if vm.IsChecked]

    def _on_key_down(self, sender, e):
        if e.Key == Key.Escape:
            self.Close()
            e.Handled = True
        elif e.Key == Key.F5:
            self._on_recheck_clicked(sender, e)
            e.Handled = True
        elif e.Key == Key.Space:
            if hasattr(self, 'dgCategories') and self.dgCategories.IsKeyboardFocusWithin:
                self._toggle_selected_category_row()
                e.Handled = True
            else:
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

            cats = self._get_active_category_ids()
            if not cats:
                self.txtStatus.Text = u"⚠️ No categories selected. Please go to 'Categories' tab and select at least one."
                self._show_topmost_dialog(
                    u"No categories selected for clash check!\n\n"
                    u"Please click the '📋 Categories' tab and check the categories you want to inspect.",
                    title="No Categories Selected",
                    dialog_type="WARNING"
                )
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

            # Automatically switch to Inspector tab to review results
            if hasattr(self, 'tabMain'):
                self.tabMain.SelectedIndex = 0

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
        # Ignore double-clicks originating from column headers or scrollbars
        try:
            from System.Windows.Media import VisualTreeHelper
            from System.Windows.Controls.Primitives import DataGridColumnHeader
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
        ClashFocus3DHandler._wndw = self
        ClashFocus3DHandler._clash_item = selected.RawItem
        ClashFocus3DHandler._row_vm = selected
        _EXT_EVENT_FOCUS.Raise()

    def _do_focus_3d(self, doc, uidoc, clash_item, row_vm=None):
        """Called by ClashFocus3DHandler on Revit UI thread."""
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

        # ── Trường hợp 1: Cả 2 đối tượng đều không còn tồn tại trong mô hình ──
        if not exists1 and not exists2:
            if row_vm:
                row_vm.mark_resolved()
                row_vm.OverlapDisplay = u"0 mm (Đã xoá)"
                self._apply_filter()
            msg = (
                u"Không thể tìm thấy đối tượng trong mô hình:\n\n"
                u"Cả 2 đối tượng trong va chạm này đã bị xoá khỏi mô hình:\n"
                u"• {} [{}]\n"
                u"• {} [{}]\n\n"
                u"Va chạm này đã tự động được đánh dấu là Resolved do đối tượng không còn tồn tại."
            ).format(cat1, id1, cat2, id2)
            self.txtStatus.Text = u"⚠️ Cả 2 đối tượng ({} [{}] & {} [{}]) đã bị xoá khỏi mô hình.".format(
                cat1, id1, cat2, id2
            )
            self._show_topmost_dialog(msg, title="Đối Tượng Đã Bị Xoá", dialog_type="INFO")
            return

        # ── Trường hợp 2: Chỉ còn 1 đối tượng tồn tại (đối tượng kia đã bị xoá) ─
        if exists1 and not exists2:
            surviving_el = live_el1
            surv_is_link = getattr(clash_item, "IsLink1", False)
            surv_tf = tf1
            surv_info = u"{} [{}]".format(cat1, id1)
            del_info = u"{} [{}]".format(cat2, id2)

            success, vname = focus_element_3d(doc, uidoc, surviving_el, padding_mm=1000, transform=surv_tf, is_link=surv_is_link)
            if row_vm:
                row_vm.mark_resolved()
                row_vm.OverlapDisplay = u"0 mm (Đã xoá 1 bên)"
                self._apply_filter()
            self.txtStatus.Text = u"Focus [{}]: {} còn tồn tại ({} đã bị xoá). Va chạm đã giải quyết.".format(
                vname or "3D", surv_info, del_info
            )
            return

        if exists2 and not exists1:
            surviving_el = live_el2
            surv_is_link = getattr(clash_item, "IsLink2", False)
            surv_tf = tf2
            surv_info = u"{} [{}]".format(cat2, id2)
            del_info = u"{} [{}]".format(cat1, id1)

            success, vname = focus_element_3d(doc, uidoc, surviving_el, padding_mm=1000, transform=surv_tf, is_link=surv_is_link)
            if row_vm:
                row_vm.mark_resolved()
                row_vm.OverlapDisplay = u"0 mm (Đã xoá 1 bên)"
                self._apply_filter()
            self.txtStatus.Text = u"Focus [{}]: {} còn tồn tại ({} đã bị xoá). Va chạm đã giải quyết.".format(
                vname or "3D", surv_info, del_info
            )
            return

        # ── Trường hợp 3: Cả 2 đối tượng đều đang tồn tại ─────────────────────
        success = focus_clash_3d(doc, uidoc, clash_item)
        vname = getattr(clash_item, "LastViewName", None) or (uidoc.ActiveView.Name if uidoc and uidoc.ActiveView else "3D")

        # Nếu là va chạm đã RESOLVED (người dùng double-click để kiểm tra lại sau khi chỉnh sửa):
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
                self.txtStatus.Text = u"⚠️ Phát hiện va chạm xuất hiện trở lại: {:.0f} mm overlap! Đã chuyển về ACTIVE.".format(overlap_mm)
                warn_msg = (
                    u"⚠️ Cảnh báo: Sau khi kiểm tra lại mô hình, 2 đối tượng này đã VA CHẠM TRỞ LẠI!\n\n"
                    u"• {} [{}] ⚡ {} [{}]\n"
                    u"• Độ giao cắt (overlap): {:.0f} mm\n\n"
                    u"Trạng thái va chạm đã được tự động chuyển lại về 'Active' để bạn tiếp tục xử lý."
                ).format(cat1, id1, cat2, id2, overlap_mm)
                self._show_topmost_dialog(warn_msg, title="Va Chạm Tái Xuất Hiện", dialog_type="WARN")
            else:
                if row_vm:
                    row_vm.mark_resolved()
                    self._apply_filter()
                self.txtStatus.Text = u"Focus [{}]: {} [{}] vs {} [{}] - ✅ Đã kiểm tra lại: Không còn va chạm.".format(
                    vname, cat1, id1, cat2, id2
                )
        else:
            if success:
                self.txtStatus.Text = u"Focus [{}]: {} [{}] vs {} [{}]".format(
                    vname, cat1, id1, cat2, id2
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
            selected.OverlapDisplay = u"0 mm (Đã xoá)"
            self._apply_filter()
            self.txtStatus.Text = u"✅ Cả 2 đối tượng đã bị xoá khỏi mô hình. Đã chuyển sang Resolved."
            self._auto_advance(doc, uidoc)
            return

        if exists1 != exists2:
            selected.mark_resolved()
            selected.OverlapDisplay = u"0 mm (Đã xoá 1 bên)"
            self._apply_filter()
            surv_info = u"{} [{}]".format(cat1, id1) if exists1 else u"{} [{}]".format(cat2, id2)
            self.txtStatus.Text = u"✅ Đối tượng kia đã bị xoá ({} còn tồn tại). Đã chuyển sang Resolved.".format(surv_info)
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