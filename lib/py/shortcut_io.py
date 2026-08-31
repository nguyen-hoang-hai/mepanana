# -*- coding: utf-8 -*-
"""
shortcut_io.py — Keyboard Shortcuts IO & Conflict Resolution Engine for mepanana.
Handles querying Revit KeyboardShortcuts.xml, detecting collisions,
scanning mepanana pushbutton tools, and applying custom shortcuts.
"""
import os
import sys
import shutil
import datetime
import xml.etree.ElementTree as ET

from py.core import safe_unicode

try:
    _unicode = unicode
except NameError:
    _unicode = str


def get_revit_appdata_folder(revit_version=None):
    """
    Finds the active Autodesk Revit AppData directory.
    If revit_version is provided (e.g. '2022'), looks for 'Autodesk Revit 2022'.
    Otherwise searches for the latest installed Revit folder.
    """
    appdata = os.environ.get("APPDATA", "")
    revit_base = os.path.join(appdata, "Autodesk", "Revit")
    if not os.path.exists(revit_base):
        return None

    if revit_version:
        target = os.path.join(revit_base, "Autodesk Revit {}".format(revit_version))
        if os.path.exists(target):
            return target

    # Search for all "Autodesk Revit 20xx" folders and sort descending
    candidates = []
    for item in os.listdir(revit_base):
        full = os.path.join(revit_base, item)
        if os.path.isdir(full) and item.startswith("Autodesk Revit 20"):
            candidates.append(full)

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0]

    return None


def get_keyboard_shortcuts_file_path(revit_version=None):
    """Returns the full path to KeyboardShortcuts.xml."""
    folder = get_revit_appdata_folder(revit_version)
    if not folder:
        return None
    xml_path = os.path.join(folder, "KeyboardShortcuts.xml")
    return xml_path


def parse_command_display_name(command_id):
    """
    Converts a raw Revit CommandId or CustomCtrl into a friendly readable name.
    e.g. 'CustomCtrl_%CustomCtrl_%mepanana%Modeling%CAD to Revit' -> 'CAD to Revit'
    e.g. 'ID_BUTTON_SELECT' -> 'Select'
    e.g. 'ID_OBJECTS_WALL' -> 'Wall'
    """
    if not command_id:
        return "Unknown"

    if command_id.startswith("CustomCtrl_%"):
        parts = command_id.split("%")
        clean_parts = [p for p in parts if p and p != "CustomCtrl_"]
        if clean_parts:
            return clean_parts[-1]

    name = command_id
    for prefix in ["ID_BUTTON_", "ID_OBJECTS_", "ID_TOGGLE_", "ID_"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    name = name.replace("_", " ").title()
    return name


def get_command_name_and_path(command_id):
    """
    Returns (clean_name, path) for a given CommandId.
    e.g. 'CustomCtrl_%CustomCtrl_%mepanana%Data%Schedule Link' -> ('Schedule Link', 'mepanana>Data')
    """
    if not command_id:
        return "Unknown", ""

    if command_id.startswith("CustomCtrl_%"):
        parts = command_id.split("%")
        clean_parts = [p for p in parts if p and p != "CustomCtrl_"]
        if len(clean_parts) >= 3:
            name = clean_parts[-1]
            path = "{}>{}".format(clean_parts[0], clean_parts[1])
            return name, path
        elif clean_parts:
            return clean_parts[-1], ">".join(clean_parts[:-1])

    return parse_command_display_name(command_id), ""


class ShortcutDatabase(object):
    """Loads and caches the entire Revit shortcut database for conflict checking."""

    def __init__(self, revit_version=None):
        self.revit_version = revit_version
        self.file_path = get_keyboard_shortcuts_file_path(revit_version)
        self.commands_map = {}   # command_id -> shortcuts_str
        self.reverse_map = {}    # single_shortcut_token (uppercase) -> (command_id, friendly_name)
        self.tree = None
        self.root = None
        self.load()

    def load(self):
        self.commands_map.clear()
        self.reverse_map.clear()

        if not self.file_path or not os.path.exists(self.file_path):
            return

        try:
            self.tree = ET.parse(self.file_path)
            self.root = self.tree.getroot()
            for item in self.root.findall("ShortcutItem"):
                cmd_id = item.get("CommandId")
                shortcuts = item.get("Shortcuts") or ""
                cmd_name = item.get("CommandName") or parse_command_display_name(cmd_id)
                if cmd_name:
                    cmd_name = " ".join(cmd_name.split())

                if cmd_id:
                    self.commands_map[cmd_id] = shortcuts
                    if shortcuts:
                        tokens = [t.strip().upper() for t in shortcuts.split("#") if t.strip()]
                        for tok in tokens:
                            self.reverse_map[tok] = (cmd_id, cmd_name)
        except Exception as ex:
            print("Error loading KeyboardShortcuts.xml: {}".format(ex))

    def get_shortcut(self, command_id):
        """Returns the shortcut string for a specific CommandId, or ''."""
        return self.commands_map.get(command_id, "")

    def check_conflict(self, candidate_shortcut, exclude_command_id=None):
        """
        Checks if candidate_shortcut (or any of its '#' separated tokens)
        collides with an existing assigned shortcut.
        Returns (has_conflict: bool, conflicting_info: str)
        """
        if not candidate_shortcut or not candidate_shortcut.strip():
            return False, ""

        candidate_tokens = [t.strip().upper() for t in candidate_shortcut.split("#") if t.strip()]
        for tok in candidate_tokens:
            if tok in self.reverse_map:
                existing_cmd_id, existing_name = self.reverse_map[tok]
                if existing_cmd_id != exclude_command_id:
                    return True, u"Shortcut '{}' is already assigned to: {}".format(tok, existing_name)

        return False, ""

    def save_changes(self, updates_dict):
        """
        Applies updates to KeyboardShortcuts.xml.
        updates_dict: { command_id: new_shortcuts_string }
        Creates an automatic timestamped backup before writing.
        Returns (success: bool, message: str)
        """
        if not self.file_path:
            return False, "Could not find KeyboardShortcuts.xml path."

        try:
            # 1. Create Backup
            if os.path.exists(self.file_path):
                now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = "{}.bak_{}".format(self.file_path, now_str)
                shutil.copy2(self.file_path, backup_path)

            # 2. Update or insert into XML tree
            if self.tree is None or self.root is None:
                if os.path.exists(self.file_path):
                    self.tree = ET.parse(self.file_path)
                    self.root = self.tree.getroot()
                else:
                    self.root = ET.Element("Shortcuts")
                    self.tree = ET.ElementTree(self.root)

            # Map existing elements by CommandId
            elem_by_id = {}
            for item in self.root.findall("ShortcutItem"):
                cid = item.get("CommandId")
                if cid:
                    elem_by_id[cid] = item

            for cmd_id, new_sc in updates_dict.items():
                new_sc = (new_sc or "").strip()
                name, path = get_command_name_and_path(cmd_id)
                if cmd_id in elem_by_id:
                    item = elem_by_id[cmd_id]
                    item.set("Shortcuts", new_sc)
                    item.set("CommandName", name)
                    if path:
                        item.set("Paths", path)
                else:
                    new_elem = ET.SubElement(self.root, "ShortcutItem")
                    new_elem.set("CommandName", name)
                    new_elem.set("CommandId", cmd_id)
                    new_elem.set("Shortcuts", new_sc)
                    if path:
                        new_elem.set("Paths", path)

            # 3. Write back
            try:
                ET.indent(self.tree, space="  ", level=0)
            except:
                pass

            self.tree.write(self.file_path, encoding="utf-8", xml_declaration=True)

            # Reload internal cache
            self.load()
            return True, "Shortcuts saved successfully to Revit."
        except Exception as ex:
            return False, "Failed to write KeyboardShortcuts.xml:\n{}".format(safe_unicode(ex))


def scan_mepanana_tools(extension_tab_path=None):
    """
    Scans the mepanana.tab directory and finds all pushbuttons.
    Returns list of dicts:
    [
        {
            "name": "CAD to Revit",
            "panel": "Modeling",
            "command_id": "CustomCtrl_%CustomCtrl_%mepanana%Modeling%CAD to Revit",
            "folder_path": "...",
            "icon_path": "..."
        }, ...
    ]
    """
    if not extension_tab_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        extension_tab_path = os.path.join(base_dir, "mepanana.tab")

    tools = []
    if not os.path.exists(extension_tab_path):
        return tools

    for panel_name in os.listdir(extension_tab_path):
        panel_path = os.path.join(extension_tab_path, panel_name)
        if not os.path.isdir(panel_path) or not panel_name.endswith(".panel"):
            continue

        clean_panel_name = panel_name[:-6] # remove .panel
        if clean_panel_name.startswith("0_"):
            clean_panel_name = clean_panel_name[2:]

        panel_tag = clean_panel_name

        def process_pushbutton(btn_path, btn_name):
            if not os.path.exists(os.path.join(btn_path, "script.py")):
                return
            clean_btn_name = btn_name.rsplit(".", 1)[0]
            bundle_file = os.path.join(btn_path, "bundle.yaml")
            title = clean_btn_name
            if os.path.exists(bundle_file):
                try:
                    with open(bundle_file, "r") as f:
                        for line in f:
                            if line.strip().startswith("title:"):
                                title = line.split(":", 1)[1].strip()
                                break
                except:
                    pass
            command_id = "CustomCtrl_%CustomCtrl_%mepanana%{}%{}".format(panel_tag, title)
            icon_path = os.path.join(btn_path, "icon.png")
            tools.append({
                "name": title,
                "panel": clean_panel_name,
                "command_id": command_id,
                "folder_path": btn_path,
                "icon_path": icon_path if os.path.exists(icon_path) else None
            })

        for item_name in os.listdir(panel_path):
            item_path = os.path.join(panel_path, item_name)
            if not os.path.isdir(item_path):
                continue
            if item_name.endswith(".pushbutton"):
                process_pushbutton(item_path, item_name)
            elif any(item_name.endswith(ext) for ext in [".stack", ".pulldown", ".splitpushbutton", ".splitbutton"]):
                for sub_name in os.listdir(item_path):
                    sub_path = os.path.join(item_path, sub_name)
                    if os.path.isdir(sub_path) and sub_name.endswith(".pushbutton"):
                        process_pushbutton(sub_path, sub_name)

    tools.sort(key=lambda t: (t["panel"], t["name"]))
    return tools