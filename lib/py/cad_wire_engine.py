# -*- coding: utf-8 -*-
"""
cad_wire_engine.py - Core Engine for CAD Wire to Revit (CW)
Part of mepanana.extension.
"""
import math
import clr
clr.AddReference('System')
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
import System
from System.Collections.Generic import List as ClrList

from Autodesk.Revit.DB import (
    FilteredElementCollector, ImportInstance, GeometryElement, GeometryInstance,
    PolyLine, Line, Arc, NurbSpline, HermiteSpline, XYZ, Options, ViewDetailLevel,
    BuiltInCategory, ElementId, Transform, Domain, BuiltInParameter, ConnectorType
)
from Autodesk.Revit.DB.Electrical import (
    Wire, WireType, WiringType, ElectricalSystem, ElectricalSystemType
)

# ── Helper Conversions & Math ────────────────────────────────────────────────
def mm_to_ft(mm):
    return mm / 304.8

def ft_to_mm(ft):
    return ft * 304.8

def distance_2d(p1, p2):
    dx = p1.X - p2.X
    dy = p1.Y - p2.Y
    return math.sqrt(dx * dx + dy * dy)

def distance_3d(p1, p2):
    dx = p1.X - p2.X
    dy = p1.Y - p2.Y
    dz = p1.Z - p2.Z
    return math.sqrt(dx * dx + dy * dy + dz * dz)

def project_pt_on_seg(p, a, b):
    abx = b.X - a.X
    aby = b.Y - a.Y
    ab_len_sq = abx * abx + aby * aby
    if ab_len_sq == 0:
        return a, 0.0, distance_2d(p, a)
    apx = p.X - a.X
    apy = p.Y - a.Y
    t = (apx * abx + apy * aby) / ab_len_sq
    t_clamped = max(0.0, min(1.0, t))
    proj = XYZ(a.X + t_clamped * abx, a.Y + t_clamped * aby, a.Z)
    d = distance_2d(p, proj)
    return proj, t_clamped, d


# ── Data Models ───────────────────────────────────────────────────────────────
class CadLinkItem(System.Object):
    def __init__(self, element, display_name):
        self.Element = element
        self.DisplayName = display_name
        self.Id = element.Id.IntegerValue

    def __repr__(self):
        return self.DisplayName


class WireTypeItem(System.Object):
    def __init__(self, element, display_name):
        self.Element = element
        self.DisplayName = display_name
        self.Id = element.Id

    def __repr__(self):
        return self.DisplayName


class PanelItem(System.Object):
    def __init__(self, element, display_name):
        self.Element = element
        self.DisplayName = display_name
        self.Id = element.Id if element else None

    def __repr__(self):
        return self.DisplayName


class WirePath(System.Object):
    def __init__(self, points, original_type="ARC", chain_id=0):
        self.Points = points               # List of XYZ in Project Coordinates
        self.OriginalType = original_type   # "ARC", "PLINE", "LINE", "SPLINE"
        self.ChainId = chain_id
        self.StartConnector = None
        self.EndConnector = None
        self.StartDevice = None
        self.EndDevice = None
        self.IsHomeRun = False

    @property
    def Length(self):
        total = 0.0
        for i in range(len(self.Points) - 1):
            total += distance_3d(self.Points[i], self.Points[i+1])
        return total


# ── Project Queries ───────────────────────────────────────────────────────────
def get_cad_links_in_view(doc, active_view):
    """Returns all DWG ImportInstance elements in active view."""
    collector = FilteredElementCollector(doc, active_view.Id).OfClass(ImportInstance).WhereElementIsNotElementType().ToElements()
    items = []
    for inst in collector:
        name = "CAD Link " + str(inst.Id.IntegerValue)
        try:
            if inst.Category and inst.Category.Name:
                name = inst.Category.Name
        except Exception:
            pass
        items.append(CadLinkItem(inst, name))
    return items


def get_wire_types(doc):
    """Returns sorted list of WireType items."""
    collector = FilteredElementCollector(doc).OfClass(WireType)
    types = []
    for wt in collector:
        try:
            p_name = wt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
            name = p_name.AsString() if p_name else wt.Name
        except Exception:
            name = wt.Name if hasattr(wt, 'Name') else "Standard Wire"
        if name:
            types.append(WireTypeItem(wt, name))
    return sorted(types, key=lambda x: x.DisplayName)


def get_electrical_panels(doc):
    """Returns available electrical equipment panels."""
    collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_ElectricalEquipment).WhereElementIsNotElementType()
    panels = [PanelItem(None, "- None (No Auto-Circuit) -")]
    for elem in collector:
        try:
            name_param = elem.get_Parameter(BuiltInParameter.RBS_ELEC_PANEL_NAME)
            name = name_param.AsString() if name_param and name_param.AsString() else elem.Name
        except Exception:
            name = elem.Name if hasattr(elem, 'Name') else "Panel"
        if name:
            panels.append(PanelItem(elem, name))
    return panels


# ── Geometry Extraction ───────────────────────────────────────────────────────
def extract_curves_from_cad(cad_instance, view_elevation=None):
    """
    Traverses geometry of an ImportInstance and safely extracts transformed curves.
    Checks curve.IsBound to prevent Revit 'The input curve is not bound' exception.
    """
    options = Options()
    options.ComputeReferences = False
    options.DetailLevel = ViewDetailLevel.Fine

    geom_elem = cad_instance.get_Geometry(options)
    if not geom_elem:
        return []

    total_transform = cad_instance.GetTotalTransform()
    raw_segments = []

    def process_geom_obj(g_obj, current_transform):
        try:
            if isinstance(g_obj, GeometryInstance):
                inst_transform = current_transform.Multiply(g_obj.Transform)
                geom_sym = g_obj.GetSymbolGeometry()
                if geom_sym:
                    for sub_obj in geom_sym:
                        process_geom_obj(sub_obj, inst_transform)
                else:
                    geom_inst = g_obj.GetInstanceGeometry()
                    if geom_inst:
                        for sub_obj in geom_inst:
                            process_geom_obj(sub_obj, current_transform)

            elif isinstance(g_obj, PolyLine):
                coords = g_obj.GetCoordinates()
                if coords and len(coords) >= 2:
                    pts = [current_transform.OfPoint(p) for p in coords]
                    if view_elevation is not None:
                        pts = [XYZ(p.X, p.Y, view_elevation) for p in pts]
                    raw_segments.append(("PLINE", pts))

            elif isinstance(g_obj, Line):
                if hasattr(g_obj, 'IsBound') and not g_obj.IsBound:
                    return
                p0 = current_transform.OfPoint(g_obj.GetEndPoint(0))
                p1 = current_transform.OfPoint(g_obj.GetEndPoint(1))
                if view_elevation is not None:
                    p0 = XYZ(p0.X, p0.Y, view_elevation)
                    p1 = XYZ(p1.X, p1.Y, view_elevation)
                raw_segments.append(("LINE", [p0, p1]))

            elif isinstance(g_obj, Arc):
                if hasattr(g_obj, 'IsBound') and not g_obj.IsBound:
                    return
                p0 = current_transform.OfPoint(g_obj.GetEndPoint(0))
                p_mid = current_transform.OfPoint(g_obj.Evaluate(0.5, True))
                p1 = current_transform.OfPoint(g_obj.GetEndPoint(1))
                if view_elevation is not None:
                    p0 = XYZ(p0.X, p0.Y, view_elevation)
                    p_mid = XYZ(p_mid.X, p_mid.Y, view_elevation)
                    p1 = XYZ(p1.X, p1.Y, view_elevation)
                raw_segments.append(("ARC", [p0, p_mid, p1]))

            elif isinstance(g_obj, (NurbSpline, HermiteSpline)):
                if hasattr(g_obj, 'IsBound') and not g_obj.IsBound:
                    return
                tess = g_obj.Tessellate()
                if tess and len(tess) >= 2:
                    pts = [current_transform.OfPoint(p) for p in tess]
                    if view_elevation is not None:
                        pts = [XYZ(p.X, p.Y, view_elevation) for p in pts]
                    raw_segments.append(("SPLINE", list(pts)))
        except Exception:
            pass

    for g_obj in geom_elem:
        process_geom_obj(g_obj, total_transform)

    return raw_segments


# ── Topology & Graph-based Connected Component Grouping ───────────────────────
def stitch_curves_to_paths(raw_segments, snap_tol_ft=mm_to_ft(150), min_len_ft=mm_to_ft(30)):
    """
    Builds a Connected Component Graph of all CAD curves.
    Curves that touch each other are assigned the same Network/Circuit ChainId.
    """
    cleaned = []
    for ctype, pts in raw_segments:
        if len(pts) < 2:
            continue
        dedup = [pts[0]]
        for p in pts[1:]:
            if distance_3d(p, dedup[-1]) > mm_to_ft(5):
                dedup.append(p)
        if len(dedup) < 2:
            continue
            
        seg_len = 0.0
        for i in range(len(dedup) - 1):
            seg_len += distance_3d(dedup[i], dedup[i+1])
        if seg_len >= min_len_ft:
            cleaned.append((ctype, dedup))

    if not cleaned:
        return []

    # Build Adjacency Graph
    n = len(cleaned)
    adj = {i: [] for i in range(n)}

    for i in range(n):
        c1_type, c1_pts = cleaned[i]
        p1_start = c1_pts[0]
        p1_end = c1_pts[-1]

        for j in range(i + 1, n):
            c2_type, c2_pts = cleaned[j]
            p2_start = c2_pts[0]
            p2_end = c2_pts[-1]

            if (distance_2d(p1_start, p2_start) <= snap_tol_ft or
                distance_2d(p1_start, p2_end) <= snap_tol_ft or
                distance_2d(p1_end, p2_start) <= snap_tol_ft or
                distance_2d(p1_end, p2_end) <= snap_tol_ft):
                adj[i].append(j)
                adj[j].append(i)

    # Find Connected Components (Circuits)
    visited = set()
    chain_counter = 1
    final_paths = []

    for i in range(n):
        if i not in visited:
            component_indices = []
            queue = [i]
            visited.add(i)
            while queue:
                curr = queue.pop(0)
                component_indices.append(curr)
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            for idx in component_indices:
                ctype, pts = cleaned[idx]
                final_paths.append(WirePath(pts, ctype, chain_id=chain_counter))

            chain_counter += 1

    return final_paths


# ── Device & Connector Query ──────────────────────────────────────────────────
def get_electrical_devices_in_view(doc, active_view):
    """
    Collects all electrical devices in active view across all relevant MEP categories.
    Extracts location point, primary electrical connector, and returns category breakdown.
    """
    category_defs = [
        (BuiltInCategory.OST_LightingFixtures, "Lighting Fixtures"),
        (BuiltInCategory.OST_ElectricalFixtures, "Electrical Fixtures"),
        (BuiltInCategory.OST_ElectricalEquipment, "Electrical Equipment"),
        (BuiltInCategory.OST_LightingDevices, "Lighting Devices"),
        (BuiltInCategory.OST_SecurityDevices, "Security Devices"),
        (BuiltInCategory.OST_CommunicationDevices, "Communication Devices"),
        (BuiltInCategory.OST_FireAlarmDevices, "Fire Alarm Devices"),
        (BuiltInCategory.OST_DataDevices, "Data Devices"),
        (BuiltInCategory.OST_NurseCallDevices, "Nurse Call Devices"),
        (BuiltInCategory.OST_TelephoneDevices, "Telephone Devices")
    ]
    devices = []
    cat_counts = {}

    for cat_enum, cat_label in category_defs:
        try:
            collector = FilteredElementCollector(doc, active_view.Id).OfCategory(cat_enum).WhereElementIsNotElementType()
            count = 0
            for elem in collector:
                conn_list = []
                try:
                    if hasattr(elem, 'MEPModel') and elem.MEPModel:
                        mgr = elem.MEPModel.ConnectorManager
                        if mgr:
                            for c in mgr.Connectors:
                                if c.Domain == Domain.DomainElectrical:
                                    conn_list.append(c)
                except Exception:
                    pass

                loc_pt = None
                if hasattr(elem, 'Location') and hasattr(elem.Location, 'Point'):
                    loc_pt = elem.Location.Point
                else:
                    bb = elem.get_BoundingBox(active_view)
                    if bb:
                        loc_pt = (bb.Min + bb.Max) * 0.5

                if loc_pt:
                    primary_conn = conn_list[0] if conn_list else None
                    devices.append({
                        'element': elem,
                        'category_name': cat_label,
                        'connector': primary_conn,
                        'connectors': conn_list,
                        'origin': loc_pt,
                        'loc_pt': loc_pt
                    })
                    count += 1
            if count > 0:
                cat_counts[cat_label] = count
        except Exception:
            pass

    return devices, cat_counts


# ── Precise Path Sub-segmentation & Accurate Arc vs Chamfer Recognition ──────
def split_paths_by_devices(stitched_paths, devices, snap_radius_ft=mm_to_ft(500)):
    """
    1. Accurately maps devices lying along CAD curves within tight snap tolerance (450-500mm).
    2. Recognizes ARCs from CAD arc entities, and CHAMFERS from polyline corners.
    3. Strictly filters out cross-row diagonal mismatches.
    """
    if not devices or not stitched_paths:
        return []

    sub_divided_paths = []

    for chain_idx, path in enumerate(stitched_paths):
        path_pts = path.Points
        if len(path_pts) < 2:
            continue

        c_id = getattr(path, 'ChainId', chain_idx + 1)

        # ── CASE 1: CAD ARC Entity ────────────────────────────────────────────
        if path.OriginalType == "ARC" and len(path_pts) == 3:
            p0 = path_pts[0]
            p_mid = path_pts[1]
            p1 = path_pts[2]

            best_d0 = snap_radius_ft
            dev0 = None
            best_d1 = snap_radius_ft
            dev1 = None

            for dev in devices:
                p_loc = dev['loc_pt']

                d0 = distance_2d(p0, p_loc)
                if d0 < best_d0:
                    best_d0 = d0
                    dev0 = dev

                d1 = distance_2d(p1, p_loc)
                if d1 < best_d1:
                    best_d1 = d1
                    dev1 = dev

            if dev0 and dev1 and dev0['element'].Id != dev1['element'].Id:
                arc_path = WirePath([dev0['loc_pt'], p_mid, dev1['loc_pt']], "ARC", chain_id=c_id)
                arc_path.StartDevice = dev0['element']
                arc_path.StartConnector = dev0['connector']
                arc_path.EndDevice = dev1['element']
                arc_path.EndConnector = dev1['connector']
                arc_path.IsHomeRun = False
                sub_divided_paths.append(arc_path)
            continue

        # ── CASE 2: Lines / Polylines ─────────────────────────────────────────
        vertex_s = [0.0]
        total_len = 0.0
        for i in range(len(path_pts) - 1):
            total_len += distance_2d(path_pts[i], path_pts[i+1])
            vertex_s.append(total_len)

        matched = []
        for dev in devices:
            p_loc = dev['loc_pt']
            best_d = 999999.0
            best_s = 0.0
            best_proj = None

            for i in range(len(path_pts) - 1):
                pA = path_pts[i]
                pB = path_pts[i+1]
                seg_len = distance_2d(pA, pB)
                proj, t, d = project_pt_on_seg(p_loc, pA, pB)

                if d < best_d:
                    best_d = d
                    best_s = vertex_s[i] + t * seg_len
                    best_proj = proj

            # Strict perpendicular tolerance: max 450-500mm
            if best_d <= snap_radius_ft:
                dev_entry = {
                    'element': dev['element'],
                    'connector': dev['connector'],
                    'connectors': dev['connectors'],
                    'origin': dev['loc_pt'],
                    'loc_pt': dev['loc_pt']
                }
                matched.append((best_s, dev_entry, best_proj))

        if len(matched) < 2:
            continue

        matched.sort(key=lambda x: x[0])

        # Create sub-paths between each consecutive pair of devices on this chain
        for i in range(len(matched) - 1):
            sA, devA, projA = matched[i]
            sB, devB, projB = matched[i+1]

            if devA['element'].Id == devB['element'].Id or sB - sA < mm_to_ft(20):
                continue

            sub_pts = [devA['loc_pt']]
            for v_idx, v_s in enumerate(vertex_s):
                if sA + mm_to_ft(30) < v_s < sB - mm_to_ft(30):
                    sub_pts.append(path_pts[v_idx])
            sub_pts.append(devB['loc_pt'])

            # Determine subtype: Chamfer if intermediate corner vertices exist, else LINE
            if len(sub_pts) > 2:
                sub_type = "CHAMFER"
            else:
                sub_type = "LINE"

            sub_path = WirePath(sub_pts, sub_type, chain_id=c_id)
            sub_path.StartDevice = devA['element']
            sub_path.StartConnector = devA['connector']
            sub_path.EndDevice = devB['element']
            sub_path.EndConnector = devB['connector']
            sub_path.IsHomeRun = False

            sub_divided_paths.append(sub_path)

    # ── Step C: Strict Deduplication ─────────────────────────────────────────
    unique_paths = []
    seen_pairs = set()

    for p in sub_divided_paths:
        d1 = p.StartDevice
        d2 = p.EndDevice
        if d1 and d2 and d1.Id != d2.Id:
            pair_key = (min(d1.Id.IntegerValue, d2.Id.IntegerValue), max(d1.Id.IntegerValue, d2.Id.IntegerValue))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            unique_paths.append(p)

    return unique_paths


# ── Wire & Circuit Creation Orchestration ────────────────────────────────────
def create_revit_wires(doc, active_view, wire_type_id, matched_paths, panel_element=None, progress_callback=None):
    """
    1. Creates a SINGLE Power Circuit for the ENTIRE continuous CAD network (All connected devices).
    2. Assigns the selected Panelboard to each created Circuit.
    3. Physically connects native Revit Wires to device connectors with complete circuit linkage.
    """
    created_wires = []
    circuits_created = 0
    errors = []

    # Get active view elevation
    view_z = 0.0
    try:
        if hasattr(active_view, 'GenLevel') and active_view.GenLevel:
            view_z = active_view.GenLevel.Elevation
    except Exception:
        pass

    # ── Step 1: Group Devices By Continuous Network Components & Create Circuits ──
    chain_groups = {}
    for path in matched_paths:
        c_id = getattr(path, 'ChainId', 1)
        if c_id not in chain_groups:
            chain_groups[c_id] = {}
        d1 = path.StartDevice
        d2 = path.EndDevice
        if d1:
            chain_groups[c_id][d1.Id.IntegerValue] = d1
        if d2:
            chain_groups[c_id][d2.Id.IntegerValue] = d2

    # Create a unified Electrical Power Circuit for each continuous connected component
    for c_id, devs_dict in chain_groups.items():
        chain_devs = list(devs_dict.values())
        if not chain_devs:
            continue

        try:
            target_sys = None
            for d in chain_devs:
                try:
                    if hasattr(d, 'MEPModel') and d.MEPModel:
                        sys_list = d.MEPModel.GetElectricalSystems()
                        if sys_list:
                            for s in sys_list:
                                if s.SystemType == ElectricalSystemType.PowerCircuit:
                                    target_sys = s
                                    break
                except Exception:
                    pass
                if target_sys:
                    break

            if target_sys:
                for d in chain_devs:
                    try:
                        if not target_sys.Elements.Contains(d):
                            target_sys.AddElements(ClrList[ElementId]([d.Id]))
                    except Exception:
                        pass
                if panel_element:
                    try:
                        target_sys.SelectPanel(panel_element)
                    except Exception:
                        pass
                circuits_created += 1

            else:
                created_sys = None
                try:
                    elem_ids = ClrList[ElementId]()
                    for d in chain_devs:
                        elem_ids.Add(d.Id)
                    created_sys = ElectricalSystem.Create(doc, elem_ids, ElectricalSystemType.PowerCircuit)
                except Exception:
                    for d in chain_devs:
                        try:
                            first_id = ClrList[ElementId]([d.Id])
                            created_sys = ElectricalSystem.Create(doc, first_id, ElectricalSystemType.PowerCircuit)
                            break
                        except Exception:
                            continue
                    if created_sys:
                        for d in chain_devs:
                            try:
                                if not created_sys.Elements.Contains(d):
                                    created_sys.AddElements(ClrList[ElementId]([d.Id]))
                            except Exception:
                                pass

                if created_sys:
                    if panel_element:
                        try:
                            created_sys.SelectPanel(panel_element)
                        except Exception:
                            pass
                    circuits_created += 1

        except Exception as e_circ:
            errors.append(str(e_circ))

    # ── Step 2: Create Connected Revit Wire Elements ─────────────────────────
    total = len(matched_paths)
    for idx, path in enumerate(matched_paths):
        if progress_callback:
            progress_callback(idx + 1, total)

        pts = path.Points
        if not pts or len(pts) < 2:
            continue

        start_conn = path.StartConnector
        end_conn = path.EndConnector

        p0_pt = pts[0]
        p1_pt = pts[-1]

        p0_2d = XYZ(p0_pt.X, p0_pt.Y, view_z)
        p1_2d = XYZ(p1_pt.X, p1_pt.Y, view_z)

        chord_len = distance_2d(p0_2d, p1_2d)

        # ── Compute 2D Planar Wire Points ─────────────────────────────────────
        if path.OriginalType == "ARC":
            mid_x = (p0_2d.X + p1_2d.X) * 0.5
            mid_y = (p0_2d.Y + p1_2d.Y) * 0.5

            if len(pts) == 3:
                p_mid_cad = pts[1]
                dx_cad = p_mid_cad.X - mid_x
                dy_cad = p_mid_cad.Y - mid_y
                h_cad = math.sqrt(dx_cad * dx_cad + dy_cad * dy_cad)
                if h_cad > mm_to_ft(5):
                    bulge = min(h_cad, chord_len * 0.45)
                    norm_x = dx_cad / h_cad
                    norm_y = dy_cad / h_cad
                else:
                    dx = p1_2d.X - p0_2d.X
                    dy = p1_2d.Y - p0_2d.Y
                    norm_x = -dy / chord_len
                    norm_y = dx / chord_len
                    bulge = min(chord_len * 0.2, mm_to_ft(180))
            else:
                dx = p1_2d.X - p0_2d.X
                dy = p1_2d.Y - p0_2d.Y
                norm_x = -dy / chord_len
                norm_y = dx / chord_len
                bulge = min(chord_len * 0.2, mm_to_ft(180))

            p_mid_2d = XYZ(mid_x + norm_x * bulge, mid_y + norm_y * bulge, view_z)
            pts_to_draw = [p0_2d, p_mid_2d, p1_2d]
            w_type = WiringType.Arc

        elif path.OriginalType == "CHAMFER" and len(pts) > 2:
            pts_to_draw = [p0_2d]
            for p in pts[1:-1]:
                pts_to_draw.append(XYZ(p.X, p.Y, view_z))
            pts_to_draw.append(p1_2d)
            w_type = WiringType.Chamfer

        else:
            mid_straight = XYZ((p0_2d.X + p1_2d.X)*0.5, (p0_2d.Y + p1_2d.Y)*0.5, view_z)
            pts_to_draw = [p0_2d, mid_straight, p1_2d]
            w_type = WiringType.Arc

        net_pts_2d = ClrList[XYZ]()
        for p in pts_to_draw:
            net_pts_2d.Add(p)

        wire = None

        # ── PRIORITY 1: Physical Connector Connection with 3D Points ──────────
        if start_conn and end_conn:
            try:
                c0 = start_conn.Origin
                c1 = end_conn.Origin
                pts_conn = ClrList[XYZ]()
                pts_conn.Add(c0)
                if path.OriginalType == "ARC":
                    mid_z = (c0.Z + c1.Z) * 0.5
                    pts_conn.Add(XYZ(p_mid_2d.X, p_mid_2d.Y, mid_z))
                elif path.OriginalType == "CHAMFER" and len(pts) > 2:
                    mid_z = (c0.Z + c1.Z) * 0.5
                    for p in pts[1:-1]:
                        pts_conn.Add(XYZ(p.X, p.Y, mid_z))
                else:
                    pts_conn.Add(XYZ((c0.X + c1.X)*0.5, (c0.Y + c1.Y)*0.5, (c0.Z + c1.Z)*0.5))
                pts_conn.Add(c1)

                wire = Wire.Create(
                    doc,
                    wire_type_id,
                    active_view.Id,
                    w_type,
                    pts_conn,
                    start_conn,
                    end_conn
                )
            except Exception:
                pass

        # ── PRIORITY 2: Planar Points Connection with Connectors ──────────────
        if not wire and start_conn and end_conn:
            try:
                wire = Wire.Create(
                    doc,
                    wire_type_id,
                    active_view.Id,
                    w_type,
                    net_pts_2d,
                    start_conn,
                    end_conn
                )
            except Exception:
                pass

        # ── PRIORITY 3: Clean Wire Fallback ───────────────────────────────────
        if not wire:
            try:
                wire = Wire.Create(
                    doc,
                    wire_type_id,
                    active_view.Id,
                    w_type,
                    net_pts_2d,
                    None,
                    None
                )
            except Exception:
                try:
                    mid_pt = XYZ((p0_2d.X + p1_2d.X)*0.5, (p0_2d.Y + p1_2d.Y)*0.5, view_z)
                    fb_pts = ClrList[XYZ]()
                    fb_pts.Add(p0_2d)
                    fb_pts.Add(mid_pt)
                    fb_pts.Add(p1_2d)
                    wire = Wire.Create(
                        doc,
                        wire_type_id,
                        active_view.Id,
                        WiringType.Arc,
                        fb_pts,
                        None,
                        None
                    )
                except Exception as e_fb:
                    errors.append(str(e_fb))

        if wire:
            created_wires.append(wire)

    return {
        "success": len(created_wires) > 0,
        "wires_created": len(created_wires),
        "home_runs": 0,
        "devices_connected": sum(len(d) for d in chain_groups.values()),
        "circuits_created": circuits_created,
        "total_paths": total,
        "errors": errors
    }
