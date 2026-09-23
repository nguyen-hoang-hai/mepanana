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
    from System.Windows import ResourceDictionary, Visibility
    from System import Uri, UriKind
    from System.Windows.Interop import WindowInteropHelper
    from System.Windows.Input import Key
    from System.Windows.Media import SolidColorBrush, Color
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
    if counter % batch_size == 0:
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