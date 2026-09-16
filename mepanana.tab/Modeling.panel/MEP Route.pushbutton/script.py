# -*- coding: utf-8 -*-
"""
script.py - MEP Route Tool Controller Window
Interactive routing tool for connecting parallel MEP elements with custom angled offsets.

Part of mepanana.extension.
Author: Hai Nguyen
"""
# ── GATEKEEPER BOILERPLATE (MANDATORY) ───────────────────────────────────────
from py.auth import is_authorized
if not is_authorized():
    from py.ui import show_warning
    show_warning("MEPANANA Access Required", "Your license is invalid or expired.\nPlease activate your extension.")
    import sys
    sys.exit()
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys

from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import script, forms
from py.core import get_doc, get_uidoc, safe_unicode
from py.ui import setup_window, show_warning, show_error, show_info
from py.mep_route_engine import MEPElementFilter, route_mep_elements

doc = get_doc()
uidoc = get_uidoc()


class RouteWindow(forms.WPFWindow):
    """MEP Angled Routing Controller Window."""

    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        setup_window(self)

        # Wire event handlers dynamically (Zero inline events in XAML rule)
        self.btnCancel.Click += self.OnCancel
        self.btnRoute.Click += self.OnPickAndRoute
        self.cmbAngle.SelectionChanged += self.OnAngleChanged
        self.txtCustom.TextChanged += self.OnCustomTextChanged

    def OnCancel(self, sender, args):
        """Closes the dialog."""
        self.Close()

    def OnAngleChanged(self, sender, args):
        """Enables the custom angle textbox when 'Custom' is selected."""
        if self.cmbAngle.SelectedItem:
            content = str(self.cmbAngle.SelectedItem.Content)
            if "Custom" in content:
                self.txtCustom.IsEnabled = True
                try:
                    self.txtCustom.Focus()
                except Exception:
                    pass
            else:
                self.txtCustom.IsEnabled = False
                self.txtCustom.Text = ""

    def OnCustomTextChanged(self, sender, args):
        """Filters input in real-time to only permit valid positive floats."""
        current_text = sender.Text
        valid_chars = []
        dot_count = 0

        for char in current_text:
            if char.isdigit():
                valid_chars.append(char)
            elif char == "." and dot_count == 0:
                valid_chars.append(char)
                dot_count += 1

        cleaned = "".join(valid_chars)
        if current_text != cleaned:
            sender.TextChanged -= self.OnCustomTextChanged
            sender.Text = cleaned
            sender.SelectionStart = len(cleaned)
            sender.TextChanged += self.OnCustomTextChanged

    def get_selected_angle(self):
        """
        Parses and validates the currently selected angle.
        Returns: float (angle in degrees) or None if invalid.
        """
        if not self.cmbAngle.SelectedItem:
            return 45.0

        content = str(self.cmbAngle.SelectedItem.Content)
        if "Custom" in content:
            raw = self.txtCustom.Text.strip()
            if not raw or raw == ".":
                show_warning("Please enter a custom angle value (e.g. 45 or 30).")
                return None
            try:
                val = float(raw)
                if val < 2.0 or val > 95.0:
                    show_warning("Elbow routing angle must be between 2.0° and 95.0°.")
                    return None
                return val
            except Exception:
                show_warning("Invalid numeric value for custom angle.")
                return None
        else:
            clean_str = content.replace(u"\xb0", "").strip()
            try:
                return float(clean_str)
            except Exception:
                return 45.0

    def OnPickAndRoute(self, sender, args):
        """
        Hides the window and runs a continuous element-picking loop.
        Re-displays the window gracefully when the user presses ESC.
        """
        angle_val = self.get_selected_angle()
        if angle_val is None:
            return

        picked_count = 0
        self.txtStatus.Text = "Picking elements in Revit..."

        # Anti-deadlock window hiding during interactive picking
        with forms.HideWindow(self):
            while True:
                try:
                    ref1 = uidoc.Selection.PickObject(
                        ObjectType.Element,
                        MEPElementFilter(),
                        "Select FIRST parallel MEP Element (Press ESC to return to window)"
                    )
                    ref2 = uidoc.Selection.PickObject(
                        ObjectType.Element,
                        MEPElementFilter(),
                        "Select SECOND parallel MEP Element (Press ESC to return to window)"
                    )

                    elem1 = doc.GetElement(ref1)
                    elem2 = doc.GetElement(ref2)

                    # Guard against picking the same element twice
                    if elem1.Id.IntegerValue == elem2.Id.IntegerValue:
                        show_warning("Cannot route an element to itself. Please pick 2 distinct parallel elements.")
                        continue

                    # Execute routing
                    success, msg = route_mep_elements(doc, elem1, elem2, angle_val)
                    if success:
                        picked_count += 1
                    else:
                        show_warning(msg)

                except OperationCanceledException:
                    # User pressed ESC to finish / return to configuration
                    break
                except Exception as ex:
                    show_error("Routing operation failed:\n{}".format(safe_unicode(ex)))
                    break

        if picked_count > 0:
            self.txtStatus.Text = "Completed {} angled route(s). Ready.".format(picked_count)
        else:
            self.txtStatus.Text = "Ready"


if __name__ == "__main__":
    xaml_path = script.get_bundle_file("ui.xaml")
    if os.path.exists(xaml_path):
        win = RouteWindow(xaml_path)
        win.ShowDialog()
    else:
        show_error("UI file 'ui.xaml' not found.")
