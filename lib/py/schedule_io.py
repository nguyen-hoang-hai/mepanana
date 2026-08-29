# -*- coding: utf-8 -*-
"""
Schedule IO module for ScheduleLink.
Handles querying Revit ViewSchedules, extracting data with _ElementId,
diff comparison, and transactional parameter updates.
"""
from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewSchedule, ViewType,
    SectionType, ElementId, StorageType
)
from py.core import SafeTransaction


def get_all_schedules(doc):
    """
    Returns a sorted list of user-facing ViewSchedule items in the document.
    Excludes templates, internal revision schedules, and titleblock revision tables.
    """
    collector = FilteredElementCollector(doc).OfClass(ViewSchedule)
    schedules = []
    for vs in collector:
        if vs.IsTemplate:
            continue
        if getattr(vs, "IsInternalKeySchedule", False):
            continue
        # Filter out internal <Revision Schedule>
        name = vs.Name or ""
        if name.startswith("<") or (name.startswith("<Revision") and name.endswith(">")):
            continue
            
        view_type = getattr(vs, "ViewType", None)
        if view_type == ViewType.Schedule or view_type == ViewType.CostReport or view_type == ViewType.ColumnSchedule:
            schedules.append({
                "id": vs.Id.IntegerValue,
                "name": name,
                "view": vs
            })
    schedules.sort(key=lambda s: s["name"].lower())
    return schedules


def extract_schedule_data(doc, view_schedule, visible_only=True):
    """
    Extracts headers and rows from a ViewSchedule.
    Returns:
    {
        "name": view_schedule.Name,
        "headers": ["_ElementId", "Field 1", "Field 2", ...],
        "rows": [
            ["12345", "Value 1", "Value 2", ...],
            ...
        ]
    }
    """
    definition = view_schedule.Definition
    field_count = definition.GetFieldCount()
    
    headers = ["_ElementId"]
    fields = []
    
    for i in range(field_count):
        field = definition.GetField(i)
        if visible_only and field.IsHidden:
            continue
        name = field.GetName()
        headers.append(name)
        fields.append(field)

    # Get elements included in the schedule
    collector = FilteredElementCollector(doc, view_schedule.Id)
    scheduled_elements = list(collector.ToElements())
    
    table_data = view_schedule.GetTableData()
    section_data = table_data.GetSectionData(SectionType.Body)
    
    num_rows = section_data.NumberOfRows
    num_cols = section_data.NumberOfColumns
    
    rows = []
    
    # Check if number of scheduled elements matches body rows (itemized schedule)
    if len(scheduled_elements) == num_rows:
        for r_idx, elem in enumerate(scheduled_elements):
            row_vals = [str(elem.Id.IntegerValue)]
            for c_idx in range(num_cols):
                cell_text = view_schedule.GetCellText(SectionType.Body, r_idx, c_idx)
                row_vals.append(cell_text or "")
            rows.append(row_vals)
    else:
        # If schedule is grouped or elements don't match 1:1, extract directly from elements
        for elem in scheduled_elements:
            row_vals = [str(elem.Id.IntegerValue)]
            for f in fields:
                field_name = f.GetName()
                param = elem.LookupParameter(field_name)
                if not param:
                    type_id = elem.GetTypeId()
                    if type_id and type_id != ElementId.InvalidElementId:
                        elem_type = doc.GetElement(type_id)
                        if elem_type:
                            param = elem_type.LookupParameter(field_name)
                
                val_str = ""
                if param:
                    val_str = param.AsValueString() or param.AsString() or ""
                    if not val_str:
                        if param.StorageType == StorageType.Double:
                            val_str = str(round(param.AsDouble(), 4))
                        elif param.StorageType == StorageType.Integer:
                            val_str = str(param.AsInteger())
                        elif param.StorageType == StorageType.String:
                            val_str = param.AsString() or ""
                row_vals.append(val_str)
            rows.append(row_vals)

    return {
        "name": view_schedule.Name,
        "headers": headers,
        "rows": rows
    }


def preview_schedule_diff(doc, excel_data):
    """
    Compares Excel data against Revit elements and returns a diff summary.
    Returns:
    {
        "total_changes": N,
        "total_readonly": N,
        "total_unchanged": N,
        "details": [
            {
                "sheet": "Lighting",
                "element_id": "12345",
                "field": "Comments",
                "old_val": "Old",
                "new_val": "New",
                "status": "CHANGED" | "READONLY" | "NOT_FOUND"
            }
        ]
    }
    """
    details = []
    total_changes = 0
    total_readonly = 0
    total_unchanged = 0
    total_errors = 0

    for sheet_name, sheet_data in excel_data.items():
        headers = sheet_data.get("headers", [])
        rows = sheet_data.get("rows", [])
        
        id_key = next((h for h in headers if h.startswith("_") or "id" in h.lower()), None)
        if not id_key:
            continue

        for row in rows:
            eid_raw = row.get(id_key, "")
            if not eid_raw or not str(eid_raw).strip().isdigit():
                continue

            eid_int = int(str(eid_raw).strip())
            elem = doc.GetElement(ElementId(eid_int))
            if not elem:
                total_errors += 1
                details.append({
                    "sheet": sheet_name,
                    "element_id": str(eid_int),
                    "field": "-",
                    "old_val": "-",
                    "new_val": "-",
                    "status": "NOT_FOUND"
                })
                continue

            for field_name, new_val in row.items():
                if field_name == id_key or not field_name:
                    continue

                param = elem.LookupParameter(field_name)
                if not param:
                    type_id = elem.GetTypeId()
                    if type_id and type_id != ElementId.InvalidElementId:
                        elem_type = doc.GetElement(type_id)
                        if elem_type:
                            param = elem_type.LookupParameter(field_name)

                if not param:
                    continue

                # Current value string
                cur_val = param.AsValueString() or param.AsString() or ""
                if not cur_val:
                    if param.StorageType == StorageType.Double:
                        cur_val = str(round(param.AsDouble(), 4))
                    elif param.StorageType == StorageType.Integer:
                        cur_val = str(param.AsInteger())
                    elif param.StorageType == StorageType.String:
                        cur_val = param.AsString() or ""

                new_val_clean = str(new_val).strip() if new_val is not None else ""
                cur_val_clean = str(cur_val).strip()

                if new_val_clean != cur_val_clean:
                    if param.IsReadOnly:
                        total_readonly += 1
                        status = "READONLY"
                    else:
                        total_changes += 1
                        status = "CHANGED"

                    details.append({
                        "sheet": sheet_name,
                        "element_id": str(eid_int),
                        "field": field_name,
                        "old_val": cur_val_clean,
                        "new_val": new_val_clean,
                        "status": status
                    })
                else:
                    total_unchanged += 1

    return {
        "total_changes": total_changes,
        "total_readonly": total_readonly,
        "total_unchanged": total_unchanged,
        "total_errors": total_errors,
        "details": details
    }


def apply_schedule_import(doc, excel_data):
    """
    Updates element parameters from Excel data in a SafeTransaction.
    Returns:
    {
        "updated_count": N,
        "readonly_count": N,
        "error_count": N
    }
    """
    updated_count = 0
    readonly_count = 0
    error_count = 0

    with SafeTransaction(doc, "ScheduleLink Import"):
        for sheet_name, sheet_data in excel_data.items():
            headers = sheet_data.get("headers", [])
            rows = sheet_data.get("rows", [])
            
            id_key = next((h for h in headers if h.startswith("_") or "id" in h.lower()), None)
            if not id_key:
                continue

            for row in rows:
                eid_raw = row.get(id_key, "")
                if not eid_raw or not str(eid_raw).strip().isdigit():
                    continue

                eid_int = int(str(eid_raw).strip())
                elem = doc.GetElement(ElementId(eid_int))
                if not elem:
                    error_count += 1
                    continue

                for field_name, new_val in row.items():
                    if field_name == id_key or not field_name:
                        continue

                    param = elem.LookupParameter(field_name)
                    if not param:
                        type_id = elem.GetTypeId()
                        if type_id and type_id != ElementId.InvalidElementId:
                            elem_type = doc.GetElement(type_id)
                            if elem_type:
                                param = elem_type.LookupParameter(field_name)

                    if not param:
                        continue

                    if param.IsReadOnly:
                        readonly_count += 1
                        continue

                    # Apply value based on StorageType
                    val_str = str(new_val).strip() if new_val is not None else ""
                    try:
                        st = param.StorageType
                        if st == StorageType.String:
                            param.Set(val_str)
                            updated_count += 1
                        elif st == StorageType.Double:
                            if not param.SetValueString(val_str):
                                param.Set(float(val_str))
                            updated_count += 1
                        elif st == StorageType.Integer:
                            if val_str.lower() in ["yes", "true", "1"]:
                                param.Set(1)
                            elif val_str.lower() in ["no", "false", "0"]:
                                param.Set(0)
                            else:
                                param.Set(int(float(val_str)))
                            updated_count += 1
                        elif st == StorageType.ElementId:
                            if val_str.isdigit():
                                param.Set(ElementId(int(val_str)))
                                updated_count += 1
                    except Exception:
                        error_count += 1

    return {
        "updated_count": updated_count,
        "readonly_count": readonly_count,
        "error_count": error_count
    }