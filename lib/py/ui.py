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


def setup_window(window):
    """Applies mepanana theme.xaml, sets Revit as owner, binds ESC to close."""
    try:
        theme_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'theme.xaml'))
        rd = ResourceDictionary()
        rd.Source = Uri(theme_path, UriKind.Absolute)
        window.Resources.MergedDictionaries.Add(rd)
    except Exception as e:
        print("Failed to load theme.xaml: {}".format(e))

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


def do_events():
    """Pumps the Windows Dispatcher queue to force immediate WPF UI repainting during long operations."""
    try:
        from System.Windows.Threading import Dispatcher, DispatcherPriority
        import System
        Dispatcher.CurrentDispatcher.Invoke(DispatcherPriority.Background, System.Action(lambda: None))
    except Exception:
        pass


# ── Synchronized Modern Alert Dialog ─────────────────────────────────────────

def _clean_u(val):
    if val is None:
        return u""
    if isinstance(val, unicode):
        return val
    try:
        return val.decode("utf-8")
    except Exception:
        try:
            return unicode(val)
        except Exception:
            try:
                return val.decode("ascii", "ignore")
            except Exception:
                return str(val)


def _show_custom_dialog(message, title, dialog_type="INFO", show_cancel=False):
    """
    Renders a unified, modern, branded modal dialog with type-specific icon badges and colors.
    """
    u_title = _clean_u(title) or u"Notification"
    u_message = _clean_u(message) or u""

    try:
        xaml_path = os.path.join(os.path.dirname(__file__), 'alert.xaml')
        if not os.path.exists(xaml_path):
            return forms.alert(u_message, title=u_title, ok=True, cancel=show_cancel)

        class ModernAlertWindow(forms.WPFWindow):
            def __init__(self):
                forms.WPFWindow.__init__(self, xaml_path)
                setup_window(self)
                self.Title = u_title
                self.user_result = False

                # Set Title Text
                if hasattr(self, 'txtAlertTitle'):
                    self.txtAlertTitle.Text = u_title

                # Set Message Body
                if hasattr(self, 'txtMessage'):
                    self.txtMessage.Text = u_message

                # Configure Visual Style by Type
                badge_bg = "#D1FAE5"
                icon_fg = "#059669"
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
        return forms.alert(u_message, title=u_title, ok=True, cancel=show_cancel)


def show_info(message, title="Information"):
    return _show_custom_dialog(message, title=title, dialog_type="INFO", show_cancel=False)


def show_success(message, title="Success"):
    return _show_custom_dialog(message, title=title, dialog_type="SUCCESS", show_cancel=False)


def show_warning(message, title="Warning"):
    return _show_custom_dialog(message, title=title, dialog_type="WARNING", show_cancel=False)


def show_error(message, title="Error", exitscript=False):
    res = _show_custom_dialog(message, title=title, dialog_type="ERROR", show_cancel=False)
    if exitscript:
        sys.exit()
    return res


def show_confirm(message, title="Confirmation"):
    return _show_custom_dialog(message, title=title, dialog_type="WARNING", show_cancel=True)