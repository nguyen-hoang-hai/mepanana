# -*- coding: utf-8 -*-
"""
quick_connect_engine.py - Advanced MEP Quick Connect Engine for MEPANANA
Provides multi-tier intelligent connections (Direct, Collinear Extend/Bridge,
Corner Elbows, Smart Coaxial Alignment, and Branch-to-Main Tees) across
Pipes, Ducts, Cable Trays, and Conduits.

Part of mepanana.extension.
Author: Hai Nguyen
"""
import os
import sys
import math
import json
import traceback

from Autodesk.Revit.DB import (
    XYZ,
    ElementId,
    BuiltInParameter,
    BuiltInCategory,
    FilteredElementCollector,
    Level,
    MEPSystemType,
    MEPSystemClassification,
    Connector,
    ConnectorType,
    ConnectorProfileType,
    Domain,
    FamilyInstance,
    Line,
    LocationCurve,
    ElementTransformUtils
)

try:
    from Autodesk.Revit.DB.Plumbing import Pipe, PipeType, PlumbingUtils
    HAS_PIPE = True
except Exception:
    HAS_PIPE = False
    PlumbingUtils = None

try:
    from Autodesk.Revit.DB.Mechanical import Duct, DuctType, MechanicalUtils
    HAS_DUCT = True
except Exception:
    HAS_DUCT = False
    MechanicalUtils = None

try:
    from Autodesk.Revit.DB.Electrical import Conduit, ConduitType
    HAS_CONDUIT = True
except Exception:
    HAS_CONDUIT = False

try:
    from Autodesk.Revit.DB.Electrical import CableTray, CableTrayType
    HAS_CABLE_TRAY = True
except Exception:
    HAS_CABLE_TRAY = False

from Autodesk.Revit.UI.Selection import ISelectionFilter

from py.core import SafeTransaction, safe_unicode, mm_to_ft, ft_to_mm, get_id_value
from py.bloom_engine import (
    get_connector_manager,
    get_open_connectors,
    _get_element_level_id,
    _get_default_pipe_type_id,
    _get_piping_system_type_id_from_connector,
    _get_default_duct_type_id,
    _get_duct_system_type_id_from_connector,
    _get_default_conduit_type_id,
    _get_default_cable_tray_type_id,
    _is_cable_tray_target
)

CONFIG_FILE = os.path.join(os.environ.get("APPDATA", ""), "pyRevit", "mepanana_quick_connect_config.json")
_MIN_LINE_LEN_FT = 0.015  # ~4.5 mm (safely above Revit's 1/16" limit)


class QuickConnectConfig(object):
    """Configuration for Quick Connect operations."""

    def __init__(self):
        self.max_align_offset_mm = 100.0
        self.allow_align_move = True
        self.preferred_mode = "Auto"  # Auto, ExtendOnly, BridgeOnly, ElbowOnly
        self.load()

    def load(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    self.max_align_offset_mm = float(data.get("max_align_offset_mm", 100.0))
                    self.allow_align_move = bool(data.get("allow_align_move", True))
                    self.preferred_mode = str(data.get("preferred_mode", "Auto"))
        except Exception:
            pass

    def save(self):
        try:
            folder = os.path.dirname(CONFIG_FILE)
            if not os.path.exists(folder):
                os.makedirs(folder)
            data = {
                "max_align_offset_mm": self.max_align_offset_mm,
                "allow_align_move": self.allow_align_move,
                "preferred_mode": self.preferred_mode
            }
            with open(CONFIG_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


class MEPConnectSelectionFilter(ISelectionFilter):
    """Allows picking any element that has MEP connectors or is a linear MEP element."""

    def AllowElement(self, elem):
        if not elem:
            return False
        try:
            if get_connector_manager(elem) is not None:
                return True
            if isinstance(elem, (Pipe, Duct, Conduit, CableTray)):
                return True
        except Exception:
            pass
        return False

    def AllowReference(self, reference, position):
        return False


def are_already_connected(el1, el2):
    """Check if el1 and el2 already share a connected port."""
    cm1 = get_connector_manager(el1)
    if not cm1:
        return False
    try:
        for c in cm1.Connectors:
            if c.IsConnected:
                for ref in c.AllRefs:
                    if ref.Owner and ref.Owner.Id == el2.Id:
                        return True
    except Exception:
        pass
    return False


def get_connector_at_point(elem, target_pt, tolerance=0.08):
    """Finds a connector on elem matching target_pt within tolerance (in feet)."""
    cm = get_connector_manager(elem)
    if not cm:
        return None
    for c in cm.Connectors:
        if c.Origin.DistanceTo(target_pt) < tolerance:
            return c
    return None


def get_best_connector(elem, pick_point=None):
    """
    Finds the best open connector on elem.
    If pick_point is provided, chooses open connector closest to pick_point.
    Otherwise, returns any open connector or closest to element midpoint.
    """
    open_conns = get_open_connectors(elem)
    if not open_conns:
        return None

    if pick_point:
        best_c = None
        min_dist = float("inf")
        for c in open_conns:
            d = c.Origin.DistanceTo(pick_point)
            if d < min_dist:
                min_dist = d
                best_c = c
        return best_c

    return open_conns[0]


def is_linear_curve(elem):
    """Returns True if elem has an editable straight Line LocationCurve."""
    if hasattr(elem, "Location") and isinstance(elem.Location, LocationCurve):
        crv = elem.Location.Curve
        if isinstance(crv, Line):
            return True
    return False


def extend_curve_to_point(curve_elem, target_pt, which_end_pt):
    """
    Extends or trims a linear MEP element's LocationCurve so that the endpoint
    nearest which_end_pt becomes target_pt.
    """
    if not is_linear_curve(curve_elem):
        return False

    line = curve_elem.Location.Curve
    pt0 = line.GetEndPoint(0)
    pt1 = line.GetEndPoint(1)

    # If already at target point within tolerance
    if pt0.DistanceTo(target_pt) < 0.0026 or pt1.DistanceTo(target_pt) < 0.0026:
        return True

    try:
        if pt0.DistanceTo(which_end_pt) < pt1.DistanceTo(which_end_pt):
            new_line = Line.CreateBound(target_pt, pt1)
        else:
            new_line = Line.CreateBound(pt0, target_pt)
        curve_elem.Location.Curve = new_line
        return True
    except Exception:
        return False


def calculate_line_intersection_3d(p1, dir1, p2, dir2, tolerance=0.08):
    """
    Calculates 3D closest approach / intersection point between two 3D rays.
    Returns: (point_3d, distance_between_lines) or (None, inf) if parallel.
    """
    u1 = dir1.Normalize()
    u2 = dir2.Normalize()

    w0 = p1 - p2
    a = u1.DotProduct(u1)
    b = u1.DotProduct(u2)
    c = u2.DotProduct(u2)
    d = u1.DotProduct(w0)
    e = u2.DotProduct(w0)

    denom = a * c - b * b
    if abs(denom) < 1e-4:
        return None, float("inf")  # Lines are parallel

    s = (b * e - c * d) / denom
    t = (a * e - b * d) / denom

    q1 = p1 + u1 * s
    q2 = p2 + u2 * t
    dist = q1.DistanceTo(q2)

    if dist <= tolerance:
        p_int = (q1 + q2) * 0.5
        return p_int, dist
    return None, dist


def create_bridging_mep_curve(doc, ref_elem, ref_conn, p_start, p_end):
    """
    Creates a new Pipe, Duct, Cable Tray, or Conduit segment bridging p_start and p_end,
    inheriting discipline, system type, type, level, and dimensions from ref_elem / ref_conn.
    """
    level_id = _get_element_level_id(doc, ref_elem, (p_start.Z + p_end.Z) * 0.5)
    domain = ref_conn.Domain

    # 1. Piping
    if domain == Domain.DomainPiping and HAS_PIPE:
        sys_id = _get_piping_system_type_id_from_connector(doc, ref_conn)
        type_id = ref_elem.GetTypeId() if isinstance(ref_elem, Pipe) else _get_default_pipe_type_id(doc)
        new_pipe = Pipe.Create(doc, sys_id, type_id, level_id, p_start, p_end)
        if new_pipe:
            # Set diameter to match connector
            try:
                diam_val = None
                if hasattr(ref_conn, "Radius") and ref_conn.Radius > 0:
                    diam_val = ref_conn.Radius * 2.0
                elif hasattr(ref_conn, "Diameter") and ref_conn.Diameter > 0:
                    diam_val = ref_conn.Diameter
                if diam_val:
                    p = new_pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
                    if p and not p.IsReadOnly:
                        p.Set(diam_val)
            except Exception:
                pass
            return new_pipe

    # 2. HVAC Ducts
    elif domain == Domain.DomainHvac and HAS_DUCT:
        sys_id = _get_duct_system_type_id_from_connector(doc, ref_conn)
        shape = ref_conn.Shape
        type_id = ref_elem.GetTypeId() if isinstance(ref_elem, Duct) else _get_default_duct_type_id(doc, shape)
        new_duct = Duct.Create(doc, sys_id, type_id, level_id, p_start, p_end)
        if new_duct:
            try:
                if shape == ConnectorProfileType.Round:
                    diam_val = ref_conn.Radius * 2.0 if hasattr(ref_conn, "Radius") else getattr(ref_conn, "Diameter", 0.0)
                    if diam_val > 0:
                        p = new_duct.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
                        if p and not p.IsReadOnly: p.Set(diam_val)
                elif shape in (ConnectorProfileType.Rectangular, ConnectorProfileType.Oval):
                    w = getattr(ref_conn, "Width", 0.0)
                    h = getattr(ref_conn, "Height", 0.0)
                    if w > 0:
                        p_w = new_duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
                        if p_w and not p_w.IsReadOnly: p_w.Set(w)
                    if h > 0:
                        p_h = new_duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
                        if p_h and not p_h.IsReadOnly: p_h.Set(h)
            except Exception:
                pass
            return new_duct

    # 3. Cable Tray vs Conduit
    elif domain == Domain.DomainCableTrayConduit:
        is_tray = _is_cable_tray_target(ref_elem, ref_conn)
        if is_tray and HAS_CABLE_TRAY:
            type_id = ref_elem.GetTypeId() if isinstance(ref_elem, CableTray) else _get_default_cable_tray_type_id(doc)
            new_tray = CableTray.Create(doc, type_id, p_start, p_end, level_id)
            if new_tray:
                try:
                    w = getattr(ref_conn, "Width", 0.0)
                    h = getattr(ref_conn, "Height", 0.0)
                    if w > 0:
                        p_w = new_tray.get_Parameter(BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM)
                        if p_w and not p_w.IsReadOnly: p_w.Set(w)
                    if h > 0:
                        p_h = new_tray.get_Parameter(BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM)
                        if p_h and not p_h.IsReadOnly: p_h.Set(h)
                except Exception:
                    pass
                return new_tray
        elif HAS_CONDUIT:
            type_id = ref_elem.GetTypeId() if isinstance(ref_elem, Conduit) else _get_default_conduit_type_id(doc)
            new_conduit = Conduit.Create(doc, type_id, p_start, p_end, level_id)
            if new_conduit:
                try:
                    diam = ref_conn.Radius * 2.0 if hasattr(ref_conn, "Radius") else getattr(ref_conn, "Diameter", 0.0)
                    if diam > 0:
                        p_d = new_conduit.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
                        if p_d and not p_d.IsReadOnly: p_d.Set(diam)
                except Exception:
                    pass
                return new_conduit

    return None


def join_or_transition(doc, c1, c2):
    """
    Attempts to join c1 and c2 directly via c1.ConnectTo(c2).
    If that fails (due to size/shape mismatch), attempts NewTransitionFitting.
    """
    try:
        c1.ConnectTo(c2)
        return True, "Directly joined connectors."
    except Exception:
        pass

    try:
        fitting = doc.Create.NewTransitionFitting(c1, c2)
        if fitting:
            return True, "Connected with transition fitting."
    except Exception:
        pass

    return False, "Could not join or place transition between connectors."


def connect_elements(doc, el1, pt1, el2, pt2, config=None):
    """
    Main Multi-tier Connection Orchestrator.
    Tiers:
      Tier 1: Direct Join / Transition (< 1.5mm)
      Tier 2: Collinear Extend or Bridge with Segment
      Tier 3: Corner / Angled Connection (Elbow Fitting)
      Tier 4: Smart Coaxial Alignment (Shift & Connect)
      Tier 5: Branch into Main (Tee Fitting)

    Returns: (bool success, str message)
    """
    if not config:
        config = QuickConnectConfig()

    if el1.Id == el2.Id:
        return False, "Please select two different MEP elements."

    if are_already_connected(el1, el2):
        return True, "These elements are already connected."

    # 1. Retrieve targeted connectors
    c1 = get_best_connector(el1, pt1)
    c2 = get_best_connector(el2, pt2)

    # Special check: Branch into Main pipe/duct (Tier 5)
    # If one has an open connector and the other is a linear curve with no open connector at the hit point
    if c1 and not c2 and is_linear_curve(el2):
        return _try_branch_to_main(doc, el1, c1, el2)
    elif c2 and not c1 and is_linear_curve(el1):
        return _try_branch_to_main(doc, el2, c2, el1)

    if not c1 or not c2:
        return False, "Could not find open MEP connectors on the selected elements."

    p1 = c1.Origin
    p2 = c2.Origin
    dist = p1.DistanceTo(p2)

    d1 = c1.CoordinateSystem.BasisZ
    d2 = c2.CoordinateSystem.BasisZ

    # =========================================================================
    # TIER 1: DIRECT SNAP / TOUCHING (dist < 0.005 ft ~ 1.5 mm)
    # =========================================================================
    if dist < 0.005:
        ok, msg = join_or_transition(doc, c1, c2)
        if ok:
            return True, msg

    # Vector between connector origins
    V = p2 - p1
    dir_v = V.Normalize() if dist > 0.001 else XYZ(1, 0, 0)
    dot_dir = d1.DotProduct(d2)

    # =========================================================================
    # TIER 2: COLLINEAR / COAXIAL FACING (dot_dir < -0.95 and dir_v aligned)
    # =========================================================================
    is_collinear_facing = dot_dir < -0.95 and abs(dir_v.DotProduct(d1) - 1.0) < 0.08

    if is_collinear_facing and config.preferred_mode in ("Auto", "ExtendOnly", "BridgeOnly"):
        # 2A: Try extending existing linear curve (cleanest Revit BIM geometry)
        if config.preferred_mode != "BridgeOnly":
            # Try extending el2 to p1
            if is_linear_curve(el2):
                if extend_curve_to_point(el2, p1, p2):
                    doc.Regenerate()
                    c2_new = get_connector_at_point(el2, p1)
                    if c2_new:
                        ok, msg = join_or_transition(doc, c1, c2_new)
                        if ok:
                            return True, "Extended curve and connected directly."

            # Try extending el1 to p2
            if is_linear_curve(el1):
                if extend_curve_to_point(el1, p2, p1):
                    doc.Regenerate()
                    c1_new = get_connector_at_point(el1, p2)
                    if c1_new:
                        ok, msg = join_or_transition(doc, c1_new, c2)
                        if ok:
                            return True, "Extended curve and connected directly."

        # 2B: Bridge with a new matching segment
        if dist >= _MIN_LINE_LEN_FT:
            new_seg = create_bridging_mep_curve(doc, el1, c1, p1, p2)
            if new_seg:
                doc.Regenerate()
                seg_c1 = get_connector_at_point(new_seg, p1)
                seg_c2 = get_connector_at_point(new_seg, p2)
                if seg_c1 and seg_c2:
                    ok1, _ = join_or_transition(doc, c1, seg_c1)
                    ok2, _ = join_or_transition(doc, seg_c2, c2)
                    if ok1 and ok2:
                        return True, "Bridged with a new matching MEP segment."

    # =========================================================================
    # TIER 3: CORNER / ANGLED INTERSECTION (ELBOW FITTING)
    # =========================================================================
    if config.preferred_mode in ("Auto", "ElbowOnly"):
        # Calculate 3D intersection of connector axes
        # Ray 1: p1 along d1
        # Ray 2: p2 along d2
        p_int, line_dist = calculate_line_intersection_3d(p1, d1, p2, d2, tolerance=0.08)

        if p_int and line_dist <= 0.08:
            # Verify intersection is in front of both connectors (or within reasonable reach)
            v1_to_int = p_int - p1
            v2_to_int = p_int - p2
            proj1 = v1_to_int.DotProduct(d1)
            proj2 = v2_to_int.DotProduct(d2)

            # Check if angle is valid for elbow (between 15° and 165°)
            angle_rad = d1.AngleTo(d2)
            angle_deg = angle_rad * 180.0 / math.pi
            if 15.0 <= angle_deg <= 165.0 and proj1 > -0.05 and proj2 > -0.05:
                # Trim/extend both curve elements to p_int
                extended1 = extend_curve_to_point(el1, p_int, p1) if is_linear_curve(el1) else False
                extended2 = extend_curve_to_point(el2, p_int, p2) if is_linear_curve(el2) else False

                if extended1 or extended2 or (p1.DistanceTo(p_int) < 0.01 and p2.DistanceTo(p_int) < 0.01):
                    doc.Regenerate()
                    c1_int = get_connector_at_point(el1, p_int)
                    c2_int = get_connector_at_point(el2, p_int)

                    if c1_int and c2_int:
                        try:
                            elbow = doc.Create.NewElbowFitting(c1_int, c2_int)
                            if elbow:
                                return True, "Connected with an elbow fitting ({:.1f}°).".format(angle_deg)
                        except Exception as ex_elb:
                            pass

    # =========================================================================
    # TIER 4: SMART COAXIAL ALIGNMENT (MINOR LATERAL OFFSET)
    # =========================================================================
    max_offset_ft = mm_to_ft(config.max_align_offset_mm)
    if config.allow_align_move and dot_dir < -0.7:
        # Calculate lateral offset vector to align el2's axis to c1
        proj_dist = V.DotProduct(d2)
        offset_vec = V - (d2 * proj_dist)
        offset_len = offset_vec.GetLength()

        if 0.001 < offset_len <= max_offset_ft:
            # Check if el2 is safe to move (has only 1 connector or other connectors are free)
            el2_conns = get_open_connectors(el2)
            all_conns = get_connector_manager(el2)
            total_count = len(list(all_conns.Connectors)) if all_conns else 0
            is_standalone = len(el2_conns) == total_count or total_count <= 2

            if is_standalone:
                try:
                    ElementTransformUtils.MoveElement(doc, el2.Id, offset_vec)
                    doc.Regenerate()

                    # Re-fetch connector after move
                    c2_moved = get_best_connector(el2, p1)
                    if c2_moved:
                        p2_new = c2_moved.Origin
                        # Now collinear, extend el2 to p1
                        if is_linear_curve(el2):
                            if extend_curve_to_point(el2, p1, p2_new):
                                doc.Regenerate()
                                c2_ext = get_connector_at_point(el2, p1)
                                if c2_ext:
                                    ok, msg = join_or_transition(doc, c1, c2_ext)
                                    if ok:
                                        return True, "Aligned axis and connected ({:.1f} mm offset).".format(ft_to_mm(offset_len))
                except Exception:
                    pass

    return False, "Could not connect elements. Please ensure routing preferences are configured and elements can reach each other."


def _try_branch_to_main(doc, branch_elem, branch_conn, main_elem):
    """
    Tier 5: Projects branch connector along its axis to hit main curve and places Tee fitting.
    """
    if not is_linear_curve(main_elem):
        return False, "Main element must be a straight linear curve for Tee connection."

    main_crv = main_elem.Location.Curve
    m_p0 = main_crv.GetEndPoint(0)
    m_p1 = main_crv.GetEndPoint(1)
    m_dir = (m_p1 - m_p0).Normalize()

    b_p = branch_conn.Origin
    b_dir = branch_conn.CoordinateSystem.BasisZ

    # Calculate intersection between branch ray and main line
    p_int, dist = calculate_line_intersection_3d(b_p, b_dir, m_p0, m_dir, tolerance=0.08)
    if not p_int or dist > 0.08:
        return False, "Branch axis does not intersect the main run."

    # Check that intersection is strictly along the interior of main curve
    proj_on_main = (p_int - m_p0).DotProduct(m_dir)
    total_len = m_p0.DistanceTo(m_p1)
    buffer_ft = mm_to_ft(50.0)

    if proj_on_main <= buffer_ft or proj_on_main >= (total_len - buffer_ft):
        return False, "Branch intersects too close to the end of the main run."

    # 1. Extend branch to p_int
    if not extend_curve_to_point(branch_elem, p_int, b_p):
        return False, "Could not extend branch curve to main run."
    doc.Regenerate()

    # 2. Break main curve at p_int
    new_piece_id = None
    try:
        if isinstance(main_elem, Pipe) and PlumbingUtils:
            new_piece_id = PlumbingUtils.BreakCurve(doc, main_elem.Id, p_int)
        elif isinstance(main_elem, Duct) and MechanicalUtils:
            new_piece_id = MechanicalUtils.BreakCurve(doc, main_elem.Id, p_int)
    except Exception as ex_break:
        return False, "Failed to break main curve: {}".format(safe_unicode(ex_break))

    if not new_piece_id or new_piece_id == ElementId.InvalidElementId:
        return False, "Could not break main curve."

    doc.Regenerate()
    new_piece = doc.GetElement(new_piece_id)

    # 3. Retrieve connectors at p_int
    c_branch = get_connector_at_point(branch_elem, p_int)
    c_main1 = get_connector_at_point(main_elem, p_int)
    c_main2 = get_connector_at_point(new_piece, p_int)

    if not (c_branch and c_main1 and c_main2):
        return False, "Could not resolve 3 connectors at Tee intersection."

    try:
        tee = doc.Create.NewTeeFitting(c_main1, c_main2, c_branch)
        if tee:
            return True, "Connected branch into main with Tee fitting."
    except Exception as ex_tee:
        return False, "Failed to insert Tee fitting: {}".format(safe_unicode(ex_tee))

    return False, "Could not complete Tee connection."
