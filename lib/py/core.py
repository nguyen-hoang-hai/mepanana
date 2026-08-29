# -*- coding: utf-8 -*-
"""
core.py - Core Engine Utilities for mepanana.extension
Leverages pyRevit built-in modules (revit, DB, UI, script, forms).
"""
import os
import tempfile
import traceback
import logging
from Autodesk.Revit.DB import Transaction
from pyrevit import revit, DB, script

# ── Background Logger ──────────────────────────────────────────────────────────
try:
    logger = script.get_logger()
except Exception:
    log_file = os.path.join(tempfile.gettempdir(), "mepanana_errors.log")
    logging.basicConfig(
        filename=log_file,
        level=logging.ERROR,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger("mepanana")

def get_log_path():
    return os.path.join(tempfile.gettempdir(), "mepanana_errors.log")

def get_uidoc():
    """Returns the ActiveUIDocument using pyRevit built-in revit.uidoc"""
    return getattr(revit, 'uidoc', None) or (__revit__.ActiveUIDocument if '__revit__' in globals() else None)

def get_doc():
    """Returns the Active DB Document using pyRevit built-in revit.doc"""
    return getattr(revit, 'doc', None) or (__revit__.ActiveUIDocument.Document if '__revit__' in globals() else None)

def get_app():
    """Returns the Revit Application using pyRevit built-in revit.app"""
    return getattr(revit, 'app', None) or (__revit__.Application if '__revit__' in globals() else None)

def mm_to_ft(mm):
    """Converts millimeters to feet"""
    return mm / 304.8

def ft_to_mm(ft):
    """Converts feet to millimeters"""
    return ft * 304.8

def get_element_name(elem):
    """Safely gets the name of an element"""
    if not elem:
        return ""
    try:
        from Autodesk.Revit.DB import Element
        return Element.Name.GetValue(elem)
    except Exception:
        try:
            return elem.Name
        except Exception:
            return ""


class SafeTransaction(object):
    """
    Context Manager for Revit Transactions.
    Auto-commits on success, rolls back on exception and logs error.
    """
    def __init__(self, doc, name):
        self.doc = doc
        self.name = name
        self.t = Transaction(doc, name)

    def __enter__(self):
        self.t.Start()
        return self.t

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            error_msg = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
            logger.error("Transaction '{}' failed:\n{}".format(self.name, error_msg))
            if self.t.HasStarted() and not self.t.HasEnded():
                self.t.RollBack()
            try:
                from py.ui import show_error
                show_error(
                    "System error in '{}'.\nDetails saved to log:\n{}".format(self.name, get_log_path()),
                    "System Error"
                )
            except Exception:
                pass
            return True
        else:
            if self.t.HasStarted() and not self.t.HasEnded():
                self.t.Commit()
