# -*- coding: utf-8 -*-
"""
script.py - MEP Route Tool Controller Window
Interactive routing tool for connecting parallel MEP elements with custom angled offsets.

Part of mepanana.extension.
Author: Hai Nguyen
"""
# ── GATEKEEPER BOILERPLATE (MANDATORY) ───────────────────────────────────────
import sys
from py.auth import require_auth, update_ribbon_state, is_authenticated
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys

from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import script, forms
from py.core import get_doc, get_uidoc, safe_unicode
from py.ui import setup_modern_window, is_dark_theme, show_warning, show_error, show_info
from py.mep_route_engine import MEPElementFilter, route_mep_elements

doc = get_doc()
uidoc = get_uidoc()
if not doc:
    show_warning(u"Please open a Revit project before using MEP Route.", "Warning")
    sys.exit()


class RouteWindow(forms.WPFWindow):
    """MEP Angled Routing Controller Window."""

    def __init__(self, dark_mode=False):
        self.dark_mode = dark_mode
        xaml_name = "ui_dark.xaml" if dark_mode else "ui_light.xaml"
        xaml_path = os.path.join(os.path.dirname(__file__), xaml_name)
        forms.WPFWindow.__init__(self, xaml_path)
        setup_modern_window(self, dark_mode=dark_mode)

        self.angle_value = None

        # Wire event handlers dynamically (Zero inline events in XAML rule)
        self.btnCancel.Click += self.OnCancel
        self.btnRoute.Click += self.OnPickAndRoute
        self.cmbAngle.SelectionChanged += self.OnAngleChanged
        self.txtCustom.TextChanged += self.OnCustomTextChanged

    def OnCancel(self, sender, args):
        """Closes the dialog without routing."""
        self.angle_value = None
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
        """Validates angle, stores it, and closes dialog to begin picking."""
        angle_val = self.get_selected_angle()
        if angle_val is None:
            return

        self.angle_value = angle_val
        self.Close()


if __name__ == "__main__":
    current_dark = is_dark_theme()
    try:
        if __shiftclick__:
            current_dark = not current_dark
    except Exception:
        pass

    angle_val = None
    while True:
        win = RouteWindow(dark_mode=current_dark)
        win.ShowDialog()
        if getattr(win, 'switch_requested', False):
            current_dark = not current_dark
            continue
        angle_val = win.angle_value
        break

    if angle_val is not None:
        # Continuous selection loop on Revit main thread
        while True:
            try:
                ref1 = uidoc.Selection.PickObject(
                    ObjectType.Element,
                    MEPElementFilter(),
                    "Select FIRST parallel MEP Element (Press ESC to finish)"
                )
                ref2 = uidoc.Selection.PickObject(
                    ObjectType.Element,
                    MEPElementFilter(),
                    "Select SECOND parallel MEP Element (Press ESC to finish)"
                )

                elem1 = doc.GetElement(ref1)
                elem2 = doc.GetElement(ref2)

                # Guard against picking the same element twice
                if elem1.Id.IntegerValue == elem2.Id.IntegerValue:
                    show_warning("Cannot route an element to itself. Please pick 2 distinct parallel elements.")
                    continue

                # Execute routing
                success, msg = route_mep_elements(doc, elem1, elem2, angle_val)
                if not success:
                    show_warning(msg)

            except OperationCanceledException:
                # User pressed ESC to finish gracefully
                break
            except Exception as ex:
                show_error("Routing operation failed:\n{}".format(safe_unicode(ex)))
                break
