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
    Pipe,
    PipeType,
    Duct,
    DuctType,
    MEPSystemType,
    MEPSystemClassification,
    Connector,
    ConnectorType,
    ConnectorProfileType,
    Domain,
    FamilyInstance
)

try:
    from Autodesk.Revit.DB.Electrical import Conduit, ConduitType
    HAS_CONDUIT = True
except Exception:
    HAS_CONDUIT = False

from Autodesk.Revit.UI.Selection import ISelectionFilter

from py.core import SafeTransaction, safe_unicode, mm_to_ft, ft_to_mm, get_id_value

CONFIG_FILE = os.path.join(os.environ.get("APPDATA", ""), "pyRevit", "mepanana_bloom_config.json")


class BloomConfig(object):
    """Stores user configuration for Bloom stub generation."""
    def __init__(self):
        self.stub_length_mm = 300.0
        self.include_pipes = True
        self.include_ducts = True
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
    Inspects connected connectors on the same element to inherit
    PipeType/DuctType/ConduitType and MEPSystemType.
    """
    info = {"type_id": None, "system_type_id": None, "level_id": None}
    conn_mgr = get_connector_manager(elem)
    if not conn_mgr:
        return info

    try:
        for c in conn_mgr.Connectors:
            if not c.IsConnected or c.Domain != domain:
                continue
            for ref_c in c.AllRefs:
                owner = ref_c.Owner
                if not owner or owner.Id == elem.Id:
                    continue
                if domain == Domain.DomainPiping and isinstance(owner, Pipe):
                    info["type_id"] = owner.PipeType.Id
                    if owner.MEPSystem:
                        info["system_type_id"] = owner.MEPSystem.GetTypeId()
                    if hasattr(owner, "ReferenceLevel") and owner.ReferenceLevel:
                        info["level_id"] = owner.ReferenceLevel.Id
                    return info
                elif domain == Domain.DomainHvac and isinstance(owner, Duct):
                    info["type_id"] = owner.DuctType.Id
                    if owner.MEPSystem:
                        info["system_type_id"] = owner.MEPSystem.GetTypeId()
                    if hasattr(owner, "ReferenceLevel") and owner.ReferenceLevel:
                        info["level_id"] = owner.ReferenceLevel.Id
                    return info
                elif HAS_CONDUIT and domain == Domain.DomainCableTrayConduit and isinstance(owner, Conduit):
                    info["type_id"] = owner.GetTypeId()
                    if hasattr(owner, "ReferenceLevel") and owner.ReferenceLevel:
                        info["level_id"] = owner.ReferenceLevel.Id
                    return info
    except Exception:
        pass
    return info


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


def _get_default_duct_type_id(doc, shape):
    """Finds appropriate DuctType in document matching shape (Round/Rectangular/Oval)."""
    try:
        for dt in FilteredElementCollector(doc).OfClass(DuctType):
            dt_name = dt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString().lower()
            if shape == ConnectorProfileType.Round and ("round" in dt_name or "tròn" in dt_name):
                return dt.Id
            elif shape == ConnectorProfileType.Rectangular and ("rect" in dt_name or "vuông" in dt_name or "chữ nhật" in dt_name):
                return dt.Id
            elif shape == ConnectorProfileType.Oval and "oval" in dt_name:
                return dt.Id
    except Exception:
        pass
    try:
        first = FilteredElementCollector(doc).OfClass(DuctType).FirstElement()
        if first:
            return first.Id
    except Exception:
        pass
    return None


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


def _bloom_pipe_connector(doc, elem, connector, stub_len_ft, auto_connect):
    """Creates a pipe stub from an open piping connector."""
    p0 = connector.Origin
    try:
        dir_vec = connector.CoordinateSystem.BasisZ.Normalize()
    except Exception:
        return None
    p1 = p0 + dir_vec * stub_len_ft

    # 1. Inherit or detect system & pipe type
    adj_info = _find_adjacent_mep_info(elem, Domain.DomainPiping)
    pipe_type_id = adj_info["type_id"] or _get_default_pipe_type_id(doc)
    system_type_id = adj_info["system_type_id"]
    if not system_type_id and connector.MEPSystem:
        try:
            system_type_id = connector.MEPSystem.GetTypeId()
        except Exception:
            pass
    if not system_type_id:
        system_type_id = _get_default_piping_system_type_id(doc)

    level_id = adj_info["level_id"] or _get_element_level_id(doc, elem, p0.Z)
    if not pipe_type_id or not system_type_id or level_id == ElementId.InvalidElementId:
        return None

    # 2. Create Pipe
    pipe = Pipe.Create(doc, system_type_id, pipe_type_id, level_id, p0, p1)
    if not pipe:
        return None

    # 3. Set Diameter matching connector
    try:
        diameter = connector.Radius * 2.0
        p_diam = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
        if not p_diam or p_diam.IsReadOnly:
            p_diam = pipe.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
        if p_diam and not p_diam.IsReadOnly:
            p_diam.Set(diameter)
    except Exception:
        pass

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
    p0 = connector.Origin
    try:
        dir_vec = connector.CoordinateSystem.BasisZ.Normalize()
    except Exception:
        return None
    p1 = p0 + dir_vec * stub_len_ft

    adj_info = _find_adjacent_mep_info(elem, Domain.DomainHvac)
    shape = getattr(connector, "Shape", ConnectorProfileType.Rectangular)
    duct_type_id = adj_info["type_id"] or _get_default_duct_type_id(doc, shape)
    system_type_id = adj_info["system_type_id"]
    if not system_type_id and connector.MEPSystem:
        try:
            system_type_id = connector.MEPSystem.GetTypeId()
        except Exception:
            pass
    if not system_type_id:
        system_type_id = _get_default_duct_system_type_id(doc)

    level_id = adj_info["level_id"] or _get_element_level_id(doc, elem, p0.Z)
    if not duct_type_id or not system_type_id or level_id == ElementId.InvalidElementId:
        return None

    duct = Duct.Create(doc, system_type_id, duct_type_id, level_id, p0, p1)
    if not duct:
        return None

    # Set dimensions
    try:
        if shape == ConnectorProfileType.Round:
            p_diam = duct.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
            if p_diam and not p_diam.IsReadOnly:
                p_diam.Set(connector.Radius * 2.0)
        else:
            p_w = duct.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
            p_h = duct.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
            if p_w and not p_w.IsReadOnly and hasattr(connector, "Width"):
                p_w.Set(connector.Width)
            if p_h and not p_h.IsReadOnly and hasattr(connector, "Height"):
                p_h.Set(connector.Height)
    except Exception:
        pass

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
    conduit_type_id = adj_info["type_id"] or _get_default_conduit_type_id(doc)
    level_id = adj_info["level_id"] or _get_element_level_id(doc, elem, p0.Z)
    if not conduit_type_id or level_id == ElementId.InvalidElementId:
        return None

    try:
        conduit = Conduit.Create(doc, conduit_type_id, p0, p1, level_id)
        if not conduit:
            return None

        # Set Diameter
        try:
            diameter = connector.Radius * 2.0
            p_diam = conduit.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
            if p_diam and not p_diam.IsReadOnly:
                p_diam.Set(diameter)
        except Exception:
            pass

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


def bloom_elements(doc, elements, config=None):
    """
    Executes Auto Bloom on the provided elements.
    Draws pipe/duct/conduit stubs from all open connectors.

    Args:
        doc: Document instance
        elements: Iterable of Element or FamilyInstance objects
        config: BloomConfig instance (or None for defaults)

    Returns:
        dict: Summary metrics {
            'pipes': int,
            'ducts': int,
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

                    elif c.Domain == Domain.DomainCableTrayConduit and config.include_conduits:
                        created = _bloom_conduit_connector(doc, elem, c, stub_len_ft, config.auto_connect)
                        if created:
                            stats["conduits"] += 1
                            elem_had_stubs = True

                except Exception as ex_stub:
                    pass

            if elem_had_stubs:
                stats["elements_processed"] += 1

    stats["total"] = stats["pipes"] + stats["ducts"] + stats["conduits"]
    return stats
