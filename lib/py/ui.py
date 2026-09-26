# -*- coding: utf-8 -*-
"""
ui.py - Shared WPF UI Utilities & Synchronized Modern Notification Dialogs
Part of mepanana.extension.
"""
import os
import sys
from pyrevit import forms

try:
    import clr
    clr.AddReference("PresentationCore")
    clr.AddReference("PresentationFramework")
    clr.AddReference("WindowsBase")
    import System
    from System import Uri, UriKind
    from System.Windows import ResourceDictionary, Visibility, UIElement
    from System.Windows.Interop import WindowInteropHelper
    from System.Windows.Input import Key
    from System.Windows.Media import SolidColorBrush, Color
    from System.Windows.Media.Animation import DoubleAnimation
    from System.Windows.Media.Effects import BlurEffect
except Exception:
    pass


def setup_window(window, set_revit_owner=True):
    """Applies mepanana theme.xaml, sets Revit as owner (if set_revit_owner), binds ESC to close."""
    try:
        theme_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'theme.xaml'))
        rd = ResourceDictionary()
        rd.Source = Uri(theme_path, UriKind.Absolute)
        window.Resources.MergedDictionaries.Add(rd)
    except Exception as e:
        print("Failed to load theme.xaml: {}".format(e))

    if set_revit_owner:
        try:
            from pyrevit import HOST_APP
            if HOST_APP and hasattr(HOST_APP, "uiapp") and HOST_APP.uiapp:
                WindowInteropHelper(window).Owner = HOST_APP.uiapp.MainWindowHandle
        except Exception:
            pass

    def on_preview_key_down(sender, args):
        if args.Key == Key.Escape:
            sender.Close()
            args.Handled = True
    window.PreviewKeyDown += on_preview_key_down


def load_watermark(window, custom_path=None):
    """Load watermark PNG into window.watermarkImage safely."""
    if not hasattr(window, 'watermarkImage') or window.watermarkImage is None:
        return
    try:
        from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
        from System import Uri, UriKind
        target_path = custom_path
        if not target_path or not os.path.exists(target_path):
            target_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "background.png"))
        if os.path.exists(target_path):
            file_uri = "file:///" + target_path.replace("\\", "/")
            bmp = BitmapImage()
            bmp.BeginInit()
            bmp.UriSource = Uri(file_uri, UriKind.Absolute)
            bmp.CacheOption = BitmapCacheOption.OnLoad
            bmp.EndInit()
            window.watermarkImage.Source = bmp
    except Exception:
        pass


def apply_modern_progressbar_style(window, dark_mode=False):
    """
    Injects the modern rounded capsule ProgressBar style into window resources.
    Matches UI Sample template: 4px height, rounded capsule (CornerRadius=2),
    flat #10B981 emerald indicator, and theme-adaptive track background.
    """
    try:
        from System.Windows.Markup import XamlReader
        track_bg = "#334155" if dark_mode else "#E2E8F0"
        xaml_pb = (
            '<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
            'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
            '<Style TargetType="{x:Type ProgressBar}">'
            '<Setter Property="Height" Value="4"/>'
            '<Setter Property="Background" Value="' + track_bg + '"/>'
            '<Setter Property="Foreground" Value="#10B981"/>'
            '<Setter Property="BorderThickness" Value="0"/>'
            '<Setter Property="Template">'
            '<Setter.Value>'
            '<ControlTemplate TargetType="{x:Type ProgressBar}">'
            '<Border Background="{TemplateBinding Background}" CornerRadius="2" ClipToBounds="True">'
            '<Grid Name="TemplateRoot">'
            '<Border Name="PART_Track" Background="Transparent"/>'
            '<Border Name="PART_Indicator" Background="{TemplateBinding Foreground}" HorizontalAlignment="Left" CornerRadius="2"/>'
            '</Grid>'
            '</Border>'
            '<ControlTemplate.Triggers>'
            '<Trigger Property="IsIndeterminate" Value="True">'
            '<Trigger.EnterActions>'
            '<BeginStoryboard>'
            '<Storyboard RepeatBehavior="Forever">'
            '<DoubleAnimation Storyboard.TargetName="PART_Indicator" '
            'Storyboard.TargetProperty="(UIElement.RenderTransform).(TranslateTransform.X)" '
            'From="-120" To="500" Duration="0:0:1.4"/>'
            '</Storyboard>'
            '</BeginStoryboard>'
            '</Trigger.EnterActions>'
            '<Setter TargetName="PART_Indicator" Property="Width" Value="120"/>'
            '<Setter TargetName="PART_Indicator" Property="RenderTransform">'
            '<Setter.Value>'
            '<TranslateTransform/>'
            '</Setter.Value>'
            '</Setter>'
            '</Trigger>'
            '</ControlTemplate.Triggers>'
            '</ControlTemplate>'
            '</Setter.Value>'
            '</Setter>'
            '</Style>'
            '</ResourceDictionary>'
        )
        rd = XamlReader.Parse(xaml_pb)
        window.Resources.MergedDictionaries.Add(rd)
    except Exception:
        pass


def setup_modern_window(window, dark_mode=False, set_revit_owner=True):
    """
    Standard initialization for modern MEPANANA Adaptive Glassmorphism windows:
    - Sets Revit MainWindowHandle as owner
    - Loads watermark image into window.watermarkImage
    - Wires titleBar dragging to window.DragMove()
    - Wires btnClose to window.Close()
    - Wires btnToggleTheme to toggle switch_requested and Close()
    - Binds ESC key to close
    """
    window.switch_requested = False
    window.dark_mode = dark_mode

    if set_revit_owner:
        try:
            from pyrevit import HOST_APP
            if HOST_APP and hasattr(HOST_APP, "uiapp") and HOST_APP.uiapp:
                WindowInteropHelper(window).Owner = HOST_APP.uiapp.MainWindowHandle
        except Exception:
            pass

    load_watermark(window)
    apply_modern_progressbar_style(window, dark_mode=dark_mode)

    if hasattr(window, 'titleBar') and window.titleBar is not None:
        def on_drag(sender, e):
            try:
                window.DragMove()
            except Exception:
                pass
        window.titleBar.MouseLeftButtonDown += on_drag

    if hasattr(window, 'btnClose') and window.btnClose is not None:
        window.btnClose.Click += lambda s, e: window.Close()

    if hasattr(window, 'btnFooterClose') and window.btnFooterClose is not None:
        window.btnFooterClose.Click += lambda s, e: window.Close()

    if hasattr(window, 'btnToggleTheme') and window.btnToggleTheme is not None:
        def on_toggle_theme(s, e):
            window.switch_requested = True
            window.Close()
        window.btnToggleTheme.Click += on_toggle_theme

    def on_preview_key_down(sender, args):
        if args.Key == Key.Escape:
            sender.Close()
            args.Handled = True
    window.PreviewKeyDown += on_preview_key_down


def do_events():
    """
    Pumps the Windows Dispatcher queue to force immediate WPF UI repainting
    and prevent window freezing during background / batch loops.
    """
    try:
        from System import Action
        from System.Windows.Threading import Dispatcher, DispatcherPriority
        Dispatcher.CurrentDispatcher.Invoke(DispatcherPriority.Background, Action(lambda: None))
    except Exception:
        pass


def yield_dispatcher_every(counter, batch_size=25):
    """
    Yields WPF dispatcher every N iterations to keep UI responsive & smooth (60 FPS)
    without incurring per-iteration dispatching context-switch overhead.
    """
# ── Universal Modern Running Mode & Floating Capsule Manager ─────────────────

class RunningModeManager(object):
    """
    Universal Running Mode & Floating Capsule Manager for MEPANANA Windows.
    Provides the benchmark UI Sample running experience:
    - Seamless cross-fade between pnlForm and pnlRunning (Modern Floating Capsule).
    - Watermark vibrancy transition (subtle watermark -> full clarity during run -> back to subtle).
    - Progress updates: progressBarRunning (0-100%), txtRunningPercent, txtRunningTitle, txtRunningDetail.
    - Cancel handling: btnStopRunning sets is_cancelled = True.
    - Non-blocking WPF message pumping (do_events).
    - Auto-return delay or manual return back to pnlForm.
    """
    def __init__(self, window, dark_mode=False, on_cancel=None):
        self.win = window
        self.dark_mode = getattr(window, 'dark_mode', dark_mode)
        self.on_cancel = on_cancel
        self.is_cancelled = False
        self._wire_events()

    def _wire_events(self):
        if hasattr(self.win, 'btnStopRunning') and self.win.btnStopRunning is not None:
            self.win.btnStopRunning.Click += self._on_stop_click

    def _on_stop_click(self, sender, e):
        self.is_cancelled = True
        if hasattr(self.win, 'txtRunningDetail') and self.win.txtRunningDetail:
            self.win.txtRunningDetail.Text = u"Cancelling operation\u2026"
        if callable(self.on_cancel):
            try:
                self.on_cancel()
            except Exception:
                pass
        do_events()

    def start(self, title=u"Processing Elements\u2026", detail=u"Initializing engine\u2026"):
        self.is_cancelled = False
        base_opacity = 0.25 if self.dark_mode else 0.22

        if hasattr(self.win, 'progressBarRunning') and self.win.progressBarRunning:
            self.win.progressBarRunning.Value = 0
        if hasattr(self.win, 'txtRunningPercent') and self.win.txtRunningPercent:
            self.win.txtRunningPercent.Text = u"0%"
        if hasattr(self.win, 'txtRunningTitle') and self.win.txtRunningTitle:
            self.win.txtRunningTitle.Text = title
        if hasattr(self.win, 'txtRunningDetail') and self.win.txtRunningDetail:
            self.win.txtRunningDetail.Text = detail
        if hasattr(self.win, 'btnStopRunning') and self.win.btnStopRunning:
            self.win.btnStopRunning.Content = u"Cancel"
            self.win.btnStopRunning.IsEnabled = True

        try:
            if hasattr(self.win, 'watermarkImage') and self.win.watermarkImage:
                anim_wm = DoubleAnimation(base_opacity, 1.0, System.TimeSpan.FromMilliseconds(250))
                self.win.watermarkImage.BeginAnimation(UIElement.OpacityProperty, anim_wm)
                if self.win.watermarkImage.Effect:
                    anim_blur = DoubleAnimation(4.0, 0.0, System.TimeSpan.FromMilliseconds(250))
                    self.win.watermarkImage.Effect.BeginAnimation(BlurEffect.RadiusProperty, anim_blur)
        except Exception:
            pass

        if hasattr(self.win, 'pnlForm') and self.win.pnlForm:
            self.win.pnlForm.Visibility = Visibility.Collapsed
        if hasattr(self.win, 'pnlRunning') and self.win.pnlRunning:
            self.win.pnlRunning.Opacity = 1.0
            self.win.pnlRunning.Visibility = Visibility.Visible

        do_events()

    def update(self, percent, detail=None, title=None):
        if self.is_cancelled:
            return False

        if hasattr(self.win, 'progressBarRunning') and self.win.progressBarRunning:
            self.win.progressBarRunning.Value = max(0, min(100, percent))
        if hasattr(self.win, 'txtRunningPercent') and self.win.txtRunningPercent:
            self.win.txtRunningPercent.Text = u"{}%".format(int(percent))
        if detail and hasattr(self.win, 'txtRunningDetail') and self.win.txtRunningDetail:
            self.win.txtRunningDetail.Text = detail
        if title and hasattr(self.win, 'txtRunningTitle') and self.win.txtRunningTitle:
            self.win.txtRunningTitle.Text = title

        do_events()
        return not self.is_cancelled

    def finish(self, title=u"\u2713 Completed Successfully!", detail=u"Operation completed.", auto_return_delay_ms=900, status_text=None):
        if hasattr(self.win, 'progressBarRunning') and self.win.progressBarRunning:
            self.win.progressBarRunning.Value = 100
        if hasattr(self.win, 'txtRunningPercent') and self.win.txtRunningPercent:
            self.win.txtRunningPercent.Text = u"100%"
        if hasattr(self.win, 'txtRunningTitle') and self.win.txtRunningTitle:
            self.win.txtRunningTitle.Text = title
        if hasattr(self.win, 'txtRunningDetail') and self.win.txtRunningDetail:
            self.win.txtRunningDetail.Text = detail
        if hasattr(self.win, 'btnStopRunning') and self.win.btnStopRunning:
            self.win.btnStopRunning.Content = u"Done"

        do_events()

        if auto_return_delay_ms > 0:
            import time
            elapsed = 0
            while elapsed < auto_return_delay_ms:
                if self.is_cancelled:
                    break
                time.sleep(0.05)
                elapsed += 50
                do_events()
            self.restore_form(status_text=status_text or title)

    def restore_form(self, status_text=None):
        base_opacity = 0.25 if self.dark_mode else 0.22

        try:
            if hasattr(self.win, 'watermarkImage') and self.win.watermarkImage:
                anim_wm = DoubleAnimation(1.0, base_opacity, System.TimeSpan.FromMilliseconds(200))
                self.win.watermarkImage.BeginAnimation(UIElement.OpacityProperty, anim_wm)
                if self.win.watermarkImage.Effect:
                    anim_blur = DoubleAnimation(0.0, 4.0, System.TimeSpan.FromMilliseconds(200))
                    self.win.watermarkImage.Effect.BeginAnimation(BlurEffect.RadiusProperty, anim_blur)
        except Exception:
            pass

        if hasattr(self.win, 'pnlRunning') and self.win.pnlRunning:
            self.win.pnlRunning.Visibility = Visibility.Collapsed
        if hasattr(self.win, 'pnlForm') and self.win.pnlForm:
            self.win.pnlForm.Opacity = 1.0
            self.win.pnlForm.Visibility = Visibility.Visible

        if hasattr(self.win, 'btnStopRunning') and self.win.btnStopRunning:
            self.win.btnStopRunning.Content = u"Cancel"

        if status_text and hasattr(self.win, 'txtStatus') and self.win.txtStatus:
            self.win.txtStatus.Text = status_text

        do_events()


def is_dark_theme():
    """
    Detect whether Revit or Windows is currently running in Dark Mode.
    
    Priority:
    1. Revit 2024+ native UIThemeManager.CurrentTheme == UITheme.Dark
    2. Revit 2024+ UIThemeManager.CurrentCanvasTheme == UITheme.Dark
    3. Windows 10/11 Personalize Registry (AppsUseLightTheme == 0)
    4. Fallback: False (Light Mode)
    """
    try:
        from Autodesk.Revit.UI import UIThemeManager, UITheme
        if hasattr(UIThemeManager, "CurrentTheme"):
            return UIThemeManager.CurrentTheme == UITheme.Dark
    except Exception:
        pass

    try:
        from Autodesk.Revit.UI import UIThemeManager, UITheme
        if hasattr(UIThemeManager, "CurrentCanvasTheme"):
            return UIThemeManager.CurrentCanvasTheme == UITheme.Dark
    except Exception:
        pass

    try:
        import Microsoft.Win32 as win32
        key = win32.Registry.CurrentUser.OpenSubKey(
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        if key:
            val = key.GetValue("AppsUseLightTheme")
            if val is not None:
                return int(val) == 0
    except Exception:
        pass

    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(val) == 0
    except Exception:
        pass

    return False


# ── Synchronized Modern Alert Dialog ─────────────────────────────────────────

def _show_custom_dialog(message, title, dialog_type="INFO", show_cancel=False, owner=None, topmost=False):
    """
    Renders a unified, modern, branded modal dialog with type-specific icon badges and colors.
    """
    try:
        xaml_path = os.path.join(os.path.dirname(__file__), 'alert.xaml')
        if not os.path.exists(xaml_path):
            return forms.alert(message, title=title, ok=True, cancel=show_cancel)

        class ModernAlertWindow(forms.WPFWindow):
            def __init__(self):
                forms.WPFWindow.__init__(self, xaml_path)
                setup_window(self, set_revit_owner=(owner is None))
                self.Title = title or "Notification"
                self.user_result = False
                if owner:
                    try:
                        self.Owner = owner
                        from System.Windows import WindowStartupLocation
                        self.WindowStartupLocation = WindowStartupLocation.CenterOwner
                    except Exception:
                        try:
                            from pyrevit import HOST_APP
                            if HOST_APP and hasattr(HOST_APP, "uiapp") and HOST_APP.uiapp:
                                WindowInteropHelper(self).Owner = HOST_APP.uiapp.MainWindowHandle
                        except Exception:
                            pass
                if topmost:
                    self.Topmost = True

                # Set Title Text
                if hasattr(self, 'txtAlertTitle'):
                    self.txtAlertTitle.Text = title or "Notification"

                # Set Message Body
                if hasattr(self, 'txtMessage'):
                    self.txtMessage.Text = message or ""

                # Configure Visual Style by Type
                badge_bg = "#EFF6FF"
                icon_fg = "#2563EB"
                icon_char = u"ℹ"

                if dialog_type == "SUCCESS":
                    badge_bg = "#D1FAE5"
                    icon_fg = "#059669"
                    icon_char = u"✓"
                elif dialog_type == "WARNING":
                    badge_bg = "#FEF3C7"
                    icon_fg = "#D97706"
                    icon_char = u"⚠"
                elif dialog_type == "ERROR":
                    badge_bg = "#FEE2E2"
                    icon_fg = "#DC2626"
                    icon_char = u"✕"

                def hex_to_brush(hex_str):
                    hex_str = hex_str.lstrip('#')
                    r = int(hex_str[0:2], 16)
                    g = int(hex_str[2:4], 16)
                    b = int(hex_str[4:6], 16)
                    return SolidColorBrush(Color.FromRgb(r, g, b))

                if hasattr(self, 'borderIconBadge'):
                    self.borderIconBadge.Background = hex_to_brush(badge_bg)

                if hasattr(self, 'txtIcon'):
                    self.txtIcon.Text = icon_char
                    self.txtIcon.Foreground = hex_to_brush(icon_fg)

                # Configure Cancel Button
                if hasattr(self, 'btnCancel'):
                    if show_cancel:
                        self.btnCancel.Visibility = Visibility.Visible
                        self.btnCancel.Click += self.on_cancel_click
                    else:
                        self.btnCancel.Visibility = Visibility.Collapsed

                if hasattr(self, 'btnOk'):
                    self.btnOk.Click += self.on_ok_click

            def on_ok_click(self, sender, args):
                self.user_result = True
                self.Close()

            def on_cancel_click(self, sender, args):
                self.user_result = False
                self.Close()

        win = ModernAlertWindow()
        win.ShowDialog()
        return win.user_result
    except Exception:
        return forms.alert(message, title=title, ok=True, cancel=show_cancel)


def show_info(message, title="Information", owner=None, topmost=False):
    return _show_custom_dialog(message, title=title, dialog_type="INFO", show_cancel=False, owner=owner, topmost=topmost)


def show_success(message, title="Success", owner=None, topmost=False):
    return _show_custom_dialog(message, title=title, dialog_type="SUCCESS", show_cancel=False, owner=owner, topmost=topmost)


def show_warning(message, title="Warning", owner=None, topmost=False):
    return _show_custom_dialog(message, title=title, dialog_type="WARNING", show_cancel=False, owner=owner, topmost=topmost)


def show_error(message, title="Error", exitscript=False, owner=None, topmost=False):
    res = _show_custom_dialog(message, title=title, dialog_type="ERROR", show_cancel=False, owner=owner, topmost=topmost)
    if exitscript:
        sys.exit()
    return res


def show_confirm(message, title="Confirmation", owner=None, topmost=False):
    return _show_custom_dialog(message, title=title, dialog_type="WARNING", show_cancel=True, owner=owner, topmost=topmost)


# ── Universal Branded WPF Progress Dialog ────────────────────────────────────

class MepananaProgressBar(object):
    """
    Modern Branded Modal/Modeless Progress Dialog Context Manager.
    Features:
    - 60 FPS smooth Dispatcher message pumping
    - Supports both Determinate (0-100%) and Indeterminate (pulsing wave animation)
    - Branded MEPANANA card design with rounded corners & shadow
    - Real-time status and detail message updates
    - Optional Cancel button
    
    Usage:
        with MepananaProgressBar("Scanning Directory...", total=len(files), cancellable=True) as pb:
            for i, f in enumerate(files):
                if pb.is_cancelled:
                    break
                # work
                pb.update(i + 1, status="Indexing files...", detail=os.path.basename(f))
    """
    def __init__(self, title="Processing...", total=0, cancellable=False, indeterminate=False, icon="⚡"):
        self.title = title
        self.total = total
        self.cancellable = cancellable
        self.indeterminate = indeterminate or (total == 0)
        self.icon = icon
        self.is_cancelled = False
        self.win = None
        self._init_window()

    def _init_window(self):
        try:
            xaml_path = os.path.join(os.path.dirname(__file__), 'progress_dialog.xaml')
            if not os.path.exists(xaml_path):
                return
            
            class _ProgressWindow(forms.WPFWindow):
                def __init__(self, owner_bar):
                    forms.WPFWindow.__init__(self, xaml_path)
                    setup_window(self)
                    self.owner_bar = owner_bar

            self.win = _ProgressWindow(self)
            
            if hasattr(self.win, 'txtTitle'):
                self.win.txtTitle.Text = self.title
            if hasattr(self.win, 'txtIcon'):
                self.win.txtIcon.Text = self.icon
            if hasattr(self.win, 'progressBar'):
                self.win.progressBar.IsIndeterminate = self.indeterminate
                self.win.progressBar.Minimum = 0
                self.win.progressBar.Maximum = self.total if self.total > 0 else 100
                self.win.progressBar.Value = 0
            if hasattr(self.win, 'btnCancel'):
                if self.cancellable:
                    self.win.btnCancel.Visibility = Visibility.Visible
                    self.win.btnCancel.Click += self._on_cancel
                else:
                    self.win.btnCancel.Visibility = Visibility.Collapsed
        except Exception:
            self.win = None

    def _on_cancel(self, sender, args):
        self.is_cancelled = True
        if hasattr(self.win, 'txtStatus'):
            self.win.txtStatus.Text = "Cancelling operation..."
        do_events()

    def __enter__(self):
        if self.win:
            try:
                self.win.Show()
                do_events()
            except Exception:
                pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.win:
            try:
                self.win.Close()
            except Exception:
                pass
            self.win = None

    def update(self, current_value=0, total=None, status=None, detail=None):
        if not self.win:
            return
        if total is not None:
            self.total = total
            if hasattr(self.win, 'progressBar'):
                self.win.progressBar.Maximum = self.total
                if self.total > 0 and self.win.progressBar.IsIndeterminate:
                    self.win.progressBar.IsIndeterminate = False

        if hasattr(self.win, 'progressBar') and not self.win.progressBar.IsIndeterminate:
            self.win.progressBar.Value = current_value
            if self.total > 0:
                pct = int((float(current_value) / self.total) * 100)
                if hasattr(self.win, 'txtPercent'):
                    self.win.txtPercent.Text = "{}%".format(min(100, max(0, pct)))

        if status and hasattr(self.win, 'txtStatus'):
            self.win.txtStatus.Text = status

        if detail is not None and hasattr(self.win, 'txtDetail'):
            self.win.txtDetail.Text = detail

        do_events()