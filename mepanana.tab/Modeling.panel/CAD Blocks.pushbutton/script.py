# -*- coding: utf-8 -*-
__title__ = "CAD Blocks"
__doc__   = "Place Revit families at CAD block positions based on layer mapping rules."
# ==============================================================================
import math
import os
import json
import time

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (
    FilteredElementCollector, FamilySymbol, ImportInstance,
    CategoryType, ElementId, Line, ElementTransformUtils, XYZ,
    Level
)
from Autodesk.Revit.DB.Structure import StructuralType
from py.core import get_doc, get_uidoc, SafeTransaction, get_element_name, mm_to_ft, get_id_value, safe_unicode
from py.ui   import show_error, show_info, show_warning, setup_window, do_events
from py.cad  import extract_cad_blocks
from py.auth import require_auth, update_ribbon_state, is_authenticated

if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        import sys
        sys.exit()


import clr
clr.AddReference("System")
clr.AddReference("PresentationCore")
from System.Windows             import Visibility
from System.Windows.Input       import Key
from System.Collections.Generic import List
from System.Windows.Media       import SolidColorBrush, Color

doc = get_doc()


# ==============================================================================
# DATA MODEL
# ==============================================================================
class MappingRule(object):
    def __init__(self, index):
        self.Index          = index
        self.Layer          = ""
        self.Category       = "Lighting Fixtures"
        self.FamilyType     = None   # FamilySymbol
        self.OffsetStr      = "0"
        self.RotationPolicy = "0"    # degrees added on top of CAD angle
        self._block_count   = 0      # filled by refresh

    @property
    def DisplayName(self):
        """Short label for the ListBox: 'LAYER_NAME (N blocks)'"""
        if not self.Layer:
            lyr = "— unassigned —"
        else:
            lyr = self.Layer if len(self.Layer) <= 22 else self.Layer[:20] + "..."
        cnt = " ({})".format(self._block_count) if self._block_count else ""
        return "{}{}".format(lyr, cnt)


# ==============================================================================
# MAIN WINDOW
# ==============================================================================
class CadBlockPlacerWindow(forms.WPFWindow):

    def __init__(self, saved_rules):
        xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        setup_window(self)

        self.rules                = saved_rules
        self.current_rule         = None
        self.action               = "CANCEL"
        self.preview_element_ids  = []
        self.cad_map              = {}      # name -> ImportInstance
        self.family_map           = {}      # "Fam : Type" -> FamilySymbol
        self.family_category_map  = {}      # "Fam : Type" -> category name
        self._cached_cad_name     = None
        self._cached_blocks       = []
        self._selected_cad        = None
        self._all_levels          = []

        # ── Detect active level (for pre-selection only) ───────────────────
        self._active_view  = doc.ActiveView
        self._active_level = self._detect_level()

        # ── Load family symbols (non-annotation) ──────────────────────────
        symbols = (FilteredElementCollector(doc)
                   .OfClass(FamilySymbol)
                   .WhereElementIsElementType()
                   .ToElements())
        all_categories = set()
        for s in symbols:
            try:
                if s.Category and s.Category.CategoryType == CategoryType.Annotation:
                    continue
                cat_name  = s.Category.Name if s.Category else "Other"
                fam_name  = s.FamilyName if hasattr(s, 'FamilyName') else ""
                type_name = get_element_name(s)
                key = "{} : {}".format(fam_name, type_name)
                self.family_map[key]          = s
                self.family_category_map[key] = cat_name
                all_categories.add(cat_name)
            except:
                pass

        # ── Load CAD Links ─────────────────────────────────────────────────
        all_imports = FilteredElementCollector(doc).OfClass(ImportInstance).ToElements()
        imports = [i for i in all_imports if i.IsLinked]
        if not imports:
            show_error("No CAD Links found in the document.", title="CAD Blocks", exitscript=True)

        cad_names = []
        for cad in imports:
            name = "CAD_" + str(get_id_value(cad))
            try: name = cad.Category.Name
            except: pass
            if name not in self.cad_map:
                self.cad_map[name] = cad
                cad_names.append(name)

        self.cmbCadLink.ItemsSource   = cad_names
        self.cmbCadLink.SelectedIndex = 0

        # ── Load Levels ────────────────────────────────────────────────────
        self._all_levels = sorted(
            list(FilteredElementCollector(doc).OfClass(Level)),
            key=lambda l: l.Elevation
        )
        level_names = [l.Name for l in self._all_levels]
        self.cmbLevel.ItemsSource = level_names
        if self._active_level and self._active_level.Name in level_names:
            self.cmbLevel.SelectedItem = self._active_level.Name
        elif level_names:
            self.cmbLevel.SelectedIndex = 0

        # ── Categories ────────────────────────────────────────────────────
        self.allowed_categories = ["All Categories"] + sorted(all_categories)
        self.cmbRuleCategory.ItemsSource = self.allowed_categories
        self.cmbRuleCategory.SelectionChanged += self._on_category_changed

        # ── Wire events ───────────────────────────────────────────────────
        self.btnAddRule.Click         += self._on_add_rule
        self.btnRemoveRule.Click      += self._on_remove_rule
        self.btnAutoScan.Click        += self._on_auto_scan
        self.btnSaveRules.Click       += self._on_save_rules
        self.btnLoadRules.Click       += self._on_load_rules
        self.btnPlace.Click           += self._on_place
        if hasattr(self, 'btnClose') and self.btnClose:
            self.btnClose.Click       += lambda s, e: self.Close()
        self.btnPreviewSingle.Click   += self._on_preview_single
        self.lstRules.SelectionChanged += self._on_rule_selected
        self.cmbRuleLayer.SelectionChanged  += self._on_detail_changed
        self.cmbRuleFamily.SelectionChanged += self._on_detail_changed
        self.txtRuleOffset.TextChanged      += self._on_detail_changed
        self.cmbRuleRotation.SelectionChanged += self._on_detail_changed
        self.PreviewKeyDown += self._on_key_down

        # ── Init display ──────────────────────────────────────────────────
        self._refresh_layer_list()
        self._refresh_rules_list()
        if self.rules:
            self.lstRules.SelectedIndex = 0

    # ── Level Detection ────────────────────────────────────────────────────
    def _detect_level(self):
        """Try GenLevel → name-match fallback."""
        try:
            lvl = self._active_view.GenLevel
            if lvl is not None:
                return lvl
        except:
            pass
        try:
            view_name = self._active_view.Name
            all_lvls  = sorted(
                list(FilteredElementCollector(doc).OfClass(Level)),
                key=lambda l: l.Elevation
            )
            for lvl in sorted(all_lvls, key=lambda l: -len(l.Name)):
                if lvl.Name in view_name:
                    return lvl
        except:
            pass
        return None

    # ── CAD Block Cache ────────────────────────────────────────────────────
    def _get_cad_blocks(self):
        cad_name = None
        try:   cad_name = self.cmbCadLink.SelectedItem
        except: cad_name = self._cached_cad_name

        if not cad_name:
            cad_name = self._cached_cad_name

        if cad_name and cad_name != self._cached_cad_name:
            cad = self.cad_map.get(cad_name)
            if cad:
                self._selected_cad   = cad
                self._cached_blocks, err = extract_cad_blocks(cad)
                if err: print("CAD warn: " + str(err))
                self._cached_cad_name = cad_name
        elif not self._cached_blocks and self._cached_cad_name:
            cad = self.cad_map.get(self._cached_cad_name)
            if cad:
                self._selected_cad   = cad
                self._cached_blocks, _ = extract_cad_blocks(cad)
        return self._cached_blocks

    # ── Layer List ─────────────────────────────────────────────────────────
    def _refresh_layer_list(self):
        blocks = self._get_cad_blocks()
        if blocks:
            layers = sorted(set(b.Layer for b in blocks))
            self.cmbRuleLayer.ItemsSource = layers

    # ── Rules List ─────────────────────────────────────────────────────────
    def _refresh_rules_list(self):
        # Update block counts for display
        blocks = self._get_cad_blocks()
        layer_counts = {}
        for b in blocks:
            layer_counts[b.Layer] = layer_counts.get(b.Layer, 0) + 1
        for r in self.rules:
            r._block_count = layer_counts.get(r.Layer, 0)

        self.lstRules.ItemsSource = None
        self.lstRules.ItemsSource = self.rules

    # ── Keyboard ───────────────────────────────────────────────────────────
    def _on_key_down(self, sender, args):
        if args.Key == Key.Escape:
            self.action = "CANCEL"
            self.Close()
            args.Handled = True

    # ── Rule CRUD ──────────────────────────────────────────────────────────
    def _on_add_rule(self, sender, args):
        rule = MappingRule(len(self.rules) + 1)
        self.rules.append(rule)
        self._refresh_rules_list()
        self.lstRules.SelectedIndex = len(self.rules) - 1

    def _on_remove_rule(self, sender, args):
        if self.current_rule:
            self.rules.remove(self.current_rule)
            for i, r in enumerate(self.rules):
                r.Index = i + 1
            self._refresh_rules_list()

    def _on_auto_scan(self, sender, args):
        blocks = self._get_cad_blocks()
        if not blocks: return
        layers = sorted(set(b.Layer for b in blocks))
        self.rules = []
        for i, lyr in enumerate(layers):
            r = MappingRule(i + 1)
            r.Layer = lyr
            self.rules.append(r)
        self._refresh_rules_list()
        if self.rules:
            self.lstRules.SelectedIndex = 0

    # ── Save / Load ────────────────────────────────────────────────────────
    def _on_save_rules(self, sender, args):
        try:
            data = []
            for r in self.rules:
                fk = ""
                if r.FamilyType:
                    try:
                        fn = r.FamilyType.FamilyName if hasattr(r.FamilyType, 'FamilyName') else ""
                        tn = get_element_name(r.FamilyType)
                        fk = "{} : {}".format(fn, tn)
                    except: pass
                data.append({
                    "layer":    r.Layer,
                    "category": r.Category,
                    "offset":   r.OffsetStr,
                    "rotation": r.RotationPolicy,
                    "family":   fk
                })
            cfg_key = "CBP_{}".format(doc.Title)
            cfg = script.get_config(cfg_key)
            cfg.set_option("saved_rules", json.dumps(data))
            script.save_config()
            show_info("Saved {} rule(s).".format(len(data)), title="Rules Saved")
        except Exception as e:
            show_warning("Could not save rules: " + str(e), title="Save Error")

    def _on_load_rules(self, sender, args):
        try:
            cfg_key = "CBP_{}".format(doc.Title)
            cfg  = script.get_config(cfg_key)
            raw  = cfg.get_option("saved_rules", "[]")
            data = json.loads(raw)
            if not data:
                show_info("No saved rules found.", title="Load Rules")
                return
            self.rules = []
            for i, rd in enumerate(data):
                r = MappingRule(i + 1)
                r.Layer          = rd.get("layer", "")
                r.Category       = rd.get("category", "Lighting Fixtures")
                r.OffsetStr      = rd.get("offset", "0")
                r.RotationPolicy = rd.get("rotation", "0")
                fk = rd.get("family", "")
                if fk and fk in self.family_map:
                    r.FamilyType = self.family_map[fk]
                self.rules.append(r)
            self._refresh_rules_list()
            if self.rules:
                self.lstRules.SelectedIndex = 0
            show_info("Loaded {} rule(s).".format(len(data)), title="Rules Loaded")
        except Exception as e:
            show_warning("Could not load rules: " + str(e), title="Load Error")

    # ── Rule Selection / Detail Changes ────────────────────────────────────
    def _on_rule_selected(self, sender, args):
        sel = self.lstRules.SelectedItem
        self.current_rule = sel
        if not sel:
            self.gridRuleDetails.IsEnabled = False
            return

        self.gridRuleDetails.IsEnabled = True
        self._unsub_detail()

        self.cmbRuleLayer.SelectedItem = sel.Layer
        self.cmbRuleCategory.SelectedItem = sel.Category
        self._load_families_for_category(sel.Category)

        if sel.FamilyType:
            try:
                fn = sel.FamilyType.FamilyName if hasattr(sel.FamilyType, 'FamilyName') else ""
                tn = get_element_name(sel.FamilyType)
                self.cmbRuleFamily.SelectedItem = "{} : {}".format(fn, tn)
            except:
                self.cmbRuleFamily.SelectedIndex = -1
        else:
            self.cmbRuleFamily.SelectedIndex = -1

        self.txtRuleOffset.Text = sel.OffsetStr

        for item in self.cmbRuleRotation.Items:
            val = str(item.Content) if hasattr(item, 'Content') else str(item)
            if val == str(sel.RotationPolicy):
                self.cmbRuleRotation.SelectedItem = item
                break

        self._resub_detail()

    def _on_detail_changed(self, sender, args):
        if not self.current_rule: return
        self.current_rule.Layer = self.cmbRuleLayer.SelectedItem or ""
        disp = self.cmbRuleFamily.SelectedItem
        self.current_rule.FamilyType = self.family_map.get(disp) if disp else None
        self.current_rule.OffsetStr  = self.txtRuleOffset.Text
        if self.cmbRuleRotation.SelectedItem:
            item = self.cmbRuleRotation.SelectedItem
            self.current_rule.RotationPolicy = str(item.Content) if hasattr(item, 'Content') else str(item)
        else:
            self.current_rule.RotationPolicy = "0"
        idx = self.lstRules.SelectedIndex
        self._refresh_rules_list()
        self.lstRules.SelectedIndex = idx

    def _on_category_changed(self, sender, args):
        if not self.current_rule: return
        self.current_rule.Category   = self.cmbRuleCategory.SelectedItem
        self.current_rule.FamilyType = None
        self._load_families_for_category(self.current_rule.Category)
        self._on_detail_changed(sender, args)

    def _load_families_for_category(self, cat_name):
        names = [
            n for n, c in self.family_category_map.items()
            if cat_name == "All Categories" or c == cat_name
        ]
        self.cmbRuleFamily.ItemsSource = sorted(names)

    def _unsub_detail(self):
        self.cmbRuleLayer.SelectionChanged    -= self._on_detail_changed
        self.cmbRuleCategory.SelectionChanged -= self._on_category_changed
        self.cmbRuleFamily.SelectionChanged   -= self._on_detail_changed
        self.txtRuleOffset.TextChanged        -= self._on_detail_changed
        self.cmbRuleRotation.SelectionChanged -= self._on_detail_changed

    def _resub_detail(self):
        self.cmbRuleLayer.SelectionChanged    += self._on_detail_changed
        self.cmbRuleCategory.SelectionChanged += self._on_category_changed
        self.cmbRuleFamily.SelectionChanged   += self._on_detail_changed
        self.txtRuleOffset.TextChanged        += self._on_detail_changed
        self.cmbRuleRotation.SelectionChanged += self._on_detail_changed

    # ── Validation ─────────────────────────────────────────────────────────
    def _valid_rules(self):
        return [r for r in self.rules if r.Layer and r.FamilyType]

    # ── Level Resolution ───────────────────────────────────────────────────
    def _get_selected_level(self):
        try:
            name = self.cmbLevel.SelectedItem
            if name:
                for lvl in self._all_levels:
                    if lvl.Name == name:
                        return lvl
        except: pass
        return self._active_level

    def _cache_before_close(self):
        """Snapshot state while window is still alive."""
        self._get_cad_blocks()   # force cache
        try:
            name = self.cmbLevel.SelectedItem
            if name:
                for lvl in self._all_levels:
                    if lvl.Name == name:
                        self._active_level = lvl
                        break
        except: pass

    # ── Placement Helper ───────────────────────────────────────────────────
    def _place_element(self, blk, symbol, level, offset_ft, rot_deg):
        """
        Places family at blk.Point (X,Y) with Z = offset_ft relative to level.
        Level elevation is NOT added; Revit's NewFamilyInstance Z = offset-from-level.
        """
        pt   = XYZ(blk.Point.X, blk.Point.Y, offset_ft)
        inst = doc.Create.NewFamilyInstance(pt, symbol, level, StructuralType.NonStructural)

        final_angle = blk.Angle + math.radians(rot_deg)
        if final_angle != 0:
            axis = Line.CreateUnbound(pt, XYZ.BasisZ)
            ElementTransformUtils.RotateElement(doc, inst.Id, axis, final_angle)
        return inst

    # ── Actions ────────────────────────────────────────────────────────────
    def _on_preview_single(self, sender, args):
        if not self.current_rule or not self.current_rule.Layer or not self.current_rule.FamilyType:
            show_warning("Please complete the current rule first.", title="Incomplete Rule")
            return
        self._cache_before_close()
        self.action = "PREVIEW_SINGLE"
        self.Close()

    def _on_place(self, sender, args):
        if not self._valid_rules():
            show_warning("Please complete at least one rule (Layer + Family).", title="Rule Required")
            return
        self.do_place_all()

    # ── Do Preview ─────────────────────────────────────────────────────────
    def do_preview(self, single_rule_only=False):
        valid = self._valid_rules()
        if single_rule_only and self.current_rule:
            valid = [r for r in valid if r.Index == self.current_rule.Index]

        all_blocks = self._get_cad_blocks()
        if not all_blocks or not valid:
            return False

        level = self._get_selected_level()
        if not level:
            show_error("Cannot determine Level. Please open a Floor Plan view.", title="View Error")
            return False

        self.preview_element_ids = []
        try:
            with SafeTransaction(doc, "CBP Preview"):
                for rule in valid:
                    blocks = [b for b in all_blocks if b.Layer == rule.Layer]
                    if not blocks: continue
                    symbol = rule.FamilyType
                    if not symbol.IsActive: symbol.Activate()
                    try:    offset_ft = mm_to_ft(float(rule.OffsetStr))
                    except: offset_ft = 0.0
                    try:    rot_deg = float(rule.RotationPolicy)
                    except: rot_deg = 0.0
                    try:
                        inst = self._place_element(blocks[0], symbol, level, offset_ft, rot_deg)
                        self.preview_element_ids.append(inst.Id)
                    except Exception as e:
                        print("Preview error: " + str(e))
                doc.Regenerate()
        except Exception as e:
            print("Preview tx error: " + str(e))
            return False

        if self.preview_element_ids:
            uidoc    = get_uidoc()
            id_list  = List[ElementId](self.preview_element_ids)
            uidoc.Selection.SetElementIds(id_list)
            uidoc.ShowElements(id_list)
            return True
        return False

    def delete_previews(self):
        if self.preview_element_ids:
            with SafeTransaction(doc, "CBP Delete Previews"):
                for eid in self.preview_element_ids:
                    try: doc.Delete(eid)
                    except: pass
            self.preview_element_ids = []

    # ── Do Place All ───────────────────────────────────────────────────────
    def do_place_all(self):
        valid      = self._valid_rules()
        all_blocks = self._get_cad_blocks()
        if not all_blocks or not valid: return

        level = self._get_selected_level()
        if not level:
            show_error("Cannot determine Level. Please open a Floor Plan view.", title="View Error")
            return

        valid_layers  = set(r.Layer for r in valid)
        total_blocks  = sum(1 for b in all_blocks if b.Layer in valid_layers)
        if total_blocks == 0:
            show_warning("No CAD blocks found for the selected rules.", title="No Elements Found")
            return

        self.btnPlace.IsEnabled = False
        self.btnClose.IsEnabled = False
        self.progressBar.Visibility = Visibility.Visible
        self.progressBar.Value = 0
        self.txtStatus.Text = "Initializing CAD Block placement..."
        do_events()

        placed_count = 0
        failed_count = 0
        all_placed   = List[ElementId]()

        try:
            # Transaction 1: Activate + Place
            with SafeTransaction(doc, "CBP Place Families"):
                for rule in valid:
                    if not rule.FamilyType.IsActive:
                        rule.FamilyType.Activate()
                doc.Regenerate()

                current = 0
                for rule in valid:
                    blocks = [b for b in all_blocks if b.Layer == rule.Layer]
                    if not blocks: continue

                    symbol = rule.FamilyType
                    try:    offset_ft = mm_to_ft(float(rule.OffsetStr))
                    except: offset_ft = 0.0
                    try:    rot_deg = float(rule.RotationPolicy)
                    except: rot_deg = 0.0

                    for blk in blocks:
                        try:
                            inst = self._place_element(blk, symbol, level, offset_ft, rot_deg)
                            if inst:
                                all_placed.Add(inst.Id)
                                placed_count += 1
                        except Exception as e:
                            failed_count += 1
                            print("Place error: " + str(e))
                        current += 1
                        pct = int((float(current) / total_blocks) * 100)
                        self.progressBar.Value = pct
                        self.txtStatus.Text = "Placing {} ({}/{} elements)...".format(rule.Layer, current, total_blocks)
                        do_events()

            self.progressBar.Value = 100
            self.txtStatus.Text = "Completed: {} placed, {} failed.".format(placed_count, failed_count)
            do_events()

        except Exception as e:
            show_error("Placement failed: " + str(e), title="Placement Error")
            return
        finally:
            self.progressBar.Visibility = Visibility.Collapsed
            self.btnPlace.IsEnabled = True
            self.btnClose.IsEnabled = True

        if placed_count > 0:
            uidoc = get_uidoc()
            uidoc.Selection.SetElementIds(all_placed)
            uidoc.ShowElements(all_placed)
            dlg = SummaryWindow(placed_count, failed_count)
            dlg.ShowDialog()
            self.action = "DONE"
            self.Close()
        else:
            show_warning("No elements were placed.", title="Placement Notice")


# ==============================================================================
# SUB-DIALOGS
# ==============================================================================
class PreviewAlertWindow(forms.WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(os.path.dirname(__file__), "preview_alert.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        setup_window(self)
        self.result = "Edit Rules"
        self.btnEdit.Click  += self._on_edit
        self.btnPlace.Click += self._on_place

    def _on_edit(self, sender, args):
        self.result = "Edit Rules"
        self.Close()

    def _on_place(self, sender, args):
        self.result = "Place All"
        self.Close()


class SummaryWindow(forms.WPFWindow):
    def __init__(self, placed, failed):
        xaml_path = os.path.join(os.path.dirname(__file__), "summary_alert.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        setup_window(self)
        self.txtPlaced.Text = str(placed)
        self.txtFailed.Text = str(failed)
        if failed > 0:
            self.txtFailed.Foreground = SolidColorBrush(Color.FromRgb(239, 68, 68))
        self.btnOk.Click += lambda s, a: self.Close()


# ==============================================================================
# EXECUTION LOOP
# ==============================================================================
try:
    SAVED_RULES = []

    while True:
        win = CadBlockPlacerWindow(SAVED_RULES)
        win.ShowDialog()

        if not hasattr(win, 'action') or win.action == "CANCEL":
            break

        SAVED_RULES = win.rules

        if win.action == "PREVIEW_SINGLE":
            ok = win.do_preview(single_rule_only=True)
            if ok:
                alert = PreviewAlertWindow()
                alert.ShowDialog()
                win.delete_previews()
                if alert.result == "Place All":
                    win.do_place_all()
                    break
            else:
                show_error("Preview failed or no valid rule.", title="Preview Notice")

        elif win.action == "DONE":
            break
except Exception as e:
    import traceback
    import tempfile
    from py.core import safe_unicode
    try:
        log_path = os.path.join(tempfile.gettempdir(), "cbp_error.log")
        with open(log_path, "w") as f:
            f.write(traceback.format_exc())
    except Exception:
        pass
    print("FATAL ERROR: " + safe_unicode(e))

