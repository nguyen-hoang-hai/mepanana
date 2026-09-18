# -*- coding: utf-8 -*-
"""
bloom_engine.py - Automated MEP Stub-out & Connector Blooming Engine for MEPANANA
Generates pipe, duct, and conduit stubs from open connectors on fittings, accessories,
and equipment to enable instantaneous 3D routing and Trim/Extend connections.

Part of mepanana.extension.
Author: Hai Nguyen
"""
import os
import sys
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
    FamilyInstance
)

try:
    from Autodesk.Revit.DB.Plumbing import Pipe, PipeType
    HAS_PIPE = True
except Exception:
    HAS_PIPE = False

try:
    from Autodesk.Revit.DB.Plumbing import PipeSystemType
except Exception:
    try:
        from Autodesk.Revit.DB import PipeSystemType
    except Exception:
        PipeSystemType = None

try:
    from Autodesk.Revit.DB.Mechanical import Duct, DuctType
    HAS_DUCT = True
except Exception:
    HAS_DUCT = False

try:
    from Autodesk.Revit.DB.Mechanical import DuctShape
except Exception:
    try:
        from Autodesk.Revit.DB import DuctShape
    except Exception:
        DuctShape = None

try:
    from Autodesk.Revit.DB.Mechanical import DuctSystemType
except Exception:
    try:
        from Autodesk.Revit.DB import DuctSystemType
    except Exception:
        DuctSystemType = None

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

CONFIG_FILE = os.path.join(os.environ.get("APPDATA", ""), "pyRevit", "mepanana_bloom_config.json")


class BloomConfig(object):
    """Stores user configuration for Bloom stub generation."""
    def __init__(self):
        self.stub_length_mm = 300.0
        self.include_pipes = True
        self.include_ducts = True
        self.include_cable_trays = True
        self.include_conduits = True
        self.auto_connect = True
        self.load()

    def load(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    self.stub_length_mm = float(data.get("stub_length_mm", 300.0))
                    self.include_pipes = bool(data.get("include_pipes", True))
                    self.include_ducts = bool(data.get("include_ducts", True))
                    self.include_cable_trays = bool(data.get("include_cable_trays", True))
                    self.include_conduits = bool(data.get("include_conduits", True))
                    self.auto_connect = bool(data.get("auto_connect", True))
        except Exception:
            pass

    def save(self):
        try:
            folder = os.path.dirname(CONFIG_FILE)
            if not os.path.exists(folder):
                os.makedirs(folder)
            data = {
                "stub_length_mm": self.stub_length_mm,
                "include_pipes": self.include_pipes,
                "include_ducts": self.include_ducts,
                "include_cable_trays": self.include_cable_trays,
                "include_conduits": self.include_conduits,
                "auto_connect": self.auto_connect,
            }
            with open(CONFIG_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


class MEPBloomSelectionFilter(ISelectionFilter):
    """Selection filter that only permits picking elements with MEP connectors."""
    def AllowElement(self, elem):
        if not elem:
            return False
        if hasattr(elem, "MEPModel") and elem.MEPModel and elem.MEPModel.ConnectorManager:
            return True
        if hasattr(elem, "ConnectorManager") and elem.ConnectorManager:
            return True
        return False

    def AllowReference(self, reference, position):
        return False


def get_connector_manager(elem):
    """Safely retrieves ConnectorManager from FamilyInstance or MEPCurve."""
    if not elem:
        return None
    try:
        if hasattr(elem, "MEPModel") and elem.MEPModel and elem.MEPModel.ConnectorManager:
            return elem.MEPModel.ConnectorManager
    except Exception:
        pass
    try:
        if hasattr(elem, "ConnectorManager") and elem.ConnectorManager:
            return elem.ConnectorManager
    except Exception:
        pass
    return None


def get_open_connectors(elem):
    """
    Returns list of open (unconnected) End connectors on the element.
    """
    conn_mgr = get_connector_manager(elem)
    if not conn_mgr:
        return []

    open_conns = []
    try:
        for c in conn_mgr.Connectors:
            try:
                # We only want physical end connectors that are open
                if not c.IsConnected and c.ConnectorType in (ConnectorType.End, ConnectorType.Curve):
                    open_conns.append(c)
            except Exception:
                pass
    except Exception:
        pass
    return open_conns


def _get_element_level_id(doc, elem, z_coord):
    """Finds valid level for element or falls back to nearest level by Z coordinate."""
    try:
        if hasattr(elem, "LevelId") and elem.LevelId and elem.LevelId != ElementId.InvalidElementId:
            return elem.LevelId
    except Exception:
        pass

    try:
        levels = list(FilteredElementCollector(doc).OfClass(Level))
        if levels:
            levels.sort(key=lambda l: abs(l.Elevation - z_coord))
            return levels[0].Id
    except Exception:
        pass
    return ElementId.InvalidElementId


def _find_adjacent_mep_info(elem, domain):
    """
    Inspects connected connectors on the same element or adjacent connected elements
    to inherit PipeType/DuctType/ConduitType, MEPSystemType, level, and dimensions.
    """
    info = {
        "type_id": None,
        "system_type_id": None,
        "level_id": None,
        "width": None,
        "height": None,
        "diameter": None
    }
    conn_mgr = get_connector_manager(elem)
    if not conn_mgr:
        return info

    visited = set()
    queue = [elem]

    depth = 0
    while queue and depth < 3:
        next_queue = []
        for current_elem in queue:
            c_mgr = get_connector_manager(current_elem)
            if not c_mgr:
                continue
            for c in c_mgr.Connectors:
                if not c.IsConnected or c.Domain != domain:
                    continue
                for ref_c in c.AllRefs:
                    owner = ref_c.Owner
                    if not owner or owner.Id == elem.Id or owner.Id in visited:
                        continue
                    visited.add(owner.Id)

                    # 1. Piping
                    if domain == Domain.DomainPiping and HAS_PIPE and isinstance(owner, Pipe):
                        info["type_id"] = owner.GetTypeId()
                        if owner.MEPSystem:
                            try:
                                info["system_type_id"] = owner.MEPSystem.GetTypeId()
                            except Exception:
                                pass
                        if hasattr(owner, "ReferenceLevel") and owner.ReferenceLevel:
                            info["level_id"] = owner.ReferenceLevel.Id
                        try:
                            p_diam = owner.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
                            if not p_diam or not p_diam.HasValue:
                                p_diam = owner.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
                            if p_diam and p_diam.HasValue:
                                info["diameter"] = p_diam.AsDouble()
                        except Exception:
                            pass
                        return info

                    # 2. HVAC Duct
                    elif domain == Domain.DomainHvac and HAS_DUCT and isinstance(owner, Duct):
                        info["type_id"] = owner.GetTypeId()
                        if owner.MEPSystem:
                            try:
                                info["system_type_id"] = owner.MEPSystem.GetTypeId()
                            except Exception:
                                pass
                        if hasattr(owner, "ReferenceLevel") and owner.ReferenceLevel:
                            info["level_id"] = owner.ReferenceLevel.Id
                        try:
                            p_w = owner.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
                            p_h = owner.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
                            p_d = owner.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
                            if p_w and p_w.HasValue:
                                info["width"] = p_w.AsDouble()
                            if p_h and p_h.HasValue:
                                info["height"] = p_h.AsDouble()
                            if p_d and p_d.HasValue:
                                info["diameter"] = p_d.AsDouble()
                        except Exception:
                            pass
                        return info

                    # 3. Cable Tray
                    elif HAS_CABLE_TRAY and domain == Domain.DomainCableTrayConduit and isinstance(owner, CableTray):
                        info["type_id"] = owner.GetTypeId()
                        if hasattr(owner, "ReferenceLevel") and owner.ReferenceLevel:
                            info["level_id"] = owner.ReferenceLevel.Id
                        elif hasattr(owner, "LevelId") and owner.LevelId != ElementId.InvalidElementId:
                            info["level_id"] = owner.LevelId
                        try:
                            p_w = owner.get_Parameter(BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM)
                            if not p_w or not p_w.HasValue:
                                p_w = owner.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
                            p_h = owner.get_Parameter(BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM)
                            if not p_h or not p_h.HasValue:
                                p_h = owner.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
                            if p_w and p_w.HasValue:
                                info["width"] = p_w.AsDouble()
                            if p_h and p_h.HasValue:
                                info["height"] = p_h.AsDouble()
                        except Exception:
                            pass
                        return info

                    # 4. Electrical Conduit
                    elif HAS_CONDUIT and domain == Domain.DomainCableTrayConduit and isinstance(owner, Conduit):
                        info["type_id"] = owner.GetTypeId()
                        if hasattr(owner, "ReferenceLevel") and owner.ReferenceLevel:
                            info["level_id"] = owner.ReferenceLevel.Id
                        elif hasattr(owner, "LevelId") and owner.LevelId != ElementId.InvalidElementId:
                            info["level_id"] = owner.LevelId
                        try:
                            p_d = owner.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
                            if p_d and p_d.HasValue:
                                info["diameter"] = p_d.AsDouble()
                        except Exception:
                            pass
                        return info

                    # If owner is another fitting / equipment, inspect its MEPModel and keep searching
                    next_queue.append(owner)
                    if hasattr(owner, "MEPModel") and owner.MEPModel and owner.MEPModel.MEPSystem:
                        try:
                            if not info["system_type_id"]:
                                info["system_type_id"] = owner.MEPModel.MEPSystem.GetTypeId()
                        except Exception:
                            pass

        queue = next_queue
        depth += 1

    return info


def _get_system_type_for_classification(doc, classification):
    """Finds MEPSystemType matching MEPSystemClassification."""
    try:
        for st in FilteredElementCollector(doc).OfClass(MEPSystemType):
            if st.SystemClassification == classification:
                return st.Id
    except Exception:
        pass
    return None


def _get_default_piping_system_type_id(doc):
    """Finds default piping system type in document."""
    try:
        for st in FilteredElementCollector(doc).OfClass(MEPSystemType):
            if st.SystemClassification in (
                MEPSystemClassification.SupplyHydronic,
                MEPSystemClassification.ReturnHydronic,
                MEPSystemClassification.DomesticColdWater,
                MEPSystemClassification.DomesticHotWater,
                MEPSystemClassification.Sanitary,
                MEPSystemClassification.FireProtectWet,
                MEPSystemClassification.OtherPiping
            ):
                return st.Id
    except Exception:
        pass
    try:
        first = FilteredElementCollector(doc).OfClass(MEPSystemType).FirstElement()
        if first:
            return first.Id
    except Exception:
        pass
    return None


def _get_piping_system_type_id_from_connector(doc, connector):
    """Determines appropriate piping MEPSystemType from connector."""
    if hasattr(connector, "MEPSystem") and connector.MEPSystem:
        try:
            return connector.MEPSystem.GetTypeId()
        except Exception:
            pass

    if hasattr(connector, "PipeSystemType") and PipeSystemType:
        try:
            pst = connector.PipeSystemType
            target_cls = None
            if pst == PipeSystemType.DomesticColdWater:
                target_cls = MEPSystemClassification.DomesticColdWater
            elif pst == PipeSystemType.DomesticHotWater:
                target_cls = MEPSystemClassification.DomesticHotWater
            elif pst == PipeSystemType.Sanitary:
                target_cls = MEPSystemClassification.Sanitary
            elif pst == PipeSystemType.FireProtectWet:
                target_cls = MEPSystemClassification.FireProtectWet
            elif pst == PipeSystemType.SupplyHydronic:
                target_cls = MEPSystemClassification.SupplyHydronic
            elif pst == PipeSystemType.ReturnHydronic:
                target_cls = MEPSystemClassification.ReturnHydronic
            elif pst == PipeSystemType.OtherPiping:
                target_cls = MEPSystemClassification.OtherPiping

            if target_cls:
                sys_id = _get_system_type_for_classification(doc, target_cls)
                if sys_id:
                    return sys_id
        except Exception:
            pass

    return _get_default_piping_system_type_id(doc)


def _get_default_pipe_type_id(doc):
    """Finds default PipeType in document."""
    try:
        pt = FilteredElementCollector(doc).OfClass(PipeType).FirstElement()
        if pt:
            return pt.Id
    except Exception:
        pass
    return None


def _get_default_duct_system_type_id(doc):
    """Finds default HVAC duct system type in document."""
    try:
        for st in FilteredElementCollector(doc).OfClass(MEPSystemType):
            if st.SystemClassification in (
                MEPSystemClassification.SupplyAir,
                MEPSystemClassification.ReturnAir,
                MEPSystemClassification.ExhaustAir,
                MEPSystemClassification.OtherAir
            ):
                return st.Id
    except Exception:
        pass
    try:
        first = FilteredElementCollector(doc).OfClass(MEPSystemType).FirstElement()
        if first:
            return first.Id
    except Exception:
        pass
    return None


def _get_duct_system_type_id_from_connector(doc, connector):
    """Determines appropriate duct MEPSystemType from connector."""
    if hasattr(connector, "MEPSystem") and connector.MEPSystem:
        try:
            return connector.MEPSystem.GetTypeId()
        except Exception:
            pass

    if hasattr(connector, "DuctSystemType") and DuctSystemType:
        try:
            dst = connector.DuctSystemType
            target_cls = None
            if dst == DuctSystemType.SupplyAir:
                target_cls = MEPSystemClassification.SupplyAir
            elif dst == DuctSystemType.ReturnAir:
                target_cls = MEPSystemClassification.ReturnAir
            elif dst == DuctSystemType.ExhaustAir:
                target_cls = MEPSystemClassification.ExhaustAir
            elif dst == DuctSystemType.OtherAir:
                target_cls = MEPSystemClassification.OtherAir

            if target_cls:
                sys_id = _get_system_type_for_classification(doc, target_cls)
                if sys_id:
                    return sys_id
        except Exception:
            pass

    return _get_default_duct_system_type_id(doc)


def _get_default_duct_type_id(doc, shape):
    """Finds appropriate DuctType in document matching shape (Round/Rectangular/Oval)."""
    if not HAS_DUCT:
        return None

    target_duct_shape = None
    if DuctShape:
        try:
            if shape == ConnectorProfileType.Round and hasattr(DuctShape, "Round"):
                target_duct_shape = DuctShape.Round
            elif shape == ConnectorProfileType.Rectangular and hasattr(DuctShape, "Rectangular"):
                target_duct_shape = DuctShape.Rectangular
            elif shape == ConnectorProfileType.Oval and hasattr(DuctShape, "Oval"):
                target_duct_shape = DuctShape.Oval
        except Exception:
            pass

    all_duct_types = list(FilteredElementCollector(doc).OfClass(DuctType))
    if not all_duct_types:
        return None

    # Pass 1: Direct Shape property match (Revit official enum)
    if target_duct_shape is not None:
        for dt in all_duct_types:
            try:
                if hasattr(dt, "Shape") and dt.Shape == target_duct_shape:
                    return dt.Id
            except Exception:
                pass

    # Pass 2: FamilyName match (e.g. "Rectangular Duct", "Round Duct", "Oval Duct")
    for dt in all_duct_types:
        try:
            fam_name = getattr(dt, "FamilyName", "") or ""
            fam_name_lower = fam_name.lower()
            if shape == ConnectorProfileType.Round and "round" in fam_name_lower:
                return dt.Id
            elif shape == ConnectorProfileType.Rectangular and ("rect" in fam_name_lower or "square" in fam_name_lower):
                return dt.Id
            elif shape == ConnectorProfileType.Oval and "oval" in fam_name_lower:
                return dt.Id
        except Exception:
            pass

    # Pass 3: Type Name keywords
    for dt in all_duct_types:
        try:
            name_p = dt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            dt_name = (name_p.AsString() if name_p else "").lower()
            if shape == ConnectorProfileType.Round and ("round" in dt_name or "tròn" in dt_name):
                return dt.Id
            elif shape == ConnectorProfileType.Rectangular and ("rect" in dt_name or "vuông" in dt_name or "chữ nhật" in dt_name or "mitered" in dt_name or "radius" in dt_name):
                return dt.Id
            elif shape == ConnectorProfileType.Oval and "oval" in dt_name:
                return dt.Id
        except Exception:
            pass

    # Pass 4: If rectangular requested, avoid picking a type with "round" in its name
    if shape == ConnectorProfileType.Rectangular:
        for dt in all_duct_types:
            try:
                fam_name = (getattr(dt, "FamilyName", "") or "").lower()
                name_p = dt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
                dt_name = (name_p.AsString() if name_p else "").lower()
                if "round" not in fam_name and "round" not in dt_name and "tròn" not in dt_name:
                    return dt.Id
            except Exception:
                pass

    # Fallback: first element
    return all_duct_types[0].Id


def _get_default_conduit_type_id(doc):
    """Finds default ConduitType in document."""
    if not HAS_CONDUIT:
        return None
    try:
        ct = FilteredElementCollector(doc).OfClass(ConduitType).FirstElement()
        if ct:
            return ct.Id
    except Exception:
        pass
    return None


def _get_default_cable_tray_type_id(doc):
    """Finds default CableTrayType in document."""
    if not HAS_CABLE_TRAY:
        return None
    try:
        ct = FilteredElementCollector(doc).OfClass(CableTrayType).FirstElement()
        if ct:
            return ct.Id
    except Exception:
        pass
    return None


def _is_cable_tray_target(elem, connector):
    """Distinguishes whether an element/connector belongs to Cable Tray vs Conduit."""
    try:
        cat = getattr(elem, "Category", None)
        if cat:
            cat_id = cat.Id.IntegerValue
            if cat_id in (int(BuiltInCategory.OST_CableTray), int(BuiltInCategory.OST_CableTrayFitting)):
                return True
            if cat_id in (int(BuiltInCategory.OST_Conduit), int(BuiltInCategory.OST_ConduitFitting)):
                return False
    except Exception:
        pass

    try:
        shape = getattr(connector, "Shape", None)
        if shape in (ConnectorProfileType.Rectangular, ConnectorProfileType.Oval):
            return True
        if shape == ConnectorProfileType.Round:
            return False
    except Exception:
        pass

    try:
        if hasattr(connector, "Width") and connector.Width > 0:
            return True
    except Exception:
        pass

    return False


def _bloom_pipe_connector(doc, elem, connector, stub_len_ft, auto_connect):
    """Creates a pipe stub from an open piping connector."""
    if not HAS_PIPE:
        return None
    p0 = connector.Origin
    try:
        dir_vec = connector.CoordinateSystem.BasisZ.Normalize()
    except Exception:
        return None
    p1 = p0 + dir_vec * stub_len_ft

    # 1. Inherit or detect system & pipe type
    adj_info = _find_adjacent_mep_info(elem, Domain.DomainPiping)
    pipe_type_id = adj_info.get("type_id") or _get_default_pipe_type_id(doc)
    system_type_id = adj_info.get("system_type_id")
    if not system_type_id:
        system_type_id = _get_piping_system_type_id_from_connector(doc, connector)

    level_id = adj_info.get("level_id") or _get_element_level_id(doc, elem, p0.Z)
    if not pipe_type_id or not system_type_id or level_id == ElementId.InvalidElementId:
        return None

    # 2. Create Pipe
    pipe = Pipe.Create(doc, system_type_id, pipe_type_id, level_id, p0, p1)
    if not pipe:
        return None

    # 3. Set Diameter matching connector
    try:
        diameter = None
        if getattr(connector, "Shape", ConnectorProfileType.Round) == ConnectorProfileType.Round:
            try:
                diameter = connector.Radius * 2.0
            except Exception:
                pass
        if not diameter and adj_info.get("diameter"):
            diameter = adj_info["diameter"]

        if diameter:
            p_diam = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
            if not p_diam or p_diam.IsReadOnly:
                p_diam = pipe.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
            if p_diam and not p_diam.IsReadOnly:
                p_diam.Set(diameter)
    except Exception:
        pass

    # Regenerate so pipe connector diameter updates before ConnectTo
    doc.Regenerate()

    # 4. Auto-connect
    if auto_connect and pipe.ConnectorManager:
        for p_conn in pipe.ConnectorManager.Connectors:
            if p_conn.Origin.DistanceTo(p0) < 0.05:
                try:
                    connector.ConnectTo(p_conn)
                except Exception:
                    pass
                break

    return pipe


def _bloom_duct_connector(doc, elem, connector, stub_len_ft, auto_connect):
    """Creates a duct stub from an open HVAC duct connector."""
    if not HAS_DUCT:
        return None
    p0 = connector.Origin
    try:
        dir_vec = connector.CoordinateSystem.BasisZ.Normalize()
    except Exception:
        return None
    p1 = p0 + dir_vec * stub_len_ft

    adj_info = _find_adjacent_mep_info(elem, Domain.DomainHvac)
    shape = getattr(connector, "Shape", ConnectorProfileType.Rectangular)

    duct_type_id = adj_info.get("type_id")
    # Verify duct_type_id matches shape if inherited
    if duct_type_id:
        try:
            dt = doc.GetElement(duct_type_id)
            if hasattr(dt, "Shape") and DuctShape:
                if shape == ConnectorProfileType.Round and dt.Shape != DuctShape.Round:
                    duct_type_id = None
                elif shape == ConnectorProfileType.Rectangular and dt.Shape != DuctShape.Rectangular:
                    duct_type_id = None
                elif shape == ConnectorProfileType.Oval and dt.Shape != DuctShape.Oval:
                    duct_type_id = None
        except Exception:
            pass

    if not duct_type_id:
        duct_type_id = _get_default_duct_type_id(doc, shape)

    system_type_id = adj_info.get("system_type_id")
    if not system_type_id:
        system_type_id = _get_duct_system_type_id_from_connector(doc, connector)

    level_id = adj_info.get("level_id") or _get_element_level_id(doc, elem, p0.Z)
    if not duct_type_id or not system_type_id or level_id == ElementId.InvalidElementId:
        return None

    duct = Duct.Create(doc, system_type_id, duct_type_id, level_id, p0, p1)
    if not duct:
        return None

    # Set dimensions matching connector
    try:
        if shape == ConnectorProfileType.Round:
            diameter = None
            try:
                diameter = connector.Radius * 2.0
            except Exception:
                pass
            if not diameter and adj_info.get("diameter"):
                diameter = adj_info["diameter"]

            if diameter:
                p_diam = duct.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
                if p_diam and not p_diam.IsReadOnly:
                    p_diam.Set(diameter)
        else:
            # Rectangular or Oval
            w = None
            h = None
            try:
                w = connector.Width
                h = connector.Height
            except Exception:
                pass

            if not w and adj_info.get("width"):
                w = adj_info["width"]
            if not h and adj_info.get("height"):
                h = adj_info["height"]

            if w and h:
                # Check connector orientation relative to Z axis
                try:
                    cs = connector.CoordinateSystem
                    # If BasisX is nearly vertical, then connector.Width is elevation height
                    if abs(cs.BasisX.Z) > 0.7 and abs(dir_vec.Z) < 0.7:
                        duct_w = h
                        duct_h = w
                    else:
                        duct_w = w
                        duct_h = h
                except Exception:
                    duct_w = w
                    duct_h = h

                p_w = duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
                p_h = duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
                if p_w and not p_w.IsReadOnly:
                    p_w.Set(duct_w)
                if p_h and not p_h.IsReadOnly:
                    p_h.Set(duct_h)
    except Exception:
        pass

    # Regenerate document to update duct connector sizes before ConnectTo
    doc.Regenerate()

    # Auto-connect
    if auto_connect and duct.ConnectorManager:
        for d_conn in duct.ConnectorManager.Connectors:
            if d_conn.Origin.DistanceTo(p0) < 0.05:
                try:
                    connector.ConnectTo(d_conn)
                except Exception:
                    pass
                break

    return duct


def _bloom_conduit_connector(doc, elem, connector, stub_len_ft, auto_connect):
    """Creates a conduit stub from an open electrical conduit connector."""
    if not HAS_CONDUIT:
        return None

    p0 = connector.Origin
    try:
        dir_vec = connector.CoordinateSystem.BasisZ.Normalize()
    except Exception:
        return None
    p1 = p0 + dir_vec * stub_len_ft

    adj_info = _find_adjacent_mep_info(elem, Domain.DomainCableTrayConduit)
    conduit_type_id = adj_info.get("type_id") or _get_default_conduit_type_id(doc)
    level_id = adj_info.get("level_id") or _get_element_level_id(doc, elem, p0.Z)
    if not conduit_type_id or level_id == ElementId.InvalidElementId:
        return None

    try:
        conduit = Conduit.Create(doc, conduit_type_id, p0, p1, level_id)
        if not conduit:
            return None

        # Set Diameter
        try:
            diameter = None
            if getattr(connector, "Shape", ConnectorProfileType.Round) == ConnectorProfileType.Round:
                try:
                    diameter = connector.Radius * 2.0
                except Exception:
                    pass
            if not diameter and adj_info.get("diameter"):
                diameter = adj_info["diameter"]

            if diameter:
                p_diam = conduit.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
                if p_diam and not p_diam.IsReadOnly:
                    p_diam.Set(diameter)
        except Exception:
            pass

        doc.Regenerate()

        if auto_connect and conduit.ConnectorManager:
            for c_conn in conduit.ConnectorManager.Connectors:
                if c_conn.Origin.DistanceTo(p0) < 0.05:
                    try:
                        connector.ConnectTo(c_conn)
                    except Exception:
                        pass
                    break

        return conduit
    except Exception:
        return None


def _bloom_cable_tray_connector(doc, elem, connector, stub_len_ft, auto_connect):
    """Creates a cable tray stub from an open cable tray connector."""
    if not HAS_CABLE_TRAY:
        return None

    p0 = connector.Origin
    try:
        dir_vec = connector.CoordinateSystem.BasisZ.Normalize()
    except Exception:
        return None
    p1 = p0 + dir_vec * stub_len_ft

    adj_info = _find_adjacent_mep_info(elem, Domain.DomainCableTrayConduit)
    cable_tray_type_id = adj_info.get("type_id") or _get_default_cable_tray_type_id(doc)
    level_id = adj_info.get("level_id") or _get_element_level_id(doc, elem, p0.Z)
    if not cable_tray_type_id or level_id == ElementId.InvalidElementId:
        return None

    try:
        cable_tray = CableTray.Create(doc, cable_tray_type_id, p0, p1, level_id)
        if not cable_tray:
            return None

        # Set Width and Height matching connector
        w = None
        h = None
        try:
            w = connector.Width
            h = connector.Height
        except Exception:
            pass

        if not w and adj_info.get("width"):
            w = adj_info["width"]
        if not h and adj_info.get("height"):
            h = adj_info["height"]

        if w and h:
            try:
                cs = connector.CoordinateSystem
                if abs(cs.BasisX.Z) > 0.7 and abs(dir_vec.Z) < 0.7:
                    ct_w = h
                    ct_h = w
                else:
                    ct_w = w
                    ct_h = h
            except Exception:
                ct_w = w
                ct_h = h

            p_w = cable_tray.get_Parameter(BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM)
            if not p_w or p_w.IsReadOnly:
                p_w = cable_tray.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
            if p_w and not p_w.IsReadOnly:
                try:
                    p_w.Set(ct_w)
                except Exception:
                    pass

            p_h = cable_tray.get_Parameter(BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM)
            if not p_h or p_h.IsReadOnly:
                p_h = cable_tray.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
            if p_h and not p_h.IsReadOnly:
                try:
                    p_h.Set(ct_h)
                except Exception:
                    pass

        doc.Regenerate()

        if auto_connect and cable_tray.ConnectorManager:
            for ct_conn in cable_tray.ConnectorManager.Connectors:
                if ct_conn.Origin.DistanceTo(p0) < 0.05:
                    try:
                        connector.ConnectTo(ct_conn)
                    except Exception:
                        pass
                    break

        return cable_tray
    except Exception:
        return None


def bloom_elements(doc, elements, config=None):
    """
    Executes Auto Bloom on the provided elements.
    Draws pipe/duct/cable tray/conduit stubs from all open connectors.

    Args:
        doc: Document instance
        elements: Iterable of Element or FamilyInstance objects
        config: BloomConfig instance (or None for defaults)

    Returns:
        dict: Summary metrics {
            'pipes': int,
            'ducts': int,
            'cable_trays': int,
            'conduits': int,
            'total': int,
            'elements_processed': int
        }
    """
    if not config:
        config = BloomConfig()

    stub_len_ft = mm_to_ft(config.stub_length_mm)
    if stub_len_ft <= 0.05:
        stub_len_ft = mm_to_ft(300.0)

    stats = {
        "pipes": 0,
        "ducts": 0,
        "cable_trays": 0,
        "conduits": 0,
        "total": 0,
        "elements_processed": 0
    }

    if not elements:
        return stats

    with SafeTransaction(doc, "MEPANANA Auto Bloom"):
        for elem in elements:
            if not elem:
                continue

            open_conns = get_open_connectors(elem)
            if not open_conns:
                continue

            elem_had_stubs = False
            for c in open_conns:
                created = None
                try:
                    if c.Domain == Domain.DomainPiping and config.include_pipes:
                        created = _bloom_pipe_connector(doc, elem, c, stub_len_ft, config.auto_connect)
                        if created:
                            stats["pipes"] += 1
                            elem_had_stubs = True

                    elif c.Domain == Domain.DomainHvac and config.include_ducts:
                        created = _bloom_duct_connector(doc, elem, c, stub_len_ft, config.auto_connect)
                        if created:
                            stats["ducts"] += 1
                            elem_had_stubs = True

                    elif c.Domain == Domain.DomainCableTrayConduit:
                        if _is_cable_tray_target(elem, c):
                            if config.include_cable_trays:
                                created = _bloom_cable_tray_connector(doc, elem, c, stub_len_ft, config.auto_connect)
                                if created:
                                    stats["cable_trays"] += 1
                                    elem_had_stubs = True
                        else:
                            if config.include_conduits:
                                created = _bloom_conduit_connector(doc, elem, c, stub_len_ft, config.auto_connect)
                                if created:
                                    stats["conduits"] += 1
                                    elem_had_stubs = True

                except Exception as ex_stub:
                    pass

            if elem_had_stubs:
                stats["elements_processed"] += 1

    stats["total"] = stats["pipes"] + stats["ducts"] + stats["cable_trays"] + stats["conduits"]
    return stats
