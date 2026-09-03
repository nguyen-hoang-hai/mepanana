# -*- coding: utf-8 -*-
"""
Upright Sprinkler Studio - Dual-Mode Controller Script (Direct Riser Up & Arm-Over Loop)
Part of mepanana.extension.
- Mode 1 (Direct Riser Up): Vertical nipple rising directly from pipe crown to deflector.
- Mode 2 (Arm-Over Loop): NFPA 13 compliant sediment trap arm-over loop.
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
from Autodesk.Revit.DB.Plumbing import PipeType
from pyrevit import revit, DB, UI, forms
from py.core import get_id_value, safe_unicode, mm_to_ft, ft_to_mm, SafeTransactionGroup
from py.ui import setup_window, show_info, show_warning, show_error, do_events
from py.sprinkler_engine import (
    create_upright_connection,
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

class UprightSprinklerWindow(forms.WPFWindow):
    def __init__(self, main_pipe=None, selected_sprinklers=None, is_direct_mode=True, riser_height="150", drop_dn_idx=0):
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
        if hasattr(self, 'rbDirect'):
            self.rbDirect.Checked += self.OnModeChanged
        if hasattr(self, 'rbArmOver'):
            self.rbArmOver.Checked += self.OnModeChanged

        # Wire Live Reactivity inputs
        if hasattr(self, 'txtRiserHeight'):
            self.txtRiserHeight.TextChanged += self.OnInputChanged
        if hasattr(self, 'cmbDropSize'):
            self.cmbDropSize.SelectionChanged += self.OnInputChanged

        # Restore Mode
        if hasattr(self, 'rbDirect') and hasattr(self, 'rbArmOver'):
            if is_direct_mode:
                self.rbDirect.IsChecked = True
            else:
                self.rbArmOver.IsChecked = True

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
            self.txtSprinklerStatus.Text = u"{} upright heads selected".format(len(self.selected_sprinklers))
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

        is_direct = self.rbDirect.IsChecked if hasattr(self, 'rbDirect') else True
        riser_str = self.txtRiserHeight.Text.strip() if hasattr(self, 'txtRiserHeight') else "150"
        drop_str = "DN25" if (hasattr(self, 'cmbDropSize') and self.cmbDropSize.SelectedIndex == 0) else "DN32"

        if hasattr(self, 'txtPreviewTag'):
            self.txtPreviewTag.Text = u"⚡ Mode: Direct Riser Up" if is_direct else u"⚡ Mode: Arm-Over Loop"

        # Theme Brushes
        pipe_brush = SolidColorBrush(Color.FromRgb(220, 38, 38))       # Vibrant Red #DC2626
        fitting_brush = SolidColorBrush(Color.FromRgb(153, 27, 27))    # Dark Crimson #991B1B
        spray_blue = SolidColorBrush(Color.FromRgb(59, 130, 246))      # Spray Blue #3B82F6
        head_gold = SolidColorBrush(Color.FromRgb(234, 179, 8))        # Brass Gold #EAB308
        green_badge = SolidColorBrush(Color.FromRgb(16, 185, 129))     # Emerald Green #10B981

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
                l.StrokeDashArray = DoubleCollection(dash)
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

        def add_upright_head(cx, cy):
            """Draws upright sprinkler head with deflector on top and umbrella spray."""
            # Fitting base
            add_line(cx - 3, cy, cx + 3, cy, fitting_brush, 2)
            # Glass bulb & frame
            add_circle(cx, cy - 4, 3.5, head_gold, pipe_brush, 1.2)
            # Deflector umbrella plate on top
            add_line(cx - 8, cy - 8.5, cx + 8, cy - 8.5, head_gold, 2.5)
            # Spray discharge pattern (arching outward and downward)
            add_line(cx - 6, cy - 11, cx - 14, cy - 2, spray_blue, 1.2)
            add_line(cx, cy - 12, cx, cy - 16, spray_blue, 1.2)
            add_line(cx + 6, cy - 11, cx + 14, cy - 2, spray_blue, 1.2)

        # 1. Ceiling / Roof Deck at top
        ceiling_brush = SolidColorBrush(Color.FromRgb(203, 213, 225))
        add_line(15, 20, 395, 20, ceiling_brush, 3)
        add_badge("Ceiling / Roof Deck", 20, 6, badge_gray_bg, badge_gray_border, badge_gray_fg)

        # 2. Horizontal Supply Branchline at bottom (Y=116)
        add_line(15, 116, 395, 116, pipe_brush, 8)
        add_badge("Branchline Supply", 20, 126, badge_gray_bg, badge_gray_border, badge_gray_fg)

        if is_direct:
            # ── MODE 1: DIRECT VERTICAL RISER UP ──
            # Crown tee/olet
            add_circle(175, 116, 6, fitting_brush, pipe_brush, 1.5)

            # Vertical riser pipe up
            add_line(175, 116, 175, 52, pipe_brush, 4.5)
            add_circle(175, 52, 4.5, fitting_brush, pipe_brush, 1.2)

            # Upright Sprinkler Head pointing UP
            add_upright_head(175, 50)

            # Badges positioned with zero overlap
            add_badge("Upright Deflector", 210, 24, badge_gray_bg, badge_gray_border, badge_gray_fg)
            add_line(185, 42, 210, 32, badge_gray_border, 1, dash=[2, 2])

            add_badge(u"Riser Nipple (" + drop_str + u", H=" + riser_str + u"mm)", 210, 72, badge_gray_bg, badge_gray_border, green_badge)

        else:
            # ── MODE 2: ARM-OVER LOOP (NFPA 13) ──
            # Takeoff at crown
            add_circle(130, 116, 6, fitting_brush, pipe_brush, 1.5)

            # Vertical riser up to Y=45
            add_line(130, 116, 130, 45, pipe_brush, 4)
            add_circle(130, 45, 4.5, fitting_brush, pipe_brush, 1.2)

            # Horizontal arm from X=130 to X=240 at Y=45
            add_line(130, 45, 240, 45, pipe_brush, 4)
            add_circle(240, 45, 4.5, fitting_brush, pipe_brush, 1.2)

            # Short vertical connection to upright head
            add_line(240, 45, 240, 56, pipe_brush, 3.5)

            # Upright head
            add_upright_head(240, 56)

            # Badges
            add_badge("Arm-Over Loop (NFPA 13)", 140, 18, badge_gray_bg, badge_gray_border, green_badge)
            add_badge("Sediment-Free Nipple", 240, 72, badge_gray_bg, badge_gray_border, badge_gray_fg)

    def OnPickMain(self, sender, args):
        self.action = "PICK_MAIN"
        self.Close()

    def OnSelectSprinklers(self, sender, args):
        self.action = "SELECT_SPRINKLERS"
        self.Close()

    def OnGenerate(self, sender, args):
        if not self.main_pipe:
            show_warning(u"Please select a Pipe first!", "Missing Pipe")
            return

        if not self.selected_sprinklers:
            show_warning(u"Please select at least 1 Upright Sprinkler head!", "Missing Sprinklers")
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
    is_direct_mode = True
    riser_height = "150"
    drop_dn_idx = 0

    while True:
        win = UprightSprinklerWindow(
            main_pipe=main_pipe,
            selected_sprinklers=selected_sprinklers,
            is_direct_mode=is_direct_mode,
            riser_height=riser_height,
            drop_dn_idx=drop_dn_idx
        )
        win.ShowDialog()

        is_direct_mode = hasattr(win, 'rbDirect') and (win.rbDirect.IsChecked == True)
        riser_height = win.txtRiserHeight.Text if hasattr(win, 'txtRiserHeight') else "150"
        drop_dn_idx = win.cmbDropSize.SelectedIndex if hasattr(win, 'cmbDropSize') else 0

        if win.action == "PICK_MAIN":
            try:
                ref = uidoc.Selection.PickObject(
                    UI.Selection.ObjectType.Element,
                    PipeSelectionFilter(),
                    "Select a Branch or Main Pipe (OST_PipeCurves)"
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
                    "Drag a rectangle window to select Upright Sprinklers (OST_Sprinklers)"
                )
                if elems:
                    selected_sprinklers = list(elems)
            except RevitExceptions.OperationCanceledException:
                pass
            except Exception as ex:
                show_warning(u"Sprinkler Selection:\n{}".format(safe_unicode(ex)), "Selection Notice")

        elif win.action == "GENERATE":
            drop_dn = 25 if drop_dn_idx == 0 else 32
            mode_str = "DIRECT" if is_direct_mode else "ARM_OVER"

            riser_h_val = 150.0
            try:
                riser_h_val = float(riser_height.strip())
            except Exception:
                riser_h_val = 150.0

            pipe_type_id = main_pipe.PipeType.Id

            success_count = 0
            fail_count = 0
            errors = []

            with SafeTransactionGroup(doc, "Create Upright Sprinklers"):
                t = DB.Transaction(doc, "Generate Upright Connections")
                t.Start()
                try:
                    for s_idx, spk in enumerate(selected_sprinklers):
                        ok, res = create_upright_connection(
                            doc,
                            spk,
                            main_pipe,
                            pipe_type_id,
                            diameter_mm=drop_dn,
                            mode=mode_str,
                            arm_offset_mm=riser_h_val
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

            msg = u"Upright Sprinkler Connections Completed!\n\n" \
                  u"✅ Successfully connected: {} heads\n" \
                  u"❌ Failed / Skipped: {} heads".format(success_count, fail_count)

            if fail_count > 0 and errors:
                msg += u"\n\nDetails:\n" + u"\n".join(errors[:5])

            show_info(msg, "Upright Sprinkler Results")
            break

        elif win.action == "CLOSE" or win.action is None:
            break


if __name__ == "__main__":
    run()