# -*- coding: utf-8 -*-
"""
Tool Visibility — Ribbon Pushbutton Visibility Manager
Part of mepanana.extension.
Author: Hai Nguyen
"""
__title__ = "Tool Visibility"
__doc__   = "Manage visibility of MEPANANA pushbuttons on the Ribbon.\n\nPreferences are saved per-machine and automatically preserved.\n\n[Click]: Open Tool Visibility Manager\n[Shift-Click]: Toggle Theme (Force Light / Dark)"

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

from py.ui import is_dark_theme, show_success
from py.tool_visibility_engine import (
    get_hidden_tools,
    save_hidden_tools,
    apply_tool_visibility,
    PANEL_TOOLS,
    PROTECTED_TOOLS,
)

try:
    import clr
    clr.AddReference("System")
    clr.AddReference("PresentationCore")
    clr.AddReference("PresentationFramework")
    clr.AddReference("WindowsBase")

    import System
    import System.Windows.Threading as wt
    from System.Windows import Visibility, UIElement
    from System.Windows.Interop import WindowInteropHelper

    from pyrevit import forms

    # Mapping of tool name -> XAML CheckBox control name
    CHECKBOX_MAP = {
        "Bloom": "chk_Bloom",
        "CAD Blocks": "chk_CAD_Blocks",
        "CAD Wire": "chk_CAD_Wire",
        "Connect To": "chk_Connect_To",
        "MEP Route": "chk_MEP_Route",
        "Pendent Sprinkler": "chk_Pendent_Sprinkler",
        "Upright Sprinkler": "chk_Upright_Sprinkler",
        "Sidewall Sprinkler": "chk_Sidewall_Sprinkler",
        "Check Clash": "chk_Check_Clash",
        "Display Clash": "chk_Display_Clash",
        "Family Cloud": "chk_Family_Cloud",
        "Family Local": "chk_Family_Local",
        "Schedule Link": "chk_Schedule_Link",
        "Shortcut Manager": "chk_Shortcut_Manager",
        "Update": "chk_Update",
        "UI Sample": "chk_UI_Sample",
    }

    class ToolVisibilityWindow(forms.WPFWindow):
        def __init__(self, dark_mode=False):
            self.dark_mode = dark_mode
            xaml_name = "ui_dark.xaml" if dark_mode else "ui_light.xaml"
            ui_path = os.path.join(os.path.dirname(__file__), xaml_name)
            forms.WPFWindow.__init__(self, ui_path)

            self.switch_requested = False
            self._load_watermark()
            self._setup_events()
            self._load_state()

        def _load_watermark(self):
            """Load the transparent sticker background."""
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
            self.btnApply.Click  += self._on_apply

            if hasattr(self, 'btnToggleTheme'):
                self.btnToggleTheme.Click += self._on_toggle_theme

            self.btnShowAll.Click += self._on_show_all
            self.btnHideAll.Click += self._on_hide_all
            self.btnDefault.Click += self._on_show_all

            self.txtSearch.TextChanged += self._on_search_changed

            # Attach click handler to each tool checkbox
            for tool_name, ctrl_name in CHECKBOX_MAP.items():
                chk = getattr(self, ctrl_name, None)
                if chk:
                    chk.Click += lambda s, e: self._update_status()

        def _on_drag(self, sender, e):
            try:
                self.DragMove()
            except Exception:
                pass

        def _on_toggle_theme(self, sender, e):
            self.switch_requested = True
            self.Close()

        def _load_state(self):
            hidden = get_hidden_tools()
            for tool_name, ctrl_name in CHECKBOX_MAP.items():
                chk = getattr(self, ctrl_name, None)
                if chk:
                    chk.IsChecked = tool_name not in hidden
            self._update_status()

        def _update_status(self):
            total = len(CHECKBOX_MAP)
            visible_count = sum(
                1 for tool_name, ctrl_name in CHECKBOX_MAP.items()
                if getattr(self, ctrl_name, None) and getattr(self, ctrl_name).IsChecked
            )
            hidden_count = total - visible_count
            if hidden_count == 0:
                self.txtStatus.Text = u"All {} tools visible".format(total)
            else:
                self.txtStatus.Text = u"{} visible, {} hidden on Ribbon".format(visible_count, hidden_count)

        def _on_show_all(self, sender, e):
            for tool_name, ctrl_name in CHECKBOX_MAP.items():
                chk = getattr(self, ctrl_name, None)
                if chk:
                    chk.IsChecked = True
            self._update_status()

        def _on_hide_all(self, sender, e):
            for tool_name, ctrl_name in CHECKBOX_MAP.items():
                chk = getattr(self, ctrl_name, None)
                if chk:
                    chk.IsChecked = False
            self._update_status()

        def _on_search_changed(self, sender, e):
            query = (self.txtSearch.Text or "").strip().lower()
            for tool_name, ctrl_name in CHECKBOX_MAP.items():
                chk = getattr(self, ctrl_name, None)
                if chk:
                    if not query or query in tool_name.lower():
                        chk.Visibility = Visibility.Visible
                    else:
                        chk.Visibility = Visibility.Collapsed

        def _on_apply(self, sender, e):
            # Gather unchecked tools
            hidden = []
            for tool_name, ctrl_name in CHECKBOX_MAP.items():
                chk = getattr(self, ctrl_name, None)
                if chk and not chk.IsChecked:
                    hidden.append(tool_name)

            # Save per-machine config
            save_hidden_tools(hidden)

            # Live update the Ribbon immediately
            apply_tool_visibility(hidden)

            self.Close()
            try:
                hidden_count = len(hidden)
                if hidden_count == 0:
                    show_success(u"All tools are now visible on the Ribbon!", "Tool Visibility")
                else:
                    show_success(
                        u"Ribbon updated!\n\n{} tool(s) hidden. Settings saved per-machine.".format(hidden_count),
                        "Tool Visibility"
                    )
            except Exception:
                pass


    # ==========================================================================
    # LAUNCHER LOOP
    # ==========================================================================
    current_dark = is_dark_theme()
    try:
        if __shiftclick__:
            current_dark = not current_dark
    except Exception:
        pass

    while True:
        win = ToolVisibilityWindow(dark_mode=current_dark)
        win.ShowDialog()
        if getattr(win, 'switch_requested', False):
            current_dark = not current_dark
            continue
        break

except Exception:
    import traceback
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("Tool Visibility Error", traceback.format_exc())
    except Exception:
        pass
