# -*- coding: utf-8 -*-
"""
tool_visibility_engine.py — Per-Machine Ribbon Tool Visibility Engine
Part of mepanana.extension.
Author: Hai Nguyen

Manages user-selected visibility of pushbuttons on the MEPANANA ribbon.
Settings are stored per-machine in %APPDATA%/mepanana/tool_visibility.json
and automatically applied on startup and ribbon updates.
"""
import os
import sys
import json

PROTECTED_TOOLS = {
    "Unlock",
    "Lock",
    "Security",
    "Tool Visibility",
}

# Mapping of all standard tools grouped by Panel
PANEL_TOOLS = [
    (
        "Modeling",
        [
            "Bloom",
            "CAD Blocks",
            "CAD Wire",
            "Connect To",
            "MEP Route",
            "Pendent Sprinkler",
            "Upright Sprinkler",
            "Sidewall Sprinkler",
        ],
    ),
    (
        "Coordinate",
        [
            "Check Clash",
            "Display Clash",
        ],
    ),
    (
        "Data",
        [
            "Family Cloud",
            "Family Local",
            "Schedule Link",
        ],
    ),
    (
        "Management",
        [
            "Shortcut Manager",
            "Update",
            "UI Sample",
            "Tool Visibility",
        ],
    ),
]


def get_config_path():
    """Returns the local per-machine configuration file path in %APPDATA%."""
    app_data = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(app_data, "mepanana")
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return os.path.join(folder, "tool_visibility.json")


def get_hidden_tools():
    """
    Reads the list of hidden tools from local JSON config.
    Returns a set of tool names.
    """
    path = get_config_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
                hidden = data.get("hidden_tools", [])
                # Ensure protected tools are never in hidden list
                return set([t for t in hidden if t not in PROTECTED_TOOLS])
        except Exception:
            pass
    return set()


def save_hidden_tools(hidden_tools):
    """
    Saves the list of hidden tools to local JSON config.
    """
    path = get_config_path()
    # Filter out protected tools
    clean_hidden = sorted(list(set([t for t in hidden_tools if t not in PROTECTED_TOOLS])))
    data = {
        "version": "1.0",
        "hidden_tools": clean_hidden,
    }
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as ex:
        print("Failed to save tool visibility config: {}".format(ex))
        return False


def _clean_text(val):
    if not val:
        return ""
    return str(val).replace("\r", "").replace("\n", " ").strip()


def apply_tool_visibility(hidden_tools=None):
    """
    Traverses the MEPANANA ribbon and updates item.IsVisible based on the hidden_tools list.
    """
    if hidden_tools is None:
        hidden_tools = get_hidden_tools()
    else:
        hidden_tools = set(hidden_tools) - PROTECTED_TOOLS

    try:
        import clr
        clr.AddReference("AdWindows")
        from Autodesk.Windows import ComponentManager

        ribbon = ComponentManager.Ribbon
        if not ribbon or not ribbon.Tabs:
            return 0

        matched_count = [0]
        for tab in ribbon.Tabs:
            tab_id    = str(getattr(tab, 'Id', '') or '').lower()
            tab_title = str(getattr(tab, 'Title', '') or '').lower()

            if "mepanana" in tab_id or "mepanana" in tab_title:
                for panel in (tab.Panels or []):
                    if not panel or not panel.Source:
                        continue

                    panel_total_tools = [0]
                    panel_visible_tools = [0]

                    # Deep recursive visit
                    def _update_vis(item):
                        if not hasattr(item, 'IsVisible'):
                            return

                        # Extract button names
                        t1 = _clean_text(getattr(item, 'Text', ''))
                        t2 = _clean_text(getattr(item, 'ItemText', ''))
                        auto_name = _clean_text(getattr(item, 'AutomationName', ''))
                        item_id = str(getattr(item, 'Id', '') or '')

                        # Check if any text matches our tools
                        matched_tool = None
                        for p_name, tools in PANEL_TOOLS:
                            for t in tools:
                                if t == t1 or t == t2 or t == auto_name:
                                    matched_tool = t
                                    break
                                # Also check if tool name is part of id
                                if t in item_id:
                                    matched_tool = t
                                    break
                            if matched_tool:
                                break

                        if matched_tool:
                            matched_count[0] += 1
                            panel_total_tools[0] += 1
                            if matched_tool in PROTECTED_TOOLS:
                                item.IsVisible = True
                                panel_visible_tools[0] += 1
                            else:
                                should_hide = matched_tool in hidden_tools
                                item.IsVisible = not should_hide
                                if not should_hide:
                                    panel_visible_tools[0] += 1

                    _traverse_items(panel.Source.Items, _update_vis)
                    if hasattr(panel.Source, 'SlideOutPanelItemsView') and panel.Source.SlideOutPanelItemsView:
                        _traverse_items(panel.Source.SlideOutPanelItemsView, _update_vis)

                    # Post-process containers (e.g. RowPanel for Sprinkler.stack):
                    # Hide container if all its children are hidden
                    _collapse_containers(panel.Source.Items)
                    if hasattr(panel.Source, 'SlideOutPanelItemsView') and panel.Source.SlideOutPanelItemsView:
                        _collapse_containers(panel.Source.SlideOutPanelItemsView)

                    # Determine Panel visibility:
                    # 1. Match panel name/id against PANEL_TOOLS
                    panel_title_clean = _clean_text(getattr(panel.Source, 'Title', '')).lower()
                    panel_id_clean = str(getattr(panel.Source, 'Id', '') or getattr(panel, 'Id', '') or '').lower()

                    matched_panel = False
                    for p_name, p_tools in PANEL_TOOLS:
                        if p_name.lower() in panel_title_clean or p_name.lower() in panel_id_clean:
                            matched_panel = True
                            all_tools_hidden = all(t in hidden_tools for t in p_tools)
                            if hasattr(panel, 'IsVisible'):
                                panel.IsVisible = not all_tools_hidden
                            break

                    # 2. Fallback: if not matched by name, use counted tools inside panel
                    if not matched_panel and panel_total_tools[0] > 0:
                        if hasattr(panel, 'IsVisible'):
                            panel.IsVisible = (panel_visible_tools[0] > 0)

        try:
            ribbon.UpdateLayout()
        except Exception:
            pass

        return matched_count[0]
    except Exception as ex:
        return 0


def _collapse_containers(collection):
    """Recursively hides containers (like RibbonRowPanel / SplitButton) if all children are hidden."""
    if not collection:
        return
    for item in collection:
        if not item:
            continue
        child_colls = []
        for attr in ('Items', 'Panels', 'Children', 'SubItems'):
            val = getattr(item, attr, None)
            if val is not None and not isinstance(val, (str, unicode)):
                child_colls.append(val)

        if child_colls:
            has_visible_child = False
            for coll in child_colls:
                _collapse_containers(coll)
                for child in coll:
                    if hasattr(child, 'IsVisible') and child.IsVisible:
                        has_visible_child = True
                        break
                if has_visible_child:
                    break

            if hasattr(item, 'IsVisible'):
                item.IsVisible = has_visible_child


def _traverse_items(obj, callback):
    """Deeply traverses ribbon elements."""
    if obj is None:
        return
    try:
        callback(obj)
    except Exception:
        pass

    for attr in ('Items', 'Panels', 'Children', 'SubItems'):
        try:
            val = getattr(obj, attr, None)
            if val is not None and not isinstance(val, (str, unicode)):
                for child in val:
                    _traverse_items(child, callback)
        except Exception:
            pass

    try:
        from System.Collections import IEnumerable
        if isinstance(obj, IEnumerable) and not isinstance(obj, (str, unicode)):
            for child in obj:
                _traverse_items(child, callback)
    except Exception:
        pass


# ==============================================================================
# STARTUP IDLING LISTENER
# ==============================================================================
_listener_initialized = False

def _get_idling_target():
    """
    Returns the Revit application object exposing the Idling event.
    Can be UIApplication or UIControlledApplication.
    """
    try:
        from pyrevit import HOST_APP
        if hasattr(HOST_APP, 'uiapp') and HOST_APP.uiapp and hasattr(HOST_APP.uiapp, 'Idling'):
            return HOST_APP.uiapp
    except Exception:
        pass

    try:
        import __builtin__
        rvt = getattr(__builtin__, '__revit__', None)
        if rvt and hasattr(rvt, 'Idling'):
            return rvt
    except Exception:
        pass

    return None


def init_startup_listener():
    """
    Applies hidden tools to the Ribbon.
    Tries immediate application first (for pyRevit reload).
    If the ribbon tab is not yet populated (fresh startup), registers an Idling listener.
    """
    global _listener_initialized
    if _listener_initialized:
        return
    _listener_initialized = True

    try:
        hidden = get_hidden_tools()
        if not hidden:
            return

        # 1. Try immediate application (works when Ribbon is already loaded, e.g. pyRevit Reload)
        applied = apply_tool_visibility(hidden)
        if applied > 0:
            return

        # 2. If not applied yet (fresh Revit launch), register Idling listener on UIApplication
        target = _get_idling_target()
        if not target:
            return

        _attempt_count = [0]
        max_attempts = 15

        def _on_idling(sender, args):
            _attempt_count[0] += 1
            try:
                cur_hidden = get_hidden_tools()
                if not cur_hidden:
                    _detach()
                    return

                res = apply_tool_visibility(cur_hidden)
                if res > 0 or _attempt_count[0] >= 3:
                    _detach()
            except Exception:
                if _attempt_count[0] >= max_attempts:
                    _detach()

        def _detach():
            try:
                target.Idling -= _on_idling
            except Exception:
                pass

        target.Idling += _on_idling
    except Exception:
        pass
