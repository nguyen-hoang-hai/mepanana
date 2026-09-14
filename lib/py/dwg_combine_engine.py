# -*- coding: utf-8 -*-
"""
dwg_combine_engine.py - Multi-Layout DWG Combine Engine for MEPANANA
Combines multiple exported DWG drawings into a single DWG file containing
multiple Layout tabs (one layout per Revit sheet) using AutoCAD Core Console (accoreconsole.exe).

Part of mepanana.extension.
Author: Hai Nguyen
"""
import os
import sys
import re
import shutil
import tempfile
import subprocess
import threading
import time

try:
    from py.core import safe_unicode
except Exception:
    def safe_unicode(val):
        try:
            return unicode(val)
        except Exception:
            return str(val)


def find_accoreconsole():
    """
    Scans standard Autodesk installation directories to find accoreconsole.exe.
    Checks AutoCAD 2027 down to 2018.
    Returns: Absolute filepath string to accoreconsole.exe, or None if not found.
    """
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    autodesk_dir = os.path.join(program_files, "Autodesk")

    if os.path.exists(autodesk_dir):
        # Check years descending: 2027, 2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018
        for year in range(2027, 2017, -1):
            candidate = os.path.join(autodesk_dir, "AutoCAD {}".format(year), "accoreconsole.exe")
            if os.path.isfile(candidate):
                return candidate

        # Also search any folder named AutoCAD* in Autodesk directory
        try:
            for item in os.listdir(autodesk_dir):
                if item.startswith("AutoCAD"):
                    candidate = os.path.join(autodesk_dir, item, "accoreconsole.exe")
                    if os.path.isfile(candidate):
                        return candidate
        except Exception:
            pass

    return None


def is_accoreconsole_available():
    """Returns True if AutoCAD Core Console is available on this system."""
    return find_accoreconsole() is not None


def _clean_layout_name(name):
    r"""
    Cleans illegal characters for AutoCAD layout names.
    AutoCAD layout names cannot contain: \ / : * ? " < > |
    Max length is 255 characters.
    """
    if not name:
        name = "Layout"
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:250] if cleaned else "Layout"


def generate_combine_lisp_script(dwg_files, sheet_names, output_dwg_path,
                                 offset_mm=2000.0):
    """
    Generates an AutoLISP script to merge dwg_files into a single DWG with multiple layouts.
    - dwg_files[0] serves as the base drawing.
    - dwg_files[1:] are inserted into Model Space at (i * 2000mm, 0) and exploded,
      then their Layout1 is imported via ._layout _template and viewports shifted.
    - offset_mm=2000: compact spacing (A0 max 1189mm wide), keeps extents manageable.
    - All interactive dialogs suppressed (EXPERT 5, ATTDIA 0, ATTREQ 0, CMDECHO 0, FILEDIA 0).
    - Layout detection uses snapshot-diff for correct parenthesis balance on any number of sheets.
    """
    out_dwg_norm = output_dwg_path.replace("\\", "/")
    lines = []

    # Suppress ALL interactive prompts — critical for accoreconsole to run non-interactively
    lines.append('(setvar "FILEDIA" 0)')
    lines.append('(setvar "CMDDIA" 0)')
    lines.append('(setvar "CMDECHO" 0)')
    lines.append('(setvar "EXPERT" 5)')
    lines.append('(setvar "ATTDIA" 0)')
    lines.append('(setvar "ATTREQ" 0)')
    lines.append('(setvar "INSUNITS" 0)')
    lines.append('(setvar "PROXYGRAPHICS" 1)')
    lines.append('(setvar "CTAB" "Model")')
    lines.append('(princ "\\n=== MEPANANA DWG MERGE START ===")')

    # Helper: collect all current layout names into a list
    lines.append('(defun mep-get-layouts (/ d item result)')
    lines.append('  (setq result (list))')
    lines.append('  (setq d (dictsearch (namedobjdict) "ACAD_LAYOUT"))')
    lines.append('  (foreach item d')
    lines.append('    (if (= (car item) 3)')
    lines.append('      (setq result (append result (list (cdr item))))')
    lines.append('    )')
    lines.append('  )')
    lines.append('  result')
    lines.append(')')

    # Step 1: Rename base layout (Sheet 0)
    base_name = _clean_layout_name(sheet_names[0]) if len(sheet_names) > 0 else "Sheet_1"
    lines.append('(command "._layout" "_rename" "Layout1" "{}")'.format(base_name))

    # Step 2: For each additional sheet — INSERT + EXPLODE + layout template
    for i in range(1, len(dwg_files)):
        dwg_path = dwg_files[i].replace("\\", "/")
        sheet_nm = _clean_layout_name(sheet_names[i]) if i < len(sheet_names) else "Sheet_{}".format(i + 1)
        curr_offset = float(i) * float(offset_mm)

        lines.append('(princ "\\n--- Sheet: {} ---")'.format(sheet_nm))

        # A: Snapshot existing layouts BEFORE template import
        lines.append('(setq mep_before (mep-get-layouts))')

        # B: Insert DWG as block at offset, then explode to bring model geometry in-place
        lines.append('(setq ins_pt (list {} 0.0 0.0))'.format(curr_offset))
        lines.append('(command "._-insert" "{}" ins_pt "1" "1" "0")'.format(dwg_path))
        lines.append('(if (entlast) (command "._explode" (entlast)))')

        # C: Import Layout1 from source DWG as a new layout tab in current drawing
        lines.append('(command "._layout" "_template" "{}" "Layout1")'.format(dwg_path))

        # D: Find the newly added layout by diff (name not in snapshot)
        lines.append('(setq mep_after (mep-get-layouts))')
        lines.append('(setq new_lay_name nil)')
        lines.append('(foreach nm mep_after')
        lines.append('  (if (not (member nm mep_before))')
        lines.append('    (setq new_lay_name nm)')
        lines.append('  )')
        lines.append(')')

        # E: Rename imported layout & shift viewport view centers by curr_offset
        lines.append('(if new_lay_name')
        lines.append('  (progn')
        lines.append('    (command "._layout" "_rename" new_lay_name "{}")'.format(sheet_nm))
        lines.append('    (setq vps (ssget "X" (list \'(0 . "VIEWPORT") (cons 410 "{}"))))'.format(sheet_nm))
        lines.append('    (if vps')
        lines.append('      (repeat (setq j (sslength vps))')
        lines.append('        (setq vp_ename (ssname vps (setq j (1- j))))')
        lines.append('        (setq vp_data (entget vp_ename))')
        lines.append('        (setq old_c (assoc 12 vp_data))')
        lines.append('        (if old_c')
        lines.append('          (progn')
        lines.append('            (setq old_pt (cdr old_c))')
        lines.append('            (setq new_pt (list (+ (car old_pt) {}) (cadr old_pt)))'.format(curr_offset))
        lines.append('            (setq vp_data (subst (cons 12 new_pt) old_c vp_data))')
        lines.append('            (entmod vp_data)')
        lines.append('          )')
        lines.append('        )')
        lines.append('      )')
        lines.append('    )')
        lines.append('  )')
        lines.append(')')

    # Step 3: Delete the default "Layout2" placeholder if it was not used
    lines.append('(command "._layout" "_delete" "Layout2")')

    # Step 4: Save as AutoCAD 2018 DWG
    lines.append('(command "._saveas" "2018" "{}")'.format(out_dwg_norm))
    lines.append('(princ "\\n=== MEPANANA DWG MERGE COMPLETE ===")')
    lines.append('QUIT')
    lines.append('Y')

    return "\n".join(lines) + "\n"





def combine_dwgs_to_multilayout(dwg_files, sheet_names, output_dwg_path,
                                progress_callback=None):
    """
    Combines a list of DWG files into a single master DWG with multiple Layout tabs.
    
    Args:
        dwg_files (list[str]): Paths to individual DWG files.
        sheet_names (list[str]): Names for the layout tabs corresponding to each dwg.
        output_dwg_path (str): Destination path for the combined DWG.
        progress_callback (callable): Optional callback(percent, msg).

    Returns:
        tuple: (success (bool), message (str))
    """
    if not dwg_files:
        return (False, "No DWG files provided to combine.")

    if len(dwg_files) == 1:
        # Only 1 file: simple copy is sufficient
        try:
            shutil.copyfile(dwg_files[0], output_dwg_path)
            return (True, "Single DWG copied.")
        except Exception as ex:
            return (False, "Error copying single DWG: {}".format(safe_unicode(ex)))

    accore_exe = find_accoreconsole()
    if not accore_exe:
        return (False, "AutoCAD Core Console (accoreconsole.exe) was not found on this computer.")

    if progress_callback:
        progress_callback(10, "Preparing DWG layout merge script...")

    temp_dir = tempfile.gettempdir()
    scr_path = os.path.join(temp_dir, "mepanana_merge_{}.scr".format(os.getpid()))

    try:
        script_content = generate_combine_lisp_script(dwg_files, sheet_names, output_dwg_path)

        with open(scr_path, "w") as f:
            f.write(script_content)

        if progress_callback:
            progress_callback(30, "Executing AutoCAD Core Console engine...")

        base_dwg = dwg_files[0]

        # Launch accoreconsole with base drawing and script
        cmd = [
            accore_exe,
            "/i", base_dwg,
            "/s", scr_path
        ]

        # Run process synchronously with startupinfo hidden
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            shell=False
        )

        # --- Non-blocking subprocess: run communicate() in a background thread
        # so the WPF UI thread stays alive via do_events() during accoreconsole execution.
        _result = [None, None, False]  # [stdout_bytes, stderr_bytes, done_flag]

        def _communicate_bg():
            try:
                out, err = proc.communicate()
                _result[0] = out
                _result[1] = err
            finally:
                _result[2] = True  # always signal done, even on exception

        bg_thread = threading.Thread(target=_communicate_bg)
        bg_thread.daemon = True
        bg_thread.start()

        # Poll until done or timeout (2 minutes = 120 s)
        # accoreconsole cold-start ~20-30s + processing. If > 120s → something is wrong.
        TIMEOUT_SECONDS = 120
        start_time = time.time()
        elapsed = 0.0

        try:
            from py.ui import do_events as _do_events
        except Exception:
            _do_events = None

        while not _result[2]:
            elapsed = time.time() - start_time
            if elapsed > TIMEOUT_SECONDS:
                try:
                    proc.kill()
                except Exception:
                    pass
                return (False,
                    u"AutoCAD Core Console did not complete within {} seconds.\n"
                    u"This usually means accoreconsole.exe is hanging or the DWG script failed.\n"
                    u"Try using 'Separate Files' DWG mode instead — it works without AutoCAD.".format(int(elapsed)))

            time.sleep(0.1)  # yield 100ms between polls

            if _do_events:
                try:
                    _do_events()
                except Exception:
                    pass

            # Update progress smoothly while waiting (30% → 85%)
            if progress_callback:
                pct = 30 + int(min(elapsed / TIMEOUT_SECONDS, 0.9) * 55)
                progress_callback(pct, u"Executing AutoCAD Core Console engine... ({:.0f}s)".format(elapsed))

        stdout_data = _result[0]
        stderr_data = _result[1]

        if progress_callback:
            progress_callback(90, "Verifying combined DWG file...")

        if os.path.exists(output_dwg_path) and os.path.getsize(output_dwg_path) > 1024:
            return (True, "Combined {} sheets into DWG successfully.".format(len(dwg_files)))
        else:
            err_msg = safe_unicode(stdout_data[-500:] if stdout_data else stderr_data)
            return (False, "DWG merge failed to generate output file. Console log: {}".format(err_msg))

    except Exception as ex:
        return (False, "Exception during DWG combine: {}".format(safe_unicode(ex)))
    finally:
        # Clean up temporary script
        if os.path.exists(scr_path):
            try:
                os.remove(scr_path)
            except Exception:
                pass
