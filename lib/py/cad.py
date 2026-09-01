# -*- coding: utf-8 -*-
"""
CAD Block extraction for mepanana.
Uses MepananaCSharp.CadExtractor.dll (compiled separately from CadExtractor.cs).
"""
import os

_loaded = False
_Extractor = None

def _find_dll(dll_name):
    lib_path = os.path.dirname(__file__)
    try:
        from py.core import is_net_core
        if is_net_core():
            p = os.path.join(lib_path, "bin", "net8.0-windows", dll_name)
            if os.path.exists(p):
                return p
    except Exception:
        pass
    p48 = os.path.join(lib_path, "bin", "net48", dll_name)
    if os.path.exists(p48):
        return p48
    p_root = os.path.join(lib_path, dll_name)
    if os.path.exists(p_root):
        return p_root
    return None

def _ensure_loaded():
    global _loaded, _Extractor
    if _loaded:
        return True
    try:
        import clr
        dll_file = _find_dll("CadExtractor.dll")
        if dll_file and os.path.exists(dll_file):
            clr.AddReferenceToFileAndPath(dll_file)
            from MepananaCSharp import Extractor
            _Extractor = Extractor
            _loaded = True
            return True
        return False
    except Exception as e:
        print("CadExtractor.dll load error: {}".format(e))
        return False


def extract_cad_blocks(cad_instance, doc=None):
    """
    Extracts block positions, rotations, and layers from a CAD ImportInstance.
    Returns: (list[BlockData], error_string or None)
    """
    if not _ensure_loaded():
        return [], "Cannot load CadExtractor.dll."

    if doc is None:
        from py.core import get_doc
        doc = get_doc()

    try:
        cs_blocks = _Extractor.ExtractBlocks(doc, cad_instance)
        return list(cs_blocks), None
    except Exception as ex:
        from py.core import safe_unicode
        return [], u"CAD extraction failed: {}".format(safe_unicode(ex))
