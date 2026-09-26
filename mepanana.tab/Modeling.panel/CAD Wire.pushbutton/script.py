# -*- coding: utf-8 -*-
"""
CAD Wire to Revit (CW)
Part of mepanana.extension.
"""
__title__ = "CAD Wire"
__doc__   = "Convert 2D AutoCAD wiring curves into native Revit Wires with automatic category detection and circuit creation."

import os
import sys
import traceback

import tempfile

def _fatal_alert(err_str):
    try:
        log_dir = tempfile.gettempdir()
        with open(os.path.join(log_dir, "mepanana_cadwire_error.log"), "w") as f:
            f.write(err_str)
    except Exception:
        pass

    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        import System.Windows.Forms as WinForms
        WinForms.MessageBox.Show(
            err_str,
            "CAD Wire - Error Details",
            WinForms.MessageBoxButtons.OK,
            WinForms.MessageBoxIcon.Error
        )
        return
    except Exception:
        pass

    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("CAD Wire Error", err_str)
    except Exception:
        pass

# ── 6-Line Security Gatekeeper Boilerplate ───────────────────────────────────
_lib_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

from py.auth import require_auth, update_ribbon_state, is_authenticated
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()
# ─────────────────────────────────────────────────────────────────────────────

try:
    import clr
    clr.AddReference("System")
    clr.AddReference("PresentationCore")
    clr.AddReference("PresentationFramework")
    clr.AddReference("WindowsBase")
    clr.AddReference("RevitAPI")
    clr.AddReference("RevitAPIUI")

    from System.Windows import Visibility
    from Autodesk.Revit.DB import ImportInstance, FilteredElementCollector, BuiltInCategory, ElementId

    from pyrevit import forms, revit, script

    from py.core import get_doc, get_uidoc, SafeTransaction, SafeTransactionGroup, mm_to_ft, safe_unicode
    from py.ui   import setup_modern_window, is_dark_theme, show_warning, show_error, yield_dispatcher_every, RunningModeManager
    from py.cad_wire_engine import (
        get_cad_links_in_view, get_wire_types, get_electrical_panels,
        extract_curves_from_cad, stitch_curves_to_paths,
        get_electrical_devices_in_view, split_paths_by_devices,
        create_revit_wires
    )




    doc = get_doc()
    if not doc:
        _fatal_alert("Please open a Revit project before launching CAD Wire.")
        sys.exit()

    uidoc = get_uidoc()

    # ==========================================================================
    # MAIN WINDOW CONTROLLER
    # ==========================================================================
    class CadWireWindow(forms.WPFWindow):
        def __init__(self, dark_mode=False):
            self.dark_mode = dark_mode
            xaml_name = "ui_dark.xaml" if dark_mode else "ui_light.xaml"
            xaml_path = os.path.join(os.path.dirname(__file__), xaml_name)
            forms.WPFWindow.__init__(self, xaml_path)
            setup_modern_window(self, dark_mode=dark_mode)
            self.rmm = RunningModeManager(self, dark_mode=dark_mode)

            self.action = "CANCEL"
            self.active_view = doc.ActiveView

            self.cad_map = {}
            self.wire_type_map = {}
            self.panel_map = {}
            self.cached_devices = []

            self._load_cad_links()
            self._load_wire_types()
            self._load_panels()
            self._scan_active_view_devices()

            self.btnRun.Click += self.on_run
            self.btnCancel.Click += self.on_cancel

        def _load_cad_links(self):
            cad_items = get_cad_links_in_view(doc, self.active_view)
            cad_names = []
            for item in cad_items:
                if item.DisplayName not in self.cad_map:
                    self.cad_map[item.DisplayName] = item.Element
                    cad_names.append(item.DisplayName)

            self.cmbCadLink.ItemsSource = None
            self.cmbCadLink.ItemsSource = cad_names
            if cad_names:
                self.cmbCadLink.SelectedIndex = 0

        def _load_wire_types(self):
            raw_types = get_wire_types(doc)
            names = []
            for wt in raw_types:
                self.wire_type_map[wt.DisplayName] = wt.Id
                names.append(wt.DisplayName)
            self.cmbWireType.ItemsSource = names
            if names:
                self.cmbWireType.SelectedIndex = 0

        def _load_panels(self):
            raw_panels = get_electrical_panels(doc)
            names = []
            for p in raw_panels:
                self.panel_map[p.DisplayName] = p.Element
                names.append(p.DisplayName)
            self.cmbPanel.ItemsSource = names
            if names:
                self.cmbPanel.SelectedIndex = 0

        def _scan_active_view_devices(self):
            devices, cat_breakdown = get_electrical_devices_in_view(doc, self.active_view)
            self.cached_devices = devices

            total_count = len(devices)
            if total_count > 0:
                parts = []
                for cat_name, cnt in sorted(cat_breakdown.items(), key=lambda x: -x[1]):
                    parts.append("{}: {}".format(cat_name, cnt))
                breakdown_str = " | ".join(parts)
                self.txtDeviceStatus.Text = "Auto-detected {} elements:\n{}".format(total_count, breakdown_str)
            else:
                self.txtDeviceStatus.Text = "No electrical devices found in active view."

        def on_cancel(self, sender, e):
            self.action = "CANCEL"
            self.Close()

        def on_run(self, sender, e):
            cad_name = self.cmbCadLink.SelectedItem
            if not cad_name or cad_name not in self.cad_map:
                show_warning("Please select a CAD link in the current active view.", "No CAD Selected")
                return

            wire_name = self.cmbWireType.SelectedItem
            if not wire_name or wire_name not in self.wire_type_map:
                show_warning("Please select a Revit Wire Type.", "No Wire Type")
                return

            try:
                snap_radius_mm = float(self.txtSnapRadius.Text.strip())
                if snap_radius_mm <= 0:
                    snap_radius_mm = 600.0
            except Exception:
                show_warning("Invalid Device Snap Radius. Please enter a valid number (e.g. 600).", "Invalid Input")
                return

            selected_cad = self.cad_map[cad_name]
            selected_wire_type = self.wire_type_map[wire_name]
            snap_radius_ft = mm_to_ft(snap_radius_mm)

            panel_name = self.cmbPanel.SelectedItem
            selected_panel = self.panel_map.get(panel_name) if panel_name else None

            self.btnRun.IsEnabled = False
            self.rmm.start(title=u"Converting Wires\u2026", detail=u"Extracting CAD curves\u2026")

            try:
                view_elev = self.active_view.GenLevel.Elevation if (hasattr(self.active_view, 'GenLevel') and self.active_view.GenLevel) else None
                raw_curves = extract_curves_from_cad(selected_cad, view_elevation=view_elev)
                
                if not raw_curves:
                    self.rmm.restore_form(status_text=u"No curves found")
                    self.btnRun.IsEnabled = True
                    show_warning("No valid wiring curves found in selected CAD link.", "No Curves Found")
                    return

                self.rmm.update(30, detail="Stitching {} curve segments...".format(len(raw_curves)))

                stitched_paths = stitch_curves_to_paths(raw_curves)
                if not stitched_paths:
                    self.rmm.restore_form(status_text=u"Empty paths")
                    self.btnRun.IsEnabled = True
                    show_warning("Could not form continuous wiring paths from the CAD curves.", "Empty Paths")
                    return

                self.rmm.update(50, detail="Sub-dividing paths at active view devices...")

                # Retrieve all active view devices
                all_devices, _ = get_electrical_devices_in_view(doc, self.active_view)

                if not all_devices:
                    self.rmm.restore_form(status_text=u"No devices found")
                    self.btnRun.IsEnabled = True
                    show_warning("No electrical devices found in active view.", "No Devices Found")
                    return

                # Sub-divide continuous lines whenever devices lie on the path
                split_paths = split_paths_by_devices(stitched_paths, all_devices, snap_radius_ft=snap_radius_ft)

                self.rmm.update(70, detail="Creating Circuits & Wires in database...")

                def update_prog(cur, tot):
                    if self.rmm.is_cancelled:
                        raise Exception("Wire conversion cancelled by user.")
                    if tot > 0:
                        pct = 70 + int((float(cur) / tot) * 28)
                        self.rmm.update(min(98, pct), detail="Creating wire {}/{}...".format(cur, tot))

                with SafeTransactionGroup(doc, "CAD Wire Conversion"):
                    with SafeTransaction(doc, "CAD Wire & Circuit"):
                        result = create_revit_wires(
                            doc=doc,
                            active_view=self.active_view,
                            wire_type_id=selected_wire_type,
                            matched_paths=split_paths,
                            panel_element=selected_panel,
                            progress_callback=update_prog
                        )

                if result["success"]:
                    panel_label = panel_name if selected_panel else "None"
                    detail_str = u"{} wires, {} devices, {} circuits. Panel: {}.".format(
                        result["wires_created"],
                        result["devices_connected"],
                        result["circuits_created"],
                        panel_label
                    )
                    self.rmm.finish(
                        title=u"\u2713 Conversion Complete!",
                        detail=detail_str,
                        auto_return_delay_ms=900,
                        status_text=u"Complete — " + detail_str
                    )
                    self.action = "SUCCESS"
                    self.Close()
                else:
                    self.rmm.restore_form(status_text=u"Failed to create wires")
                    err_text = "\n".join([safe_unicode(e) for e in result["errors"][:3]]) if result["errors"] else u"Unknown error."
                    show_error(u"Failed to create wires:\n{}".format(err_text), "Creation Failed")
                    self.txtStatus.Text = "Failed to create wires."

            except Exception as ex:
                self.rmm.restore_form(status_text=u"Error occurred")
                err_msg = safe_unicode(ex)
                if u"cancelled" not in err_msg.lower():
                    show_error(u"An error occurred during wire conversion:\n{}".format(err_msg), "Execution Error")
            finally:
                self.btnRun.IsEnabled = True

    # Launch Window
    current_dark = is_dark_theme()
    try:
        if __shiftclick__:
            current_dark = not current_dark
    except Exception:
        pass

    while True:
        win = CadWireWindow(dark_mode=current_dark)
        win.ShowDialog()
        if getattr(win, 'switch_requested', False):
            current_dark = not current_dark
            continue
        break

except Exception as global_ex:
    _fatal_alert("GLOBAL FATAL ERROR in CAD Wire:\n\n" + traceback.format_exc())

