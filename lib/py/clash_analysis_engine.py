# -*- coding: utf-8 -*-
"""
clash_analysis_engine.py - Pure Transient AVF (Analysis Results 1) Clash Engine
Integrates Native Revit 3D Solid Geometry & Boolean Interference Check (BooleanOperationsType.Intersect).
Uses compiled C# MepananaAvf.dll.

Zero False Positive Engine:
- Strictly enforces Native 3D Solid Boolean Collision (Intersect volume > 1e-6 ft3).
- GeometryInstance single-transform accuracy.
- Requires genuine physical 3D solids from both elements.
- Device-Aware snug geometry highlighting.
- Real-time progress callback support.

Part of mepanana.extension.
"""
import os
import math
import clr

clr.AddReference("System")
clr.AddReference("System.Core")
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from System.Collections.Generic import List
import System

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, FilteredElementCollector, XYZ, Line, Curve,
    Color, RevitLinkInstance, BoundingBoxXYZ, Transform, ElementId, Solid, CategoryType,
    View3D, ViewFamilyType, ViewFamily
)

from py.core import SafeTransaction, mm_to_ft, ft_to_mm, get_id_value, safe_unicode

# ── Load Latest Compiled C# AVF Assembly ────────────────────────────────────
dll_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "MepananaAvf.dll"))

if os.path.exists(dll_path):
    try:
        clr.AddReferenceToFileAndPath(dll_path)
        from Mepanana.Avf import ClashVisualizer, ClashPolygonData, NativeGeometryEngine, NativeClashResult
    except Exception as ex:
        print("Failed to load AVF assembly: {}".format(safe_unicode(ex)))


# ── Relevant Categories In Linked Models To Scan ────────────────────────────
ALL_LINKED_CATEGORIES = [
    # MEP Linear & Fittings
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_Conduit,
    BuiltInCategory.OST_ConduitFitting,
    BuiltInCategory.OST_DuctCurves,
    BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_DuctAccessory,
    BuiltInCategory.OST_DuctTerminal,
    BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_PipeAccessory,
    BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_FlexPipeCurves,
    # MEP Equipment & Devices
    BuiltInCategory.OST_MechanicalEquipment,
    BuiltInCategory.OST_ElectricalEquipment,
    BuiltInCategory.OST_ElectricalFixtures,
    BuiltInCategory.OST_LightingFixtures,
    BuiltInCategory.OST_LightingDevices,
    BuiltInCategory.OST_PlumbingFixtures,
    BuiltInCategory.OST_Sprinklers,
    BuiltInCategory.OST_FireAlarmDevices,
    BuiltInCategory.OST_DataDevices,
    BuiltInCategory.OST_CommunicationDevices,
    BuiltInCategory.OST_SecurityDevices,
    BuiltInCategory.OST_TelephoneDevices,
    BuiltInCategory.OST_NurseCallDevices,
    # Structure
    BuiltInCategory.OST_StructuralFraming,
    BuiltInCategory.OST_StructuralColumns,
    BuiltInCategory.OST_Columns,
    BuiltInCategory.OST_StructuralFoundation,
    BuiltInCategory.OST_StructuralFramingSystem,
    BuiltInCategory.OST_StructuralStiffener,
    BuiltInCategory.OST_StructConnections,
    # Architecture
    BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_Floors,
    BuiltInCategory.OST_Ceilings,
    BuiltInCategory.OST_Roofs,
    BuiltInCategory.OST_Doors,
    BuiltInCategory.OST_Windows,
    BuiltInCategory.OST_Stairs,
    BuiltInCategory.OST_Ramps,
    BuiltInCategory.OST_CurtainWallPanels,
    BuiltInCategory.OST_CurtainWallMullions,
    BuiltInCategory.OST_GenericModel,
    BuiltInCategory.OST_SpecialityEquipment,
    BuiltInCategory.OST_Casework,
    BuiltInCategory.OST_Furniture,
    BuiltInCategory.OST_FurnitureSystems,
    BuiltInCategory.OST_AudioVisualDevices,
    BuiltInCategory.OST_FoodServiceEquipment,
    BuiltInCategory.OST_MedicalEquipment,
    BuiltInCategory.OST_Signage,
    BuiltInCategory.OST_Hardscape,
    BuiltInCategory.OST_Parking,
    BuiltInCategory.OST_StairsRailing,
    BuiltInCategory.OST_Roads,
    BuiltInCategory.OST_Site,
    BuiltInCategory.OST_Topography,
    BuiltInCategory.OST_Mass,
]


# ── Data Models ───────────────────────────────────────────────────────────────

class ClashItem(System.Object):
    def __init__(self, elem1, elem2, clash_point=None,
                 clash_type="HARD", overlap_mm=0.0, elev_diff_mm=0.0,
                 width1_ft=0.0, width2_ft=0.0,
                 is_link1=False, is_link2=False, link_name="",
                 host_polygon_corners=None, host_band=None, host_top_z=None,
                 link_polygon_corners=None, link_top_z=None, **kwargs):
        self.Element1 = elem1
        self.Element2 = elem2
        self.ClashPoint = clash_point
        self.ClashType = clash_type
        self.OverlapMm = overlap_mm
        self.ElevDiffMm = elev_diff_mm
        self.Width1Ft = width1_ft
        self.Width2Ft = width2_ft
        self.IsLink1 = is_link1
        self.IsLink2 = is_link2
        self.IsLink = bool(is_link1 or is_link2)
        self.LinkName = link_name
        
        # Polygon corners and elevations for AVF highlight bands
        self.HostPolygonCorners = host_polygon_corners if host_polygon_corners is not None else host_band
        self.HostBand = self.HostPolygonCorners
        self.HostTopZ = host_top_z
        self.LinkPolygonCorners = link_polygon_corners
        self.LinkTopZ = link_top_z
        
        # Display properties (Clean & Compact)
        name1 = elem1.Category.Name if (elem1 and elem1.Category) else "Element"
        name2 = elem2.Category.Name if (elem2 and elem2.Category) else "Element"
        id1 = get_id_value(elem1) if elem1 else 0
        id2 = get_id_value(elem2) if elem2 else 0
        
        self.Elem1IdInt = id1
        self.Elem2IdInt = id2
        self.Elem1CatName = name1
        self.Elem2CatName = name2

        if is_link2:
            self.DisplayName = u"{} [{}] ⚡ {} [{}] (Link)".format(name1, id1, name2, id2)
        elif is_link1:
            self.DisplayName = u"{} [{}] (Link) ⚡ {} [{}]".format(name1, id1, name2, id2)
        else:
            self.DisplayName = u"{} [{}] ⚡ {} [{}]".format(name1, id1, name2, id2)
            
        self.DetailInfo = u"{:.0f} mm".format(overlap_mm)
        self.Status = "ACTIVE"
        self.StatusIcon = u"🔴"


# ── MEP Connector & Joint Relationship Inspectors ────────────────────────────

def are_elements_connected(elem1, elem2):
    """Checks if elem1 and elem2 are physically connected via MEP Connectors."""
    if not elem1 or not elem2:
        return False
    try:
        id1 = get_id_value(elem1)
        id2 = get_id_value(elem2)
        if id1 == id2:
            return True
            
        cm1 = getattr(elem1, "ConnectorManager", getattr(getattr(elem1, "MEPModel", None), "ConnectorManager", None))
        if cm1 and hasattr(cm1, "Connectors"):
            for c in cm1.Connectors:
                if c.IsConnected:
                    for ref in c.AllRefs:
                        if ref.Owner and get_id_value(ref.Owner) == id2:
                            return True

        cm2 = getattr(elem2, "ConnectorManager", getattr(getattr(elem2, "MEPModel", None), "ConnectorManager", None))
        if cm2 and hasattr(cm2, "Connectors"):
            for c in cm2.Connectors:
                if c.IsConnected:
                    for ref in c.AllRefs:
                        if ref.Owner and get_id_value(ref.Owner) == id1:
                            return True
    except Exception:
        pass
    return False


def is_connected_endpoint_joint(p0, p1, q0, q1, threshold_ft=0.65):
    """Checks if elements meet at an endpoint joint."""
    try:
        min_dist = min(
            p0.DistanceTo(q0), p0.DistanceTo(q1),
            p1.DistanceTo(q0), p1.DistanceTo(q1)
        )
        return min_dist <= threshold_ft
    except Exception:
        return False


# ── Active View 3D Spatial Bounds Calculation ────────────────────────────────

def get_view_spatial_bounds(doc, view):
    """Computes the 3D spatial bounding box of the active view (Level elevation slice & XY extent)."""
    try:
        if hasattr(view, "CropBoxActive") and view.CropBoxActive and view.CropBox:
            cb = view.CropBox
            tf = cb.Transform
            corners = [
                XYZ(cb.Min.X, cb.Min.Y, cb.Min.Z),
                XYZ(cb.Max.X, cb.Min.Y, cb.Min.Z),
                XYZ(cb.Min.X, cb.Max.Y, cb.Min.Z),
                XYZ(cb.Max.X, cb.Max.Y, cb.Min.Z),
                XYZ(cb.Min.X, cb.Min.Y, cb.Max.Z),
                XYZ(cb.Max.X, cb.Min.Y, cb.Max.Z),
                XYZ(cb.Min.X, cb.Max.Y, cb.Max.Z),
                XYZ(cb.Max.X, cb.Max.Y, cb.Max.Z),
            ]
            t_corners = [tf.OfPoint(pt) for pt in corners]
            min_x = min(pt.X for pt in t_corners)
            min_y = min(pt.Y for pt in t_corners)
            min_z = min(pt.Z for pt in t_corners)
            max_x = max(pt.X for pt in t_corners)
            max_y = max(pt.Y for pt in t_corners)
            max_z = max(pt.Z for pt in t_corners)
            
            bb = BoundingBoxXYZ()
            bb.Min = XYZ(min_x, min_y, min_z)
            bb.Max = XYZ(max_x, max_y, max_z)
            return bb
            
        level = getattr(view, "GenLevel", None)
        z_min = -1e9
        z_max = 1e9
        if level:
            lvl_elev = level.Elevation
            z_min = lvl_elev - 5.0
            z_max = lvl_elev + 16.0
            
        host_elements = FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType().ToElements()
        all_min_x, all_min_y = 1e9, 1e9
        all_max_x, all_max_y = -1e9, -1e9
        found = False
        
        for el in host_elements:
            if el.Category:
                bb = el.get_BoundingBox(view) or el.get_BoundingBox(None)
                if bb:
                    all_min_x = min(all_min_x, bb.Min.X)
                    all_min_y = min(all_min_y, bb.Min.Y)
                    all_max_x = max(all_max_x, bb.Max.X)
                    all_max_y = max(all_max_y, bb.Max.Y)
                    found = True
                    
        if found:
            bb = BoundingBoxXYZ()
            bb.Min = XYZ(all_min_x - 15.0, all_min_y - 15.0, z_min)
            bb.Max = XYZ(all_max_x + 15.0, all_max_y + 15.0, z_max)
            return bb
    except Exception:
        pass
        
    return None


# ── Precise Element Dimension Extractor ──────────────────────────────────────

def extract_element_dimensions(elem):
    """Robustly extracts exact physical thickness/diameter for any element without oversized bounds."""
    w_ft = None
    h_ft = None
    
    # 1. Wall thickness directly from Wall.Width
    if hasattr(elem, "Width") and elem.Category and "Wall" in elem.Category.Name:
        try:
            val = elem.Width
            if val and val > 0:
                return val, 10.0
        except Exception:
            pass
            
    # 2. BuiltInParameters for MEP
    for bip in [
        BuiltInParameter.RBS_PIPE_OUTER_DIAMETER,
        BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
        BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
        BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
        BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
        BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM,
        BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM,
    ]:
        try:
            p = elem.get_Parameter(bip)
            if p and p.HasValue:
                val = p.AsDouble()
                if val and val > 0:
                    w_ft = val
                    if bip in [BuiltInParameter.RBS_PIPE_OUTER_DIAMETER, BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
                               BuiltInParameter.RBS_CURVE_DIAMETER_PARAM, BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM,
                               BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM]:
                        h_ft = val
                    break
        except Exception:
            pass

    if h_ft is None or h_ft <= 0:
        for bip in [
            BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
            BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM,
            BuiltInParameter.RBS_PIPE_OUTER_DIAMETER,
            BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
        ]:
            try:
                p = elem.get_Parameter(bip)
                if p and p.HasValue:
                    val = p.AsDouble()
                    if val and val > 0:
                        h_ft = val
                        break
            except Exception:
                pass

    # 3. Lookup Parameters
    if w_ft is None or w_ft <= 0:
        for pname in ["Diameter", "Outside Diameter", "Width", "b", "B", "d", "Thickness"]:
            try:
                p = elem.LookupParameter(pname)
                if p and p.HasValue:
                    val = p.AsDouble()
                    if val and val > 0:
                        w_ft = val
                        break
            except Exception:
                pass

    if h_ft is None or h_ft <= 0:
        for pname in ["Height", "h", "H", "d", "Diameter"]:
            try:
                p = elem.LookupParameter(pname)
                if p and p.HasValue:
                    val = p.AsDouble()
                    if val and val > 0:
                        h_ft = val
                        break
            except Exception:
                pass

    # 4. Element Type parameters (for Beams, Columns, Framing)
    if w_ft is None or w_ft <= 0:
        try:
            doc = elem.Document
            el_type = doc.GetElement(elem.GetTypeId())
            if el_type:
                for pname in ["Width", "b", "B", "Diameter", "d", "Thickness"]:
                    p = el_type.LookupParameter(pname)
                    if p and p.HasValue:
                        val = p.AsDouble()
                        if val and val > 0:
                            w_ft = val
                            break
        except Exception:
            pass

    # 5. Fallback: Use smallest physical dimension (thickness) rather than full extent
    if w_ft is None or w_ft <= 0:
        bb = elem.get_BoundingBox(None)
        if bb:
            dims = [abs(bb.Max.X - bb.Min.X), abs(bb.Max.Y - bb.Min.Y), abs(bb.Max.Z - bb.Min.Z)]
            pos_dims = [d for d in dims if d > 0.05]
            w_ft = min(pos_dims) if pos_dims else 0.5
        else:
            w_ft = 0.5

    if h_ft is None or h_ft <= 0:
        h_ft = w_ft

    return max(0.05, min(w_ft, 2.0)), max(0.05, min(h_ft, 3.5))


# ── Element Geometry Extractors (With Native 3D Solids Caching) ──────────────

def get_mep_curve_data(elem, transform=None, is_link=False, link_name=""):
    """Extracts centerline Line, width, height, world bounding box, and native 3D Solids."""
    try:
        loc = elem.Location
        p0 = None
        p1 = None
        has_curve = False
        
        w_ft, h_ft = extract_element_dimensions(elem)
        
        bb_local = elem.get_BoundingBox(None)
        if not bb_local:
            return None
            
        if transform:
            bb_world = transform_bounding_box(bb_local, transform)
        else:
            bb_world = bb_local
            
        if loc and hasattr(loc, "Curve") and loc.Curve:
            curve = loc.Curve
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            
            if transform:
                p0 = transform.OfPoint(p0)
                p1 = transform.OfPoint(p1)
            has_curve = True
        else:
            # Point-based element (FamilyInstance, Equipment, Fitting, Fixture)
            min_pt = bb_world.Min
            max_pt = bb_world.Max
            center_x = (min_pt.X + max_pt.X) / 2.0
            center_y = (min_pt.Y + max_pt.Y) / 2.0
            center_z = (min_pt.Z + max_pt.Z) / 2.0
            
            p0 = XYZ(min_pt.X, center_y, center_z)
            p1 = XYZ(max_pt.X, center_y, center_z)
            has_curve = False
            
        solids = NativeGeometryEngine.GetElementSolids(elem, transform)
        cat_name = elem.Category.Name if elem.Category else ""
        is_wall = "Wall" in cat_name
                
        return {
            "element": elem,
            "p0": p0,
            "p1": p1,
            "has_curve": has_curve,
            "width": w_ft,
            "height": h_ft,
            "half_w": w_ft / 2.0,
            "half_h": h_ft / 2.0,
            "bb": bb_world,
            "solids": solids,
            "is_link": is_link,
            "is_wall": is_wall,
            "link_name": link_name
        }
    except Exception:
        return None


def transform_bounding_box(bb, tf):
    """Transforms a BoundingBoxXYZ by a Revit Transform."""
    corners = [
        XYZ(bb.Min.X, bb.Min.Y, bb.Min.Z),
        XYZ(bb.Max.X, bb.Min.Y, bb.Min.Z),
        XYZ(bb.Min.X, bb.Max.Y, bb.Min.Z),
        XYZ(bb.Max.X, bb.Max.Y, bb.Min.Z),
        XYZ(bb.Min.X, bb.Min.Y, bb.Max.Z),
        XYZ(bb.Max.X, bb.Min.Y, bb.Max.Z),
        XYZ(bb.Min.X, bb.Max.Y, bb.Max.Z),
        XYZ(bb.Max.X, bb.Max.Y, bb.Max.Z),
    ]
    t_corners = [tf.OfPoint(pt) for pt in corners]
    min_x = min(pt.X for pt in t_corners)
    min_y = min(pt.Y for pt in t_corners)
    min_z = min(pt.Z for pt in t_corners)
    max_x = max(pt.X for pt in t_corners)
    max_y = max(pt.Y for pt in t_corners)
    max_z = max(pt.Z for pt in t_corners)
    
    new_bb = BoundingBoxXYZ()
    new_bb.Min = XYZ(min_x, min_y, min_z)
    new_bb.Max = XYZ(max_x, max_y, max_z)
    return new_bb


# ── Snug Geometry Band & Point Device Footprint Calculations ──────────────────

def get_point_device_corners(bb_world, padding_ft=0.08):
    """Computes a snug 4-corner polygon directly wrapping the point device/fixture bounding box."""
    min_x = bb_world.Min.X - padding_ft
    min_y = bb_world.Min.Y - padding_ft
    max_x = bb_world.Max.X + padding_ft
    max_y = bb_world.Max.Y + padding_ft
    
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    hw = max((max_x - min_x) / 2.0, 0.25)
    hh = max((max_y - min_y) / 2.0, 0.25)
    
    hw = min(hw, 1.2)
    hh = min(hh, 1.2)
    
    pA = (cx - hw, cy - hh)
    pB = (cx + hw, cy - hh)
    pC = (cx + hw, cy + hh)
    pD = (cx - hw, cy + hh)
    return (pA, pB, pC, pD)


def get_snug_clash_band(p0, p1, half_w, clash_pt, other_half_w=0.5, is_wall=False):
    """
    Computes a crisp, compact rectangular band snugly hugging the exact element geometry
    at the clash zone without oversized footprint carpets.
    """
    dx = p1.X - p0.X
    dy = p1.Y - p0.Y
    length = math.sqrt(dx * dx + dy * dy)
    
    eff_half_w = max(0.05, min(half_w, 1.2))
    
    if length < 1e-5:
        return (
            (clash_pt.X - eff_half_w, clash_pt.Y - eff_half_w),
            (clash_pt.X + eff_half_w, clash_pt.Y - eff_half_w),
            (clash_pt.X + eff_half_w, clash_pt.Y + eff_half_w),
            (clash_pt.X - eff_half_w, clash_pt.Y + eff_half_w)
        )
        
    ux = dx / length
    uy = dy / length
    nx = -uy
    ny = ux
    
    t = ((clash_pt.X - p0.X) * dx + (clash_pt.Y - p0.Y) * dy) / (length * length)
    t = max(0.0, min(1.0, t))
    center_x = p0.X + t * dx
    center_y = p0.Y + t * dy
    
    # Compact span along element centerline (~250mm - 350mm)
    if is_wall:
        half_span = min(1.2, max(other_half_w + 0.35, 0.65))
    else:
        half_span = min(1.2, max(eff_half_w * 1.3, 0.75))
        
    half_span = min(length / 2.0, half_span)
    
    s0_x = center_x - ux * half_span
    s0_y = center_y - uy * half_span
    s1_x = center_x + ux * half_span
    s1_y = center_y + uy * half_span
    
    pA = (s0_x + nx * eff_half_w, s0_y + ny * eff_half_w)
    pB = (s1_x + nx * eff_half_w, s1_y + ny * eff_half_w)
    pC = (s1_x - nx * eff_half_w, s1_y - ny * eff_half_w)
    pD = (s0_x - nx * eff_half_w, s0_y - ny * eff_half_w)
    return (pA, pB, pC, pD)


def check_clash_between_elements(data1, data2):
    """
    Checks if two elements physically clash using Revit Native 3D Solid Boolean Interference Check.
    Returns ClashItem or None.
    """
    elem1 = data1["element"]
    elem2 = data2["element"]
    bb1 = data1["bb"]
    bb2 = data2["bb"]
    
    # ── Tier 1: Strict 3D BoundingBox XYZ Hard Overlap in World Coordinates ──
    overlap_x = min(bb1.Max.X, bb2.Max.X) - max(bb1.Min.X, bb2.Min.X)
    overlap_y = min(bb1.Max.Y, bb2.Max.Y) - max(bb1.Min.Y, bb2.Min.Y)
    overlap_z_bb = min(bb1.Max.Z, bb2.Max.Z) - max(bb1.Min.Z, bb2.Min.Z)
    
    if overlap_x <= 0.007 or overlap_y <= 0.007 or overlap_z_bb <= 0.007:  # <= 2mm
        return None
        
    # ── Tier 2: Skip legitimately connected MEP elements ─────────────────────
    if not data1.get("is_link") and not data2.get("is_link"):
        if are_elements_connected(elem1, elem2):
            return None
            
    p0, p1 = data1["p0"], data1["p1"]
    q0, q1 = data2["p0"], data2["p1"]
    
    # ── Tier 3: Skip end-to-end continuous run joints ────────────────────────
    if data1.get("has_curve") and data2.get("has_curve"):
        if is_connected_endpoint_joint(p0, p1, q0, q1, threshold_ft=0.65):
            cat1 = get_id_value(elem1.Category) if elem1.Category else 0
            cat2 = get_id_value(elem2.Category) if elem2.Category else 0
            if cat1 == cat2 or "Fitting" in str(getattr(elem1.Category, 'Name', '')) or "Fitting" in str(getattr(elem2.Category, 'Name', '')):
                return None
            
    # ── Tier 4 & 5: Strict Native Revit 3D Solid Boolean Interference Check ──
    solids1 = data1.get("solids")
    solids2 = data2.get("solids")
    
    # Require genuine physical 3D solids from both elements
    if not solids1 or not solids2 or len(solids1) == 0 or len(solids2) == 0:
        return None  # If either element has no physical 3D solids, it cannot clash!
        
    native_res = NativeGeometryEngine.CheckSolidIntersection(solids1, solids2)
    if not native_res.HasClash:
        return None  # 100% physically clear in true 3D solid geometry!
        
    clash_center = XYZ(native_res.ClashX, native_res.ClashY, native_res.ClashZ)
    overlap_mm = math.pow(native_res.OverlapVolumeMm3, 1.0 / 3.0)
    elev_diff_mm = ft_to_mm(abs(bb1.Min.Z - bb2.Min.Z))
        
    is_link1 = data1.get("is_link", False)
    is_link2 = data2.get("is_link", False)
    link_name = data1.get("link_name") or data2.get("link_name", "")
    
    # ── Compute Snug Polygon Band for Host Element 1 (RED) ────────────────────
    if data1.get("has_curve"):
        other_hw = data2["half_w"] if data2.get("has_curve") else min((data2["bb"].Max.X - data2["bb"].Min.X) / 2.0, (data2["bb"].Max.Y - data2["bb"].Min.Y) / 2.0)
        host_band = get_snug_clash_band(
            p0, p1, data1["half_w"], clash_center,
            other_half_w=other_hw, is_wall=data1.get("is_wall", False)
        )
    else:
        host_band = get_point_device_corners(data1["bb"])
        
    host_top_z = max(p0.Z, p1.Z) + data1["half_h"]
    
    # ── Compute Snug Polygon Band for Element 2 (GREEN if Link, RED if Host 2) ──
    if data2.get("has_curve"):
        other_hw = data1["half_w"] if data1.get("has_curve") else min((data1["bb"].Max.X - data1["bb"].Min.X) / 2.0, (data1["bb"].Max.Y - data1["bb"].Min.Y) / 2.0)
        link_band = get_snug_clash_band(
            q0, q1, data2["half_w"], clash_center,
            other_half_w=other_hw, is_wall=data2.get("is_wall", False)
        )
    else:
        link_band = get_point_device_corners(data2["bb"])
        
    link_top_z = max(q0.Z, q1.Z) + data2["half_h"]
    
    return ClashItem(
        elem1, elem2, clash_center,
        clash_type="HARD", overlap_mm=overlap_mm, elev_diff_mm=elev_diff_mm,
        width1_ft=data1["width"], width2_ft=data2["width"],
        is_link1=is_link1, is_link2=is_link2, link_name=link_name,
        host_polygon_corners=host_band, host_top_z=host_top_z,
        link_polygon_corners=link_band, link_top_z=link_top_z
    )


# ── Broad-Phase Clash Scanner (Host vs Host, Host vs Link - NEVER Link vs Link)

def scan_clashes(doc, view, categories=None, selected_ids=None, progress_callback=None):
    """
    Scans Host elements from user-selected categories, and cross-checks against other Host elements
    and ALL categories in Linked Models within the Active View using Native 3D Solid Boolean Intersection.
    
    When selected_ids is provided:
    - Tight Selection Boundary is computed (+ 1.0m buffer).
    - Linked & Host elements outside this tight boundary are skipped instantaneously (< 0.2s).
    - NEVER checks clashes between Link and Link.
    Returns a list of ClashItem.
    """
    if progress_callback:
        progress_callback(5, "Filtering active view elements and spatial bounds...")

    if categories is None:
        categories = [BuiltInCategory.OST_CableTray]
        
    view_bounds = get_view_spatial_bounds(doc, view)
    cat_ints = set()
    for c in categories:
        try:
            val = get_id_value(c) if not isinstance(c, int) else int(c)
            cat_ints.add(val)
        except Exception:
            pass
    
    # 1. Collect Primary Host Elements (Selected Elements OR All Active View Elements)
    host_data_list = []
    selected_id_set = set()
    
    if selected_ids and len(selected_ids) > 0:
        for eid in selected_ids:
            el = doc.GetElement(eid)
            if el and el.Category:
                cdata = get_mep_curve_data(el, is_link=False)
                if cdata and cdata.get("solids") and len(cdata["solids"]) > 0:
                    host_data_list.append(cdata)
                    selected_id_set.add(get_id_value(el))
    else:
        for cat_int in cat_ints:
            try:
                col = FilteredElementCollector(doc, view.Id).OfCategoryId(ElementId(cat_int)).WhereElementIsNotElementType()
                for el in col:
                    cdata = get_mep_curve_data(el, is_link=False)
                    if cdata and cdata.get("solids") and len(cdata["solids"]) > 0:
                        host_data_list.append(cdata)
            except Exception:
                pass

    # ── Compute Spatial Target Bounds (Tight Boundary for Selection or View Bounds) ──
    target_bounds = None
    if selected_ids and len(host_data_list) > 0:
        padding = 3.28  # 1.0 meter buffer around selected elements
        sel_min_x = min(d["bb"].Min.X for d in host_data_list) - padding
        sel_min_y = min(d["bb"].Min.Y for d in host_data_list) - padding
        sel_min_z = min(d["bb"].Min.Z for d in host_data_list) - padding
        sel_max_x = max(d["bb"].Max.X for d in host_data_list) + padding
        sel_max_y = max(d["bb"].Max.Y for d in host_data_list) + padding
        sel_max_z = max(d["bb"].Max.Z for d in host_data_list) + padding
        
        target_bounds = BoundingBoxXYZ()
        target_bounds.Min = XYZ(sel_min_x, sel_min_y, sel_min_z)
        target_bounds.Max = XYZ(sel_max_x, sel_max_y, sel_max_z)
        
        if progress_callback:
            progress_callback(20, "Tight selection boundary active ({} elements). Scanning zone...".format(len(host_data_list)))
    else:
        target_bounds = view_bounds
        if progress_callback:
            progress_callback(20, "Loaded {} host 3D elements. Scanning active view...".format(len(host_data_list)))

    # If Selected Mode: Also collect other nearby Host elements in target_bounds to check against selected items!
    other_host_data_list = []
    if selected_ids and len(selected_ids) > 0 and target_bounds:
        for cat_int in cat_ints:
            try:
                col = FilteredElementCollector(doc, view.Id).OfCategoryId(ElementId(cat_int)).WhereElementIsNotElementType()
                for el in col:
                    if get_id_value(el) in selected_id_set:
                        continue
                    bb_local = el.get_BoundingBox(view) or el.get_BoundingBox(None)
                    if not bb_local:
                        continue
                    if (bb_local.Max.X < target_bounds.Min.X or bb_local.Min.X > target_bounds.Max.X or
                        bb_local.Max.Y < target_bounds.Min.Y or bb_local.Min.Y > target_bounds.Max.Y or
                        bb_local.Max.Z < target_bounds.Min.Z or bb_local.Min.Z > target_bounds.Max.Z):
                        continue
                    cdata = get_mep_curve_data(el, is_link=False)
                    if cdata and cdata.get("solids") and len(cdata["solids"]) > 0:
                        other_host_data_list.append(cdata)
            except Exception:
                pass
                        
    # 2. Collect Linked Elements (Filtered tightly within target_bounds)
    link_data_list = []
    link_instances = FilteredElementCollector(doc, view.Id).OfClass(RevitLinkInstance).WhereElementIsNotElementType().ToElements()
    for link_inst in link_instances:
        try:
            link_doc = link_inst.GetLinkDocument()
            if not link_doc:
                continue
            tf = link_inst.GetTotalTransform()
            link_name = link_inst.Name
            
            target_link_cats = [c for c in cat_ints] if cat_ints else ALL_LINKED_CATEGORIES
            for cat_item in target_link_cats:
                try:
                    c_id = ElementId(int(cat_item))
                    col_link = FilteredElementCollector(link_doc).OfCategoryId(c_id).WhereElementIsNotElementType()
                    for el in col_link:
                        bb_local = el.get_BoundingBox(None)
                        if not bb_local:
                            continue
                            
                        bb_world = transform_bounding_box(bb_local, tf)
                        
                        # Spatial Filter: Strict Target bounds check (Tight Selection Bounds or View Bounds)
                        if target_bounds:
                            if (bb_world.Max.X < target_bounds.Min.X or bb_world.Min.X > target_bounds.Max.X or
                                bb_world.Max.Y < target_bounds.Min.Y or bb_world.Min.Y > target_bounds.Max.Y or
                                bb_world.Max.Z < target_bounds.Min.Z or bb_world.Min.Z > target_bounds.Max.Z):
                                continue
                                
                        cdata = get_mep_curve_data(el, transform=tf, is_link=True, link_name=link_name)
                        if cdata and cdata.get("solids") and len(cdata["solids"]) > 0:
                            link_data_list.append(cdata)
                except Exception:
                    pass
        except Exception:
            pass
            
    clashes = []
    seen_pairs = set()
    
    # Phase A: Host vs Host Clashes (Selected vs Selected + Selected vs Other Nearby Host)
    n_host = len(host_data_list)
    # A1: Among selected elements
    for i in range(n_host):
        if progress_callback and n_host > 0 and i % 5 == 0:
            pct = 30 + int((float(i) / n_host) * 30.0)
            progress_callback(pct, "Testing Host vs Host solid collisions ({}/{})...".format(i + 1, n_host))

        d1 = host_data_list[i]
        id1 = get_id_value(d1["element"])
        
        for j in range(i + 1, n_host):
            d2 = host_data_list[j]
            id2 = get_id_value(d2["element"])
            
            pair_key = (id1, id2)
            if pair_key in seen_pairs or (id2, id1) in seen_pairs:
                continue
                
            clash = check_clash_between_elements(d1, d2)
            if clash:
                clashes.append(clash)
                seen_pairs.add(pair_key)

        # A2: Selected vs other nearby Host elements
        for d2 in other_host_data_list:
            id2 = get_id_value(d2["element"])
            pair_key = (id1, id2)
            if pair_key in seen_pairs or (id2, id1) in seen_pairs:
                continue
                
            clash = check_clash_between_elements(d1, d2)
            if clash:
                clashes.append(clash)
                seen_pairs.add(pair_key)
                
    # Phase B: Host vs Link Clashes (Selected Elements vs Linked Elements in tight boundary)
    n_link = len(link_data_list)
    for i in range(n_host):
        if progress_callback and n_host > 0 and i % 5 == 0:
            pct = 60 + int((float(i) / n_host) * 30.0)
            progress_callback(pct, "Testing Host vs Link solid collisions ({}/{})...".format(i + 1, n_host))

        d1 = host_data_list[i]
        id1 = get_id_value(d1["element"])
        
        for j in range(n_link):
            d2 = link_data_list[j]
            id2 = get_id_value(d2["element"])
            
            pair_key = (id1, ("link", id2, d2.get("link_name", "")))
            if pair_key in seen_pairs:
                continue
                
            clash = check_clash_between_elements(d1, d2)
            if clash:
                clashes.append(clash)
                seen_pairs.add(pair_key)

    if progress_callback:
        progress_callback(92, "Found {} physical clashes. Rendering visual markers...".format(len(clashes)))
                
    return clashes


# ── Pure Native AVF (Analysis Results 1) Renderer ───────────────────────────

def render_clashes_avf(doc, view, clashes):
    """
    Renders pure native Revit Analysis Results (1):
    1. 🟢 GREEN (#22C55E) localized band on the Linked Model element around the clash zone.
    2. 🔴 RED (#EF4444) localized band on the Host Model element around the clash zone (rendered strictly on top).
    via compiled C# MepananaAvf.dll.
    """
    try:
        if not clashes:
            clear_clash_analysis(doc, view)
            return 0
            
        poly_list = List[ClashPolygonData]()
        
        # Step 1: Render localized GREEN bands on Linked Elements (underneath)
        for clash in clashes:
            if clash.IsLink and clash.LinkPolygonCorners and len(clash.LinkPolygonCorners) == 4:
                lA, lB, lC, lD = clash.LinkPolygonCorners
                link_z = getattr(clash, "LinkTopZ", clash.ClashPoint.Z) + 0.01
                poly_green = ClashPolygonData(
                    lA[0], lA[1],
                    lB[0], lB[1],
                    lC[0], lC[1],
                    lD[0], lD[1],
                    link_z, 1.0, True  # IsLink=True -> GREEN
                )
                poly_list.Add(poly_green)
                
        # Step 2: Render localized RED bands on Host Elements (STRICTLY ON TOP)
        for clash in clashes:
            if clash.HostPolygonCorners and len(clash.HostPolygonCorners) == 4:
                hA, hB, hC, hD = clash.HostPolygonCorners
                host_z = getattr(clash, "HostTopZ", clash.ClashPoint.Z) + 0.05
                poly_red = ClashPolygonData(
                    hA[0], hA[1],
                    hB[0], hB[1],
                    hC[0], hC[1],
                    hD[0], hD[1],
                    host_z, 1.0, False  # IsLink=False -> RED
                )
                poly_list.Add(poly_red)
                
            # If Host vs Host clash (both elements in Host), also render Element 2 in RED
            if not clash.IsLink and clash.LinkPolygonCorners and len(clash.LinkPolygonCorners) == 4:
                lA, lB, lC, lD = clash.LinkPolygonCorners
                link_z = getattr(clash, "LinkTopZ", clash.ClashPoint.Z) + 0.05
                poly_red2 = ClashPolygonData(
                    lA[0], lA[1],
                    lB[0], lB[1],
                    lC[0], lC[1],
                    lD[0], lD[1],
                    link_z, 1.0, False  # IsLink=False -> RED
                )
                poly_list.Add(poly_red2)
            
        count = ClashVisualizer.RenderClashPolygons(doc, view, poly_list)
        return count
    except Exception as ex:
        print("AVF Rendering exception: {}".format(ex))
        return 0


def clear_clash_analysis(doc, view):
    """Clears all native Analysis Results (1) from the view."""
    try:
        return ClashVisualizer.ClearClashAnalysis(view)
    except Exception:
        return False


# ── Interactive 3D Navigation & Instant Recheck Functions ────────────────────

def recheck_single_clash(doc, clash_item, tolerance_mm=0.0):
    """
    Rechecks if clash_item is still physically clashing in <0.05s.
    Returns: (still_clashing: bool, overlap_mm: float, new_clash_item or None)
    """
    try:
        el1 = clash_item.Element1
        el2 = clash_item.Element2
        
        if not el1 or not el1.IsValidObject:
            return (False, 0.0, None)
        if not el2 or not el2.IsValidObject:
            return (False, 0.0, None)
            
        d1 = get_mep_curve_data(el1, is_link=clash_item.IsLink1)
        if not d1 or not d1.get("solids") or len(d1["solids"]) == 0:
            return (False, 0.0, None)
            
        tf = None
        if clash_item.IsLink2 and clash_item.LinkName:
            link_instances = FilteredElementCollector(doc).OfClass(RevitLinkInstance).WhereElementIsNotElementType()
            for li in link_instances:
                if li.Name == clash_item.LinkName:
                    tf = li.GetTotalTransform()
                    break
                    
        d2 = get_mep_curve_data(el2, transform=tf, is_link=clash_item.IsLink2, link_name=clash_item.LinkName)
        if not d2 or not d2.get("solids") or len(d2["solids"]) == 0:
            return (False, 0.0, None)
            
        new_clash = check_clash_between_elements(d1, d2)
        if new_clash:
            if new_clash.OverlapMm > tolerance_mm:
                return (True, new_clash.OverlapMm, new_clash)
        return (False, 0.0, None)
    except Exception as ex:
        print("recheck_single_clash error: {}".format(ex))
        return (False, 0.0, None)


def focus_clash_3d(doc, uidoc, clash_item, padding_mm=800):
    """
    Navigates to or creates an isometric 3D View.
    Smart View Naming:
    - If doc is Workshared (Central/Local): uses '{3D - <username>}' to prevent element borrowing
      conflicts and keep each user's Section Box independent.
    - If doc is Non-workshared: uses standard '{3D}' default view.
    Sets a tight Section Box around the clash center, and highlights clashing elements.
    Returns True on success.
    """
    try:
        clash_pt = clash_item.ClashPoint
        if not clash_pt:
            bb = None
            el1 = getattr(clash_item, "Element1", None)
            if el1 and getattr(el1, "IsValidObject", False):
                try:
                    bb = el1.get_BoundingBox(None)
                except Exception:
                    bb = None
            if not bb:
                el2 = getattr(clash_item, "Element2", None)
                if el2 and getattr(el2, "IsValidObject", False):
                    try:
                        bb = el2.get_BoundingBox(None)
                    except Exception:
                        bb = None
            if bb:
                clash_pt = XYZ((bb.Min.X + bb.Max.X) * 0.5, (bb.Min.Y + bb.Max.Y) * 0.5, (bb.Min.Z + bb.Max.Z) * 0.5)
            else:
                return False
                
        pad_ft = mm_to_ft(padding_mm)
        
        # 1. Determine target 3D view name based on Worksharing status
        if getattr(doc, "IsWorkshared", False):
            try:
                username = doc.Application.Username
            except Exception:
                username = "User"
            view_name = "{3D - " + str(username) + "}"
        else:
            view_name = "{3D}"
        
        # 2. Search for existing 3D view
        target_view = None
        col = FilteredElementCollector(doc).OfClass(View3D).WhereElementIsNotElementType()
        for v in col:
            if not v.IsTemplate and v.Name.strip().lower() == view_name.strip().lower():
                target_view = v
                break
                
        # 3. Create view if not found & configure Section Box
        with SafeTransaction(doc, "MEPANANA Focus Clash 3D"):
            if not target_view:
                vft_col = FilteredElementCollector(doc).OfClass(ViewFamilyType)
                iso_vft = None
                for vft in vft_col:
                    if vft.ViewFamily == ViewFamily.ThreeDimensional:
                        iso_vft = vft
                        break
                if not iso_vft:
                    return False
                target_view = View3D.CreateIsometric(doc, iso_vft.Id)
                try:
                    target_view.Name = view_name
                except Exception:
                    try:
                        target_view.Name = "MEPANANA_Clash_3D"
                    except Exception:
                        pass
                
            box = BoundingBoxXYZ()
            box.Min = XYZ(clash_pt.X - pad_ft, clash_pt.Y - pad_ft, clash_pt.Z - pad_ft)
            box.Max = XYZ(clash_pt.X + pad_ft, clash_pt.Y + pad_ft, clash_pt.Z + pad_ft)
            
            try:
                target_view.IsSectionBoxActive = True
                target_view.SetSectionBox(box)
            except Exception as ex_box:
                print("Warning: Could not set Section Box: {}".format(ex_box))
            
        # 4. Regenerate document to finalize SectionBox geometry
        try:
            doc.Regenerate()
        except Exception:
            pass

        # 5. Highlight clashing elements
        sel_ids = List[ElementId]()
        el1 = getattr(clash_item, "Element1", None)
        el2 = getattr(clash_item, "Element2", None)
        if el1 and not getattr(clash_item, "IsLink1", False):
            try:
                if getattr(el1, "IsValidObject", False):
                    sel_ids.Add(el1.Id)
            except Exception:
                pass
        if el2 and not getattr(clash_item, "IsLink2", False):
            try:
                if getattr(el2, "IsValidObject", False):
                    sel_ids.Add(el2.Id)
            except Exception:
                pass

        if sel_ids.Count > 0:
            uidoc.Selection.SetElementIds(sel_ids)

        # 6. Switch to or zoom target 3D view
        if uidoc and target_view:
            clash_item.LastViewName = target_view.Name

            # Pre-zoom any open UI view for this target
            for uv in uidoc.GetOpenUIViews():
                if uv.ViewId == target_view.Id:
                    try:
                        uv.ZoomToFit()
                    except Exception:
                        pass
                    break

            if uidoc.ActiveView.Id == target_view.Id:
                # Already on 3D view: ShowElements zooms smoothly
                if sel_ids.Count > 0:
                    try:
                        uidoc.ShowElements(sel_ids)
                    except Exception:
                        pass
            else:
                # Use RequestViewChange (required in ExternalEvent / modeless context)
                switched = False
                if hasattr(uidoc, "RequestViewChange"):
                    try:
                        uidoc.RequestViewChange(target_view)
                        switched = True
                    except Exception as ex_req:
                        print("RequestViewChange failed: {}".format(ex_req))

                if not switched:
                    try:
                        uidoc.ActiveView = target_view
                    except Exception as ex_act:
                        print("ActiveView fallback failed: {}".format(ex_act))

        return True
    except Exception as ex:
        print("focus_clash_3d error: {}".format(ex))
        return False


def check_element_exists(doc, elem, elem_id_int=None, is_link=False, link_name=""):
    """
    Safely verifies if an element still physically exists and is valid in the Revit project or link document.
    Returns: (exists: bool, live_element: Element or None, transform: Transform or None)
    """
    try:
        if elem_id_int is None and elem:
            try:
                elem_id_int = get_id_value(elem)
            except Exception:
                pass

        target_doc = doc
        tf = None
        if is_link and link_name:
            col = FilteredElementCollector(doc).OfClass(RevitLinkInstance).WhereElementIsNotElementType()
            for li in col:
                if li.Name == link_name:
                    tf = li.GetTotalTransform()
                    ldoc = li.GetLinkDocument()
                    if ldoc:
                        target_doc = ldoc
                    break

        if elem_id_int:
            try:
                el = target_doc.GetElement(ElementId(elem_id_int))
                if el is not None and getattr(el, "IsValidObject", False):
                    _ = el.Id
                    return (True, el, tf)
            except Exception:
                pass
            return (False, None, tf)

        if elem is not None:
            try:
                if getattr(elem, "IsValidObject", False):
                    el = target_doc.GetElement(elem.Id)
                    if el is not None:
                        return (True, el, tf)
            except Exception:
                pass

        return (False, None, tf)
    except Exception:
        return (False, None, None)


def focus_element_3d(doc, uidoc, elem, padding_mm=1000, transform=None, is_link=False):
    """
    Navigates to or creates an isometric 3D View and sets Section Box around a single element.
    Used when one clashing element was deleted and user needs to inspect the surviving element.
    Returns: (success: bool, view_name: str)
    """
    try:
        if not elem:
            return (False, "")

        bb = elem.get_BoundingBox(None)
        if not bb:
            return (False, "")

        pad_ft = mm_to_ft(padding_mm)
        min_pt = bb.Min
        max_pt = bb.Max

        if transform and is_link:
            pt1 = transform.OfPoint(min_pt)
            pt2 = transform.OfPoint(max_pt)
            min_x = min(pt1.X, pt2.X) - pad_ft
            min_y = min(pt1.Y, pt2.Y) - pad_ft
            min_z = min(pt1.Z, pt2.Z) - pad_ft
            max_x = max(pt1.X, pt2.X) + pad_ft
            max_y = max(pt1.Y, pt2.Y) + pad_ft
            max_z = max(pt1.Z, pt2.Z) + pad_ft
        else:
            min_x = min_pt.X - pad_ft
            min_y = min_pt.Y - pad_ft
            min_z = min_pt.Z - pad_ft
            max_x = max_pt.X + pad_ft
            max_y = max_pt.Y + pad_ft
            max_z = max_pt.Z + pad_ft

        # Determine target 3D view name based on Worksharing status
        if getattr(doc, "IsWorkshared", False):
            try:
                username = doc.Application.Username
            except Exception:
                username = "User"
            view_name = "{3D - " + str(username) + "}"
        else:
            view_name = "{3D}"

        # Search for existing 3D view
        target_view = None
        col = FilteredElementCollector(doc).OfClass(View3D).WhereElementIsNotElementType()
        for v in col:
            if not v.IsTemplate and v.Name.strip().lower() == view_name.strip().lower():
                target_view = v
                break

        # Create view if not found & configure Section Box
        with SafeTransaction(doc, "MEPANANA Focus Element 3D"):
            if not target_view:
                vft_col = FilteredElementCollector(doc).OfClass(ViewFamilyType)
                iso_vft = None
                for vft in vft_col:
                    if vft.ViewFamily == ViewFamily.ThreeDimensional:
                        iso_vft = vft
                        break
                if not iso_vft:
                    return (False, "")
                target_view = View3D.CreateIsometric(doc, iso_vft.Id)
                try:
                    target_view.Name = view_name
                except Exception:
                    try:
                        target_view.Name = "MEPANANA_Clash_3D"
                    except Exception:
                        pass

            box = BoundingBoxXYZ()
            box.Min = XYZ(min_x, min_y, min_z)
            box.Max = XYZ(max_x, max_y, max_z)

            try:
                target_view.IsSectionBoxActive = True
                target_view.SetSectionBox(box)
            except Exception as ex_box:
                print("Warning: Could not set Section Box: {}".format(ex_box))

        try:
            doc.Regenerate()
        except Exception:
            pass

        # Highlight element if in host
        sel_ids = List[ElementId]()
        if not is_link and hasattr(elem, "Id"):
            try:
                if getattr(elem, "IsValidObject", False):
                    sel_ids.Add(elem.Id)
                    uidoc.Selection.SetElementIds(sel_ids)
            except Exception:
                pass

        if uidoc and target_view:
            for uv in uidoc.GetOpenUIViews():
                if uv.ViewId == target_view.Id:
                    try:
                        uv.ZoomToFit()
                    except Exception:
                        pass
                    break

            if uidoc.ActiveView.Id == target_view.Id:
                if sel_ids.Count > 0:
                    try:
                        uidoc.ShowElements(sel_ids)
                    except Exception:
                        pass
            else:
                switched = False
                if hasattr(uidoc, "RequestViewChange"):
                    try:
                        uidoc.RequestViewChange(target_view)
                        switched = True
                    except Exception:
                        pass
                if not switched:
                    try:
                        uidoc.ActiveView = target_view
                    except Exception:
                        pass

        return (True, target_view.Name if target_view else "")
    except Exception as ex:
        print("focus_element_3d error: {}".format(ex))
        return (False, "")


def export_clash_report(clashes, file_path):
    """
    Exports clash items to an Excel file (.xlsx) with professional formatting.
    """
    from py.excel_io import write_excel_workbook
    
    headers = [
        "No.", "Status", "Element 1 Category", "Element 1 ID",
        "Element 2 Category", "Element 2 ID", "Link Model",
        "Overlap (mm)", "Elevation Diff (mm)", "Clash Type", "Location (X, Y, Z)"
    ]
    
    rows = []
    for idx, c in enumerate(clashes):
        status = getattr(c, "Status", "ACTIVE")
        cat1 = c.Element1.Category.Name if (c.Element1 and c.Element1.Category) else "Element"
        id1 = str(get_id_value(c.Element1))
        cat2 = c.Element2.Category.Name if (c.Element2 and c.Element2.Category) else "Element"
        id2 = str(get_id_value(c.Element2))
        link = c.LinkName if c.IsLink else "Host Model"
        pt_str = "{:.1f}, {:.1f}, {:.1f}".format(c.ClashPoint.X, c.ClashPoint.Y, c.ClashPoint.Z) if c.ClashPoint else "-"
        
        rows.append([
            str(idx + 1),
            status,
            cat1,
            id1,
            cat2,
            id2,
            link,
            "{:.0f}".format(c.OverlapMm),
            "{:.0f}".format(c.ElevDiffMm),
            getattr(c, "ClashType", "HARD"),
            pt_str
        ])
        
    sheet_data = {
        "Clash Results": {
            "headers": headers,
            "rows": rows
        }
    }
    return write_excel_workbook(file_path, sheet_data)


def import_clash_report(doc, file_path):
    """
    Imports clash items from an Excel file (.xlsx) exported by Check Clash.
    Matches Element IDs against the active document and linked documents.
    Returns a list of ClashItem instances.
    """
    from py.excel_io import read_excel_workbook

    data = read_excel_workbook(file_path)
    if not data:
        return []

    # Get primary sheet (prefer "Clash Results", fallback to first sheet)
    sheet = data.get("Clash Results")
    if not sheet and data:
        first_key = list(data.keys())[0]
        sheet = data[first_key]

    if not sheet or "rows" not in sheet:
        return []

    rows = sheet["rows"]
    if not rows:
        return []

    # Build cache of RevitLinkInstances
    link_instances = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))

    clashes = []
    for r in rows:
        id1_str = str(r.get("Element 1 ID", "")).strip()
        id2_str = str(r.get("Element 2 ID", "")).strip()
        if not id1_str or not id2_str:
            continue

        try:
            id1 = int(float(id1_str))
            id2 = int(float(id2_str))
        except Exception:
            continue

        elem1 = doc.GetElement(ElementId(id1))
        if not elem1:
            continue

        link_name = str(r.get("Link Model", "")).strip()
        is_link2 = bool(link_name and link_name != "Host Model" and link_name != "-")
        elem2 = None

        if is_link2:
            for li in link_instances:
                lname = li.Name or ""
                if link_name.lower() in lname.lower():
                    ldoc = li.GetLinkDocument()
                    if ldoc:
                        elem2 = ldoc.GetElement(ElementId(id2))
                        break
        else:
            elem2 = doc.GetElement(ElementId(id2))

        if not elem2:
            continue

        # Parse Overlap & Elev Diff
        overlap_mm = 0.0
        elev_diff_mm = 0.0
        try:
            overlap_mm = float(str(r.get("Overlap (mm)", 0)).replace("mm", "").strip())
        except Exception:
            pass
        try:
            elev_diff_mm = float(str(r.get("Elevation Diff (mm)", 0)).replace("mm", "").strip())
        except Exception:
            pass

        # Parse ClashPoint XYZ
        clash_pt = None
        loc_str = str(r.get("Location (X, Y, Z)", "")).strip()
        if loc_str and loc_str != "-":
            parts = loc_str.split(",")
            if len(parts) >= 3:
                try:
                    clash_pt = XYZ(float(parts[0]), float(parts[1]), float(parts[2]))
                except Exception:
                    pass

        if not clash_pt:
            bb = elem1.get_BoundingBox(None)
            if bb:
                clash_pt = (bb.Min + bb.Max) * 0.5

        status = str(r.get("Status", "ACTIVE")).strip().upper()
        if "RESOLV" in status:
            status = "RESOLVED"
        else:
            status = "ACTIVE"

        clash_type = str(r.get("Clash Type", "HARD")).strip()

        item = ClashItem(
            elem1=elem1,
            elem2=elem2,
            clash_point=clash_pt,
            clash_type=clash_type,
            overlap_mm=overlap_mm,
            elev_diff_mm=elev_diff_mm,
            is_link1=False,
            is_link2=is_link2,
            link_name=link_name if is_link2 else ""
        )
        item.Status = status
        item.StatusIcon = u"✅" if status == "RESOLVED" else u"🔴"
        clashes.append(item)

    return clashes

