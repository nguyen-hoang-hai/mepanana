# -*- coding: utf-8 -*-
"""
Display Clash - Transient Visual Clash Analysis for MEP Elements, Architecture & Structure
Utilizes Revit Analysis Visualization Framework (AVF - SpatialFieldManager)
to render interactive clash heatmaps directly in the model view without database clutter.
Dual Color Coding:
- 🔴 Fiery Red (#EF4444) for Host Model clashes (localized).
- 🟢 Vibrant Emerald Green (#22C55E) for Linked File clashes (localized).
- Persistent Clash History: Retains detected clash list until Clear Analysis is clicked.
- Comprehensive Categories: Loads all Revit 3D Model Categories dynamically.
- Real-time Animated Progress Bar with Dispatcher message pump.

Part of mepanana.extension.
"""
__title__ = "Display Clash"
__doc__   = "Transient visual clash analysis for MEP and BIM elements using Revit Analysis Visualization Framework (AVF)."

# ── 6-Line Security Gatekeeper Boilerplate ───────────────────────────────────
import os
import sys

_lib_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

from py.auth import require_auth, update_ribbon_state, is_authenticated
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()
# ─────────────────────────────────────────────────────────────────────────────

import json
import tempfile
import traceback

def _fatal_alert(err_str):
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("Display Clash Error", err_str)
    except Exception:
        pass

# ── Dynamic Lib Resolution (already done above) ──────────────────────────────
lib_path = _lib_path


# ── Imports ──────────────────────────────────────────────────────────────────
try:
    import clr
    clr.AddReference("System")
    clr.AddReference("PresentationCore")
    clr.AddReference("PresentationFramework")
    clr.AddReference("WindowsBase")
    clr.AddReference("RevitAPI")
    clr.AddReference("RevitAPIUI")

    import System
    from System.Windows import Visibility
    from System.Windows.Data import CollectionViewSource
    from System.Windows.Interop import WindowInteropHelper
    from System.Windows.Threading import Dispatcher, DispatcherFrame, DispatcherPriority
    from System.Collections.ObjectModel import ObservableCollection
    from System.Collections.Generic import List as CSharpList
    from Autodesk.Revit.DB import BuiltInCategory, ElementId, CategoryType, XYZ
    from Autodesk.Revit.DB.Analysis import SpatialFieldManager
    from pyrevit import forms, revit
    from py.core import get_doc, get_uidoc, SafeTransaction, get_id_value, safe_unicode
    from py.ui   import setup_modern_window, is_dark_theme, show_info, show_warning, show_error, show_success, do_events

    from py.clash_analysis_engine import (
        scan_clashes, render_clashes_avf, clear_clash_analysis, ClashItem
    )

    doc = get_doc()
    if not doc:
        _fatal_alert("Please open a Revit project before launching Display Clash.")
        sys.exit()

    uidoc = get_uidoc()

    # ── Category Item Model ──────────────────────────────────────────────────────

    class CategoryItem(object):
        """Represents a selectable category with CheckBox state."""
        def __init__(self, name, cat_id, is_checked=False, is_default=False):
            self._name = name
            self._cat_id = cat_id
            self._is_checked = is_checked
            self._is_default = is_default

        @property
        def Name(self):
            return self._name

        @property
        def CatId(self):
            return self._cat_id

        @property
        def Bic(self):
            return self._cat_id

        @property
        def IsChecked(self):
            return self._is_checked

        @IsChecked.setter
        def IsChecked(self, value):
            self._is_checked = bool(value)

        @property
        def IsDefault(self):
            return self._is_default


    # ── Comprehensive Default MEP BuiltInCategories Set ──────────────────────────
    DEFAULT_MEP_BIC_SET = {
        int(BuiltInCategory.OST_DuctTerminal),
        int(BuiltInCategory.OST_CableTrayFitting),
        int(BuiltInCategory.OST_CableTray),
        int(BuiltInCategory.OST_CommunicationDevices),
        int(BuiltInCategory.OST_ConduitFitting),
        int(BuiltInCategory.OST_Conduit),
        int(BuiltInCategory.OST_DataDevices),
        int(BuiltInCategory.OST_DuctAccessory),
        int(BuiltInCategory.OST_DuctFitting),
        int(BuiltInCategory.OST_DuctCurves),
        int(BuiltInCategory.OST_ElectricalEquipment),
        int(BuiltInCategory.OST_ElectricalFixtures),
        int(BuiltInCategory.OST_FireAlarmDevices),
        int(BuiltInCategory.OST_FlexDuctCurves),
        int(BuiltInCategory.OST_FlexPipeCurves),
        int(BuiltInCategory.OST_LightingDevices),
        int(BuiltInCategory.OST_LightingFixtures),
        int(BuiltInCategory.OST_MechanicalEquipment),
        int(BuiltInCategory.OST_NurseCallDevices),
        int(BuiltInCategory.OST_PipeAccessory),
        int(BuiltInCategory.OST_PipeFitting),
        int(BuiltInCategory.OST_PipeCurves),
        int(BuiltInCategory.OST_PlumbingFixtures),
        int(BuiltInCategory.OST_SecurityDevices),
        int(BuiltInCategory.OST_Sprinklers),
        int(BuiltInCategory.OST_TelephoneDevices),
    }

    COMPLETE_FALLBACK_CATALOG = [
        ("Air Terminals", BuiltInCategory.OST_DuctTerminal, True),
        ("Audio Visual Devices", BuiltInCategory.OST_AudioVisualDevices, False),
        ("Cable Tray Fittings", BuiltInCategory.OST_CableTrayFitting, True),
        ("Cable Trays", BuiltInCategory.OST_CableTray, True),
        ("Casework", BuiltInCategory.OST_Casework, False),
        ("Ceilings", BuiltInCategory.OST_Ceilings, False),
        ("Columns", BuiltInCategory.OST_Columns, False),
        ("Communication Devices", BuiltInCategory.OST_CommunicationDevices, True),
        ("Conduit Fittings", BuiltInCategory.OST_ConduitFitting, True),
        ("Conduits", BuiltInCategory.OST_Conduit, True),
        ("Curtain Panels", BuiltInCategory.OST_CurtainWallPanels, False),
        ("Curtain Wall Mullions", BuiltInCategory.OST_CurtainWallMullions, False),
        ("Data Devices", BuiltInCategory.OST_DataDevices, True),
        ("Doors", BuiltInCategory.OST_Doors, False),
        ("Duct Accessories", BuiltInCategory.OST_DuctAccessory, True),
        ("Duct Fittings", BuiltInCategory.OST_DuctFitting, True),
        ("Ducts", BuiltInCategory.OST_DuctCurves, True),
        ("Electrical Equipment", BuiltInCategory.OST_ElectricalEquipment, True),
        ("Electrical Fixtures", BuiltInCategory.OST_ElectricalFixtures, True),
        ("Fire Alarm Devices", BuiltInCategory.OST_FireAlarmDevices, True),
        ("Flex Ducts", BuiltInCategory.OST_FlexDuctCurves, True),
        ("Flex Pipes", BuiltInCategory.OST_FlexPipeCurves, True),
        ("Floors", BuiltInCategory.OST_Floors, False),
        ("Food Service Equipment", BuiltInCategory.OST_FoodServiceEquipment, False),
        ("Furniture", BuiltInCategory.OST_Furniture, False),
        ("Furniture Systems", BuiltInCategory.OST_FurnitureSystems, False),
        ("Generic Models", BuiltInCategory.OST_GenericModel, False),
        ("Lighting Devices", BuiltInCategory.OST_LightingDevices, True),
        ("Lighting Fixtures", BuiltInCategory.OST_LightingFixtures, True),
        ("Mass", BuiltInCategory.OST_Mass, False),
        ("Mechanical Equipment", BuiltInCategory.OST_MechanicalEquipment, True),
        ("Medical Equipment", BuiltInCategory.OST_MedicalEquipment, False),
        ("Nurse Call Devices", BuiltInCategory.OST_NurseCallDevices, True),
        ("Parking", BuiltInCategory.OST_Parking, False),
        ("Pipe Accessories", BuiltInCategory.OST_PipeAccessory, True),
        ("Pipe Fittings", BuiltInCategory.OST_PipeFitting, True),
        ("Pipes", BuiltInCategory.OST_PipeCurves, True),
        ("Plumbing Fixtures", BuiltInCategory.OST_PlumbingFixtures, True),
        ("Railings", BuiltInCategory.OST_StairsRailing, False),
        ("Ramps", BuiltInCategory.OST_Ramps, False),
        ("Roads", BuiltInCategory.OST_Roads, False),
        ("Roofs", BuiltInCategory.OST_Roofs, False),
        ("Security Devices", BuiltInCategory.OST_SecurityDevices, True),
        ("Signage", BuiltInCategory.OST_Signage, False),
        ("Site", BuiltInCategory.OST_Site, False),
        ("Specialty Equipment", BuiltInCategory.OST_SpecialityEquipment, False),
        ("Sprinklers", BuiltInCategory.OST_Sprinklers, True),
        ("Stairs", BuiltInCategory.OST_Stairs, False),
        ("Structural Beam Systems", BuiltInCategory.OST_StructuralFramingSystem, False),
        ("Structural Columns", BuiltInCategory.OST_StructuralColumns, False),
        ("Structural Connections", BuiltInCategory.OST_StructConnections, False),
        ("Structural Foundations", BuiltInCategory.OST_StructuralFoundation, False),
        ("Structural Framing", BuiltInCategory.OST_StructuralFraming, False),
        ("Structural Stiffeners", BuiltInCategory.OST_StructuralStiffener, False),
        ("Telephone Devices", BuiltInCategory.OST_TelephoneDevices, True),
        ("Topography", BuiltInCategory.OST_Topography, False),
        ("Walls", BuiltInCategory.OST_Walls, False),
        ("Windows", BuiltInCategory.OST_Windows, False),
    ]

    def get_all_model_categories(doc_obj):
        cats = []
        if doc_obj and hasattr(doc_obj, "Settings") and doc_obj.Settings:
            for cat in doc_obj.Settings.Categories:
                try:
                    if cat.CategoryType == CategoryType.Model:
                        bic_val = get_id_value(cat)
                        if bic_val < 0:
                            name = cat.Name
                            if not name.startswith("<") and not name.startswith("Analytical") and "Tag" not in name:
                                is_default = bic_val in DEFAULT_MEP_BIC_SET
                                cats.append((name, cat.Id, is_default))
                except Exception:
                    pass

        if not cats:
            for name, bic_val, is_def in COMPLETE_FALLBACK_CATALOG:
                try:
                    cats.append((name, ElementId(int(bic_val)), is_def))
                except Exception:
                    pass

        seen_ids = set()
        unique = []
        for name, cid, is_def in sorted(cats, key=lambda x: x[0]):
            iid = get_id_value(cid)
            if iid not in seen_ids:
                seen_ids.add(iid)
                unique.append((name, cid, is_def))
                
        return unique


    # ── Persistent Storage Across Tool Invocations ───────────────────────────────

    CACHE_FILE = os.path.join(tempfile.gettempdir(), "mepanana_clash_results_cache.json")

    def _get_cache_key(doc_obj, view_obj):
        doc_name = os.path.basename(doc_obj.PathName) if doc_obj.PathName else doc_obj.Title
        return "{}_view_{}".format(doc_name, get_id_value(view_obj))

    def _save_cache(doc_obj, view_obj, clash_items):
        try:
            data = {}
            if os.path.exists(CACHE_FILE):
                try:
                    with open(CACHE_FILE, 'r') as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            key = _get_cache_key(doc_obj, view_obj)
            serialized = []
            for c in clash_items:
                serialized.append({
                    "name1": c.Element1.Category.Name if c.Element1.Category else "Element",
                    "id1": get_id_value(c.Element1),
                    "name2": c.Element2.Category.Name if c.Element2.Category else "Element",
                    "id2": get_id_value(c.Element2),
                    "is_link": c.IsLink,
                    "link_name": getattr(c, 'LinkName', ''),
                    "overlap_mm": c.OverlapMm,
                    "elev_diff_mm": c.ElevDiffMm,
                    "display_name": c.DisplayName,
                    "detail_info": c.DetailInfo,
                    "clash_x": c.ClashPoint.X if c.ClashPoint else None,
                    "clash_y": c.ClashPoint.Y if c.ClashPoint else None,
                    "clash_z": c.ClashPoint.Z if c.ClashPoint else None,
                })
            data[key] = serialized
            with open(CACHE_FILE, 'w') as f:
                json.dump(data, f)
        except Exception:
            pass

    def _load_cache(doc_obj, view_obj):
        try:
            if not os.path.exists(CACHE_FILE):
                return None
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
            key = _get_cache_key(doc_obj, view_obj)
            raw_list = data.get(key)
            if not raw_list:
                return None
                
            items = []
            for item in raw_list:
                el1 = doc_obj.GetElement(ElementId(item["id1"]))
                el2 = doc_obj.GetElement(ElementId(item["id2"]))
                if not el1:
                    continue
                clash_pt = None
                if item.get("clash_x") is not None and item.get("clash_y") is not None and item.get("clash_z") is not None:
                    try:
                        clash_pt = XYZ(float(item["clash_x"]), float(item["clash_y"]), float(item["clash_z"]))
                    except Exception:
                        clash_pt = None
                c_item = ClashItem(
                    el1, el2 if el2 else el1,
                    clash_pt,
                    overlap_mm=item["overlap_mm"],
                    elev_diff_mm=item["elev_diff_mm"],
                    is_link1=False, is_link2=item["is_link"],
                    link_name=item["link_name"]
                )
                c_item.DisplayName = item["display_name"]
                c_item.DetailInfo = item["detail_info"]
                items.append(c_item)
            return items
        except Exception:
            return None

    def _clear_cache(doc_obj, view_obj):
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, 'r') as f:
                    data = json.load(f)
                key = _get_cache_key(doc_obj, view_obj)
                if key in data:
                    del data[key]
                with open(CACHE_FILE, 'w') as f:
                    json.dump(data, f)
        except Exception:
            pass


    # ── Main Controller Window ───────────────────────────────────────────────────

    class DisplayClashWindow(forms.WPFWindow):
        def __init__(self, dark_mode=False):
            self.dark_mode = dark_mode
            xaml_name = "ui_dark.xaml" if dark_mode else "ui_light.xaml"
            xaml_path = os.path.join(os.path.dirname(__file__), xaml_name)
            forms.WPFWindow.__init__(self, xaml_path)
            setup_modern_window(self, dark_mode=dark_mode, set_revit_owner=True)
            
            self.doc = doc
            self.uidoc = uidoc
            self.active_view = doc.ActiveView

            # Build Categories Collection dynamically from all 3D Model Categories in Revit
            self._updating_categories = True
            all_cats = get_all_model_categories(self.doc)
            self.categories = ObservableCollection[CategoryItem]()
            for name, cid, is_def in all_cats:
                item = CategoryItem(name, cid, is_checked=is_def, is_default=is_def)
                self.categories.Add(item)

            self.categories_view = CollectionViewSource.GetDefaultView(self.categories)
            self.lstCategories.ItemsSource = self.categories_view
            self._update_category_count()

            # Wire Category Search & Events
            self.txtSearchCategory.TextChanged += self.on_category_search_changed
            self.btnClearCategorySearch.Click += self.on_clear_category_search

            self.lstCategories.AddHandler(
                System.Windows.Controls.Primitives.ToggleButton.CheckedEvent,
                System.Windows.RoutedEventHandler(self.on_category_item_checked)
            )
            self.lstCategories.AddHandler(
                System.Windows.Controls.Primitives.ToggleButton.UncheckedEvent,
                System.Windows.RoutedEventHandler(self.on_category_item_checked)
            )

            # Wire Check Same Model Toggle & Color Badges
            if hasattr(self, 'chkIncludeHost'):
                self.chkIncludeHost.Checked += self.on_same_model_toggled
                self.chkIncludeHost.Unchecked += self.on_same_model_toggled
                self._update_color_badges()

            # Wire Events
            self.radDefault.Checked += self.on_mode_default
            self.radCustom.Checked  += self.on_mode_custom
            self.btnSelectAll.Click += self.on_select_all
            self.btnSelectNone.Click += self.on_select_none

            self.btnAnalyze.Click += self.on_analyze
            self.btnClear.Click   += self.on_clear
            if hasattr(self, 'btnFooterClose') and self.btnFooterClose:
                self.btnFooterClose.Click += self.on_close
            if hasattr(self, 'btnClose') and self.btnClose:
                self.btnClose.Click += self.on_close
            self.lstClashes.SelectionChanged += self.on_clash_selected

            # Auto-detect pre-selected elements in Revit
            sel = self.uidoc.Selection.GetElementIds()
            if sel and len(sel) > 0:
                self.cmbScope.SelectedIndex = 1  # "Selected Elements Only"
            else:
                self.cmbScope.SelectedIndex = 0  # "Active View (All Elements)"

            # Initial lock state
            self._apply_mode_state()
            self._updating_categories = False

            # Restore Persistent Clash Results if Active View still has active AVF
            self._restore_active_results()

        def on_same_model_toggled(self, sender, e):
            self._update_color_badges()

        def _update_color_badges(self):
            is_same = bool(self.chkIncludeHost.IsChecked) if hasattr(self, 'chkIncludeHost') else True
            if hasattr(self, 'badgeHost2'):
                self.badgeHost2.Visibility = Visibility.Visible if is_same else Visibility.Collapsed
            if hasattr(self, 'txtBadgeHost1'):
                self.txtBadgeHost1.Text = "🔴 Host 1 (Red)" if is_same else "🔴 Host (Red)"

        def _restore_active_results(self):
            try:
                sfm = SpatialFieldManager.GetSpatialFieldManager(self.active_view)
                has_active_avf = sfm is not None and sfm.GetRegisteredResults().Count > 0
                if has_active_avf:
                    cached_items = _load_cache(self.doc, self.active_view)
                    if cached_items and len(cached_items) > 0:
                        self.lstClashes.ItemsSource = cached_items
                        link_count = sum(1 for c in cached_items if c.IsLink)
                        host_count = len(cached_items) - link_count
                        self.txtClashCount.Text = "{} Total (🔴 {} Host | 🟢 {} Link)".format(
                            len(cached_items), host_count, link_count
                        )
                        self.txtStatus.Text = "Active analysis: {} clash elements highlighted in view.".format(len(cached_items))
                        return
            except Exception:
                pass
                
            self.txtStatus.Text = "Ready. Active View: {}".format(self.active_view.Name)

        def on_clash_selected(self, sender, e):
            item = self.lstClashes.SelectedItem
            if not item:
                return
            try:
                host_elem = item.Element1 if not getattr(item, 'IsLink1', False) else (item.Element2 if not item.IsLink else None)
                if host_elem:
                    self.uidoc.Selection.SetElementIds(CSharpList[ElementId]([host_elem.Id]))
                    self.uidoc.ShowElements(host_elem.Id)
            except Exception:
                pass

        def _apply_mode_state(self):
            is_custom = bool(self.radCustom.IsChecked)
            if hasattr(self, 'pnlCustomSettings'):
                self.pnlCustomSettings.IsEnabled = is_custom
                self.pnlCustomSettings.Opacity = 1.0 if is_custom else 0.55
            self.txtSearchCategory.IsEnabled = is_custom
            self.btnClearCategorySearch.IsEnabled = is_custom
            self.btnSelectAll.IsEnabled = is_custom
            self.btnSelectNone.IsEnabled = is_custom
            self.lstCategories.IsEnabled = is_custom

        def _update_category_count(self):
            cnt = sum(1 for c in self.categories if c.IsChecked)
            self.txtCategoryCount.Text = "{} Selected".format(cnt)

        def on_category_item_checked(self, sender, e):
            if getattr(self, '_updating_categories', False):
                return
            self._update_category_count()

        def on_category_search_changed(self, sender, e):
            query = (self.txtSearchCategory.Text or "").strip().lower()
            self.btnClearCategorySearch.Visibility = Visibility.Visible if query else Visibility.Collapsed
            if not query:
                self.categories_view.Filter = None
            else:
                def _filter_pred(item):
                    if item is None:
                        return False
                    return query in item.Name.lower()
                try:
                    self.categories_view.Filter = System.Predicate[object](_filter_pred)
                except Exception:
                    try:
                        self.categories_view.Filter = _filter_pred
                    except Exception:
                        pass

        def on_clear_category_search(self, sender, e):
            self.txtSearchCategory.Text = ""

        def on_mode_default(self, sender, e):
            self._updating_categories = True
            try:
                self.txtSearchCategory.Text = ""
                for c in self.categories:
                    c.IsChecked = c.IsDefault
                self.lstCategories.Items.Refresh()
            finally:
                self._updating_categories = False
            self._apply_mode_state()
            self._update_category_count()

        def on_mode_custom(self, sender, e):
            self._apply_mode_state()
            self._update_category_count()

        def on_select_all(self, sender, e):
            self.radCustom.IsChecked = True
            self._apply_mode_state()
            target_list = [item for item in self.categories_view] if self.categories_view.Filter else self.categories
            for c in target_list:
                c.IsChecked = True
            self.lstCategories.Items.Refresh()
            self._update_category_count()

        def on_select_none(self, sender, e):
            self.radCustom.IsChecked = True
            self._apply_mode_state()
            target_list = [item for item in self.categories_view] if self.categories_view.Filter else self.categories
            for c in target_list:
                c.IsChecked = False
            self.lstCategories.Items.Refresh()
            self._update_category_count()

        def _get_extent_mm(self):
            try:
                val = float(str(self.txtExtent.Text).strip())
                if val > 0:
                    return val
            except Exception:
                pass
            return 600.0

        def _get_selected_categories(self):
            return [get_id_value(c.CatId) for c in self.categories if c.IsChecked]

        def on_analyze(self, sender, e):
            self._update_category_count()
            cats = self._get_selected_categories()
            if not cats:
                show_warning("Please select at least one Host category to inspect.", "No Category Selected")
                return

            selected_ids = []
            if self.cmbScope.SelectedIndex == 1:
                sel = self.uidoc.Selection.GetElementIds()
                if not sel or len(sel) == 0:
                    show_warning("No elements selected. Please select elements in Revit or switch to 'Active View'.", "Empty Selection")
                    return
                selected_ids = list(sel)

            extent_val = self._get_extent_mm()
            check_same = bool(self.chkIncludeHost.IsChecked) if hasattr(self, 'chkIncludeHost') else True

            self.btnAnalyze.IsEnabled = False
            self.btnClear.IsEnabled = False
            self.progressBar.Visibility = Visibility.Visible
            self.progressBar.Value = 0
            self.txtStatus.Text = "Initializing 3D Solid Clash Analysis Engine..."
            do_events()

            def update_prog(pct, msg):
                try:
                    self.progressBar.Value = pct
                    self.txtStatus.Text = msg
                    do_events()
                except Exception:
                    pass

            try:
                # 1. Compute hard clashes with Native 3D Boolean Engine + Progress Callback
                clashes = scan_clashes(
                    self.doc, self.active_view,
                    categories=cats,
                    selected_ids=selected_ids,
                    extent_mm=extent_val,
                    check_same_model=check_same,
                    progress_callback=update_prog
                )

                # 2. Render native Revit Analysis Results (1) on view (AVF)
                update_prog(95, "Rendering visual clash markers on active view...")
                with SafeTransaction(self.doc, "MEPANANA Visual Clash Analysis"):
                    primitives_count = render_clashes_avf(self.doc, self.active_view, clashes, extent_mm=extent_val)

                # 3. Save Persistent Cache
                _save_cache(self.doc, self.active_view, clashes)

                # 4. Update UI List
                self.lstClashes.ItemsSource = clashes
                link_count = sum(1 for c in clashes if c.IsLink)
                host_count = len(clashes) - link_count
                
                if check_same:
                    self.txtClashCount.Text = "{} Total (🔴 {} Host | 🟢 {} Link)".format(
                        len(clashes), host_count, link_count
                    )
                else:
                    self.txtClashCount.Text = "{} Total (🟢 {} Link | Host vs Link only)".format(
                        len(clashes), link_count
                    )

                self.txtStatus.Text = "Analysis complete: {} clash elements highlighted in view{}.".format(
                    len(clashes), "" if check_same else " (Host vs Link only)"
                )
                self.progressBar.Value = 100
                do_events()

                if len(clashes) > 0:
                    if check_same:
                        self.txtStatus.Text = u"Analysis complete: {} clashes — 🔴 Red=Host1, 🟠 Orange=Host2, 🟢 Green=Link — rendered in active view.".format(len(clashes))
                    else:
                        self.txtStatus.Text = u"Analysis complete: {} clashes — 🟢 Green=Link (Host vs Link only) — rendered in active view.".format(len(clashes))
                else:
                    self.txtStatus.Text = u"Analysis complete: Zero hard clashes detected in active view. Everything is clear."

            except Exception as ex:
                show_error(u"Clash Analysis Error:\n{}\n\n{}".format(safe_unicode(ex), traceback.format_exc()), "Analysis Error")
            finally:
                self.progressBar.Visibility = Visibility.Collapsed
                self.btnAnalyze.IsEnabled = True
                self.btnClear.IsEnabled = True

        def on_clear(self, sender, e):
            try:
                with SafeTransaction(self.doc, "Clear Clash Analysis"):
                    cleared = clear_clash_analysis(self.doc, self.active_view)

                _clear_cache(self.doc, self.active_view)
                self.lstClashes.ItemsSource = []
                self.txtClashCount.Text = "0 clashes detected"
                self.txtStatus.Text = u"Visual analysis display cleared from view."
            except Exception as ex:
                show_error(u"Failed to clear analysis: {}".format(safe_unicode(ex)), "Error")

        def on_close(self, sender, e):
            self.Close()


    # ── Launcher ──────────────────────────────────────────────────────────────
    current_dark = is_dark_theme()
    try:
        if __shiftclick__:
            current_dark = not current_dark
    except Exception:
        pass

    while True:
        win = DisplayClashWindow(dark_mode=current_dark)

        # Modeless: Show() + Dispatcher.PushFrame() keeps Python scope alive without
        # blocking Revit (same pattern as Check Clash tool).
        try:
            revit_handle = System.IntPtr(uidoc.Application.MainWindowHandle)
            helper = WindowInteropHelper(win)
            helper.Owner = revit_handle
        except Exception:
            pass

        frame = DispatcherFrame()

        def _on_closed(s, e):
            frame.Continue = False

        win.Closed += _on_closed
        win.Show()
        Dispatcher.PushFrame(frame)

        if getattr(win, 'switch_requested', False):
            current_dark = not current_dark
            continue
        break

except Exception as ex:
    _fatal_alert(u"Display Clash Initialization Error:\n\n{}\n\n{}".format(safe_unicode(ex), traceback.format_exc()))
