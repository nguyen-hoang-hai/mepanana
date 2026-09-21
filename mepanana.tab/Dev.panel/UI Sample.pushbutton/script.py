# -*- coding: utf-8 -*-
"""
UI Sample — Dark Glassmorphism Design Template
Demonstrates: ambient blur glow background, glass cards, mepanana gradient
              button, dark ComboBox/CheckBox, inline stats row.

Part of mepanana.extension.
Author: Hai Nguyen
"""
__title__ = "UI Sample"
__doc__   = "Dark glassmorphism UI design template — new color system, ambient blur background, modern card layout."

import os
import sys

_lib_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

try:
    import clr
    clr.AddReference("System")
    clr.AddReference("PresentationCore")
    clr.AddReference("PresentationFramework")
    clr.AddReference("WindowsBase")

    import System
    import System.Windows.Threading as wt
    from System.Windows import Visibility
    from System.Windows.Interop import WindowInteropHelper

    from pyrevit import forms
    from py.ui import setup_window

    # ==========================================================================
    # WINDOW CONTROLLER
    # ==========================================================================
    class UISampleWindow(forms.WPFWindow):
        def __init__(self):
            ui_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
            forms.WPFWindow.__init__(self, ui_path)
            setup_window(self)
            self._setup_events()
            self._populate()

        def _setup_events(self):
            # ── Title bar drag ──────────────────────────────────────────────
            self.titleBar.MouseLeftButtonDown += self._on_drag

            # ── Window buttons ──────────────────────────────────────────────
            self.btnClose.Click  += lambda s, e: self.Close()
            self.btnCancel.Click += lambda s, e: self.Close()
            self.btnRun.Click    += self._on_run

            # ── Advanced panel toggle ───────────────────────────────────────
            self.chkAdvanced.Click += self._on_advanced_toggle

        def _populate(self):
            """Populate ComboBox items."""
            for d in ["Piping (MEP)", "HVAC (MEP)", "Electrical", "Architecture", "Structure", "All Disciplines"]:
                self.cmbDiscipline.Items.Add(d)
            self.cmbDiscipline.SelectedIndex = 0

            for m in ["Smart Auto", "Manual Override", "Batch Process"]:
                self.cmbMethod.Items.Add(m)
            self.cmbMethod.SelectedIndex = 0

        # ── Handlers ──────────────────────────────────────────────────────────
        def _on_drag(self, sender, e):
            try:
                self.DragMove()
            except Exception:
                pass

        def _on_advanced_toggle(self, sender, e):
            checked = self.chkAdvanced.IsChecked
            self.pnlAdvanced.Visibility = Visibility.Visible if checked else Visibility.Collapsed

        def _on_run(self, sender, e):
            """Simulate a run operation with indeterminate progress bar."""
            self.progressBorder.Visibility = Visibility.Visible
            self.progressBar.Visibility    = Visibility.Visible
            self.btnRun.IsEnabled          = False
            self.btnCancel.IsEnabled       = False
            self.txtStatus.Text            = u"Processing…"

            def _on_tick(s2, e2):
                _timer.Stop()
                self.progressBorder.Visibility = Visibility.Collapsed
                self.progressBar.Visibility    = Visibility.Collapsed
                self.btnRun.IsEnabled          = True
                self.btnCancel.IsEnabled       = True
                self.txtStatus.Text            = u"Ready"

            _timer = wt.DispatcherTimer()
            _timer.Interval = System.TimeSpan.FromSeconds(1.8)
            _timer.Tick    += _on_tick
            _timer.Start()

    # Launch window
    win = UISampleWindow()
    win.ShowDialog()

except Exception as _ex:
    import traceback
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("UI Sample Error", traceback.format_exc())
    except Exception:
        pass
