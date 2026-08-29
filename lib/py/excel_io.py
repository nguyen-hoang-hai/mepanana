# -*- coding: utf-8 -*-
"""
Excel IO module for ScheduleLink.
Handles exporting to .xlsx (via xlsxwriter) and reading from .xlsx (pure Python zip/XML).
"""
import sys
import os
import zipfile
import xml.etree.ElementTree as ET

try:
    _unicode = unicode
except NameError:
    _unicode = str

# Ensure pyRevit site-packages is in sys.path for xlsxwriter
appdata = os.environ.get("APPDATA", "")
site_pkg = os.path.join(appdata, "pyRevit-Master", "site-packages")
if os.path.exists(site_pkg) and site_pkg not in sys.path:
    sys.path.append(site_pkg)


def export_schedules_to_excel(file_path, schedules_data):
    """
    Exports multiple schedules to an Excel (.xlsx) file.
    schedules_data: list of dicts:
        {
            "name": "Lighting Fixtures",
            "headers": ["_ElementId", "Mark", "Type", ...],
            "rows": [
                ["12345", "LT-01", "18W Downlight", ...],
                ...
            ]
        }
    """
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)

    # Styles
    fmt_header = workbook.add_format({
        'bold': True,
        'font_name': 'Segoe UI',
        'font_size': 10,
        'bg_color': '#0F172A',
        'font_color': '#FFFFFF',
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#CBD5E1',
    })

    fmt_id_header = workbook.add_format({
        'bold': True,
        'font_name': 'Segoe UI',
        'font_size': 10,
        'bg_color': '#334155',
        'font_color': '#94A3B8',
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#CBD5E1',
    })

    fmt_id_cell = workbook.add_format({
        'font_name': 'Segoe UI',
        'font_size': 9.5,
        'bg_color': '#F1F5F9',
        'font_color': '#64748B',
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#E2E8F0',
    })

    fmt_cell = workbook.add_format({
        'font_name': 'Segoe UI',
        'font_size': 9.5,
        'bg_color': '#FFFFFF',
        'font_color': '#0F172A',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#E2E8F0',
    })

    fmt_cell_alt = workbook.add_format({
        'font_name': 'Segoe UI',
        'font_size': 9.5,
        'bg_color': '#F8FAFC',
        'font_color': '#0F172A',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#E2E8F0',
    })

    # Excel sheet name limit is 31 characters
    used_sheet_names = set()

    for item in schedules_data:
        raw_name = item.get("name", "Schedule")
        # Clean invalid characters: \ / ? * : [ ]
        for ch in ['\\', '/', '?', '*', ':', '[', ']']:
            raw_name = raw_name.replace(ch, '_')
        sheet_name = raw_name[:31]
        
        # Ensure unique name
        counter = 1
        base_name = sheet_name[:28]
        while sheet_name.lower() in used_sheet_names:
            sheet_name = "{}_{}".format(base_name, counter)
            counter += 1
        used_sheet_names.add(sheet_name.lower())

        ws = workbook.add_worksheet(sheet_name)
        ws.set_row(0, 26)  # Header row height
        ws.freeze_panes(1, 1)  # Freeze header and _ElementId column

        headers = item.get("headers", [])
        rows = item.get("rows", [])

        # Write Headers
        col_widths = [14] * len(headers)
        for col_idx, h in enumerate(headers):
            is_id = h.startswith("_") or "id" in h.lower()
            style = fmt_id_header if is_id else fmt_header
            ws.write(0, col_idx, h, style)
            col_widths[col_idx] = max(col_widths[col_idx], len(str(h)) + 4)

        # Write Data Rows
        for r_idx, row in enumerate(rows):
            row_num = r_idx + 1
            ws.set_row(row_num, 20)
            is_alt = (r_idx % 2 == 1)
            row_style = fmt_cell_alt if is_alt else fmt_cell

            for c_idx, val in enumerate(row):
                is_id = (c_idx == 0) and (headers and (headers[0].startswith("_") or "id" in headers[0].lower()))
                cell_style = fmt_id_cell if is_id else row_style
                str_val = u"" if val is None else _unicode(val)
                ws.write(row_num, c_idx, str_val, cell_style)
                if c_idx < len(col_widths):
                    col_widths[c_idx] = min(max(col_widths[c_idx], len(str_val) + 3), 45)

        # Set column widths
        for col_idx, width in enumerate(col_widths):
            ws.set_column(col_idx, col_idx, width)

    workbook.close()
    return True


def read_excel_workbook(file_path):
    """
    Reads all sheets, headers, and rows from an .xlsx file using standard zipfile/XML.
    Returns dict:
    {
        "SheetName": {
            "headers": ["_ElementId", "Mark", ...],
            "rows": [
                {"_ElementId": "12345", "Mark": "LT-01", ...},
                ...
            ]
        }
    }
    """
    if not os.path.exists(file_path):
        raise IOError("File does not exist: {}".format(file_path))

    z = zipfile.ZipFile(file_path)

    # 1. Read Shared Strings
    shared_strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root:
            t_nodes = [elem for elem in si.iter() if elem.tag.endswith('t')]
            text = "".join(t.text for t in t_nodes if t.text is not None)
            shared_strings.append(text)

    # 2. Read Workbook Sheet Info
    wb_root = ET.fromstring(z.read("xl/workbook.xml"))
    sheet_meta = []
    for elem in wb_root.iter():
        if elem.tag.endswith('sheet') and 'name' in elem.attrib:
            r_id = elem.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id', '')
            sheet_meta.append((elem.attrib['name'], r_id))

    # 3. Read Workbook Relationships to find sheet XML paths
    sheet_rel_map = {}
    if "xl/_rels/workbook.xml.rels" in z.namelist():
        rel_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for elem in rel_root.iter():
            if elem.tag.endswith('Relationship'):
                rel_id = elem.attrib.get('Id', '')
                target = elem.attrib.get('Target', '')
                sheet_rel_map[rel_id] = target

    result = {}

    for idx, (sheet_name, r_id) in enumerate(sheet_meta):
        target_path = sheet_rel_map.get(r_id, "worksheets/sheet{}.xml".format(idx + 1))
        if not target_path.startswith("xl/"):
            target_path = "xl/" + target_path.lstrip('/')

        if target_path not in z.namelist():
            target_path = "xl/worksheets/sheet{}.xml".format(idx + 1)
            if target_path not in z.namelist():
                continue

        sheet_xml = z.read(target_path)
        sheet_root = ET.fromstring(sheet_xml)

        # Parse rows and columns
        rows_map = {}
        for row_elem in sheet_root.iter():
            if row_elem.tag.endswith('row'):
                r_idx = int(row_elem.attrib.get('r', 0))
                cells = {}
                for c in row_elem.iter():
                    if c.tag.endswith('c'):
                        ref = c.attrib.get('r', '')
                        col_letters = ''.join([ch for ch in ref if ch.isalpha()])
                        t = c.attrib.get('t', '')
                        v_node = next((e for e in c if e.tag.endswith('v')), None)
                        val = v_node.text if v_node is not None else ""
                        if t == 's' and val.isdigit():
                            idx_str = int(val)
                            val = shared_strings[idx_str] if idx_str < len(shared_strings) else ""
                        elif t == 'b':
                            val = "True" if val == "1" else "False"
                        cells[col_letters] = val
                if cells:
                    rows_map[r_idx] = cells

        if not rows_map:
            continue

        sorted_row_indices = sorted(rows_map.keys())
        header_row_idx = sorted_row_indices[0]
        header_cells = rows_map[header_row_idx]

        def col_to_num(col_str):
            num = 0
            for c in col_str:
                num = num * 26 + (ord(c.upper()) - ord('A') + 1)
            return num

        sorted_cols = sorted(header_cells.keys(), key=col_to_num)
        headers = [header_cells.get(c, "") for c in sorted_cols]

        rows_data = []
        for r_idx in sorted_row_indices[1:]:
            row_dict = {}
            row_cells = rows_map[r_idx]
            for col_letter, h in zip(sorted_cols, headers):
                if h:
                    row_dict[h] = row_cells.get(col_letter, "")
            rows_data.append(row_dict)

        result[sheet_name] = {
            "headers": headers,
            "rows": rows_data
        }

    return result