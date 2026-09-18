# -*- coding: utf-8 -*-
"""
batch_detach_engine.py - Automated Batch Detach & Workset Relinquish Engine for MEPANANA
Opens Revit projects in background detached from central, relinquishes all workset
ownership to non-editable, unloads links, and saves clean central/standalone models.

Part of mepanana.extension.
Author: Hai Nguyen
"""
import os
import sys
import shutil

from Autodesk.Revit.DB import (
    ModelPathUtils,
    OpenOptions,
    DetachFromCentralOption,
    SaveAsOptions,
    WorksharingSaveAsOptions,
    WorksharingUtils,
    RelinquishOptions,
    FilteredElementCollector,
    RevitLinkType,
    WorksetConfiguration,
    WorksetConfigurationOption
)

from py.core import safe_unicode


def get_file_size_display(file_path):
    """Returns human-readable file size string (e.g. '125.4 MB')."""
    try:
        size_bytes = os.path.getsize(file_path)
        if size_bytes >= 1024 * 1024 * 1024:
            return "{:.2f} GB".format(size_bytes / (1024.0 * 1024.0 * 1024.0))
        elif size_bytes >= 1024 * 1024:
            return "{:.1f} MB".format(size_bytes / (1024.0 * 1024.0))
        elif size_bytes >= 1024:
            return "{:.0f} KB".format(size_bytes / 1024.0)
        return "{} B".format(size_bytes)
    except Exception:
        return "Unknown"

import time
import datetime
import tempfile


def log_batch_detach(msg):
    """Logs batch detach events to %TEMP%/mepanana_batch_detach.log."""
    try:
        log_path = os.path.join(tempfile.gettempdir(), "mepanana_batch_detach.log")
        with open(log_path, "a") as f:
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write((u"[{}] {}\n".format(stamp, safe_unicode(msg))).encode("utf-8", "ignore"))
    except Exception:
        pass


def _safe_atomic_file_swap(original_path, new_temp_path, max_retries=6):
    """
    Safely swaps new_temp_path into original_path with retry mechanism
    to handle transient Windows file locks (antivirus, OneDrive sync, Revit background workers).
    """
    bak_file = original_path + u".orig_bak"
    if os.path.exists(bak_file):
        try:
            os.remove(bak_file)
        except Exception:
            pass

    # Step 1: Rename original file to backup
    renamed_original = False
    for attempt in range(max_retries):
        try:
            os.rename(original_path, bak_file)
            renamed_original = True
            break
        except Exception as ex_ren:
            log_batch_detach(u"Retry {}/{} renaming original file: {}".format(attempt + 1, max_retries, safe_unicode(ex_ren)))
            time.sleep(0.5)

    if not renamed_original:
        # If rename failed, try direct remove if backup exists
        try:
            os.remove(original_path)
            renamed_original = True
        except Exception as ex_del:
            return (False, u"File is locked by another process (e.g. OneDrive or Revit). Cannot overwrite: {}".format(safe_unicode(ex_del)))

    # Step 2: Rename temp file to original file path
    swapped = False
    for attempt in range(max_retries):
        try:
            os.rename(new_temp_path, original_path)
            swapped = True
            break
        except Exception as ex_swp:
            log_batch_detach(u"Retry {}/{} moving temp file to destination: {}".format(attempt + 1, max_retries, safe_unicode(ex_swp)))
            time.sleep(0.5)

    if not swapped:
        # Attempt rollback
        if os.path.exists(bak_file) and not os.path.exists(original_path):
            try:
                os.rename(bak_file, original_path)
            except Exception:
                pass
        return (False, u"Failed to replace original file with detached model.")

    # Step 3: Swap backup directory if present
    temp_backup_dir = os.path.splitext(new_temp_path)[0] + u"_backup"
    src_backup_dir = os.path.splitext(original_path)[0] + u"_backup"
    if os.path.exists(temp_backup_dir):
        if os.path.exists(src_backup_dir):
            try:
                shutil.rmtree(src_backup_dir, ignore_errors=True)
            except Exception:
                pass
        try:
            os.rename(temp_backup_dir, src_backup_dir)
        except Exception:
            pass

    # Step 4: Clean up temporary backup file
    if os.path.exists(bak_file):
        try:
            os.remove(bak_file)
        except Exception:
            pass

    return (True, u"Swap successful.")


def detach_and_clean_model(app, source_path, dest_path,
                           relinquish_all=True,
                           unload_links=True,
                           audit=False,
                           preserve_worksets=True):
    """
    Opens a single Revit model detached in the background, cleans it, and saves it.

    Args:
        app: Revit UI Application or Application instance.
        source_path (str): Full path to the source .rvt file.
        dest_path (str): Destination full path to save the detached model.
        relinquish_all (bool): Relinquish all worksets to make them non-editable.
        unload_links (bool): Unload all Revit links for clean transmission.
        audit (bool): Audit the model during open.
        preserve_worksets (bool): True = DetachAndPreserveWorksets, False = DetachAndDiscardWorksets.

    Returns:
        tuple: (success (bool), message (unicode))
    """
    log_batch_detach(u"Starting detach for: {} -> {}".format(safe_unicode(source_path), safe_unicode(dest_path)))

    if not os.path.exists(source_path):
        msg = u"Source file does not exist: {}".format(safe_unicode(source_path))
        log_batch_detach(msg)
        return (False, msg)

    # Check if the document is currently open in Revit UI
    try:
        if app and hasattr(app, "Documents"):
            for open_doc in app.Documents:
                try:
                    if open_doc and open_doc.PathName:
                        if os.path.abspath(open_doc.PathName).lower() == os.path.abspath(source_path).lower():
                            msg = u"File is currently open in Revit. Please close it before detaching."
                            log_batch_detach(msg)
                            return (False, msg)
                except Exception:
                    pass
    except Exception:
        pass

    # Normalize destination path
    dest_dir = os.path.dirname(dest_path)
    if not os.path.exists(dest_dir):
        try:
            os.makedirs(dest_dir)
        except Exception as ex_dir:
            msg = u"Cannot create destination directory: {}".format(safe_unicode(ex_dir))
            log_batch_detach(msg)
            return (False, msg)

    # Handle in-place overwrite safely (when source and dest are the same file)
    is_same_file = (os.path.abspath(source_path).lower() == os.path.abspath(dest_path).lower())
    actual_save_path = dest_path
    temp_save_path = None

    if is_same_file:
        dest_base, dest_ext = os.path.splitext(dest_path)
        temp_save_path = dest_base + u"_mep_tmp_detach" + dest_ext
        actual_save_path = temp_save_path

    model_path = ModelPathUtils.ConvertUserVisibleStringToModelPath(source_path)
    open_opts = OpenOptions()
    open_opts.Audit = bool(audit)

    if preserve_worksets:
        open_opts.DetachFromCentralOption = DetachFromCentralOption.DetachAndPreserveWorksets
        try:
            ws_config = WorksetConfiguration(WorksetConfigurationOption.OpenAllWorksets)
            open_opts.SetOpenWorksetsConfiguration(ws_config)
        except Exception:
            pass
    else:
        open_opts.DetachFromCentralOption = DetachFromCentralOption.DetachAndDiscardWorksets

    doc = None
    try:
        log_batch_detach(u"Calling app.OpenDocumentFile for: {}".format(safe_unicode(source_path)))
        doc = app.OpenDocumentFile(model_path, open_opts)
        if not doc:
            msg = u"Revit failed to open document."
            log_batch_detach(msg)
            return (False, msg)

        log_batch_detach(u"Document opened successfully: IsWorkshared={}".format(doc.IsWorkshared))

        # 1. Unload Revit Links if requested
        if unload_links:
            try:
                link_types = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements()
                for lt in link_types:
                    try:
                        if not lt.IsNestedLink and lt.IsLoaded(doc, lt.Id):
                            lt.Unload(None)
                    except Exception:
                        pass
                log_batch_detach(u"Unloaded Revit links.")
            except Exception as ex_links:
                log_batch_detach(u"Warning unloading links: {}".format(safe_unicode(ex_links)))

        # 2. Save As new Central model
        save_opts = SaveAsOptions()
        save_opts.OverwriteExistingFile = True

        if doc.IsWorkshared:
            ws_save_opts = WorksharingSaveAsOptions()
            ws_save_opts.SaveAsCentral = True
            save_opts.SetWorksharingSaveAsOptions(ws_save_opts)

        dest_model_path = ModelPathUtils.ConvertUserVisibleStringToModelPath(actual_save_path)
        log_batch_detach(u"Saving document to: {}".format(safe_unicode(actual_save_path)))
        doc.SaveAs(dest_model_path, save_opts)
        log_batch_detach(u"Document saved successfully.")

        # 3. Relinquish all worksets (Make Non-Editable)
        if doc.IsWorkshared and relinquish_all:
            try:
                r_opts = RelinquishOptions(True)
                r_opts.UserWorksets = True
                r_opts.FamilyWorksets = True
                r_opts.ViewWorksets = True
                r_opts.ProjectStandardsWorksets = True
                r_opts.StandardWorksets = True
                r_opts.CheckedOutElements = True
                WorksharingUtils.RelinquishOwnership(doc, r_opts, None)
                log_batch_detach(u"Relinquished all workset ownership.")
            except Exception as ex_relinq:
                log_batch_detach(u"Relinquish notice (normal for new central): {}".format(safe_unicode(ex_relinq)))

        # Close document and release all Win32/CLR file locks before swap
        try:
            doc.Close(False)
        except Exception:
            pass
        doc = None

        # Force CLR Garbage Collection to release unmanaged file handles immediately
        try:
            import System
            System.GC.Collect()
            System.GC.WaitForPendingFinalizers()
        except Exception:
            pass

        # 4. If in-place overwrite, perform atomic file swap
        if is_same_file and temp_save_path and os.path.exists(temp_save_path):
            log_batch_detach(u"Performing atomic file swap: {} -> {}".format(safe_unicode(temp_save_path), safe_unicode(source_path)))
            ok_swap, swap_msg = _safe_atomic_file_swap(source_path, temp_save_path)
            if not ok_swap:
                log_batch_detach(u"Atomic swap failed: {}".format(safe_unicode(swap_msg)))
                return (False, swap_msg)
            log_batch_detach(u"Atomic swap completed successfully.")

        log_batch_detach(u"Batch detach completed successfully for: {}".format(safe_unicode(source_path)))
        return (True, u"Detached and saved successfully.")

    except Exception as ex:
        err_msg = safe_unicode(ex)
        log_batch_detach(u"Exception in detach_and_clean_model: {}".format(err_msg))
        if temp_save_path and os.path.exists(temp_save_path):
            try:
                os.remove(temp_save_path)
            except Exception:
                pass
        return (False, u"Error: {}".format(err_msg))

    except:
        import sys
        fatal_msg = safe_unicode(sys.exc_info()[1])
        log_batch_detach(u"Fatal CLR error in detach_and_clean_model: {}".format(fatal_msg))
        if temp_save_path and os.path.exists(temp_save_path):
            try:
                os.remove(temp_save_path)
            except Exception:
                pass
        return (False, u"Fatal error: {}".format(fatal_msg))

    finally:
        if doc:
            try:
                doc.Close(False)
            except Exception:
                pass


def batch_detach_models(app, file_list, dest_mode, output_folder, suffix,
                        relinquish_all=True, unload_links=True, audit=False,
                        preserve_worksets=True, progress_callback=None):
    """
    Batches multiple Revit project files through the detach and clean engine.

    Args:
        app: Revit application.
        file_list (list[str]): List of absolute paths to .rvt files.
        dest_mode (str): 'folder' (save in output_folder) or 'suffix' (save alongside with suffix).
        output_folder (str): Directory if dest_mode is 'folder'.
        suffix (str): Suffix (e.g. '_detached') if dest_mode is 'suffix'.
        relinquish_all (bool): Relinquish ownership.
        unload_links (bool): Unload RVT links.
        audit (bool): Audit models.
        preserve_worksets (bool): Preserve worksets vs discard.
        progress_callback (callable): Optional progress_callback(percent: int, status: str).

    Returns:
        tuple: (success_count (int), fail_count (int), results (list[dict]))
    """
    total = len(file_list)
    if total == 0:
        return (0, 0, [])

    success_count = 0
    fail_count = 0
    results = []

    for idx, src_path in enumerate(file_list):
        filename = os.path.basename(src_path)
        percent = int(float(idx) / float(total) * 100.0)

        if progress_callback:
            progress_callback(percent, u"Detaching {} ({}/{})...".format(filename, idx + 1, total))

        # Determine target output path
        if dest_mode == "folder":
            dst_path = os.path.join(output_folder, filename)
        else:
            base, ext = os.path.splitext(src_path)
            clean_suffix = suffix.strip() if suffix else "_detached"
            dst_path = base + clean_suffix + ext

        ok, msg = detach_and_clean_model(
            app=app,
            source_path=src_path,
            dest_path=dst_path,
            relinquish_all=relinquish_all,
            unload_links=unload_links,
            audit=audit,
            preserve_worksets=preserve_worksets
        )

        if ok:
            success_count += 1
        else:
            fail_count += 1

        results.append({
            "source": src_path,
            "dest": dst_path,
            "success": ok,
            "message": msg
        })

    if progress_callback:
        progress_callback(100, u"Batch detach completed.")

    return (success_count, fail_count, results)
