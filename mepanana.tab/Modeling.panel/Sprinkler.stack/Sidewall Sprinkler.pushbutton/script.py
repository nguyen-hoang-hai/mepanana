# -*- coding: utf-8 -*-
"""
Sidewall Sprinkler Studio - Dual-Mode Controller Script (Rigid Wall Drop & Flexible Hose)
Part of mepanana.extension.
- Mode 1 (Rigid Wall Drop): Steel pipe drop with 90° horizontal elbow penetrating wall to head.
- Mode 2 (Flexible Hose): NFPA 13 compliant stainless steel corrugated hose to sidewall bracket.
- Dynamic Adaptive UI & Live Reactive Vector Schematic Preview.
"""
import os
import sys

# 1. Dynamic Lib Resolution
cur_dir = os.path.dirname(__file__)
while cur_dir and not os.path.exists(os.path.join(cur_dir, "lib", "py", "auth.py")):
    parent = os.path.dirname(cur_dir)
    if parent == cur_dir:
        break
    cur_dir = parent
lib_path = os.path.join(cur_dir, "lib")
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from py.auth import require_auth, update_ribbon_state, is_authenticated

# 2. Security Gatekeeper
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()

import clr
clr.AddReference("System")
clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
import System
import Autodesk.Revit.Exceptions as RevitExceptions
from System.Windows import Visibility, Point, FontWeights, Thickness, CornerRadius
from System.Windows.Controls import Canvas, TextBlock, Border
from System.Windows.Shapes import Line, Rectangle, Ellipse, Path
from System.Windows.Media import Brushes, SolidColorBrush, Color, PointCollection, DoubleCollection, PenLineCap
from Autodesk.Revit.DB.Plumbing import PipeType, FlexPipeType
from pyrevit import revit, DB, UI, forms
from py.core import get_id_value, safe_unicode, mm_to_ft, ft_to_mm, SafeTransactionGroup
from py.ui import setup_window, show_info, show_warning, show_error, do_events
from py.sprinkler_engine import (
    create_sidewall_connection,
    SIZING_STANDARDS
)

doc   = revit.doc
uidoc = revit.uidoc


# ── Selection Filters ─────────────────────────────────────────────────────────

class PipeSelectionFilter(UI.Selection.ISelectionFilter):
    def AllowElement(self, elem):
        try:
            if elem is not None and elem.Category is not None:
                return get_id_value(elem.Category) == int(DB.BuiltInCategory.OST_PipeCurves)
        except Exception:
            pass
        return False

    def AllowReference(self, ref, point):
        return True


class SprinklerSelectionFilter(UI.Selection.ISelectionFilter):
    def AllowElement(self, elem):
        try:
            if elem is not None and elem.Category is not None:
                return get_id_value(elem.Category) == int(DB.BuiltInCategory.OST_Sprinklers)
        except Exception:
            pass
        return False

    def AllowReference(self, ref, point):
        return True


# ── WPF Window Controller ─────────────────────────────────────────────────────

class SidewallSprinklerWindow(forms.WPFWindow):
    def __init__(self, main_pipe=None, selected_sprinklers=None, is_rigid_mode=True, wall_offset="100", drop_dn_idx=0):
        xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        setup_window(self)

        self.action = None
        self.main_pipe = main_pipe
        self.selected_sprinklers = selected_sprinklers or []

        # Wire UI event handlers
        if hasattr(self, 'btnPickMain'):
            self.btnPickMain.Click += self.OnPickMain
        if hasattr(self, 'btnSelectSprinklers'):
            self.btnSelectSprinklers.Click += self.OnSelectSprinklers
        if hasattr(self, 'btnGenerate'):
            self.btnGenerate.Click += self.OnGenerate
        if hasattr(self, 'btnClose'):
            self.btnClose.Click += self.OnClose

        # Wire Mode switchers
        if hasattr(self, 'rbRigid'):
            self.rbRigid.Checked += self.OnModeChanged
        if hasattr(self, 'rbFlex'):
            self.rbFlex.Checked += self.OnModeChanged

        # Wire Live Reactivity inputs
        if hasattr(self, 'txtWallOffset'):
            self.txtWallOffset.TextChanged += self.OnInputChanged
        if hasattr(self, 'cmbDropSize'):
            self.cmbDropSize.SelectionChanged += self.OnInputChanged

        # Restore Mode
        if hasattr(self, 'rbRigid') and hasattr(self, 'rbFlex'):
            if is_rigid_mode:
                self.rbRigid.IsChecked = True
            else:
                self.rbFlex.IsChecked = True

        # Restore Main Pipe UI state
        if self.main_pipe:
            try:
                size_param = self.main_pipe.get_Parameter(DB.BuiltInParameter.RBS_CALCULATED_SIZE)
                size_str = size_param.AsString() if size_param else "Pipe"
                self.txtMainPipeStatus.Text = u"Pipe #{} ({})".format(get_id_value(self.main_pipe), size_str)
                self.txtMainPipeStatus.Foreground = Brushes.ForestGreen
            except Exception:
                pass

        # Restore Sprinklers UI state
        if self.selected_sprinklers:
            self.txtSprinklerStatus.Text = u"{} sidewall heads selected".format(len(self.selected_sprinklers))
            self.txtSprinklerStatus.Foreground = Brushes.ForestGreen

        self.UpdateSchematicPreview()

    def OnModeChanged(self, sender, args):
        self.UpdateSchematicPreview()

    def OnInputChanged(self, sender, args):
        self.UpdateSchematicPreview()

    def UpdateSchematicPreview(self):
        """Draws dynamic vector schematic on canvasPreview reflecting exact dimensions."""
        if not hasattr(self, 'canvasPreview') or self.canvasPreview is None:
            return

        canvas = self.canvasPreview
        canvas.Children.Clear()

        is_rigid = self.rbRigid.IsChecked if hasattr(self, 'rbRigid') else True
        offset_str = self.txtWallOffset.Text.strip() if hasattr(self, 'txtWallOffset') else "100"
        drop_str = "DN25" if (hasattr(self, 'cmbDropSize') and self.cmbDropSize.SelectedIndex == 0) else "DN32"

        if hasattr(self, 'txtPreviewTag'):
            self.txtPreviewTag.Text = u"⚡ Mode: Rigid Wall Drop" if is_rigid else u"⚡ Mode: Flexible Hose"

        # Theme Brushes
        pipe_brush = SolidColorBrush(Color.FromRgb(59, 130, 246))      # Blue #3B82F6
        fitting_brush = SolidColorBrush(Color.FromRgb(30, 64, 175))    # Dark Blue #1E40AF
        spray_cyan = SolidColorBrush(Color.FromRgb(6, 182, 212))       # Cyan #06B6D4
        head_gold = SolidColorBrush(Color.FromRgb(234, 179, 8))        # Brass Gold #EAB308
        wall_brush = SolidColorBrush(Color.FromRgb(148, 163, 184))     # Wall Gray #94A3B8
        ceiling_brush = SolidColorBrush(Color.FromRgb(203, 213, 225))  # Ceiling Slate #CBD5E1

        badge_gray_bg = SolidColorBrush(Color.FromRgb(241, 245, 249))
        badge_gray_border = SolidColorBrush(Color.FromRgb(203, 213, 225))
        badge_gray_fg = SolidColorBrush(Color.FromRgb(71, 85, 105))

        def add_line(x1, y1, x2, y2, brush, thickness=2, dash=None, rounded=True):
            l = Line()
            l.X1 = x1; l.Y1 = y1; l.X2 = x2; l.Y2 = y2
            l.Stroke = brush
            l.StrokeThickness = thickness
            if rounded:
                l.StrokeStartLineCap = PenLineCap.Round
                l.StrokeEndLineCap = PenLineCap.Round
            if dash:
                try:
                    if isinstance(dash, (list, tuple)):
                        l.StrokeDashArray = DoubleCollection([float(v) for v in dash])
                    else:
                        l.StrokeDashArray = DoubleCollection([3.0, 3.0])
                except Exception:
                    pass
            canvas.Children.Add(l)
            return l

        def add_badge(text, x, y, bg, border, fg):
            b = Border()
            b.Background = bg
            b.BorderBrush = border
            b.BorderThickness = Thickness(1)
            b.CornerRadius = CornerRadius(4)
            b.Padding = Thickness(6, 2, 6, 2)

            tb = TextBlock()
            tb.Text = text
            tb.FontSize = 10.5
            tb.FontWeight = FontWeights.Bold
            tb.Foreground = fg
            b.Child = tb

            Canvas.SetLeft(b, x)
            Canvas.SetTop(b, y)
            canvas.Children.Add(b)
            return b

        def add_circle(cx, cy, r, fill, stroke, thickness=1.5):
            el = Ellipse()
            el.Width = r * 2; el.Height = r * 2
            el.Fill = fill
            el.Stroke = stroke
            el.StrokeThickness = thickness
            Canvas.SetLeft(el, cx - r)
            Canvas.SetTop(el, cy - r)
            canvas.Children.Add(el)
            return el

        # 1. Ceiling Slab Line at Y=22
        add_line(15, 22, 360, 22, ceiling_brush, 3)
        add_badge("Ceiling / Slab Deck", 20, 6, badge_gray_bg, badge_gray_border, badge_gray_fg)

        # 2. Vertical Wall Line at X=310
        add_line(310, 22, 310, 138, wall_brush, 8)
        add_badge("Wall / Partition", 260, 6, badge_gray_bg, badge_gray_border, badge_gray_fg)

        # 3. Supply Pipe near ceiling (X=65, Y=40)
        add_line(25, 40, 95, 40, pipe_brush, 9)
        add_circle(65, 40, 6, fitting_brush, pipe_brush, 1.5)
        add_badge("Supply Pipe", 20, 62, badge_gray_bg, badge_gray_border, badge_gray_fg)

        # 4. Sidewall Head mounted on Wall (X=304, Y=80)
        add_line(304, 80, 294, 80, fitting_brush, 4)
        add_circle(292, 80, 4, head_gold, pipe_brush, 1.2)
        add_line(290, 72, 290, 88, head_gold, 2.5)

        # Crescent horizontal spray out into room (leftward)
        add_line(288, 80, 215, 70, spray_cyan, 1.5)
        add_line(288, 80, 205, 80, spray_cyan, 1.8)
        add_line(288, 80, 218, 92, spray_cyan, 1.5)

        # Deflector badge placed cleanly in lower-middle zone
        add_badge("Sidewall Deflector", 140, 118, badge_gray_bg, badge_gray_border, badge_gray_fg)
        add_line(235, 118, 288, 86, badge_gray_border, 1, dash=[2.0, 2.0])

        if is_rigid:
            # ── MODE 1: RIGID STEEL DROP ──
            add_line(65, 40, 304, 40, pipe_brush, 4.5)
            add_circle(304, 40, 5, fitting_brush, pipe_brush, 1.5)
            add_line(304, 40, 304, 80, pipe_brush, 4)
            add_circle(304, 80, 5, fitting_brush, pipe_brush, 1.5)
            add_badge("90° Wall Elbow (" + drop_str + ")", 115, 48, badge_gray_bg, badge_gray_border, pipe_brush)

        else:
            # ── MODE 2: FLEXIBLE HOSE TO WALL ──
            coral_brush = SolidColorBrush(Color.FromRgb(248, 113, 113))
            p0 = (65.0, 40.0)
            p1 = (160.0, 40.0)
            p2 = (240.0, 80.0)
            p3 = (294.0, 80.0)

            for s_idx in range(25):
                t = float(s_idx) / 24.0
                t_next = float(s_idx + 1) / 24.0
                x1 = (1-t)**3 * p0[0] + 3*(1-t)**2 * t * p1[0] + 3*(1-t) * t**2 * p2[0] + t**3 * p3[0]
                y1 = (1-t)**3 * p0[1] + 3*(1-t)**2 * t * p1[1] + 3*(1-t) * t**2 * p2[1] + t**3 * p3[1]
                x2 = (1-t_next)**3 * p0[0] + 3*(1-t_next)**2 * t_next * p1[0] + 3*(1-t_next) * t_next**2 * p2[0] + t_next**3 * p3[0]
                y2 = (1-t_next)**3 * p0[1] + 3*(1-t_next)**2 * t_next * p1[1] + 3*(1-t_next) * t_next**2 * p2[1] + t_next**3 * p3[1]
                add_line(x1, y1, x2, y2, coral_brush, 5)

            add_badge("🌀 Flex Hose (" + drop_str + ")", 125, 48, badge_gray_bg, badge_gray_border, coral_brush)

    def OnPickMain(self, sender, args):
        self.action = "PICK_MAIN"
        self.Close()

    def OnSelectSprinklers(self, sender, args):
        self.action = "SELECT_SPRINKLERS"
        self.Close()

    def OnGenerate(self, sender, args):
        if not self.main_pipe:
            show_warning(u"Please select a Supply Pipe first!", "Missing Pipe")
            return

        if not self.selected_sprinklers:
            show_warning(u"Please select at least 1 Sidewall Sprinkler head!", "Missing Sprinklers")
            return

        self.action = "GENERATE"
        self.Close()

    def OnClose(self, sender, args):
        self.action = "CLOSE"
        self.Close()


# ── Interactive Selection & Execution Loop ───────────────────────────────────

def run():
    main_pipe = None
    selected_sprinklers = []
    is_rigid_mode = True
    wall_offset = "100"
    drop_dn_idx = 0

    while True:
        win = SidewallSprinklerWindow(
            main_pipe=main_pipe,
            selected_sprinklers=selected_sprinklers,
            is_rigid_mode=is_rigid_mode,
            wall_offset=wall_offset,
            drop_dn_idx=drop_dn_idx
        )
        win.ShowDialog()

        is_rigid_mode = hasattr(win, 'rbRigid') and (win.rbRigid.IsChecked == True)
        wall_offset = win.txtWallOffset.Text if hasattr(win, 'txtWallOffset') else "100"
        drop_dn_idx = win.cmbDropSize.SelectedIndex if hasattr(win, 'cmbDropSize') else 0

        if win.action == "PICK_MAIN":
            try:
                ref = uidoc.Selection.PickObject(
                    UI.Selection.ObjectType.Element,
                    PipeSelectionFilter(),
                    "Select a Supply Pipe along Corridor or Room (OST_PipeCurves)"
                )
                if ref:
                    elem = doc.GetElement(ref.ElementId)
                    if elem:
                        main_pipe = elem
            except RevitExceptions.OperationCanceledException:
                pass
            except Exception as ex:
                show_warning(u"Pipe Selection:\n{}".format(safe_unicode(ex)), "Selection Notice")

        elif win.action == "SELECT_SPRINKLERS":
            try:
                elems = uidoc.Selection.PickElementsByRectangle(
                    SprinklerSelectionFilter(),
                    "Drag a rectangle window to select Sidewall Sprinklers (OST_Sprinklers)"
                )
                if elems:
                    selected_sprinklers = list(elems)
            except RevitExceptions.OperationCanceledException:
                pass
            except Exception as ex:
                show_warning(u"Sprinkler Selection:\n{}".format(safe_unicode(ex)), "Selection Notice")

        elif win.action == "GENERATE":
            drop_dn = 25 if drop_dn_idx == 0 else 32

            offset_val = 100.0
            try:
                offset_val = float(wall_offset.strip())
            except Exception:
                offset_val = 100.0

            pipe_type_id = main_pipe.PipeType.Id

            flex_pipe_type_id = None
            if not is_rigid_mode:
                flex_types = list(DB.FilteredElementCollector(doc).OfClass(FlexPipeType).ToElements())
                if flex_types:
                    flex_pipe_type_id = flex_types[0].Id
                else:
                    show_warning(u"No Flexible Pipe Type found in project. Falling back to Rigid Steel.", "Notice")
                    is_rigid_mode = True

            success_count = 0
            fail_count = 0
            errors = []

            with SafeTransactionGroup(doc, "Create Sidewall Sprinklers"):
                t = DB.Transaction(doc, "Generate Sidewall Connections")
                t.Start()
                try:
                    for s_idx, spk in enumerate(selected_sprinklers):
                        ok, res = create_sidewall_connection(
                            doc,
                            spk,
                            main_pipe,
                            pipe_type_id,
                            flex_pipe_type_id=flex_pipe_type_id,
                            is_flex=(not is_rigid_mode),
                            diameter_mm=drop_dn,
                            wall_offset_mm=offset_val
                        )
                        if ok:
                            success_count += 1
                        else:
                            fail_count += 1
                            errors.append(u"Head #{}: {}".format(get_id_value(spk), res))

                    t.Commit()
                except Exception as ex:
                    t.RollBack()
                    show_error(u"Generation Error:\n{}".format(safe_unicode(ex)), "Error")
                    break

            msg = u"Sidewall Sprinkler Connections Completed!\n\n" \
                  u"✅ Successfully connected: {} heads\n" \
                  u"❌ Failed / Skipped: {} heads".format(success_count, fail_count)

            if fail_count > 0 and errors:
                msg += u"\n\nDetails:\n" + u"\n".join(errors[:5])

            show_info(msg, "Sidewall Sprinkler Results")
            break

        elif win.action == "CLOSE" or win.action is None:
            break


# ── Launch Entry ──────────────────────────────────────────────────────────────
run()