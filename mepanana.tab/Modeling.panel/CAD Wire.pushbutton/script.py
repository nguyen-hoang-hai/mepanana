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

    from py.auth import require_auth, update_ribbon_state, is_authenticated
    from py.core import get_doc, get_uidoc, SafeTransaction, SafeTransactionGroup, mm_to_ft, safe_unicode
    from py.ui   import setup_window, show_info, show_warning, show_error, yield_dispatcher_every
    from py.cad_wire_engine import (
        get_cad_links_in_view, get_wire_types, get_electrical_panels,
        extract_curves_from_cad, stitch_curves_to_paths,
        get_electrical_devices_in_view, split_paths_by_devices,
        create_revit_wires
    )

    if not is_authenticated():
        update_ribbon_state(False)
        if not require_auth():
            sys.exit()


    doc = get_doc()
    if not doc:
        _fatal_alert("Please open a Revit project before launching CAD Wire.")
        sys.exit()

    uidoc = get_uidoc()

    # ==========================================================================
    # MAIN WINDOW CONTROLLER
    # ==========================================================================
    class CadWireWindow(forms.WPFWindow):
        def __init__(self):
            xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
            forms.WPFWindow.__init__(self, xaml_path)
            setup_window(self)

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

            self.progressBar.Visibility = Visibility.Visible
            self.progressBar.Value = 10
            self.txtStatus.Text = "Extracting CAD curves..."
            self.btnRun.IsEnabled = False

            try:
                view_elev = self.active_view.GenLevel.Elevation if (hasattr(self.active_view, 'GenLevel') and self.active_view.GenLevel) else None
                raw_curves = extract_curves_from_cad(selected_cad, view_elevation=view_elev)
                
                if not raw_curves:
                    self.progressBar.Visibility = Visibility.Collapsed
                    self.btnRun.IsEnabled = True
                    show_warning("No valid wiring curves found in selected CAD link.", "No Curves Found")
                    return

                self.progressBar.Value = 30
                self.txtStatus.Text = "Stitching {} curve segments...".format(len(raw_curves))

                stitched_paths = stitch_curves_to_paths(raw_curves)
                if not stitched_paths:
                    self.progressBar.Visibility = Visibility.Collapsed
                    self.btnRun.IsEnabled = True
                    show_warning("Could not form continuous wiring paths from the CAD curves.", "Empty Paths")
                    return

                self.progressBar.Value = 50
                self.txtStatus.Text = "Sub-dividing paths at active view devices..."

                # Retrieve all active view devices
                all_devices, _ = get_electrical_devices_in_view(doc, self.active_view)

                if not all_devices:
                    self.progressBar.Visibility = Visibility.Collapsed
                    self.btnRun.IsEnabled = True
                    show_warning("No electrical devices found in active view.", "No Devices Found")
                    return

                # Sub-divide continuous lines whenever devices lie on the path
                split_paths = split_paths_by_devices(stitched_paths, all_devices, snap_radius_ft=snap_radius_ft)

                self.progressBar.Value = 70
                self.txtStatus.Text = "Creating Circuits & Wires in database..."

                def update_prog(cur, tot):
                    if tot > 0:
                        pct = 70 + int((float(cur) / tot) * 25)
                        self.progressBar.Value = min(98, pct)
                        self.txtStatus.Text = "Creating wire {}/{}...".format(cur, tot)
                        yield_dispatcher_every(cur, batch_size=15)

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

                self.progressBar.Value = 100
                self.progressBar.Visibility = Visibility.Collapsed
                self.btnRun.IsEnabled = True

                if result["success"]:
                    self.txtStatus.Text = "Completed: {} wires, {} circuits.".format(
                        result["wires_created"], result["circuits_created"]
                    )
                    panel_label = panel_name if selected_panel else "None"
                    summary_msg = (
                        u"CAD Wire & Circuit conversion completed successfully!\n\n"
                        u"• Wires Created: {}\n"
                        u"• Devices Connected: {}\n"
                        u"• Circuits Created: {}\n"
                        u"• Panelboard Assigned: {}"
                    ).format(
                        result["wires_created"],
                        result["devices_connected"],
                        result["circuits_created"],
                        panel_label
                    )
                    show_info(summary_msg, "Conversion Summary")
                    self.action = "SUCCESS"
                    self.Close()
                else:
                    err_text = "\n".join([safe_unicode(e) for e in result["errors"][:3]]) if result["errors"] else u"Unknown error."
                    show_error(u"Failed to create wires:\n{}".format(err_text), "Creation Failed")
                    self.txtStatus.Text = "Failed to create wires."

            except Exception as ex:
                self.progressBar.Visibility = Visibility.Collapsed
                self.btnRun.IsEnabled = True
                show_error(u"An error occurred during wire conversion:\n{}".format(safe_unicode(ex)), "Execution Error")
                self.txtStatus.Text = "Error occurred."

    # Launch Window
    win = CadWireWindow()
    win.ShowDialog()

except Exception as global_ex:
    _fatal_alert("GLOBAL FATAL ERROR in CAD Wire:\n\n" + traceback.format_exc())

