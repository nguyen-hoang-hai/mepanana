# -*- coding: utf-8 -*-
"""
core.py - Core Engine Utilities for mepanana.extension
Leverages pyRevit built-in modules (revit, DB, UI, script, forms).
"""
import os
import sys
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

def get_revit_year():
    """Returns the host Revit release year as integer (e.g. 2024, 2025, 2026)."""
    try:
        from pyrevit import HOST_APP
        return int(HOST_APP.version)
    except Exception:
        try:
            app = get_app()
            if app:
                return int(app.VersionNumber)
        except Exception:
            pass
    return 2024

def is_net_core():
    """Returns True if running under .NET 8 / .NET Core runtime (Revit 2025+)."""
    try:
        import System
        return System.Environment.Version.Major >= 8
    except Exception:
        return False

def safe_unicode(val):
    """
    Safely converts any value (string, exception, object) to Unicode without throwing UnicodeEncodeError.
    Fully compatible with IronPython 2.7, Python 3, and Vietnamese diacritics.
    """
    if val is None:
        return u""
    # Python 3
    if sys.version_info[0] >= 3:
        if isinstance(val, str):
            return val
        if isinstance(val, bytes):
            try:
                return val.decode("utf-8", "ignore")
            except Exception:
                return str(val)
        return str(val)

    # Python 2 / IronPython 2.7
    try:
        if isinstance(val, unicode):
            return val
        if isinstance(val, str):
            try:
                return val.decode("utf-8")
            except Exception:
                try:
                    return val.decode("cp1252", "ignore")
                except Exception:
                    return unicode(val, errors="ignore")
        return unicode(val)
    except Exception:
        try:
            return unicode(str(val), errors="ignore")
        except Exception:
            return u""


def get_id_value(elem_or_id):
    """
    Safely extracts numeric integer ID from an Element or ElementId.
    Seamlessly supports both Int32 (Revit 2020-2023 via IntegerValue)
    and Int64 (Revit 2024-2026 via Value) without deprecation warnings.
    """
    if elem_or_id is None:
        return -1
    eid = elem_or_id.Id if hasattr(elem_or_id, "Id") else elem_or_id
    if hasattr(eid, "Value"):
        try:
            return eid.Value
        except Exception:
            pass
    if hasattr(eid, "IntegerValue"):
        try:
            return eid.IntegerValue
        except Exception:
            pass
    return -1


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
                    u"System error in '{}'.\nDetails saved to log:\n{}".format(safe_unicode(self.name), safe_unicode(get_log_path())),
                    "System Error"
                )
            except Exception:
                pass
            return True
        else:
            if self.t.HasStarted() and not self.t.HasEnded():
                self.t.Commit()


class SafeTransactionGroup(object):
    """
    Context Manager for Revit TransactionGroup.
    Assimilates all inner transactions on success into a single 1-Click Undo step.
    Rolls back everything cleanly if any exception occurs.
    """
    def __init__(self, doc, name):
        self.doc = doc
        self.name = name
        self.tg = DB.TransactionGroup(doc, name)

    def __enter__(self):
        self.tg.Start()
        return self.tg

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            if self.tg.HasStarted() and not self.tg.HasEnded():
                self.tg.RollBack()
            return False
        else:
            if self.tg.HasStarted() and not self.tg.HasEnded():
                self.tg.Assimilate()

