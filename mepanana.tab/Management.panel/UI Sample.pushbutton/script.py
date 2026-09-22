# -*- coding: utf-8 -*-
"""
UI Sample — Adaptive Glassmorphism Design Template
Automatically detects whether Revit is running in Dark Mode or Light Mode,
and applies the corresponding cohesive UI theme.
Part of mepanana.extension.
Author: Hai Nguyen
"""
__title__ = "UI Sample"
__doc__   = "Adaptive glassmorphism UI design template — automatically matches Revit Dark or Light mode.\n\n[Click]: Open UI Sample (Auto Theme)\n[Shift-Click]: Toggle Theme (Force Light / Dark)"

# ==============================================================================
# 2. DYNAMIC LIB RESOLUTION & GATEKEEPER
# ==============================================================================
import os
import sys

lib_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib")
)
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from py.auth import is_authenticated, require_auth, update_ribbon_state

if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()

from py.ui import is_dark_theme

try:
    import clr
    clr.AddReference("System")
    clr.AddReference("PresentationCore")
    clr.AddReference("PresentationFramework")
    clr.AddReference("WindowsBase")

    import System
    import System.Windows.Threading as wt
    from System.Windows import Visibility, UIElement
    from System.Windows.Media.Animation import DoubleAnimation
    from System.Windows.Media.Effects import BlurEffect
    from System.Windows.Interop import WindowInteropHelper

    from pyrevit import forms, script

    # ==========================================================================
    # ADAPTIVE WINDOW CONTROLLER
    # ==========================================================================
    class UISampleAdaptiveWindow(forms.WPFWindow):
        def __init__(self, dark_mode=False):
            self.dark_mode = dark_mode
            xaml_name = "ui_dark.xaml" if dark_mode else "ui_light.xaml"
            ui_path = os.path.join(os.path.dirname(__file__), xaml_name)
            forms.WPFWindow.__init__(self, ui_path)

            self.switch_requested = False
            self._load_watermark()
            self._setup_events()
            self._populate()

        def _load_watermark(self):
            """Load the 32-bit transparent sticker background."""
            try:
                from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
                from System import Uri, UriKind
                img_path = os.path.join(os.path.dirname(__file__), "background.png")
                if os.path.exists(img_path):
                    file_uri = "file:///" + img_path.replace("\\", "/")
                    bmp = BitmapImage()
                    bmp.BeginInit()
                    bmp.UriSource = Uri(file_uri, UriKind.Absolute)
                    bmp.CacheOption = BitmapCacheOption.OnLoad
                    bmp.EndInit()
                    self.watermarkImage.Source = bmp
            except Exception as ex:
                import traceback
                print("Watermark load exception: " + traceback.format_exc())

        def _setup_events(self):
            self.titleBar.MouseLeftButtonDown += self._on_drag
            self.btnClose.Click  += lambda s, e: self.Close()
            self.btnCancel.Click += lambda s, e: self.Close()
            self.btnRun.Click    += self._on_run
            self.chkAdvanced.Click += self._on_advanced_toggle
            if hasattr(self, 'btnStopRunning'):
                self.btnStopRunning.Click += self._on_stop_running
            if hasattr(self, 'btnToggleTheme'):
                self.btnToggleTheme.Click += self._on_toggle_theme

        def _on_toggle_theme(self, sender, e):
            """Dynamically toggle theme between Light and Dark."""
            self.switch_requested = True
            self.Close()

        def _populate(self):
            for d in ["Piping (MEP)", "HVAC (MEP)", "Electrical", "Architecture", "Structure", "All Disciplines"]:
                self.cmbDiscipline.Items.Add(d)
            self.cmbDiscipline.SelectedIndex = 0

            for m in ["Smart Auto", "Manual Override", "Batch Process"]:
                self.cmbMethod.Items.Add(m)
            self.cmbMethod.SelectedIndex = 0

        def _on_drag(self, sender, e):
            try:
                self.DragMove()
            except Exception:
                pass

        def _on_advanced_toggle(self, sender, e):
            checked = self.chkAdvanced.IsChecked
            self.pnlAdvanced.Visibility = Visibility.Visible if checked else Visibility.Collapsed

        def _on_run(self, sender, e):
            self._animate_to_running()

        def _animate_to_running(self):
            base_opacity = 0.25 if self.dark_mode else 0.22

            # 1. Fade out pnlForm smoothly (180ms)
            anim_form_out = DoubleAnimation(1.0, 0.0, System.TimeSpan.FromMilliseconds(180))

            # 2. Smoothly cross-fade watermark from subtle to full color (250ms)
            anim_wm = DoubleAnimation(base_opacity, 1.0, System.TimeSpan.FromMilliseconds(250))
            self.watermarkImage.BeginAnimation(UIElement.OpacityProperty, anim_wm)

            # 3. Smoothly reduce blur to 0 (250ms)
            try:
                if self.watermarkImage.Effect:
                    anim_blur = DoubleAnimation(4.0, 0.0, System.TimeSpan.FromMilliseconds(250))
                    self.watermarkImage.Effect.BeginAnimation(BlurEffect.RadiusProperty, anim_blur)
            except Exception:
                pass

            def _on_form_faded(s, ev):
                self.pnlForm.Visibility = Visibility.Collapsed
                self.pnlRunning.Opacity = 0.0
                self.pnlRunning.Visibility = Visibility.Visible

                # 4. Fade in running dock smoothly (180ms)
                anim_run_in = DoubleAnimation(0.0, 1.0, System.TimeSpan.FromMilliseconds(180))
                self.pnlRunning.BeginAnimation(UIElement.OpacityProperty, anim_run_in)
                self._start_progress_steps()

            anim_form_out.Completed += _on_form_faded
            self.pnlForm.BeginAnimation(UIElement.OpacityProperty, anim_form_out)

        def _start_progress_steps(self):
            self.progressBarRunning.Value = 0
            self.txtRunningTitle.Text = u"Processing 256 Elements\u2026"
            self.txtRunningDetail.Text = u"Initializing routing engine\u2026"
            self.txtRunningPercent.Text = u"0%"
            self.btnStopRunning.Content = u"Cancel"

            steps = [
                (25, u"Scanning model elements in active view\u2026"),
                (55, u"Calculating optimal routing and slopes\u2026"),
                (85, u"Generating fittings and connections\u2026"),
                (100, u"\u2713 Operation completed successfully!"),
            ]
            self._step_idx = 0

            def _on_tick(s2, e2):
                if self._step_idx < len(steps):
                    val, detail = steps[self._step_idx]
                    self.progressBarRunning.Value = val
                    self.txtRunningPercent.Text = u"{}%".format(val)
                    self.txtRunningDetail.Text = detail
                    if val == 100:
                        self.txtRunningTitle.Text = u"\u2713 Completed Successfully!"
                        self.btnStopRunning.Content = u"Done"
                    self._step_idx += 1
                else:
                    self._timer.Stop()
                    def _on_close_tick(s3, e3):
                        self._close_timer.Stop()
                        self._on_stop_running(None, None)
                    self._close_timer = wt.DispatcherTimer()
                    self._close_timer.Interval = System.TimeSpan.FromMilliseconds(900)
                    self._close_timer.Tick += _on_close_tick
                    self._close_timer.Start()

            self._timer = wt.DispatcherTimer()
            self._timer.Interval = System.TimeSpan.FromMilliseconds(500)
            self._timer.Tick += _on_tick
            self._timer.Start()

        def _on_stop_running(self, sender, e):
            if hasattr(self, '_timer') and self._timer.IsEnabled:
                self._timer.Stop()
            if hasattr(self, '_close_timer') and self._close_timer.IsEnabled:
                self._close_timer.Stop()

            base_opacity = 0.25 if self.dark_mode else 0.22

            # Smoothly transition back from Running Mode -> Form
            # 1. Fade out running dock (180ms)
            anim_run_out = DoubleAnimation(1.0, 0.0, System.TimeSpan.FromMilliseconds(180))

            # 2. Fade watermark back to subtle (250ms)
            anim_wm = DoubleAnimation(1.0, base_opacity, System.TimeSpan.FromMilliseconds(250))
            self.watermarkImage.BeginAnimation(UIElement.OpacityProperty, anim_wm)

            try:
                if self.watermarkImage.Effect:
                    anim_blur = DoubleAnimation(0.0, 4.0, System.TimeSpan.FromMilliseconds(250))
                    self.watermarkImage.Effect.BeginAnimation(BlurEffect.RadiusProperty, anim_blur)
            except Exception:
                pass

            def _on_running_faded(s, ev):
                self.pnlRunning.Visibility = Visibility.Collapsed
                self.pnlForm.Opacity = 0.0
                self.pnlForm.Visibility = Visibility.Visible
                self.btnStopRunning.Content = u"Cancel"
                self.txtStatus.Text = u"Ready (Last run: 256 elements updated)"

                # 3. Fade in form smoothly (180ms)
                anim_form_in = DoubleAnimation(0.0, 1.0, System.TimeSpan.FromMilliseconds(180))
                self.pnlForm.BeginAnimation(UIElement.OpacityProperty, anim_form_in)

            anim_run_out.Completed += _on_running_faded
            self.pnlRunning.BeginAnimation(UIElement.OpacityProperty, anim_run_out)


    # ==========================================================================
    # LAUNCHER LOOP (Supports dynamic in-window theme switching)
    # ==========================================================================
    # 1. Determine active theme (Auto detect Revit theme, inverted on Shift-Click)
    current_dark = is_dark_theme()
    try:
        if __shiftclick__:
            current_dark = not current_dark
    except Exception:
        pass

    # 2. Display window with automatic theme (can toggle inside window)
    while True:
        win = UISampleAdaptiveWindow(dark_mode=current_dark)
        win.ShowDialog()
        if getattr(win, 'switch_requested', False):
            current_dark = not current_dark
            continue
        break

except Exception:
    import traceback
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("UI Sample Error", traceback.format_exc())
    except Exception:
        pass
