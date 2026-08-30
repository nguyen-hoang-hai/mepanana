# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import Transaction
import traceback
import logging
import os
import tempfile

# ── Background Logger ──────────────────────────────────────────────────────────
log_file = os.path.join(tempfile.gettempdir(), "mepanana_errors.log")
logging.basicConfig(
    filename=log_file,
    level=logging.ERROR,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("mepanana")

def get_log_path():
    return log_file

def get_uidoc():
    """Returns the ActiveUIDocument"""
    return __revit__.ActiveUIDocument

def get_doc():
    """Returns the Active DB Document"""
    return __revit__.ActiveUIDocument.Document

def get_app():
    """Returns the Revit Application"""
    return __revit__.Application

def mm_to_ft(mm):
    """Converts millimeters to feet"""
    return mm / 304.8

def get_element_name(elem):
    """Safely gets the name of an element"""
    try:
        from Autodesk.Revit.DB import Element
        return Element.Name.GetValue(elem)
    except Exception:
        try:
            return elem.Name
        except:
            return ""


class SafeTransaction(object):
    """
    Context Manager for Revit Transactions.
    Auto-commits on success, rolls back on exception.
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
            except:
                pass
            return True
        else:
            if self.t.HasStarted() and not self.t.HasEnded():
                self.t.Commit()
