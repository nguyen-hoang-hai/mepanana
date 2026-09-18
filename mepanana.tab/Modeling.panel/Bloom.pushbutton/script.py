# -*- coding: utf-8 -*-
"""
Auto Bloom MEP Connectors (BL)
Part of mepanana.extension.
"""
__title__ = "Bloom"
__doc__   = "Automatically generates pipe, duct, or conduit stubs from open connectors on fittings, accessories, and equipment.\n\n[Click]: Run Bloom immediately on current selection (or pick elements).\n[Shift-Click]: Open Bloom Settings (stub length, disciplines, auto-connect)."

import os
import sys
import tempfile

def _fatal_alert(err_str):
    try:
        log_dir = tempfile.gettempdir()
        with open(os.path.join(log_dir, "mepanana_bloom_error.log"), "w") as f:
            f.write(err_str)
    except Exception:
        pass

    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        import System.Windows.Forms as WinForms
        WinForms.MessageBox.Show(
            err_str,
            "Auto Bloom - Error Details",
            WinForms.MessageBoxButtons.OK,
            WinForms.MessageBoxIcon.Error
        )
        return
    except Exception:
        pass

    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("Auto Bloom Error", err_str)
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

    from pyrevit import forms, revit, script, EXEC_PARAMS
    from py.auth import require_auth, update_ribbon_state, is_authenticated
    from py.core import get_doc, get_uidoc, safe_unicode
    from py.ui   import setup_window, show_success, show_warning, show_error
    from py.bloom_engine import (
        BloomConfig,
        MEPBloomSelectionFilter,
        get_open_connectors,
        bloom_elements
    )

    if not is_authenticated():
        update_ribbon_state(False)
        if not require_auth():
            sys.exit()

    doc = get_doc()
    if not doc:
        _fatal_alert("Please open a Revit project before launching Auto Bloom.")
        sys.exit()

    uidoc = get_uidoc()

    # ==========================================================================
    # SETTINGS WINDOW CONTROLLER (SHIFT-CLICK)
    # ==========================================================================
    class BloomSettingsWindow(forms.WPFWindow):
        def __init__(self, config):
            xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
            forms.WPFWindow.__init__(self, xaml_path)
            setup_window(self)
            self.config = config

            # Initialize UI controls with stored config
            self.txtStubLength.Text = str(int(self.config.stub_length_mm))
            self.chkPipes.IsChecked = bool(self.config.include_pipes)
            self.chkDucts.IsChecked = bool(self.config.include_ducts)
            self.chkCableTrays.IsChecked = bool(self.config.include_cable_trays)
            self.chkConduits.IsChecked = bool(self.config.include_conduits)
            self.chkAutoConnect.IsChecked = bool(self.config.auto_connect)

            # Wire Routed Event Handlers in Python (Zero inline XAML events rule)
            self.btnSave.Click += self.OnSave
            self.btnCancel.Click += self.OnCancel

            self.btnPreset150.Click += lambda s, e: self.SetPreset(150)
            self.btnPreset200.Click += lambda s, e: self.SetPreset(200)
            self.btnPreset300.Click += lambda s, e: self.SetPreset(300)
            self.btnPreset500.Click += lambda s, e: self.SetPreset(500)

        def SetPreset(self, val):
            self.txtStubLength.Text = str(val)

        def OnSave(self, sender, args):
            try:
                val = float(self.txtStubLength.Text.strip())
                if val <= 10.0:
                    val = 50.0
                self.config.stub_length_mm = val
            except Exception:
                self.config.stub_length_mm = 300.0

            self.config.include_pipes = bool(self.chkPipes.IsChecked)
            self.config.include_ducts = bool(self.chkDucts.IsChecked)
            self.config.include_cable_trays = bool(self.chkCableTrays.IsChecked)
            self.config.include_conduits = bool(self.chkConduits.IsChecked)
            self.config.auto_connect = bool(self.chkAutoConnect.IsChecked)

            self.config.save()
            self.Close()
            show_success(
                u"Bloom settings updated:\n• Stub Length: {} mm\n• Pipes: {}\n• Ducts: {}\n• Cable Trays: {}\n• Conduits: {}\n• Auto-Connect: {}".format(
                    int(self.config.stub_length_mm),
                    u"Enabled" if self.config.include_pipes else u"Disabled",
                    u"Enabled" if self.config.include_ducts else u"Disabled",
                    u"Enabled" if self.config.include_cable_trays else u"Disabled",
                    u"Enabled" if self.config.include_conduits else u"Disabled",
                    u"Enabled" if self.config.auto_connect else u"Disabled"
                ),
                "Bloom Settings"
            )

        def OnCancel(self, sender, args):
            self.Close()

    # ==========================================================================
    # MAIN EXECUTION ROUTINE
    # ==========================================================================
    def run():
        config = BloomConfig()

        # Check if executed in Config Mode (Shift-Click)
        if getattr(EXEC_PARAMS, "config_mode", False):
            win = BloomSettingsWindow(config)
            win.ShowDialog()
            return

        # 1-Click Execution Mode
        elements_to_bloom = []

        # Step 1: Check existing pre-selection
        try:
            sel_ids = uidoc.Selection.GetElementIds()
            if sel_ids and sel_ids.Count > 0:
                for eid in sel_ids:
                    try:
                        el = doc.GetElement(eid)
                        if el and get_open_connectors(el):
                            elements_to_bloom.append(el)
                    except Exception:
                        pass
        except Exception:
            pass

        # Step 2: If nothing selected, prompt interactive single picking
        if not elements_to_bloom:
            try:
                from Autodesk.Revit.UI.Selection import ObjectType
                from Autodesk.Revit.Exceptions import OperationCanceledException

                flt = MEPBloomSelectionFilter()
                picked_ref = uidoc.Selection.PickObject(
                    ObjectType.Element,
                    flt,
                    "Pick an MEP fitting, valve, cable tray, or equipment to bloom"
                )
                if not picked_ref:
                    return

                el = doc.GetElement(picked_ref.ElementId)
                if el:
                    open_conns = get_open_connectors(el)
                    if open_conns:
                        elements_to_bloom.append(el)
                    else:
                        show_warning(
                            u"Selected element has no open connectors.\nPlease pick a fitting, valve, or equipment with unconnected ports.",
                            "Auto Bloom"
                        )
                        return

            except OperationCanceledException:
                return
            except Exception as ex_pick:
                show_error(u"Selection error: {}".format(safe_unicode(ex_pick)), "Auto Bloom")
                return

        if not elements_to_bloom:
            return

        # Step 3: Execute Bloom
        try:
            results = bloom_elements(doc, elements_to_bloom, config)

            if results["total"] > 0:
                summary_lines = []
                if results["pipes"] > 0:
                    summary_lines.append(u"• {} pipe stubs".format(results["pipes"]))
                if results["ducts"] > 0:
                    summary_lines.append(u"• {} duct stubs".format(results["ducts"]))
                if results.get("cable_trays", 0) > 0:
                    summary_lines.append(u"• {} cable tray stubs".format(results["cable_trays"]))
                if results["conduits"] > 0:
                    summary_lines.append(u"• {} conduit stubs".format(results["conduits"]))

                msg = u"Auto Bloom completed successfully!\n" + u"\n".join(summary_lines) + \
                      u"\n\nFrom {} elements (Stub Length: {} mm).".format(
                          results["elements_processed"], int(config.stub_length_mm)
                      )
                show_success(msg, "Auto Bloom Success")
            else:
                show_warning(
                    u"Could not generate stubs for the selected open connectors.\nPlease ensure matching Pipe, Duct, Cable Tray, or Conduit types exist in project.",
                    "Auto Bloom Notice"
                )
        except Exception as ex_bloom:
            show_error(u"Error during Auto Bloom: {}".format(safe_unicode(ex_bloom)), "Auto Bloom Error")

    run()

except Exception as ex:
    import traceback
    _fatal_alert("Auto Bloom failed to initialize:\n" + traceback.format_exc())
