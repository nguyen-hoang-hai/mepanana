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

# Flat list of all known tool names for quick lookup
_ALL_TOOLS = set()
for _p, _ts in PANEL_TOOLS:
    _ALL_TOOLS.update(_ts)


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


def _item_matches_tool(item, tool_name):
    """
    Returns True if the AdWindows ribbon item matches the given tool_name.
    Uses multiple heuristics: Text, AutomationName, Id, Name.
    """
    candidates = []
    for attr in ('Text', 'AutomationName', 'Name'):
        v = _clean_text(getattr(item, attr, ''))
        if v:
            candidates.append(v)

    # Direct text match
    for c in candidates:
        if c == tool_name:
            return True

    # Id substring match — pyRevit encodes tool names into the Id/UID
    # e.g. "mepanana.tab%Modeling.panel%Bloom.pushbutton" or similar
    oid = str(getattr(item, 'Id', '') or getattr(item, 'UID', '') or '')
    tool_slug = tool_name.lower().replace(" ", "")
    if tool_slug in oid.lower().replace(" ", "").replace("-", "").replace("_", ""):
        return True

    return False


def apply_tool_visibility(hidden_tools=None):
    """
    Traverses the MEPANANA ribbon via AdWindows and updates item visibility.
    Returns count of items successfully matched and processed.
    """
    if hidden_tools is None:
        hidden_tools = get_hidden_tools()
    else:
        hidden_tools = set(hidden_tools) - PROTECTED_TOOLS

    matched_count = [0]
    log_lines = []

    try:
        import clr
        clr.AddReference("AdWindows")
        from Autodesk.Windows import ComponentManager

        ribbon = ComponentManager.Ribbon
        if not ribbon or not ribbon.Tabs:
            return 0

        for tab in ribbon.Tabs:
            tab_id    = str(getattr(tab, 'Id', '') or '').lower()
            tab_title = str(getattr(tab, 'Title', '') or '').lower()

            if "mepanana" not in tab_id and "mepanana" not in tab_title:
                continue

            for panel in (tab.Panels or []):
                if not panel or not panel.Source:
                    continue

                panel_any_visible = [False]

                # Traverse all leaf items in this panel
                def _visit(item):
                    cls = type(item).__name__

                    # --- Leaf items: actual buttons ---
                    if hasattr(item, 'IsVisible'):
                        text    = _clean_text(getattr(item, 'Text', ''))
                        autoname = _clean_text(getattr(item, 'AutomationName', ''))
                        name    = _clean_text(getattr(item, 'Name', ''))
                        oid     = str(getattr(item, 'Id', '') or getattr(item, 'UID', '') or '')

                        log_lines.append("  [{}] Text='{}' Auto='{}' Name='{}' Id='{}'".format(
                            cls, text, autoname, name, oid[:80]))

                        # Find matching tool name
                        matched_tool = None
                        for p_name, tools in PANEL_TOOLS:
                            for t in tools:
                                if _item_matches_tool(item, t):
                                    matched_tool = t
                                    break
                            if matched_tool:
                                break

                        if matched_tool:
                            matched_count[0] += 1
                            if matched_tool in PROTECTED_TOOLS:
                                item.IsVisible = True
                                panel_any_visible[0] = True
                            else:
                                should_hide = matched_tool in hidden_tools
                                item.IsVisible = not should_hide
                                log_lines[-1] += " -> should_hide={} visible={}".format(
                                    should_hide, item.IsVisible)
                                if not should_hide:
                                    panel_any_visible[0] = True

                # Simple flat traversal — visit every item in the tree
                _flat_walk(panel.Source.Items, _visit)

                # After processing all items in the panel, collapse empty containers
                _collapse_empty(panel.Source.Items)

            # After processing panels, collapse any fully-hidden panels
            for panel in (tab.Panels or []):
                if not panel or not panel.Source:
                    continue
                # Check if any tool is visible in this panel
                panel_has_visible = _any_visible(panel.Source.Items)
                if hasattr(panel, 'IsVisible'):
                    panel.IsVisible = panel_has_visible

        try:
            ribbon.UpdateLayout()
        except Exception:
            pass

        # Write debug log to temp file
        try:
            tmp = os.path.join(os.environ.get('TEMP', ''), 'mepanana_tv_debug.txt')
            with open(tmp, 'w') as f:
                f.write("hidden_tools={}\n".format(list(hidden_tools)))
                f.write("matched={}\n\n".format(matched_count[0]))
                f.write("\n".join(log_lines))
        except Exception:
            pass

        return matched_count[0]

    except Exception as ex:
        try:
            tmp = os.path.join(os.environ.get('TEMP', ''), 'mepanana_tv_error.txt')
            with open(tmp, 'w') as f:
                import traceback
                f.write(traceback.format_exc())
        except Exception:
            pass
        return 0


def _flat_walk(collection, callback):
    """Flat walk: visit every item in the tree (depth-first), calling callback on each."""
    if not collection:
        return
    for item in collection:
        if item is None:
            continue
        try:
            callback(item)
        except Exception:
            pass
        # Walk children — wrap each attr individually to avoid IronPython protected-member TypeError
        for attr in ('Items', 'Children', 'SubItems'):
            try:
                val = getattr(item, attr, None)
            except (TypeError, AttributeError, Exception):
                continue
            try:
                if val is not None and not isinstance(val, (str, unicode)):
                    _flat_walk(val, callback)
            except Exception:
                pass


def _any_visible(collection):
    """Returns True if any leaf item with IsVisible=True exists in the tree."""
    if not collection:
        return False
    for item in collection:
        if item is None:
            continue
        # Check children first
        has_children = False
        for attr in ('Items', 'Children', 'SubItems'):
            try:
                val = getattr(item, attr, None)
            except (TypeError, AttributeError, Exception):
                continue
            if val is not None and not isinstance(val, (str, unicode)):
                try:
                    lst = list(val)
                    if lst:
                        has_children = True
                        if _any_visible(val):
                            return True
                except Exception:
                    pass

        if not has_children:
            if hasattr(item, 'IsVisible') and item.IsVisible:
                return True
    return False


def _collapse_empty(collection):
    """Recursively collapses container items (row panels, split buttons) that have no visible children."""
    if not collection:
        return
    for item in collection:
        if item is None:
            continue
        # Only collapse containers (items that have sub-collections)
        child_colls = []
        for attr in ('Items', 'Children', 'SubItems'):
            try:
                val = getattr(item, attr, None)
            except (TypeError, AttributeError, Exception):
                continue
            if val is not None and not isinstance(val, (str, unicode)):
                try:
                    lst = list(val)
                    if lst:
                        child_colls.append((attr, val))
                except Exception:
                    pass

        if child_colls:
            # Recurse first
            for attr, coll in child_colls:
                _collapse_empty(coll)

            # Now check if any child is visible
            has_visible = False
            for attr, coll in child_colls:
                try:
                    for child in coll:
                        if hasattr(child, 'IsVisible') and child.IsVisible:
                            has_visible = True
                            break
                except Exception:
                    pass
                if has_visible:
                    break

            if hasattr(item, 'IsVisible'):
                item.IsVisible = has_visible


# ==============================================================================
# STARTUP IDLING LISTENER
# ==============================================================================
_listener_initialized = False


def _get_idling_target():
    """
    Returns the Revit application object exposing the Idling event.
    UIApplication preferred; falls back to __revit__ builtin.
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
