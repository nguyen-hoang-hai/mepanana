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

try:
    string_types = (basestring,)
except NameError:
    string_types = (str,)


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


def generate_combine_lisp_script(dwg_files, sheet_names=None, output_dwg_path=None,
                                 offset_mm=300000.0):
    """
    Generates an AutoLISP script to merge dwg_files into a single DWG with multiple layouts.
    - dwg_files[0] serves as the base drawing.
    - dwg_files[1:] are inserted into Model Space at safe non-overlapping intervals (min 300m or 1.5x span),
      then their Layout1 is imported via ._layout _template and viewports shifted accordingly.
    - Suppresses interactive dialogs and optimizes AutoCAD system variables.
    - Layout detection uses snapshot-diff for correct parenthesis balance on any number of sheets.
    """
    if output_dwg_path is None and isinstance(sheet_names, string_types):
        output_dwg_path = sheet_names
        sheet_names = None

    if not output_dwg_path:
        output_dwg_path = "output.dwg"

    if not sheet_names:
        sheet_names = [
            os.path.splitext(os.path.basename(f))[0]
            for f in dwg_files
        ]

    # Ensure unique layout names to prevent AutoCAD duplicate layout collisions
    unique_names = []
    seen_names = set()
    for idx, s_name in enumerate(sheet_names):
        cleaned = _clean_layout_name(s_name)
        candidate = cleaned
        counter = 1
        while candidate.lower() in seen_names:
            candidate = u"{}_{}".format(cleaned[:240], counter)
            counter += 1
        seen_names.add(candidate.lower())
        unique_names.append(candidate)
    sheet_names = unique_names

    out_dwg_norm = output_dwg_path.replace("\\", "/")
    lines = []

    # Suppress ALL interactive prompts & optimize AutoCAD performance
    lines.append('(setvar "FILEDIA" 0)')
    lines.append('(setvar "CMDDIA" 0)')
    lines.append('(setvar "CMDECHO" 0)')
    lines.append('(setvar "EXPERT" 5)')
    lines.append('(setvar "REGENMODE" 0)')
    lines.append('(setvar "DRAWORDERCTL" 0)')
    lines.append('(setvar "INDEXCTL" 0)')
    lines.append('(setvar "HPQUICKPREV" 0)')
    lines.append('(setvar "XREFAUTODOWNLOAD" 0)')
    lines.append('(setvar "PROXYNOTICE" 0)')
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

    # Helper: get the first non-Model layout
    lines.append('(defun mep-get-first-layout (/ d item lay)')
    lines.append('  (setq lay nil)')
    lines.append('  (setq d (dictsearch (namedobjdict) "ACAD_LAYOUT"))')
    lines.append('  (foreach item d')
    lines.append('    (if (and (= (car item) 3) (/= (cdr item) "Model") (null lay))')
    lines.append('      (setq lay (cdr item))')
    lines.append('    )')
    lines.append('  )')
    lines.append('  lay')
    lines.append(')')

    # Step 1: Rename base layout (Sheet 0)
    base_name = _clean_layout_name(sheet_names[0]) if len(sheet_names) > 0 else "Sheet_1"
    lines.append('(setq mep_base_lay (mep-get-first-layout))')
    lines.append('(if mep_base_lay (command "._layout" "_rename" mep_base_lay "{}"))'.format(base_name))

    # Calculate model space footprint to prevent drawing collisions
    lines.append('(setq mep_ext_min (getvar "EXTMIN"))')
    lines.append('(setq mep_ext_max (getvar "EXTMAX"))')
    lines.append('(setq mep_span (if (and mep_ext_min mep_ext_max) (abs (- (car mep_ext_max) (car mep_ext_min))) 0.0))')
    lines.append('(if (or (null mep_span) (< mep_span 1000.0)) (setq mep_step {0}) (setq mep_step (max {0} (* mep_span 1.5))))'.format(float(offset_mm)))

    # Step 2: For each additional sheet — INSERT + EXPLODE + layout template
    for i in range(1, len(dwg_files)):
        dwg_path = dwg_files[i].replace("\\", "/")
        sheet_nm = _clean_layout_name(sheet_names[i]) if i < len(sheet_names) else "Sheet_{}".format(i + 1)

        lines.append('(princ "\\n--- Sheet: {} ---")'.format(sheet_nm))
        lines.append('(setq curr_offset (* {} mep_step))'.format(i))

        # A: Snapshot existing layouts BEFORE template import
        lines.append('(setq mep_before (mep-get-layouts))')

        # B: Insert DWG as block at offset, then explode to bring model geometry in-place
        lines.append('(setq ins_pt (list curr_offset 0.0 0.0))')
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

        # E: Rename imported layout, copy page setup, activate viewports & pan to match model offset
        lines.append('(if new_lay_name')
        lines.append('  (progn')
        lines.append('    (command "._layout" "_rename" new_lay_name "{}")'.format(sheet_nm))
        lines.append('    ;; 1. Copy plot/page setup & paper limits from base layout')
        lines.append('    (setq d (dictsearch (namedobjdict) "ACAD_LAYOUT"))')
        lines.append('    (if d')
        lines.append('      (progn')
        lines.append('        (setq src_lay (dictsearch (cdr (assoc -1 d)) "{}"))'.format(base_name))
        lines.append('        (setq tgt_lay (dictsearch (cdr (assoc -1 d)) "{}"))'.format(sheet_nm))
        lines.append('        (if (and src_lay tgt_lay)')
        lines.append('          (progn')
        lines.append('            (setq new_tgt tgt_lay)')
        lines.append('            (foreach grp \'(4 10 11 12 14 40 41 42 43 44 45 46 47 48 49 140 141 142 143 144 145 146 147 148)')
        lines.append('              (if (assoc grp src_lay)')
        lines.append('                (if (assoc grp new_tgt)')
        lines.append('                  (setq new_tgt (subst (assoc grp src_lay) (assoc grp new_tgt) new_tgt))')
        lines.append('                  (setq new_tgt (append new_tgt (list (assoc grp src_lay))))')
        lines.append('                )')
        lines.append('              )')
        lines.append('            )')
        lines.append('            (entmod new_tgt)')
        lines.append('          )')
        lines.append('        )')
        lines.append('      )')
        lines.append('    )')
        lines.append('    ;; 2. Switch to this layout tab and initialize viewport display')
        lines.append('    (setvar "CTAB" "{}")'.format(sheet_nm))
        lines.append('    (command "._zoom" "_extents")')
        lines.append('    ;; 3. Turn ON all viewports on this layout')
        lines.append('    (command "._mview" "_on" "_all" "")')
        lines.append('    ;; 4. Pan all floating viewports by curr_offset')
        lines.append('    (setq ss_vp (ssget "X" (list \'(0 . "VIEWPORT") (cons 410 "{}"))))'.format(sheet_nm))
        lines.append('    (if ss_vp')
        lines.append('      (repeat (setq j (sslength ss_vp))')
        lines.append('        (setq vp_en (ssname ss_vp (setq j (1- j))))')
        lines.append('        (setq vp_ed (entget vp_en))')
        lines.append('        (setq vp_id (cdr (assoc 69 vp_ed)))')
        lines.append('        (if (> vp_id 1)')
        lines.append('          (progn')
        lines.append('            (command "._mspace")')
        lines.append('            (setvar "CVPORT" vp_id)')
        lines.append('            (command "._-pan" \'(0 0 0) (list (- curr_offset) 0 0))')
        lines.append('            (command "._pspace")')
        lines.append('          )')
        lines.append('        )')
        lines.append('      )')
        lines.append('    )')
        lines.append('    (command "._zoom" "_extents")')
        lines.append('    (command "._pspace")')
        lines.append('  )')
        lines.append(')')

    # Step 2.5: Switch CTAB back to base layout
    lines.append('(setvar "CTAB" "{}")'.format(base_name))
    lines.append('(command "._zoom" "_extents")')

    # Step 3: Delete the default "Layout2" placeholder if it was not used
    lines.append('(command "._layout" "_delete" "Layout2")')

    # Step 4: Purge intermediate unreferenced block definitions
    lines.append('(command "._-purge" "_blocks" "*" "_n")')

    # Step 5: Save as AutoCAD 2018 DWG
    lines.append('(command "._saveas" "2018" "{}")'.format(out_dwg_norm))
    lines.append('(princ "\\n=== MEPANANA DWG MERGE COMPLETE ===")')
    lines.append('QUIT')
    lines.append('Y')

    return "\n".join(lines) + "\n"





def combine_dwgs_to_multilayout(dwg_files, sheet_names=None, output_dwg_path=None,
                                progress_callback=None):
    """
    Combines a list of DWG files into a single master DWG with multiple Layout tabs.
    Supports both signatures:
      - combine_dwgs_to_multilayout(dwg_files, sheet_names, output_dwg_path, progress_callback)
      - combine_dwgs_to_multilayout(dwg_files, output_dwg_path, progress_callback)

    Args:
        dwg_files (list[str]): Paths to individual DWG files.
        sheet_names (list[str] or str): Names for the layout tabs, or output_dwg_path if 2 positional args.
        output_dwg_path (str): Destination path for the combined DWG.
        progress_callback (callable): Optional callback(percent, msg).

    Returns:
        tuple: (success (bool), message (str))
    """
    if output_dwg_path is None and isinstance(sheet_names, string_types):
        output_dwg_path = sheet_names
        sheet_names = None

    if not dwg_files:
        return (False, "No DWG files provided to combine.")

    if not output_dwg_path:
        return (False, "No destination output DWG path specified.")

    if not sheet_names:
        sheet_names = [
            os.path.splitext(os.path.basename(f))[0]
            for f in dwg_files
        ]

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
