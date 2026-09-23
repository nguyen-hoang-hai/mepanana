# -*- coding: utf-8 -*-
"""
Connect To - Multi-tier Intelligent MEP Connection Tool (CT)
Direct Join, Collinear Extension/Bridging, Corner Elbows, and Branch Tees.

Part of mepanana.extension.
Author: Hai Nguyen
"""
__title__ = "Connect To"
__doc__   = "Intelligently connects pipes, ducts, cable trays, and conduits.\n\n[Click]: Enter continuous interactive connection mode (pick pairs, Esc to exit).\n[Shift-Click]: Open Connect To Settings."

# ── GATEKEEPER BOILERPLATE (MANDATORY) ───────────────────────────────────────
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

import os
import tempfile
import traceback

def _fatal_alert(err_str):
    try:
        log_dir = tempfile.gettempdir()
        with open(os.path.join(log_dir, "mepanana_connect_to_error.log"), "w") as f:
            f.write(err_str)
    except Exception:
        pass

    try:
        from py.ui import show_error
        show_error(err_str, "Connect To")
        return
    except Exception:
        pass

    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("Connect To Error", err_str)
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

    from Autodesk.Revit.UI.Selection import ObjectType
    from Autodesk.Revit.Exceptions import OperationCanceledException

    from pyrevit import forms, revit, script, EXEC_PARAMS
    from py.core import get_doc, get_uidoc, SafeTransaction, safe_unicode
    from py.ui   import setup_modern_window, is_dark_theme, show_warning, show_error, show_info
    from py.connect_to_engine import (
        ConnectToConfig,
        MEPConnectSelectionFilter,
        connect_elements
    )

    doc = get_doc()
    if not doc:
        _fatal_alert("Please open a Revit project before launching Connect To.")
        sys.exit()

    uidoc = get_uidoc()

    # ==========================================================================
    # SETTINGS WINDOW CONTROLLER (SHIFT-CLICK)
    # ==========================================================================
    class ConnectToSettingsWindow(forms.WPFWindow):
        def __init__(self, config, dark_mode=False):
            self.dark_mode = dark_mode
            xaml_name = "ui_dark.xaml" if dark_mode else "ui_light.xaml"
            xaml_path = os.path.join(os.path.dirname(__file__), xaml_name)
            forms.WPFWindow.__init__(self, xaml_path)
            setup_modern_window(self, dark_mode=dark_mode)
            self.config = config

            # Populate controls from stored config
            self.txtMaxOffset.Text = str(int(self.config.max_align_offset_mm))
            self.chkAllowMove.IsChecked = bool(self.config.allow_align_move)

            # Wire events dynamically (Zero inline events rule)
            self.btnSave.Click += self.OnSave
            self.btnCancel.Click += self.OnCancel

            self.btnPreset25.Click += lambda s, e: self.SetPreset(25)
            self.btnPreset50.Click += lambda s, e: self.SetPreset(50)
            self.btnPreset100.Click += lambda s, e: self.SetPreset(100)
            self.btnPreset200.Click += lambda s, e: self.SetPreset(200)

        def SetPreset(self, val):
            self.txtMaxOffset.Text = str(val)

        def OnSave(self, sender, args):
            try:
                raw_txt = self.txtMaxOffset.Text.strip() if hasattr(self, 'txtMaxOffset') and self.txtMaxOffset.Text else ""
                val = float(raw_txt) if raw_txt else 100.0
                if val < 5.0:
                    val = 5.0
                elif val > 1000.0:
                    val = 1000.0
                self.config.max_align_offset_mm = val
            except Exception:
                self.config.max_align_offset_mm = 100.0

            self.config.allow_align_move = bool(self.chkAllowMove.IsChecked)
            self.config.preferred_mode = "Auto"

            self.config.save()
            self.Close()

        def OnCancel(self, sender, args):
            self.Close()

    # ==========================================================================
    # MAIN EXECUTION ROUTINE
    # ==========================================================================
    def run():
        config = ConnectToConfig()

        # Check if launched in Config Mode (Shift-Click)
        if getattr(EXEC_PARAMS, "config_mode", False):
            current_dark = is_dark_theme()
            while True:
                win = ConnectToSettingsWindow(config, dark_mode=current_dark)
                win.ShowDialog()
                if getattr(win, 'switch_requested', False):
                    current_dark = not current_dark
                    continue
                break
            return

        # 1. Pre-selection check: If exactly 2 elements are pre-selected
        try:
            sel_ids = list(uidoc.Selection.GetElementIds())
            if len(sel_ids) == 2:
                el1 = doc.GetElement(sel_ids[0])
                el2 = doc.GetElement(sel_ids[1])
                if el1 and el2:
                    with SafeTransaction(doc, "Connect To"):
                        ok, msg = connect_elements(doc, el1, None, el2, None, config)
                    if not ok:
                        show_warning(msg, "Connect To")
                    return
        except Exception:
            pass

        # 2. Interactive Continuous Connection Loop
        flt = MEPConnectSelectionFilter()
        connection_count = 0

        while True:
            try:
                # Step A: Pick first element or connector
                prompt1 = "Select FIRST MEP element or connector (Esc to finish)" if connection_count == 0 else \
                          "Select FIRST MEP element for next connection (Esc to finish)"
                ref1 = uidoc.Selection.PickObject(ObjectType.Element, flt, prompt1)
                if not ref1:
                    break

                el1 = doc.GetElement(ref1.ElementId)
                pt1 = ref1.GlobalPoint

                # Step B: Pick second element or connector
                ref2 = uidoc.Selection.PickObject(ObjectType.Element, flt, "Select SECOND MEP element or connector")
                if not ref2:
                    break

                el2 = doc.GetElement(ref2.ElementId)
                pt2 = ref2.GlobalPoint

                # Step C: Execute connection within atomic SafeTransaction
                with SafeTransaction(doc, "Connect To"):
                    ok, msg = connect_elements(doc, el1, pt1, el2, pt2, config)

                if ok:
                    connection_count += 1
                else:
                    show_warning(msg, "Connect To")

            except OperationCanceledException:
                # User pressed Esc to terminate interactive loop
                break
            except Exception as ex_loop:
                show_error(u"Connect To error: {}".format(safe_unicode(ex_loop)), "Connect To")
                break

    run()

except Exception as ex:
    _fatal_alert("Connect To failed to initialize:\n" + traceback.format_exc())
