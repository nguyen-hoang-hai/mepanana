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
        tuple: (success (bool), message (str))
    """
    if not os.path.exists(source_path):
        return (False, "Source file does not exist: {}".format(source_path))

    # Check if the document is currently open in Revit UI
    try:
        for open_doc in app.Documents:
            if open_doc.PathName and os.path.abspath(open_doc.PathName).lower() == os.path.abspath(source_path).lower():
                return (False, "File is currently open in Revit. Please close it before detaching.")
    except Exception:
        pass

    # Normalize destination path
    dest_dir = os.path.dirname(dest_path)
    if not os.path.exists(dest_dir):
        try:
            os.makedirs(dest_dir)
        except Exception as ex_dir:
            return (False, "Cannot create destination directory: {}".format(safe_unicode(ex_dir)))

    # Handle in-place overwrite safely (when source and dest are the same file)
    is_same_file = (os.path.abspath(source_path).lower() == os.path.abspath(dest_path).lower())
    actual_save_path = dest_path
    temp_save_path = None

    if is_same_file:
        dest_base, dest_ext = os.path.splitext(dest_path)
        temp_save_path = dest_base + "_mep_tmp_detach" + dest_ext
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
        doc = app.OpenDocumentFile(model_path, open_opts)
        if not doc:
            return (False, "Revit failed to open document.")

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
            except Exception:
                pass

        # 2. Save As new Central model
        save_opts = SaveAsOptions()
        save_opts.OverwriteExistingFile = True

        if doc.IsWorkshared:
            ws_save_opts = WorksharingSaveAsOptions()
            ws_save_opts.SaveAsCentral = True
            save_opts.SetWorksharingSaveAsOptions(ws_save_opts)

        dest_model_path = ModelPathUtils.ConvertUserVisibleStringToModelPath(actual_save_path)
        doc.SaveAs(dest_model_path, save_opts)

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
            except Exception:
                pass

        # Close document to release all file locks before potential in-place swap
        doc.Close(False)
        doc = None

        # 4. If in-place overwrite, perform atomic file swap
        if is_same_file and temp_save_path and os.path.exists(temp_save_path):
            bak_file = source_path + ".orig_bak"
            if os.path.exists(bak_file):
                try:
                    os.remove(bak_file)
                except Exception:
                    pass
            try:
                os.rename(source_path, bak_file)
            except Exception:
                try:
                    os.remove(source_path)
                except Exception:
                    pass

            os.rename(temp_save_path, source_path)

            # Also swap backup directory if created
            temp_backup_dir = os.path.splitext(temp_save_path)[0] + "_backup"
            src_backup_dir = os.path.splitext(source_path)[0] + "_backup"
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

            # Clean up backup
            if os.path.exists(bak_file):
                try:
                    os.remove(bak_file)
                except Exception:
                    pass

        return (True, "Detached and saved successfully.")

    except Exception as ex:
        if temp_save_path and os.path.exists(temp_save_path):
            try:
                os.remove(temp_save_path)
            except Exception:
                pass
        return (False, "Error: {}".format(safe_unicode(ex)))

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
