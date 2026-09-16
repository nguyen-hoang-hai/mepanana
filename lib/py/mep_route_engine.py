# -*- coding: utf-8 -*-
"""
mep_route_engine.py - 3D MEP Angled Routing Engine for MEPANANA
Calculates 3D vector offset geometry and places intermediate elements and elbow
fittings for Cable Trays, Conduits, Ducts, and Pipes.

Part of mepanana.extension.
Author: Hai Nguyen
"""
import math
import clr

from Autodesk.Revit.DB import (
    XYZ,
    ElementId,
    BuiltInParameter,
    FilteredElementCollector,
    Line,
    ConnectorType,
    Level
)
from Autodesk.Revit.UI.Selection import ISelectionFilter
from Autodesk.Revit.DB.Electrical import CableTray, Conduit
from Autodesk.Revit.DB.Mechanical import Duct, MechanicalSystemType
from Autodesk.Revit.DB.Plumbing import Pipe, PipingSystemType

from py.core import SafeTransaction, safe_unicode, get_id_value


class MEPElementFilter(ISelectionFilter):
    """View-safe selection filter allowing only linear MEP elements."""

    def AllowElement(self, elem):
        if isinstance(elem, (CableTray, Conduit, Duct, Pipe)):
            return True
        return False

    def AllowReference(self, reference, position):
        return False


def get_end_connectors(element):
    """
    Retrieves all linear end connectors of an MEP element.
    Returns: list of Connector objects.
    """
    connectors = []
    try:
        manager = element.ConnectorManager
        if manager:
            for conn in manager.Connectors:
                # Filter for end connectors (ignore surface/tap connectors)
                if conn.ConnectorType == ConnectorType.End:
                    connectors.append(conn)
    except Exception:
        pass
    return connectors


def get_closest_end_connectors(elem1, elem2):
    """
    Finds the two nearest end connectors between two MEP elements facing each other.
    Returns: (conn1, conn2) or (None, None).
    """
    conns1 = get_end_connectors(elem1)
    conns2 = get_end_connectors(elem2)

    if not conns1 or not conns2:
        return None, None

    min_dist = float("inf")
    closest_pair = (None, None)

    for c1 in conns1:
        for c2 in conns2:
            dist = c1.Origin.DistanceTo(c2.Origin)
            if dist < min_dist:
                min_dist = dist
                closest_pair = (c1, c2)

    return closest_pair[0], closest_pair[1]


def get_connector_at_point(element, target_pt, tolerance=0.08):
    """
    Finds a specific end connector on an element matching a given 3D coordinate.
    Tolerance in feet (0.08 ft ~ 24 mm).
    """
    for c in get_end_connectors(element):
        if c.Origin.DistanceTo(target_pt) < tolerance:
            return c
    return None


def get_element_level_id(doc, element):
    """
    Robust multi-tier fallback to obtain a valid Level ElementId for MEP curves.
    """
    # 1. ReferenceLevel property
    if hasattr(element, "ReferenceLevel") and element.ReferenceLevel:
        return element.ReferenceLevel.Id

    # 2. LevelId property
    if hasattr(element, "LevelId") and element.LevelId != ElementId.InvalidElementId:
        return element.LevelId

    # 3. BuiltInParameter RBS_START_LEVEL_PARAM
    lvl_param = element.get_Parameter(BuiltInParameter.RBS_START_LEVEL_PARAM)
    if lvl_param and lvl_param.AsElementId() != ElementId.InvalidElementId:
        return lvl_param.AsElementId()

    # 4. Project-wide fallback to first level
    first_lvl = FilteredElementCollector(doc).OfClass(Level).FirstElementId()
    if first_lvl != ElementId.InvalidElementId:
        return first_lvl

    return ElementId.InvalidElementId


def get_element_system_id(doc, element):
    """
    Determines MEPSystem type ElementId for Ducts and Pipes with multi-tier fallback.
    """
    if isinstance(element, Duct):
        if element.MEPSystem:
            sys_type = element.MEPSystem.GetTypeId()
            if sys_type != ElementId.InvalidElementId:
                return sys_type
        sys_param = element.get_Parameter(BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM)
        if sys_param and sys_param.AsElementId() != ElementId.InvalidElementId:
            return sys_param.AsElementId()
        first_sys = FilteredElementCollector(doc).OfClass(MechanicalSystemType).FirstElementId()
        if first_sys != ElementId.InvalidElementId:
            return first_sys

    elif isinstance(element, Pipe):
        if element.MEPSystem:
            sys_type = element.MEPSystem.GetTypeId()
            if sys_type != ElementId.InvalidElementId:
                return sys_type
        sys_param = element.get_Parameter(BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
        if sys_param and sys_param.AsElementId() != ElementId.InvalidElementId:
            return sys_param.AsElementId()
        first_sys = FilteredElementCollector(doc).OfClass(PipingSystemType).FirstElementId()
        if first_sys != ElementId.InvalidElementId:
            return first_sys

    return ElementId.InvalidElementId


def create_mep_element(doc, reference_elem, p_start, p_end):
    """
    Dynamically creates an intermediate MEP curve of the same category, type, and system.
    """
    type_id = reference_elem.GetTypeId()
    level_id = get_element_level_id(doc, reference_elem)

    if isinstance(reference_elem, CableTray):
        return CableTray.Create(doc, type_id, p_start, p_end, level_id)

    elif isinstance(reference_elem, Conduit):
        return Conduit.Create(doc, type_id, p_start, p_end, level_id)

    elif isinstance(reference_elem, Duct):
        system_id = get_element_system_id(doc, reference_elem)
        if system_id == ElementId.InvalidElementId:
            raise Exception("No valid Duct system type found. Please assign a system to the duct first.")
        return Duct.Create(doc, system_id, type_id, level_id, p_start, p_end)

    elif isinstance(reference_elem, Pipe):
        system_id = get_element_system_id(doc, reference_elem)
        if system_id == ElementId.InvalidElementId:
            raise Exception("No valid Pipe system type found. Please assign a system to the pipe first.")
        return Pipe.Create(doc, system_id, type_id, level_id, p_start, p_end)

    return None


def match_mep_dimensions(source_elem, target_elem):
    """
    Copies all cross-sectional dimension parameters (Rectangular & Round) from source to target.
    """
    dim_params = [
        BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
        BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM,
        BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
        BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
        BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
        BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
        BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM
    ]
    for b_param in dim_params:
        p_source = source_elem.get_Parameter(b_param)
        p_target = target_elem.get_Parameter(b_param)
        if p_source and p_target and not p_target.IsReadOnly:
            try:
                p_target.Set(p_source.AsDouble())
            except Exception:
                pass


def is_rectangular_profile(elem):
    """Returns True if the element has rectangular cross-section (Width & Height)."""
    p_w = elem.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
    if not p_w:
        p_w = elem.get_Parameter(BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM)
    return p_w is not None and p_w.HasValue


def calculate_route_geometry(elem1, elem2, angle_degrees):
    """
    Calculates 3D vector offset geometry and validates geometric feasibility.

    Returns:
        tuple: (success (bool), result_data (dict) or error_msg (str))
    """
    # 1. Category validation
    if type(elem1) != type(elem2):
        return (False, "Both elements must be of the same category (Pipe, Duct, Cable Tray, or Conduit).")

    # 2. Connector retrieval
    conn1, conn2 = get_closest_end_connectors(elem1, elem2)
    if not conn1 or not conn2:
        return (False, "Cannot find valid end connectors on the selected elements.")

    pt1 = conn1.Origin
    pt2 = conn2.Origin

    dir1 = conn1.CoordinateSystem.BasisZ
    dir2 = conn2.CoordinateSystem.BasisZ

    # 3. Parallelism check
    # In an angled offset/jog, both runs must be parallel along their longitudinal axis
    dot_dirs = abs(dir1.DotProduct(dir2))
    if dot_dirs < 0.96:
        return (False, "The selected elements are not parallel. Angled offset routing requires parallel elements.")

    # 4. 3D Vector projection & offset calculation
    vec_between = pt2 - pt1
    proj_len = vec_between.DotProduct(dir1)
    proj_vec = dir1 * proj_len
    raw_offset = vec_between - proj_vec

    # Filter out micro-deviations from hand clicking (< 0.005 ft ~ 1.5 mm)
    ox = 0.0 if abs(raw_offset.X) < 0.005 else raw_offset.X
    oy = 0.0 if abs(raw_offset.Y) < 0.005 else raw_offset.Y
    oz = 0.0 if abs(raw_offset.Z) < 0.005 else raw_offset.Z
    offset_vector = XYZ(ox, oy, oz)

    offset_distance = offset_vector.GetLength()

    if offset_distance < 0.01:
        return (False, "The selected elements are collinear. No angled offset is needed.")

    # 5. Compound 3D bend check for rectangular profiles (Cable Trays and Rectangular Ducts)
    if isinstance(elem1, CableTray) or is_rectangular_profile(elem1):
        has_horiz = math.sqrt(ox * ox + oy * oy) > 0.01
        has_vert = abs(oz) > 0.01
        if has_horiz and has_vert:
            return (
                False,
                "Rectangular elements (Cable Trays / Ducts) cannot make compound 3D bends.\n"
                "Please align either their horizontal coordinates or vertical elevation."
            )

    # 6. Longitudinal run calculation
    angle_rad = math.radians(angle_degrees)
    if abs(angle_degrees - 90.0) < 0.01:
        long_dist = 0.0
    else:
        long_dist = offset_distance / math.tan(angle_rad)

    # Meet point on elem2 centerline
    P_meet = pt1 + (dir1 * long_dist) + offset_vector

    # 7. Endpoint & direction validation on elem2
    crv2 = elem2.Location.Curve
    p2_0 = crv2.GetEndPoint(0)
    p2_1 = crv2.GetEndPoint(1)

    dist_to_0 = p2_0.DistanceTo(pt2)
    dist_to_1 = p2_1.DistanceTo(pt2)

    # The far endpoint that stays fixed
    p2_fixed = p2_1 if dist_to_0 < dist_to_1 else p2_0

    # Ensure the new line for elem2 is longer than Revit's minimum curve tolerance (~0.0026 ft)
    new_len2 = P_meet.DistanceTo(p2_fixed)
    if new_len2 < 0.05:
        return (
            False,
            "The calculated route leaves the target element too short (< 15 mm).\n"
            "Please shorten the target element or choose a smaller angle."
        )

    # Ensure P_meet does not overshoot past p2_fixed (inverting element direction)
    orig_dir2 = (p2_fixed - pt2).Normalize()
    new_dir2 = (p2_fixed - P_meet).Normalize()
    if orig_dir2.DotProduct(new_dir2) < 0.5:
        return (
            False,
            "The calculated angle/offset overshoots the target element.\n"
            "Please extend the target element or select a smaller angle."
        )

    result_data = {
        "pt1": pt1,
        "pt2": pt2,
        "P_meet": P_meet,
        "p2_fixed": p2_fixed,
        "offset_distance": offset_distance,
        "long_dist": long_dist
    }
    return (True, result_data)


def route_mep_elements(doc, elem1, elem2, angle_degrees):
    """
    Executes atomic MEP angled routing:
    1. Trims/extends elem2 to P_meet.
    2. Creates intermediate angled MEP element.
    3. Copies dimensions and properties.
    4. Places standard Revit elbow fittings.

    Returns:
        tuple: (success (bool), message (str))
    """
    success, geom_or_err = calculate_route_geometry(elem1, elem2, angle_degrees)
    if not success:
        return (False, geom_or_err)

    geom = geom_or_err
    pt1 = geom["pt1"]
    P_meet = geom["P_meet"]
    p2_fixed = geom["p2_fixed"]

    try:
        with SafeTransaction(doc, "MEPANANA - Route MEP Angled Offset"):
            # 1. Trim or extend Element 2 to P_meet
            new_crv2 = Line.CreateBound(P_meet, p2_fixed)
            elem2.Location.Curve = new_crv2
            doc.Regenerate()

            # 2. Create intermediate angled MEP curve
            new_elem = create_mep_element(doc, elem1, pt1, P_meet)
            if not new_elem:
                raise Exception("Failed to instantiate intermediate MEP element.")

            match_mep_dimensions(elem1, new_elem)
            doc.Regenerate()

            # 3. Retrieve end connectors for fitting placement
            c1 = get_connector_at_point(elem1, pt1)
            c_new_1 = get_connector_at_point(new_elem, pt1)
            c2 = get_connector_at_point(elem2, P_meet)
            c_new_2 = get_connector_at_point(new_elem, P_meet)

            if not (c1 and c_new_1 and c2 and c_new_2):
                raise Exception(
                    "Connectors could not be aligned. The offset may be too short for the required elbow radius."
                )

            # 4. Insert standard Revit elbow fittings
            try:
                elbow1 = doc.Create.NewElbowFitting(c1, c_new_1)
            except Exception as ex_elb1:
                raise Exception(
                    "Could not create first elbow fitting. Ensure an elbow is defined in Routing Preferences.\n"
                    "Detail: {}".format(safe_unicode(ex_elb1))
                )

            try:
                elbow2 = doc.Create.NewElbowFitting(c2, c_new_2)
            except Exception as ex_elb2:
                raise Exception(
                    "Could not create second elbow fitting. Ensure an elbow is defined in Routing Preferences.\n"
                    "Detail: {}".format(safe_unicode(ex_elb2))
                )

        return (True, "Route created successfully with {}° elbows.".format(angle_degrees))

    except Exception as ex:
        return (False, "Routing failed:\n{}".format(safe_unicode(ex)))
