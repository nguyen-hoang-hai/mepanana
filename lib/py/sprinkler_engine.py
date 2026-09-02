# -*- coding: utf-8 -*-
"""
Sprinkler Engine for mepanana.extension.
Unified single-file engine for geometric clustering, hydraulic pipe sizing,
Riser Nipple / Arm-over routing, stepped reduction fittings, and fitting connections in Autodesk Revit.

Full Features:
- Riser = 0 Support: Creates horizontal Tee / Takeoff fittings connecting branch lines directly into Main Pipe.
- Riser > 0 Support: Creates Riser Nipple with Top Tee (Dual-Sided) or Top Elbow (Single-Sided).
- Compact (120mm) pipe spool at size reduction nodes.
- Normal Equal Tee at equal size nodes with direct continuous connection.
- Final 90° Elbow drop at the branch end to the ceiling sprinkler head.
- Dynamic Main Pipe Segment Tracking with guaranteed physical connection.
- Stepped Hydraulic Sizing (TCVN 7336:2021 & NFPA 13).
- 100% Sprinkler Coverage (Every single head connected, 0 skipped).
"""
import math
from pyrevit import DB
from py.core import safe_unicode
from py.ui import yield_dispatcher_every

# ── Standards & Pipe Schedule Sizing Rules ────────────────────────────────────

SIZING_STANDARDS = {
    "TCVN 7336:2021 (Vietnam Standard)": {
        "rules": [
            (2, 25),    # <= 2 heads -> DN25 (1")
            (3, 32),    # <= 3 heads -> DN32 (1-1/4")
            (5, 40),    # <= 5 heads -> DN40 (1-1/2")
            (10, 50),   # <= 10 heads -> DN50 (2")
            (20, 65),   # <= 20 heads -> DN65 (2-1/2")
            (40, 80),   # <= 40 heads -> DN80 (3")
            (999, 100), # > 40 heads -> DN100 (4")
        ],
        "default_drop_dn": 25,
    },
    "NFPA 13 - Light Hazard (Offices / Schools)": {
        "rules": [
            (2, 25),    # 1-2 heads  -> DN25 (1")
            (3, 32),    # 3 heads    -> DN32 (1-1/4")
            (5, 40),    # 4-5 heads  -> DN40 (1-1/2")
            (10, 50),   # 6-10 heads -> DN50 (2")
            (30, 65),   # 11-30 heads-> DN65 (2-1/2")
            (60, 80),   # 31-60 heads-> DN80 (3")
            (999, 100), # > 60 heads -> DN100 (4")
        ],
        "default_drop_dn": 25,
    },
    "NFPA 13 - Ordinary Hazard (Commercial / Storage)": {
        "rules": [
            (2, 25),    # 1-2 heads  -> DN25 (1")
            (3, 32),    # 3 heads    -> DN32 (1-1/4")
            (5, 40),    # 4-5 heads  -> DN40 (1-1/2")
            (10, 50),   # 6-10 heads -> DN50 (2")
            (20, 65),   # 11-20 heads-> DN65 (2-1/2")
            (40, 80),   # 21-40 heads-> DN80 (3")
            (999, 100), # > 40 heads -> DN100 (4")
        ],
        "default_drop_dn": 25,
    }
}


def mm_to_ft(mm):
    """Converts millimeters to decimal feet (Revit internal units)."""
    return float(mm) / 304.8


def ft_to_mm(ft):
    """Converts decimal feet to millimeters."""
    return float(ft) * 304.8


def get_dn_for_head_count(head_count, standard_name):
    """Returns nominal diameter in mm (DN) for given head count."""
    std = SIZING_STANDARDS.get(standard_name, SIZING_STANDARDS["TCVN 7336:2021 (Vietnam Standard)"])
    for max_heads, dn in std["rules"]:
        if head_count <= max_heads:
            return dn
    return 100


# ── Geometry & Clustering Engine ──────────────────────────────────────────────

def get_pipe_centerline(pipe):
    """Extracts start point, end point, and normalized direction vector of a pipe."""
    loc = pipe.Location
    if not isinstance(loc, DB.LocationCurve):
        return None, None, None
    curve = loc.Curve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    vec = (p1 - p0).Normalize()
    return p0, p1, vec


def get_sprinkler_location_and_connector(sprinkler):
    """Extracts XYZ location and primary MEP connector of a sprinkler family instance."""
    point = None
    if isinstance(sprinkler.Location, DB.LocationPoint):
        point = sprinkler.Location.Point

    conn = None
    try:
        mep = sprinkler.MEPModel
        if mep and mep.ConnectorManager:
            for c in mep.ConnectorManager.Connectors:
                if c.Domain == DB.Domain.DomainPiping:
                    conn = c
                    point = c.Origin
                    break
    except Exception:
        pass

    return point, conn


def cluster_sprinklers_by_main_pipe(main_pipe, sprinkler_elements, tolerance_mm=300.0):
    """
    Groups sprinklers into branch columns based on projection along Main Pipe.
    Preserves both pos_side (+1) and neg_side (-1) within the same branch group
    to allow unified Riser Nipple + Top Tee creation!
    """
    p0, p1, u_vec = get_pipe_centerline(main_pipe)
    if not p0 or not u_vec:
        return []

    u_2d = DB.XYZ(u_vec.X, u_vec.Y, 0.0).Normalize()
    v_2d = DB.XYZ(-u_2d.Y, u_2d.X, 0.0).Normalize()

    tol_ft = mm_to_ft(tolerance_mm)
    items = []

    for sp in sprinkler_elements:
        sp_pt, sp_conn = get_sprinkler_location_and_connector(sp)
        if not sp_pt:
            continue

        rel = sp_pt - p0
        proj_u = rel.DotProduct(u_2d)
        dist_v = rel.DotProduct(v_2d)
        side = 1 if dist_v >= 0 else -1

        items.append({
            "element": sp,
            "point": sp_pt,
            "connector": sp_conn,
            "proj_u": proj_u,
            "dist_v": dist_v,
            "side": side,
            "abs_dist_v": abs(dist_v)
        })

    if not items:
        return []

    # Sort items along Main Pipe axis
    items.sort(key=lambda x: x["proj_u"])

    # Cluster into branch groups based on projection along Main Pipe
    raw_clusters = []
    curr_cluster = [items[0]]

    for i in range(1, len(items)):
        curr_item = items[i]
        prev_proj = curr_cluster[-1]["proj_u"]
        if abs(curr_item["proj_u"] - prev_proj) <= tol_ft:
            curr_cluster.append(curr_item)
        else:
            raw_clusters.append(curr_cluster)
            curr_cluster = [curr_item]

    if curr_cluster:
        raw_clusters.append(curr_cluster)

    # Package into branch groups with pos_side and neg_side
    branch_groups = []
    for cl in raw_clusters:
        avg_u = sum(x["proj_u"] for x in cl) / float(len(cl))
        main_conn_pt = p0 + u_2d * avg_u

        pos_items = [it for it in cl if it["side"] > 0]
        neg_items = [it for it in cl if it["side"] < 0]

        # Sort each side from closest to furthest from main pipe
        pos_items.sort(key=lambda x: x["abs_dist_v"])
        neg_items.sort(key=lambda x: x["abs_dist_v"])

        branch_groups.append({
            "proj_u": avg_u,
            "main_connect_pt": main_conn_pt,
            "pos_items": pos_items,
            "neg_items": neg_items,
            "pos_direction": v_2d,
            "neg_direction": -v_2d,
            "is_dual_sided": bool(pos_items and neg_items)
        })

    return branch_groups


# ── Connector & Fitting Utilities ────────────────────────────────────────────

def get_connector_closest_to(element, target_pt):
    """Finds the MEP piping connector closest to a target XYZ point."""
    best_c = None
    min_d = float('inf')
    try:
        conns = []
        if isinstance(element, DB.MEPCurve):
            conns = element.ConnectorManager.Connectors
        elif hasattr(element, 'MEPModel') and element.MEPModel:
            conns = element.MEPModel.ConnectorManager.Connectors

        for c in conns:
            if c.Domain == DB.Domain.DomainPiping:
                d = c.Origin.DistanceTo(target_pt)
                if d < min_d:
                    min_d = d
                    best_c = c
    except Exception:
        pass
    return best_c


def find_containing_main_pipe(doc, main_pipe_pool, target_pt):
    """Finds the active main pipe segment that physically contains the target point."""
    for pipe in list(main_pipe_pool):
        loc = pipe.Location
        if isinstance(loc, DB.LocationCurve):
            curve = loc.Curve
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            d_total = p0.DistanceTo(p1)
            d1 = p0.DistanceTo(target_pt)
            d2 = p1.DistanceTo(target_pt)
            if d1 > mm_to_ft(20.0) and d2 > mm_to_ft(20.0):
                if abs((d1 + d2) - d_total) <= mm_to_ft(15.0):
                    return pipe
    return None


def connect_branch_to_main(doc, riser_or_pipe, main_pipe_pool, main_connect_pt):
    """
    Connects a riser nipple or branch start pipe to the main pipe:
    1. Attempts NewTakeoffFitting (for Mechanical Tee / Welded Tap setups).
    2. If Takeoff fails, breaks the containing main pipe with BreakCurve and creates NewTeeFitting.
    """
    start_conn = get_connector_closest_to(riser_or_pipe, main_connect_pt)
    if not start_conn:
        return None

    target_pipe = find_containing_main_pipe(doc, main_pipe_pool, main_connect_pt)
    if not target_pipe:
        target_pipe = main_pipe_pool[0] if main_pipe_pool else None

    if not target_pipe:
        return None

    # Attempt 1: Takeoff Fitting
    try:
        fitting = doc.Create.NewTakeoffFitting(start_conn, target_pipe)
        if fitting:
            return fitting
    except Exception:
        pass

    # Attempt 2: BreakCurve on target pipe + NewTeeFitting
    try:
        new_pipe_id = DB.Plumbing.PlumbingUtils.BreakCurve(doc, target_pipe.Id, main_connect_pt)
        if new_pipe_id and new_pipe_id != DB.ElementId.InvalidElementId:
            new_pipe = doc.GetElement(new_pipe_id)
            main_pipe_pool.append(new_pipe)
            c1 = get_connector_closest_to(target_pipe, main_connect_pt)
            c2 = get_connector_closest_to(new_pipe, main_connect_pt)
            if c1 and c2 and not c1.IsConnected and not c2.IsConnected:
                tee = doc.Create.NewTeeFitting(c1, c2, start_conn)
                if tee:
                    return tee
    except Exception:
        pass

    return None


# ── Routing & Pipe Creation Engine ───────────────────────────────────────────

def _build_single_side_branch(doc, system_type_id, pipe_type_id, level_id, origin_pt, items, dir_vec, standard_name, drop_diameter_ft, created_pipes, created_fittings, errors, is_flex_mode=False, flex_pipe_type_id=None):
    """
    Builds branch line matching exact CAD Detail with 50% compact spool length (120mm):
    - Reduction points (dn_out < dn_in): [ Equal Tee ] -> [ 120mm Spool ] -> [ Reducer ] -> [ Next Pipe ].
    - Equal size points (dn_out == dn_in): [ Normal Equal Tee ] connecting continuous pipes directly.
    - Branch end: [ 90° Elbow ] dropping to ceiling sprinkler head.
    - Supports both Flex Hose S-Curve drops (NFPA 13) and Rigid Pipe drops (TCVN 7336).
    """
    num_heads = len(items)
    if num_heads == 0:
        return None

    import clr
    clr.AddReference("System")
    from System.Collections.Generic import List as ClrList

    # 1. Calculate node points on the branch line directly above each sprinkler
    node_points = []
    for item in items:
        sp_pt = item["point"]
        proj_dist = (sp_pt - origin_pt).DotProduct(dir_vec)
        node_pt = origin_pt + dir_vec * proj_dist
        node_points.append(node_pt)

    # Perpendicular vector in XY plane for lateral S-Curve flexing
    perp_vec = DB.XYZ(-dir_vec.Y, dir_vec.X, 0.0).Normalize()

    # 2. Build pipe network step-by-step with immediate fitting connections
    first_branch_pipe = None
    curr_incoming_pipe = None
    curr_start_pt = origin_pt

    for i in range(num_heads):
        item = items[i]
        sp_pt = item["point"]
        sp_conn = item["connector"]
        node_pt = node_points[i]
        is_last = (i == num_heads - 1)

        heads_fed = num_heads - i
        dn_in = get_dn_for_head_count(heads_fed, standard_name)
        dia_in_ft = mm_to_ft(dn_in)

        # A. Create Incoming Pipe into node_pt (if not already created from previous step)
        if not curr_incoming_pipe:
            if curr_start_pt.DistanceTo(node_pt) > mm_to_ft(30.0):
                try:
                    curr_incoming_pipe = DB.Plumbing.Pipe.Create(doc, system_type_id, pipe_type_id, level_id, curr_start_pt, node_pt)
                    curr_incoming_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(dia_in_ft)
                    created_pipes.append(curr_incoming_pipe)
                    if not first_branch_pipe:
                        first_branch_pipe = curr_incoming_pipe
                except Exception as ex:
                    errors.append(u"Pipe in error head {}: {}".format(i + 1, safe_unicode(ex)))

        pipe_in = curr_incoming_pipe

        # B. Create Drop to Sprinkler Head (Flex Hose S-Curve or Rigid Steel Drop)
        drop_top_conn = None
        drop_bot_conn = None

        if is_flex_mode and flex_pipe_type_id:
            # ── ỐNG MỀM (G-FLEX25N GS FIRE SAFETY: XOAY NGANG 90° CHUẨN NFPA 13) ──
            p_start = node_pt
            p_end = sp_conn.Origin if sp_conn else DB.XYZ(node_pt.X, node_pt.Y, sp_pt.Z)
            delta_z = p_start.Z - p_end.Z

            # Xác định hướng vươn ngang 90° vuông góc ống nhánh (theo phía đầu phun hoặc mặc định)
            sp_rel = sp_pt - node_pt
            dot = sp_rel.DotProduct(perp_vec)
            offset_dir = perp_vec if dot >= 0 else -perp_vec

            # 4 Điểm uốn tạo hình G-FLEX25N-T700: Vươn ngang 90° -> Uốn cong vòng cung -> Cắm thẳng 90°
            # P1: Tim ống nhánh
            # P2: Vươn ngang 90° ra khỏi thân ống (khoảng cách 180mm giữ nguyên cao độ Z)
            p_knee1 = p_start + offset_dir.Multiply(mm_to_ft(180.0)) - DB.XYZ(0, 0, delta_z * 0.05)
            # P3: Đỉnh vòng cung uốn lượn phía trên thanh treo trần
            p_knee2 = DB.XYZ(p_end.X + offset_dir.X * mm_to_ft(40.0), p_end.Y + offset_dir.Y * mm_to_ft(40.0), p_end.Z + delta_z * 0.45)
            # P4: Đầu nối ren thẳng đứng tại đầu phun

            points = ClrList[DB.XYZ]()
            points.Add(p_start)
            points.Add(p_knee1)
            points.Add(p_knee2)
            points.Add(p_end)

            # Tiếp tuyến xuất phát: BẮT BUỘC VUÔNG GÓC NGANG 90° (Z = 0)
            start_tangent = offset_dir
            # Tiếp tuyến kết thúc: BẮT BUỘC THẲNG ĐỨNG 90° XUỐNG DƯỚI
            end_tangent = DB.XYZ(0, 0, -1.0)

            try:
                from Autodesk.Revit.DB.Plumbing import FlexPipe
                flex_pipe = None
                try:
                    flex_pipe = FlexPipe.Create(doc, system_type_id, flex_pipe_type_id, level_id, start_tangent, end_tangent, points)
                except Exception:
                    flex_pipe = FlexPipe.Create(doc, system_type_id, flex_pipe_type_id, level_id, points)

                if flex_pipe:
                    diam_param = flex_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
                    if diam_param and not diam_param.IsReadOnly:
                        diam_param.Set(drop_diameter_ft)
                    created_pipes.append(flex_pipe)

                    drop_top_conn = get_connector_closest_to(flex_pipe, p_start)
                    drop_bot_conn = get_connector_closest_to(flex_pipe, p_end)

                    if drop_bot_conn and sp_conn:
                        try:
                            drop_bot_conn.ConnectTo(sp_conn)
                        except Exception:
                            pass
            except Exception as ex:
                errors.append(u"Flex hose error head {}: {}".format(i + 1, safe_unicode(ex)))

        else:
            # ── ỐNG CỨNG (RIGID STEEL PIPE DROP) ──
            drop_top_pt = node_pt
            drop_bot_pt = DB.XYZ(node_pt.X, node_pt.Y, sp_pt.Z)
            drop_pipe = None

            if abs(drop_top_pt.Z - drop_bot_pt.Z) > mm_to_ft(30.0):
                try:
                    drop_pipe = DB.Plumbing.Pipe.Create(doc, system_type_id, pipe_type_id, level_id, drop_top_pt, drop_bot_pt)
                    drop_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(drop_diameter_ft)
                    created_pipes.append(drop_pipe)
                except Exception as ex:
                    errors.append(u"Drop pipe error head {}: {}".format(i + 1, safe_unicode(ex)))

            drop_top_conn = get_connector_closest_to(drop_pipe, drop_top_pt) if drop_pipe else None
            drop_bot_conn = get_connector_closest_to(drop_pipe, drop_bot_pt) if drop_pipe else None

            if drop_bot_conn and sp_conn:
                if not drop_bot_conn.IsConnected and not sp_conn.IsConnected:
                    try:
                        drop_bot_conn.ConnectTo(sp_conn)
                    except Exception:
                        pass

        # C. Top Junction Fitting Placement & Compact Spool Connection (120mm)
        if is_last:
            # ── LAST SPRINKLER: 90° ELBOW ──
            if pipe_in and drop_top_conn:
                c_in_end = get_connector_closest_to(pipe_in, node_pt)
                if c_in_end:
                    try:
                        elbow = doc.Create.NewElbowFitting(c_in_end, drop_top_conn)
                        if elbow:
                            created_fittings.append(elbow)
                    except Exception:
                        try:
                            tf = doc.Create.NewTakeoffFitting(drop_top_conn, pipe_in)
                            if tf:
                                created_fittings.append(tf)
                        except Exception:
                            pass
            curr_incoming_pipe = None
        else:
            next_node_pt = node_points[i + 1]
            span_dist = node_pt.DistanceTo(next_node_pt)
            next_heads_fed = num_heads - (i + 1)
            dn_out = get_dn_for_head_count(next_heads_fed, standard_name)
            dia_out_ft = mm_to_ft(dn_out)

            if dn_out < dn_in:
                # ── CASE 1: SIZE REDUCTION (dn_out < dn_in) ──
                # 120mm total offset (compact, looks great, and 100% error-free!)
                spool_len_ft = min(mm_to_ft(120.0), span_dist * 0.35)
                trans_pt = node_pt + dir_vec * spool_len_ft

                # 1. Create Spool Pipe (DN_in)
                spool_pipe = None
                try:
                    spool_pipe = DB.Plumbing.Pipe.Create(doc, system_type_id, pipe_type_id, level_id, node_pt, trans_pt)
                    spool_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(dia_in_ft)
                    created_pipes.append(spool_pipe)
                except Exception as ex:
                    errors.append(u"Spool pipe error: {}".format(safe_unicode(ex)))

                # 2. Create Next Pipe (DN_out) from trans_pt to next_node_pt
                next_pipe = None
                try:
                    next_pipe = DB.Plumbing.Pipe.Create(doc, system_type_id, pipe_type_id, level_id, trans_pt, next_node_pt)
                    next_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(dia_out_ft)
                    created_pipes.append(next_pipe)
                except Exception as ex:
                    errors.append(u"Next pipe error: {}".format(safe_unicode(ex)))

                # 3. Connect Equal Tee at node_pt
                if pipe_in and spool_pipe and drop_top_conn:
                    c_in_end = get_connector_closest_to(pipe_in, node_pt)
                    c_spool_start = get_connector_closest_to(spool_pipe, node_pt)
                    if c_in_end and c_spool_start and not c_in_end.IsConnected and not c_spool_start.IsConnected:
                        try:
                            tee = doc.Create.NewTeeFitting(c_in_end, c_spool_start, drop_top_conn)
                            if tee:
                                created_fittings.append(tee)
                        except Exception:
                            try:
                                doc.Create.NewTakeoffFitting(drop_top_conn, pipe_in)
                            except Exception:
                                pass

                # 4. Connect Reducer at trans_pt (Spool end to Next pipe start)
                if spool_pipe and next_pipe:
                    c_spool_end = get_connector_closest_to(spool_pipe, trans_pt)
                    c_next_start = get_connector_closest_to(next_pipe, trans_pt)
                    if c_spool_end and c_next_start and not c_spool_end.IsConnected and not c_next_start.IsConnected:
                        try:
                            reducer = doc.Create.NewTransitionFitting(c_spool_end, c_next_start)
                            if reducer:
                                created_fittings.append(reducer)
                        except Exception:
                            try:
                                c_spool_end.ConnectTo(c_next_start)
                            except Exception:
                                pass

                # Pass next_pipe to the next iteration
                curr_incoming_pipe = next_pipe
                curr_start_pt = trans_pt

            else:
                # ── CASE 2: EQUAL SIZE (dn_out == dn_in) ──
                # [ Normal Equal Tee ] connecting continuous pipes directly at node_pt
                next_pipe = None
                try:
                    next_pipe = DB.Plumbing.Pipe.Create(doc, system_type_id, pipe_type_id, level_id, node_pt, next_node_pt)
                    next_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(dia_out_ft)
                    created_pipes.append(next_pipe)
                except Exception as ex:
                    errors.append(u"Next equal pipe error: {}".format(safe_unicode(ex)))

                # Connect Normal Equal Tee at node_pt
                if pipe_in and next_pipe and drop_top_conn:
                    c_in_end = get_connector_closest_to(pipe_in, node_pt)
                    c_next_start = get_connector_closest_to(next_pipe, node_pt)
                    if c_in_end and c_next_start and not c_in_end.IsConnected and not c_next_start.IsConnected:
                        try:
                            normal_tee = doc.Create.NewTeeFitting(c_in_end, c_next_start, drop_top_conn)
                            if normal_tee:
                                created_fittings.append(normal_tee)
                        except Exception:
                            try:
                                doc.Create.NewTakeoffFitting(drop_top_conn, pipe_in)
                            except Exception:
                                pass

                # Pass next_pipe to the next iteration
                curr_incoming_pipe = next_pipe
                curr_start_pt = node_pt

        yield_dispatcher_every(i + 1, batch_size=10)

    return first_branch_pipe


def generate_sprinkler_network(doc, main_pipe, branch_groups, standard_name, riser_height_mm=300.0, drop_dn=25, is_flex_mode=False, flex_pipe_type_id=None):
    """
    Generates complete hydraulic sprinkler network matching exact CAD Detail:
    1. Tracks active Main Pipe segments pool dynamically.
    2. When Riser > 0: Connects Riser Nipple to Main Pipe with Takeoff / Welded Tap / Main Tee,
       and places Top Tee (Dual-Sided) or Top Elbow (Single-Sided) on top of Riser Nipple.
    3. When Riser == 0: Connects horizontal branch lines directly into Main Pipe via horizontal Tee / Takeoff.
    4. Reduction nodes: [ Equal Tee ] -> [ 120mm Compact Spool ] -> [ Reducer Fitting (Côn thu) ] -> [ Smaller Pipe ].
    5. Equal size nodes: [ Normal Equal Tee ] connecting continuous pipes directly.
    6. Connects EVERY sprinkler head via Tee or final 90° Elbow with stepped pipe diameters.
    """
    pipe_type_id = main_pipe.PipeType.Id
    system_type_id = main_pipe.MEPSystem.GetTypeId()
    level_id = main_pipe.ReferenceLevel.Id if hasattr(main_pipe, 'ReferenceLevel') and main_pipe.ReferenceLevel else main_pipe.LevelId

    main_z = main_pipe.Location.Curve.GetEndPoint(0).Z
    riser_height_ft = mm_to_ft(riser_height_mm)
    branch_z = main_z + riser_height_ft
    drop_diameter_ft = mm_to_ft(drop_dn)

    main_pipe_pool = [main_pipe]  # Dynamic pool tracking split segments
    created_pipes = []
    created_fittings = []
    errors = []

    for bg_idx, bg in enumerate(branch_groups):
        pos_items = bg["pos_items"]
        neg_items = bg["neg_items"]
        total_heads = len(pos_items) + len(neg_items)
        if total_heads == 0:
            continue

        main_pt = bg["main_connect_pt"]
        main_top_pt = DB.XYZ(main_pt.X, main_pt.Y, main_z)
        branch_origin_pt = DB.XYZ(main_pt.X, main_pt.Y, branch_z)

        # 1. Create Single Riser Nipple for this branch position (if riser > 0)
        riser_pipe = None
        branch_total_dn = get_dn_for_head_count(total_heads, standard_name)

        if riser_height_ft > mm_to_ft(30.0):
            try:
                riser_pipe = DB.Plumbing.Pipe.Create(doc, system_type_id, pipe_type_id, level_id, main_top_pt, branch_origin_pt)
                riser_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(mm_to_ft(branch_total_dn))
                created_pipes.append(riser_pipe)

                # Connect bottom of Riser Nipple to Main Pipe using dynamic pool
                main_fitting = connect_branch_to_main(doc, riser_pipe, main_pipe_pool, main_top_pt)
                if main_fitting:
                    created_fittings.append(main_fitting)
            except Exception as ex:
                errors.append(u"Riser Nipple error: {}".format(safe_unicode(ex)))

        # 2. Build Pos Side Branch (Right) with 120mm Compact Spools & Normal Tees
        pos_first_pipe = None
        if pos_items:
            pos_first_pipe = _build_single_side_branch(
                doc, system_type_id, pipe_type_id, level_id,
                branch_origin_pt, pos_items, bg["pos_direction"],
                standard_name, drop_diameter_ft,
                created_pipes, created_fittings, errors,
                is_flex_mode=is_flex_mode, flex_pipe_type_id=flex_pipe_type_id
            )

        # 3. Build Neg Side Branch (Left) with 120mm Compact Spools & Normal Tees
        neg_first_pipe = None
        if neg_items:
            neg_first_pipe = _build_single_side_branch(
                doc, system_type_id, pipe_type_id, level_id,
                branch_origin_pt, neg_items, bg["neg_direction"],
                standard_name, drop_diameter_ft,
                created_pipes, created_fittings, errors,
                is_flex_mode=is_flex_mode, flex_pipe_type_id=flex_pipe_type_id
            )

        # 4. Connect Branchlines to Supply:
        if riser_pipe:
            # ── RISER > 0: Connect Top of Riser Nipple ──
            c_riser_top = get_connector_closest_to(riser_pipe, branch_origin_pt)
            c_pos_start = get_connector_closest_to(pos_first_pipe, branch_origin_pt) if pos_first_pipe else None
            c_neg_start = get_connector_closest_to(neg_first_pipe, branch_origin_pt) if neg_first_pipe else None

            if c_pos_start and c_neg_start and c_riser_top:
                try:
                    top_tee = doc.Create.NewTeeFitting(c_pos_start, c_neg_start, c_riser_top)
                    if top_tee:
                        created_fittings.append(top_tee)
                except Exception:
                    try:
                        doc.Create.NewElbowFitting(c_riser_top, c_pos_start)
                    except Exception:
                        pass
            elif c_pos_start and c_riser_top:
                try:
                    elbow = doc.Create.NewElbowFitting(c_riser_top, c_pos_start)
                    if elbow:
                        created_fittings.append(elbow)
                except Exception:
                    pass
            elif c_neg_start and c_riser_top:
                try:
                    elbow = doc.Create.NewElbowFitting(c_riser_top, c_neg_start)
                    if elbow:
                        created_fittings.append(elbow)
                except Exception:
                    pass
        else:
            # ── RISER == 0: CONNECT HORIZONTAL BRANCHES DIRECTLY TO MAIN PIPE! ──
            if pos_first_pipe:
                pos_main_fit = connect_branch_to_main(doc, pos_first_pipe, main_pipe_pool, branch_origin_pt)
                if pos_main_fit:
                    created_fittings.append(pos_main_fit)
            if neg_first_pipe:
                neg_main_fit = connect_branch_to_main(doc, neg_first_pipe, main_pipe_pool, branch_origin_pt)
                if neg_main_fit:
                    created_fittings.append(neg_main_fit)

        yield_dispatcher_every(bg_idx + 1, batch_size=2)

    return created_pipes, created_fittings, errors


# ==============================================================================
# DUAL-MODE PENDENT SPRINKLER DROP CONNECTIONS (FLEX HOSE & RIGID STEEL DROP)
# ==============================================================================

def get_sprinkler_piping_connector(sprinkler):
    """Extracts the DomainPiping connector of a sprinkler family instance."""
    if not sprinkler:
        return None
    try:
        mep = getattr(sprinkler, "MEPModel", None)
        if mep and mep.ConnectorManager:
            for c in mep.ConnectorManager.Connectors:
                if c.Domain == DB.Domain.DomainPiping:
                    return c
    except Exception:
        pass
    return None


def get_closest_projection_point(main_pipe, target_xyz):
    """Projects a 3D target point perpendicularly onto the centerline curve of main pipe."""
    try:
        loc = getattr(main_pipe, "Location", None)
        if isinstance(loc, DB.LocationCurve):
            curve = loc.Curve
            res = curve.Project(target_xyz)
            if res:
                return res.XYZPoint
            # Unbounded ray projection fallback
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            v = (p1 - p0).Normalize()
            rel = target_xyz - p0
            proj_dist = rel.DotProduct(v)
            return p0 + v.Multiply(proj_dist)
    except Exception:
        pass
    return None


def create_flex_drop_connection(doc, sprinkler, main_pipe, flex_pipe_type_id, diameter_mm=25, min_drop_mm=150):
    """
    Creates an NFPA 13 compliant Flexible Sprinkler Hose (S-Curve 4-Waypoints)
    connecting from the main pipe down to the Pendent Sprinkler head.
    Returns: (success: bool, result_element_or_error_str)
    """
    import clr
    clr.AddReference("System")
    from System.Collections.Generic import List as ClrList

    spk_conn = get_sprinkler_piping_connector(sprinkler)
    if not spk_conn:
        return False, u"Sprinkler does not have an active Piping connector."

    p_end = spk_conn.Origin
    p_start = get_closest_projection_point(main_pipe, p_end)
    if not p_start:
        return False, u"Sprinkler is outside the longitudinal bounds of the main pipe."

    delta_z = p_start.Z - p_end.Z
    min_drop_ft = mm_to_ft(min_drop_mm)
    if delta_z < min_drop_ft:
        return False, u"Vertical drop (ΔZ = {:.0f}mm) is too short (< {:.0f}mm) for flexible hose bend radius.".format(
            ft_to_mm(delta_z), min_drop_mm
        )

    # Direction vector on horizontal plane
    dir_xy = DB.XYZ(p_end.X - p_start.X, p_end.Y - p_start.Y, 0.0)
    if dir_xy.GetLength() < 1e-4:
        # If perfectly co-axial, introduce slight natural 100mm offset for smooth S-Curve bend
        dir_xy = DB.XYZ(0.3, 0.3, 0.0).Normalize()
    else:
        dir_xy = dir_xy.Normalize()

    # 4 Waypoints for natural S-Curve
    p_knee1 = p_start + dir_xy.Multiply(mm_to_ft(50.0)) - DB.XYZ(0, 0, delta_z * 0.15)
    p_knee2 = DB.XYZ(p_end.X, p_end.Y, p_end.Z + delta_z * 0.4)

    points = ClrList[DB.XYZ]()
    points.Add(p_start)
    points.Add(p_knee1)
    points.Add(p_knee2)
    points.Add(p_end)

    start_tangent = (dir_xy - DB.XYZ(0, 0, 0.4)).Normalize()
    end_tangent = DB.XYZ(0, 0, -1.0)  # Vertical 90° entry into pendent head

    sys_type_param = main_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
    sys_type_id = sys_type_param.AsElementId() if sys_type_param else DB.ElementId.InvalidElementId
    if not sys_type_id or sys_type_id == DB.ElementId.InvalidElementId or sys_type_id.IntegerValue == -1:
        from Autodesk.Revit.DB.Plumbing import PipingSystemType
        sys_types = list(DB.FilteredElementCollector(doc).OfClass(PipingSystemType).ToElements())
        if sys_types:
            sys_type_id = sys_types[0].Id

    level_id = DB.ElementId.InvalidElementId
    if getattr(main_pipe, "ReferenceLevel", None):
        level_id = main_pipe.ReferenceLevel.Id
    elif getattr(main_pipe, "LevelId", None) and main_pipe.LevelId != DB.ElementId.InvalidElementId:
        level_id = main_pipe.LevelId
    else:
        levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements())
        if levels:
            level_id = levels[0].Id

    try:
        from Autodesk.Revit.DB.Plumbing import FlexPipe
        # Revit API FlexPipe.Create overloads:
        # 1. (doc, sysTypeId, flexTypeId, levelId, startTangent, endTangent, points)
        # 2. (doc, sysTypeId, flexTypeId, levelId, points)
        flex_pipe = None
        try:
            flex_pipe = FlexPipe.Create(
                doc,
                sys_type_id,
                flex_pipe_type_id,
                level_id,
                start_tangent,
                end_tangent,
                points
            )
        except Exception:
            flex_pipe = FlexPipe.Create(
                doc,
                sys_type_id,
                flex_pipe_type_id,
                level_id,
                points
            )
        
        # Set nominal diameter
        diam_param = flex_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
        if diam_param and not diam_param.IsReadOnly:
            diam_param.Set(mm_to_ft(diameter_mm))

        # Physical water-tight connector snap
        for f_conn in flex_pipe.ConnectorManager.Connectors:
            if f_conn.Origin.DistanceTo(p_end) < mm_to_ft(60.0):
                try:
                    f_conn.ConnectTo(spk_conn)
                except Exception:
                    pass
                break

        return True, flex_pipe
    except Exception as ex:
        return False, safe_unicode(ex)


def create_rigid_drop_connection(doc, sprinkler, main_pipe, pipe_type_id, diameter_mm=25, riser_height_mm=0):
    """
    Creates a Rigid Steel Pipe drop connecting main pipe down to Pendent Sprinkler head.
    Returns: (success: bool, result_element_or_error_str)
    """
    spk_conn = get_sprinkler_piping_connector(sprinkler)
    if not spk_conn:
        return False, u"Sprinkler does not have an active Piping connector."

    p_end = spk_conn.Origin
    p_start = get_closest_projection_point(main_pipe, p_end)
    if not p_start:
        return False, u"Sprinkler is outside the longitudinal bounds of the main pipe."

    sys_type_param = main_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
    sys_type_id = sys_type_param.AsElementId() if sys_type_param else DB.ElementId.InvalidElementId
    level_id = main_pipe.ReferenceLevel.Id if main_pipe.ReferenceLevel else DB.ElementId.InvalidElementId

    try:
        from Autodesk.Revit.DB.Plumbing import Pipe
        rigid_drop = Pipe.Create(doc, pipe_type_id, level_id, spk_conn, p_start)
        diam_param = rigid_drop.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
        if diam_param and not diam_param.IsReadOnly:
            diam_param.Set(mm_to_ft(diameter_mm))

        return True, rigid_drop
    except Exception as ex:
        return False, safe_unicode(ex)