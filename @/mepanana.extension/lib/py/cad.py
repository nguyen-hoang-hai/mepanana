# -*- coding: utf-8 -*-
"""
CAD Block extraction for mepanana.
Uses MepananaCSharp.CadExtractor.dll (compiled separately from CadExtractor.cs).
"""
import os

_loaded = False
_Extractor = None

def _ensure_loaded():
    global _loaded, _Extractor
    if _loaded:
        return True
    try:
        import clr
        lib_path = os.path.dirname(__file__)
        clr.AddReferenceToFileAndPath(os.path.join(lib_path, "CadExtractor.dll"))
        from MepananaCSharp import Extractor
        _Extractor = Extractor
        _loaded = True
        return True
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
        return [], "CAD extraction failed: {}".format(ex)
