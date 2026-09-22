# -*- coding: utf-8 -*-
"""
DEBUG: Dump Ribbon Items for mepanana tab
Chạy tool này trong Revit để xem ID/Text/AutomationName thực tế của ribbon items.
Paste kết quả ra cho AI để debug.
"""
__title__ = "TV Debug"
__doc__ = "Debug: Dump mepanana ribbon item names/IDs to console."

import os, sys
lib_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from py.auth import is_authenticated, update_ribbon_state
if not is_authenticated():
    update_ribbon_state(False)
    sys.exit()

try:
    import clr
    clr.AddReference("AdWindows")
    from Autodesk.Windows import ComponentManager

    ribbon = ComponentManager.Ribbon
    output = []

    def walk(obj, depth=0):
        indent = "  " * depth
        t1 = str(getattr(obj, 'Text', '') or '').strip()
        t2 = str(getattr(obj, 'ItemText', '') or '').strip()
        t3 = str(getattr(obj, 'AutomationName', '') or '').strip()
        oid = str(getattr(obj, 'Id', '') or '').strip()
        cls = type(obj).__name__
        visible = getattr(obj, 'IsVisible', '?')
        output.append("{}[{}] Text='{}' ItemText='{}' AutoName='{}' Id='{}' Visible={}".format(
            indent, cls, t1, t2, t3, oid, visible
        ))
        for attr in ('Items', 'Panels', 'Children', 'SubItems'):
            val = getattr(obj, attr, None)
            if val is not None:
                try:
                    for child in val:
                        walk(child, depth + 1)
                except Exception:
                    pass

    for tab in ribbon.Tabs:
        tab_id = str(getattr(tab, 'Id', '') or '').lower()
        tab_title = str(getattr(tab, 'Title', '') or '').lower()
        if 'mepanana' in tab_id or 'mepanana' in tab_title:
            output.append("=== TAB: '{}' id='{}' ===".format(tab_title, tab_id))
            for panel in (tab.Panels or []):
                panel_title = str(getattr(getattr(panel, 'Source', panel), 'Title', '') or '')
                panel_id = str(getattr(getattr(panel, 'Source', panel), 'Id', '') or getattr(panel, 'Id', '') or '')
                output.append("  PANEL: title='{}' id='{}' IsVisible={}".format(
                    panel_title, panel_id, getattr(panel, 'IsVisible', '?')
                ))
                if panel and panel.Source:
                    for item in (panel.Source.Items or []):
                        walk(item, 2)

    result = "\n".join(output)
    from Autodesk.Revit.UI import TaskDialog
    td = TaskDialog("TV Debug - Ribbon Dump")
    td.MainInstruction = "Copy kết quả bên dưới và gửi cho AI:"
    td.MainContent = result[:4096]
    td.Show()

    # Also write to temp file for full output
    tmp = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'mepanana_ribbon_dump.txt')
    with open(tmp, 'w') as f:
        f.write(result)
    print("Full dump saved to: " + tmp)

except Exception:
    import traceback
    from Autodesk.Revit.UI import TaskDialog
    TaskDialog.Show("TV Debug Error", traceback.format_exc())
