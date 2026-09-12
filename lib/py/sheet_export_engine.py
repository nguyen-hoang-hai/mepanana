# -*- coding: utf-8 -*-
"""
sheet_export_engine.py - Automated Batch Sheet Export Engine for MEPANANA
Supports Native Revit 2022+ PDF Export and Native DWG Export with:
- Auto paper size detection (A0, A1, A2, A3, A4) & orientation (Landscape/Portrait)
  from TitleBlock geometry and parameters.
- Flexible token-based filename builder ([Sheet Number] - [Sheet Name] - Rev[Current Revision]).
- Support for Single Combined PDF or Separate Individual Files.
- Non-blocking batch processing with Dispatcher pumping (do_events).

Part of mepanana.extension.
Author: Hai Nguyen
"""
import os
import re
import traceback

import clr
clr.AddReference("System")
clr.AddReference("System.Core")
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    ViewSheet, ElementId, XYZ
)

try:
    from Autodesk.Revit.DB import (
        PDFExportOptions, ExportPaperFormat, PageOrientationType,
        ColorDepthType, ZoomType, RasterQualityType
    )
    NATIVE_PDF_SUPPORTED = True
except Exception:
    NATIVE_PDF_SUPPORTED = False

try:
    from Autodesk.Revit.DB import DWGExportOptions, ACADVersion, ExportDWGSettings
    DWG_SUPPORTED = True
except Exception:
    DWG_SUPPORTED = False

from py.core import safe_unicode, mm_to_ft, ft_to_mm


# Standard ISO A-Series dimensions in mm (short_side, long_side)
ISO_PAPER_SIZES = {
    "A0": (841.0, 1189.0),
    "A1": (594.0, 841.0),
    "A2": (420.0, 594.0),
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
}


# -- 1. Data Model for Sheet Items --------------------------------------------

class SheetExportItem(object):
    """View-model item representing a Revit sheet in the UI DataGrid."""
    def __init__(self, sheet, paper_size_name="A1", orientation_name="Landscape",
                 paper_format_enum=None, orientation_enum=None):
        self.Sheet = sheet
        self.Id = sheet.Id
        self.SheetNumber = sheet.SheetNumber or ""
        self.SheetName = sheet.Name or ""
        self.IsSelected = True
        self.IsPlaceholder = sheet.IsPlaceholder

        # Revision
        rev_param = sheet.get_Parameter(BuiltInParameter.SHEET_CURRENT_REVISION)
        self.Revision = rev_param.AsString() if rev_param and rev_param.HasValue else ""

        # Detected Paper Format
        self.PaperSizeName = paper_size_name
        self.OrientationName = orientation_name
        self.PaperFormatEnum = paper_format_enum
        self.OrientationEnum = orientation_enum

        # Short tag for UI display: e.g. "A1 (L)" or "A3 (P)"
        ori_short = "L" if "Land" in orientation_name else "P"
        self.FormatTag = "{} ({})".format(paper_size_name, ori_short)

    def __repr__(self):
        return "<SheetExportItem {} - {} [{}]>".format(
            self.SheetNumber, self.SheetName, self.FormatTag
        )


# -- 2. Auto-Detection of Paper Size & Orientation ----------------------------

def detect_sheet_paper_format(doc, sheet):
    """
    Detects the paper size (A0-A4) and orientation (Landscape/Portrait)
    by inspecting the TitleBlock family instance on the sheet.
    Returns: (size_name, orientation_name, paper_format_enum, orientation_enum)
    """
    default_format = getattr(ExportPaperFormat, "ISO_A1", None) if NATIVE_PDF_SUPPORTED else None
    default_ori = getattr(PageOrientationType, "Landscape", None) if NATIVE_PDF_SUPPORTED else None

    col = (FilteredElementCollector(doc, sheet.Id)
           .OfCategory(BuiltInCategory.OST_TitleBlocks)
           .WhereElementIsNotElementType())
    tb = col.FirstElement()

    if not tb:
        return ("A1", "Landscape", default_format, default_ori)

    # 1. Try reading standard TitleBlock width and height parameters
    w_param = tb.get_Parameter(BuiltInParameter.SHEET_WIDTH)
    h_param = tb.get_Parameter(BuiltInParameter.SHEET_HEIGHT)

    w_mm = 0.0
    h_mm = 0.0

    if w_param and h_param and w_param.HasValue and h_param.HasValue:
        w_mm = w_param.AsDouble() * 304.8
        h_mm = h_param.AsDouble() * 304.8

    # 2. Fallback to geometry BoundingBox on sheet view
    if w_mm <= 10.0 or h_mm <= 10.0:
        bb = tb.get_BoundingBox(sheet)
        if bb:
            w_mm = abs(bb.Max.X - bb.Min.X) * 304.8
            h_mm = abs(bb.Max.Y - bb.Min.Y) * 304.8

    if w_mm <= 10.0 or h_mm <= 10.0:
        return ("A1", "Landscape", default_format, default_ori)

    # 3. Determine Orientation
    if w_mm >= h_mm:
        orientation_name = "Landscape"
        orientation_enum = getattr(PageOrientationType, "Landscape", None) if NATIVE_PDF_SUPPORTED else None
        short_side, long_side = h_mm, w_mm
    else:
        orientation_name = "Portrait"
        orientation_enum = getattr(PageOrientationType, "Portrait", None) if NATIVE_PDF_SUPPORTED else None
        short_side, long_side = w_mm, h_mm

    # 4. Compare against ISO A-series with tolerance (15mm for margins/borders)
    TOLERANCE_MM = 15.0
    detected_size = "A1"
    paper_format_enum = default_format

    for name, (iso_short, iso_long) in ISO_PAPER_SIZES.items():
        if (abs(short_side - iso_short) <= TOLERANCE_MM and
                abs(long_side - iso_long) <= TOLERANCE_MM):
            detected_size = name
            if NATIVE_PDF_SUPPORTED:
                enum_name = "ISO_" + name
                paper_format_enum = getattr(ExportPaperFormat, enum_name, default_format)
            break
    else:
        # Check if proportional to A-series (e.g. elongated title blocks)
        ratio = long_side / (short_side if short_side > 0 else 1.0)
        if 1.35 <= ratio <= 1.50:
            if long_side >= 1000:
                detected_size = "A0"
                paper_format_enum = getattr(ExportPaperFormat, "ISO_A0", default_format)
            elif long_side >= 750:
                detected_size = "A1"
                paper_format_enum = getattr(ExportPaperFormat, "ISO_A1", default_format)
            elif long_side >= 500:
                detected_size = "A2"
                paper_format_enum = getattr(ExportPaperFormat, "ISO_A2", default_format)
            elif long_side >= 350:
                detected_size = "A3"
                paper_format_enum = getattr(ExportPaperFormat, "ISO_A3", default_format)
            else:
                detected_size = "A4"
                paper_format_enum = getattr(ExportPaperFormat, "ISO_A4", default_format)

    return (detected_size, orientation_name, paper_format_enum, orientation_enum)


def get_all_sheets(doc, include_placeholders=False):
    """
    Returns a sorted list of SheetExportItem view-models for all sheets in the project.
    """
    col = FilteredElementCollector(doc).OfClass(ViewSheet).WhereElementIsNotElementType()
    sheets = []
    for s in col:
        if not s.IsTemplate:
            if not include_placeholders and s.IsPlaceholder:
                continue
            sheets.append(s)

    # Sort naturally by SheetNumber
    def natural_sort_key(s):
        num = s.SheetNumber or ""
        return [int(text) if text.isdigit() else text.lower()
                for text in re.split(r'(\d+)', num)]

    sheets.sort(key=natural_sort_key)

    items = []
    for s in sheets:
        size_name, ori_name, fmt_enum, ori_enum = detect_sheet_paper_format(doc, s)
        item = SheetExportItem(
            s, paper_size_name=size_name, orientation_name=ori_name,
            paper_format_enum=fmt_enum, orientation_enum=ori_enum
        )
        items.append(item)

    return items


# -- 3. Token-based Filename Builder ------------------------------------------

def build_sheet_filename(doc, sheet, pattern_template):
    """
    Replaces [ParamName] tokens with actual values from the Sheet or Project Information.
    Example template: '[Sheet Number] - [Sheet Name] - Rev[Current Revision]'
    Cleans all invalid Windows characters (\\ / : * ? \" < > |).
    """
    if not pattern_template:
        pattern_template = "[Sheet Number] - [Sheet Name]"

    proj_info = doc.ProjectInformation if doc else None

    def resolve_token(match):
        token = match.group(1).strip()
        t_low = token.lower()

        # Built-in shortcuts
        if sheet:
            if t_low in ["sheet number", "sheetnumber", "sheet_number", "number"]:
                return sheet.SheetNumber or ""
            elif t_low in ["sheet name", "sheetname", "sheet_name", "name"]:
                return sheet.Name or ""
            elif t_low in ["revision", "current revision", "rev", "current_revision"]:
                p = sheet.get_Parameter(BuiltInParameter.SHEET_CURRENT_REVISION)
                return p.AsString() if p and p.HasValue else ""
            elif t_low in ["sheet issue date", "issue date", "date"]:
                p = sheet.get_Parameter(BuiltInParameter.SHEET_ISSUE_DATE)
                return p.AsString() if p and p.HasValue else ""
            elif t_low in ["drawn by", "drawnby"]:
                p = sheet.get_Parameter(BuiltInParameter.SHEET_DRAWN_BY)
                return p.AsString() if p and p.HasValue else ""
            elif t_low in ["checked by", "checkedby"]:
                p = sheet.get_Parameter(BuiltInParameter.SHEET_CHECKED_BY)
                return p.AsString() if p and p.HasValue else ""
            elif t_low in ["approved by", "approvedby"]:
                p = sheet.get_Parameter(BuiltInParameter.SHEET_APPROVED_BY)
                return p.AsString() if p and p.HasValue else ""

        # Project Information shortcuts
        if proj_info:
            if t_low in ["project number", "projectnumber", "proj_number"]:
                p = proj_info.get_Parameter(BuiltInParameter.PROJECT_NUMBER)
                return p.AsString() if p and p.HasValue else ""
            elif t_low in ["project name", "projectname", "proj_name"]:
                p = proj_info.get_Parameter(BuiltInParameter.PROJECT_NAME)
                return p.AsString() if p and p.HasValue else ""
            elif t_low in ["client name", "client"]:
                p = proj_info.get_Parameter(BuiltInParameter.CLIENT_NAME)
                return p.AsString() if p and p.HasValue else ""

        # Generic lookup from Sheet parameters
        if sheet:
            p = sheet.LookupParameter(token)
            if p and p.HasValue:
                val = p.AsString() or p.AsValueString()
                if val:
                    return str(val)

        # Generic lookup from Project Information parameters
        if proj_info:
            p = proj_info.LookupParameter(token)
            if p and p.HasValue:
                val = p.AsString() or p.AsValueString()
                if val:
                    return str(val)

        return ""

    # Replace all [tokens]
    resolved = re.sub(r'\[(.*?)\]', resolve_token, pattern_template)

    # Clean illegal Windows file characters
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', resolved)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Clean up empty revision tokens left as dangling "Rev", "- Rev", or trailing delimiters
    cleaned = re.sub(r'[\s\-_]+Rev\b', '', cleaned)
    cleaned = re.sub(r'[\s\-_]+$', '', cleaned)

    # Ensure valid fallback if result is empty
    if not cleaned:
        cleaned = (sheet.SheetNumber if sheet else "Combined_Drawing_Set") or "Export"

    return cleaned


# -- 4. Batch PDF Export Engine (Native Revit 2022+) ---------------------------

def export_sheets_to_pdf(doc, sheet_items, output_folder, naming_template,
                         combine=False, combined_filename="Combined_Sheets",
                         color_mode="Color", force_paper_format=None,
                         hide_crop_boundaries=True, hide_unreferenced_tags=True,
                         progress_callback=None):
    """
    Exports sheets to PDF using native Revit 2022+ PDF export engine.
    Yields progress via progress_callback(current, total, current_item_name).
    Returns: (success_count, error_list)
    """
    if not NATIVE_PDF_SUPPORTED:
        raise RuntimeError("Native PDF Export is not supported in this Revit version (Requires Revit 2022+).")

    if not sheet_items:
        return (0, ["No sheets provided for export."])

    if not os.path.exists(output_folder):
        try:
            os.makedirs(output_folder)
        except Exception as ex:
            return (0, ["Could not create output directory: {}".format(ex)])

    # Map color mode
    c_mode = ColorDepthType.Color
    if color_mode == "Grayscale":
        c_mode = getattr(ColorDepthType, "GrayScale", ColorDepthType.Color)
    elif color_mode in ["Black & White", "BlackAndWhite", "BlackLine"]:
        c_mode = getattr(ColorDepthType, "BlackLine", getattr(ColorDepthType, "GrayScale", ColorDepthType.Color))

    success_count = 0
    errors = []
    total = len(sheet_items)

    # --- Mode A: Combine All Selected Sheets into Single PDF ---
    if combine:
        try:
            if progress_callback:
                progress_callback(1, 1, "Generating combined PDF...")

            opts = PDFExportOptions()
            opts.Combine = True
            opts.FileName = re.sub(r'[\\/*?:"<>|]', '_', combined_filename.replace(".pdf", ""))
            opts.ColorDepth = c_mode
            opts.ZoomType = ZoomType.Zoom
            opts.ZoomPercentage = 100
            opts.RasterQuality = RasterQualityType.High
            opts.HideCropBoundaries = hide_crop_boundaries
            opts.HideUnreferencedViewTags = hide_unreferenced_tags
            opts.HideScopeBoxes = True
            opts.StopOnError = False

            # Auto format or forced
            if force_paper_format:
                opts.PaperFormat = force_paper_format
            else:
                opts.PaperFormat = getattr(ExportPaperFormat, "Default", ExportPaperFormat.ISO_A1)

            auto_ori = getattr(PageOrientationType, "Auto", None)
            if auto_ori:
                opts.PaperOrientation = auto_ori

            view_ids = List[ElementId]()
            for item in sheet_items:
                view_ids.Add(item.Id)

            doc.Export(output_folder, view_ids, opts)
            success_count = total
        except Exception as ex:
            errors.append("Combine PDF Export failed: {}".format(safe_unicode(ex)))

        return (success_count, errors)

    # --- Mode B: Separate Individual PDF per Sheet ---
    for i, item in enumerate(sheet_items):
        sheet = item.Sheet
        curr_name = build_sheet_filename(doc, sheet, naming_template)

        if progress_callback:
            progress_callback(i + 1, total, u"Exporting PDF: {}".format(curr_name))

        try:
            opts = PDFExportOptions()
            opts.Combine = False
            opts.FileName = curr_name
            opts.ColorDepth = c_mode
            opts.ZoomType = ZoomType.Zoom
            opts.ZoomPercentage = 100
            opts.RasterQuality = RasterQualityType.High
            opts.HideCropBoundaries = hide_crop_boundaries
            opts.HideUnreferencedViewTags = hide_unreferenced_tags
            opts.HideScopeBoxes = True
            opts.StopOnError = False

            # Set Paper Size & Orientation
            if force_paper_format:
                opts.PaperFormat = force_paper_format
            elif item.PaperFormatEnum:
                opts.PaperFormat = item.PaperFormatEnum
            else:
                opts.PaperFormat = getattr(ExportPaperFormat, "ISO_A1", ExportPaperFormat.Default)

            if item.OrientationEnum:
                opts.PaperOrientation = item.OrientationEnum

            single_id = List[ElementId]()
            single_id.Add(sheet.Id)

            doc.Export(output_folder, single_id, opts)
            success_count += 1
        except Exception as ex:
            errors.append(u"{} ({}): {}".format(sheet.SheetNumber, curr_name, safe_unicode(ex)))

    return (success_count, errors)


# -- 5. Batch DWG Export Engine -----------------------------------------------

def export_sheets_to_dwg(doc, sheet_items, output_folder, naming_template,
                         progress_callback=None):
    """
    Exports sheets to DWG (AutoCAD 2018 format) with views merged.
    Returns: (success_count, error_list)
    """
    if not DWG_SUPPORTED:
        return (0, ["DWG Export is not supported in this environment."])

    if not sheet_items:
        return (0, ["No sheets selected."])

    if not os.path.exists(output_folder):
        try:
            os.makedirs(output_folder)
        except Exception as ex:
            return (0, ["Could not create output directory: {}".format(ex)])

    success_count = 0
    errors = []
    total = len(sheet_items)
    used_names = set()

    for i, item in enumerate(sheet_items):
        sheet = item.Sheet
        curr_name = build_sheet_filename(doc, sheet, naming_template)

        # Collision safeguard: ensure each DWG filename is strictly unique
        if curr_name in used_names:
            curr_name = u"{}_{}".format(curr_name, sheet.SheetNumber or (i + 1))
        used_names.add(curr_name)

        if progress_callback:
            progress_callback(i + 1, total, u"Exporting DWG: {}".format(curr_name))

        try:
            opts = DWGExportOptions()
            opts.MergedViews = True
            if hasattr(ACADVersion, "R2018"):
                opts.FileVersion = ACADVersion.R2018
            elif hasattr(ACADVersion, "Default"):
                opts.FileVersion = ACADVersion.Default

            single_id = List[ElementId]()
            single_id.Add(sheet.Id)

            doc.Export(output_folder, curr_name, single_id, opts)
            success_count += 1
        except Exception as ex:
            errors.append(u"{} ({}): {}".format(sheet.SheetNumber, curr_name, safe_unicode(ex)))

    return (success_count, errors)
