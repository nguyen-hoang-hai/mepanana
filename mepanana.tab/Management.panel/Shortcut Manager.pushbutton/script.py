# -*- coding: utf-8 -*-
__title__ = "Shortcut Manager"
__doc__   = "Assign and manage custom keyboard shortcuts for mepanana tools."

import os
import sys
import traceback

try:
    import clr
    clr.AddReference("System")
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")

    import System
    import System.Windows
    from System.Windows import Thickness, Visibility, HorizontalAlignment, VerticalAlignment
    from System.Windows.Controls import (
        Border, Grid, ColumnDefinition, RowDefinition, TextBlock, TextBox, Button, StackPanel, Image
    )
    from System.Windows.Media import SolidColorBrush, Color
    from System.Windows.Media.Imaging import BitmapImage
    from System.Windows.Input import Key, ModifierKeys, Keyboard
    from System import Uri, UriKind

    from pyrevit import forms, HOST_APP
    from py.auth import require_auth, update_ribbon_state, is_authenticated
    from py.core import get_doc, get_app
    from py.ui   import show_info, show_warning, show_error, setup_window
    from py.shortcut_io import ShortcutDatabase, scan_mepanana_tools

    # ── Authentication Gatekeeper ─────────────────────────────────────────────────
    if not is_authenticated():
        update_ribbon_state(False)
        if not require_auth():
            sys.exit()

    try:
        from py.updater_engine import check_updates_in_background
        check_updates_in_background()
    except Exception:
        pass

    def get_key_string(key):
        """Converts WPF Key enum to a clean character / name string safely in IronPython."""
        try:
            k_str = str(key)
            if not k_str:
                return ""
            # Single letter: A, B, C... Z
            if len(k_str) == 1 and k_str.isalpha():
                return k_str.upper()
            # D0 - D9
            if k_str.startswith("D") and len(k_str) == 2 and k_str[1].isdigit():
                return k_str[1]
            # NumPad0 - NumPad9
            if k_str.startswith("NumPad") and len(k_str) == 7 and k_str[6].isdigit():
                return k_str[6]
            # Function keys F1 - F24
            if k_str.startswith("F") and k_str[1:].isdigit():
                return k_str
            # Punctuation / OEM
            if k_str in ("OemPeriod", "Decimal"):
                return "."
            if k_str == "OemComma":
                return ","
            if k_str in ("OemMinus", "Subtract"):
                return "-"
            if k_str in ("OemPlus", "Add"):
                return "+"
            if k_str in ("OemQuestion", "Divide"):
                return "/"
            if k_str in ("Oem1", "OemSemicolon"):
                return ";"
            if k_str in ("Oem3", "OemTilde"):
                return "`"
            if k_str == "Space":
                return "Space"
            if k_str.startswith("Oem"):
                return k_str[3:]
            return k_str
        except Exception:
            return ""

    class ToolRowUI(object):
        def __init__(self, tool_info, current_sc, parent_window):
            self.tool_info = tool_info
            self.current_sc = (current_sc or "").strip().upper()
            self.parent = parent_window

            # Root Container
            self.container = Border()
            self.container.Background = SolidColorBrush(Color.FromArgb(255, 255, 255, 255))
            self.container.BorderBrush = SolidColorBrush(Color.FromArgb(255, 241, 245, 249))
            self.container.BorderThickness = Thickness(0, 0, 0, 1)
            self.container.Padding = Thickness(10, 8, 10, 8)

            grid = Grid()
            c0 = ColumnDefinition(); c0.Width = System.Windows.GridLength(230)
            c1 = ColumnDefinition(); c1.Width = System.Windows.GridLength(110)
            c2 = ColumnDefinition(); c2.Width = System.Windows.GridLength(180)
            c3 = ColumnDefinition(); c3.Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Star)
            grid.ColumnDefinitions.Add(c0)
            grid.ColumnDefinitions.Add(c1)
            grid.ColumnDefinitions.Add(c2)
            grid.ColumnDefinitions.Add(c3)

            # Col 0: Tool Info (Icon + Name + Panel)
            sp_tool = StackPanel()
            sp_tool.Orientation = System.Windows.Controls.Orientation.Horizontal
            sp_tool.VerticalAlignment = VerticalAlignment.Center

            # Icon
            if tool_info.get("icon_path") and os.path.exists(tool_info["icon_path"]):
                try:
                    img = Image()
                    img.Width = 24
                    img.Height = 24
                    img.Margin = Thickness(0, 0, 10, 0)
                    bi = BitmapImage()
                    bi.BeginInit()
                    bi.UriSource = Uri(tool_info["icon_path"], UriKind.Absolute)
                    bi.EndInit()
                    img.Source = bi
                    sp_tool.Children.Add(img)
                except:
                    pass

            sp_text = StackPanel()
            sp_text.VerticalAlignment = VerticalAlignment.Center

            txt_title = TextBlock()
            txt_title.Text = tool_info["name"]
            txt_title.FontWeight = System.Windows.FontWeights.SemiBold
            txt_title.FontSize = 12.5
            txt_title.Foreground = SolidColorBrush(Color.FromArgb(255, 30, 41, 59))
            sp_text.Children.Add(txt_title)

            txt_panel = TextBlock()
            txt_panel.Text = u"Panel: {}".format(tool_info["panel"])
            txt_panel.FontSize = 11
            txt_panel.Foreground = SolidColorBrush(Color.FromArgb(255, 100, 116, 139))
            sp_text.Children.Add(txt_panel)

            sp_tool.Children.Add(sp_text)
            Grid.SetColumn(sp_tool, 0)
            grid.Children.Add(sp_tool)

            # Col 1: Current Shortcut Badge
            self.bdr_current = Border()
            self.bdr_current.CornerRadius = System.Windows.CornerRadius(4)
            self.bdr_current.Padding = Thickness(8, 4, 8, 4)
            self.bdr_current.HorizontalAlignment = HorizontalAlignment.Left
            self.bdr_current.VerticalAlignment = VerticalAlignment.Center

            self.txt_current = TextBlock()
            self.txt_current.FontSize = 12
            self.txt_current.FontWeight = System.Windows.FontWeights.SemiBold
            self.bdr_current.Child = self.txt_current
            self.update_current_badge()

            Grid.SetColumn(self.bdr_current, 1)
            grid.Children.Add(self.bdr_current)

            # Col 2: New Shortcut Input
            self.txt_input = TextBox()
            self.txt_input.Height = 32
            self.txt_input.Width = 165
            self.txt_input.HorizontalAlignment = HorizontalAlignment.Left
            self.txt_input.FontSize = 12.5
            self.txt_input.FontWeight = System.Windows.FontWeights.SemiBold
            self.txt_input.VerticalContentAlignment = VerticalAlignment.Center
            self.txt_input.Text = self.current_sc
            self.txt_input.PreviewKeyDown += self.on_preview_key_down
            self.txt_input.TextChanged += self.on_text_changed

            Grid.SetColumn(self.txt_input, 2)
            grid.Children.Add(self.txt_input)

            # Col 3: Status Badge
            self.bdr_status = Border()
            self.bdr_status.CornerRadius = System.Windows.CornerRadius(4)
            self.bdr_status.Padding = Thickness(10, 4, 10, 4)
            self.bdr_status.HorizontalAlignment = HorizontalAlignment.Right
            self.bdr_status.VerticalAlignment = VerticalAlignment.Center
            self.bdr_status.Margin = Thickness(0, 0, 4, 0)

            self.txt_status = TextBlock()
            self.txt_status.FontSize = 11.5
            self.txt_status.FontWeight = System.Windows.FontWeights.SemiBold
            self.bdr_status.Child = self.txt_status

            Grid.SetColumn(self.bdr_status, 3)
            grid.Children.Add(self.bdr_status)

            self.container.Child = grid
            self.has_conflict = False

        def update_current_badge(self):
            if self.current_sc:
                self.bdr_current.Background = SolidColorBrush(Color.FromArgb(255, 239, 246, 255))
                self.txt_current.Foreground = SolidColorBrush(Color.FromArgb(255, 37, 99, 235))
                self.txt_current.Text = self.current_sc
            else:
                self.bdr_current.Background = SolidColorBrush(Color.FromArgb(255, 241, 245, 249))
                self.txt_current.Foreground = SolidColorBrush(Color.FromArgb(255, 148, 163, 184))
                self.txt_current.Text = u"—"

        def on_preview_key_down(self, sender, args):
            try:
                key = args.Key
                if key == Key.System:
                    key = args.SystemKey

                # Ignore raw modifier keys alone
                if key in (Key.LeftCtrl, Key.RightCtrl, Key.LeftAlt, Key.RightAlt,
                           Key.LeftShift, Key.RightShift, Key.LWin, Key.RWin):
                    return

                # Clear on Backspace or Delete
                if key in (Key.Back, Key.Delete):
                    self.txt_input.Text = ""
                    args.Handled = True
                    return

                # Allow Tab or Escape for navigation / exit
                if key in (Key.Tab, Key.Escape):
                    return

                # Check Modifiers
                mods = Keyboard.Modifiers
                has_ctrl = bool(mods & ModifierKeys.Control)
                has_alt = bool(mods & ModifierKeys.Alt)
                has_shift = bool(mods & ModifierKeys.Shift)

                key_char = get_key_string(key)
                if not key_char:
                    return

                # Format with Modifiers (e.g. Ctrl+Shift+W)
                if has_ctrl or has_alt or has_shift:
                    parts = []
                    if has_ctrl: parts.append("Ctrl")
                    if has_alt: parts.append("Alt")
                    if has_shift: parts.append("Shift")
                    parts.append(key_char)
                    self.txt_input.Text = "+".join(parts)
                else:
                    # Direct letter / chord (e.g. WA, SL, MM)
                    current_val = self.txt_input.Text.strip().upper()
                    if "+" in current_val or len(current_val) >= 4 or not self.txt_input.IsFocused:
                        self.txt_input.Text = key_char
                    else:
                        # Append chord up to 4 chars
                        self.txt_input.Text = current_val + key_char

                self.txt_input.CaretIndex = len(self.txt_input.Text)
                args.Handled = True
            except Exception:
                pass

        def on_text_changed(self, sender, args):
            self.parent.validate_all()

        def get_new_shortcut(self):
            return self.txt_input.Text.strip().upper()

        def set_status(self, status_type, text=""):
            self.has_conflict = (status_type == "CONFLICT")
            if status_type == "UNCHANGED":
                self.bdr_status.Background = SolidColorBrush(Color.FromArgb(255, 241, 245, 249))
                self.txt_status.Foreground = SolidColorBrush(Color.FromArgb(255, 100, 116, 139))
                self.txt_status.Text = u"Unchanged"
                self.container.Background = SolidColorBrush(Color.FromArgb(255, 255, 255, 255))
            elif status_type == "MODIFIED":
                self.bdr_status.Background = SolidColorBrush(Color.FromArgb(255, 254, 243, 199))
                self.txt_status.Foreground = SolidColorBrush(Color.FromArgb(255, 146, 64, 14))
                self.txt_status.Text = u"🟡 Modified"
                self.container.Background = SolidColorBrush(Color.FromArgb(255, 255, 255, 255))
            elif status_type == "CLEARED":
                self.bdr_status.Background = SolidColorBrush(Color.FromArgb(255, 241, 245, 249))
                self.txt_status.Foreground = SolidColorBrush(Color.FromArgb(255, 148, 163, 184))
                self.txt_status.Text = u"⚪ Cleared"
                self.container.Background = SolidColorBrush(Color.FromArgb(255, 255, 255, 255))
            elif status_type == "CONFLICT":
                self.bdr_status.Background = SolidColorBrush(Color.FromArgb(255, 254, 226, 226))
                self.txt_status.Foreground = SolidColorBrush(Color.FromArgb(255, 153, 27, 27))
                self.txt_status.Text = u"🔴 Conflict"
                self.container.Background = SolidColorBrush(Color.FromArgb(255, 255, 241, 242))


    class ShortcutManagerWindow(forms.WPFWindow):
        def __init__(self):
            xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
            forms.WPFWindow.__init__(self, xaml_path)
            setup_window(self)

            # Detect Revit Version
            version_str = None
            try:
                version_str = HOST_APP.version
            except:
                try:
                    version_str = str(get_app().VersionNumber)
                except:
                    pass

            self.db = ShortcutDatabase(revit_version=version_str)
            self.tools = scan_mepanana_tools()
            self.rows = []

            # Populate UI Rows
            self.txtTotalToolsCount.Text = u"{} Tools".format(len(self.tools))
            for t in self.tools:
                cur_sc = self.db.get_shortcut(t["command_id"])
                row = ToolRowUI(t, cur_sc, self)
                self.rows.append(row)
                self.pnlToolsList.Children.Add(row.container)

            # Events
            self.btnResetAll.Click += self.on_reset_all
            self.btnApply.Click += self.on_apply

            self.validate_all()

        def validate_all(self):
            conflicts = []
            assigned_so_far = {} # new_sc -> tool_name

            for r in self.rows:
                new_sc = r.get_new_shortcut()

                if not new_sc:
                    if r.current_sc:
                        r.set_status("CLEARED")
                    else:
                        r.set_status("UNCHANGED")
                    continue

                # 1. Check internal duplicates among mepanana tools
                if new_sc in assigned_so_far:
                    conflict_msg = u"Duplicate in mepanana: '{}' is also set for '{}'".format(
                        new_sc, assigned_so_far[new_sc]
                    )
                    r.set_status("CONFLICT", conflict_msg)
                    conflicts.append(conflict_msg)
                    continue

                assigned_so_far[new_sc] = r.tool_info["name"]

                # 2. Check collision with Revit DB
                has_coll, coll_info = self.db.check_conflict(new_sc, exclude_command_id=r.tool_info["command_id"])
                if has_coll:
                    r.set_status("CONFLICT", coll_info)
                    conflicts.append(coll_info)
                else:
                    if new_sc == r.current_sc:
                        r.set_status("UNCHANGED")
                    else:
                        r.set_status("MODIFIED")

            # Update Conflict Banner
            if conflicts:
                self.bdrConflictBanner.Visibility = Visibility.Visible
                self.txtConflictMessage.Text = conflicts[0]
                self.btnApply.IsEnabled = False
            else:
                self.bdrConflictBanner.Visibility = Visibility.Collapsed
                self.btnApply.IsEnabled = True

        def on_reset_all(self, sender, args):
            for r in self.rows:
                r.txt_input.Text = r.current_sc
            self.validate_all()

        def on_apply(self, sender, args):
            updates = {}
            modified_count = 0

            for r in self.rows:
                new_sc = r.get_new_shortcut()
                if new_sc != r.current_sc:
                    updates[r.tool_info["command_id"]] = new_sc
                    modified_count += 1

            if modified_count == 0:
                show_info(u"No shortcut changes to apply.", "Shortcut Manager")
                return

            ok, msg = self.db.save_changes(updates)
            if ok:
                # Update current state on rows
                for r in self.rows:
                    r.current_sc = r.get_new_shortcut()
                    r.update_current_badge()
                self.validate_all()

                info_msg = (
                    u"Successfully applied {} shortcut(s) to Revit!\n\n"
                    u"💡 Note: To use the new shortcuts immediately without restarting Revit, "
                    u"open 'View > User Interface > Keyboard Shortcuts' (or type KS) and click OK.\n\n"
                    u"Alternatively, your shortcuts will be active automatically upon your next Revit restart."
                ).format(modified_count)
                show_info(info_msg, "Shortcuts Applied")
            else:
                show_error(msg, "Error Saving Shortcuts")

    win = ShortcutManagerWindow()
    win.ShowDialog()

except Exception as ex:
    err_msg = "Shortcut Manager Error:\n{}\n\n{}".format(str(ex), traceback.format_exc())
    try:
        from py.ui import show_error
        show_error(err_msg, "Shortcut Manager Error")
    except:
        print(err_msg)