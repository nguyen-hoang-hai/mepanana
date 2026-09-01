#! python3
# -*- coding: utf-8 -*-
"""
Pendent Sprinkler Connector - Controller Script
Part of mepanana.extension.
Matches exact CAD Detail:
- Individual Riser Nipple from top of Crossmain for each branch/armover (or horizontal when Riser=0)
- Stepped hydraulic sizing strictly following TCVN 7336:2021
- Live Interactive Vector Schematic Preview with Pill Badge Callout System
- Intermediate Tee drops & Final 90° Elbow drop to Pendent Sprinklers
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
from System.Windows.Shapes import Line, Rectangle, Ellipse, Polygon
from System.Windows.Media import Brushes, SolidColorBrush, Color, PointCollection, DoubleCollection, PenLineCap
from pyrevit import revit, DB, UI, forms
from py.core import get_id_value, safe_unicode
from py.ui import setup_window, show_info, show_warning, show_error
from py.sprinkler_engine import (
    cluster_sprinklers_by_main_pipe,
    generate_sprinkler_network,
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

class PendentSprinklerWindow(forms.WPFWindow):
    def __init__(self, main_pipe=None, selected_sprinklers=None, riser_height="300", drop_dn_idx=0):
        xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        setup_window(self)

        self.action = None
        self.main_pipe = main_pipe
        self.selected_sprinklers = selected_sprinklers or []

        # Wire event handlers
        if hasattr(self, 'btnPickMain'):
            self.btnPickMain.Click += self.OnPickMain
        if hasattr(self, 'btnSelectSprinklers'):
            self.btnSelectSprinklers.Click += self.OnSelectSprinklers
        if hasattr(self, 'btnGenerate'):
            self.btnGenerate.Click += self.OnGenerate
        if hasattr(self, 'btnClose'):
            self.btnClose.Click += self.OnClose

        # Wire Live Reactivity inputs
        if hasattr(self, 'txtRiserHeight'):
            self.txtRiserHeight.TextChanged += self.OnInputChanged
        if hasattr(self, 'cmbDropSize'):
            self.cmbDropSize.SelectionChanged += self.OnInputChanged

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
            self.txtSprinklerStatus.Text = u"{} sprinkler heads selected".format(len(self.selected_sprinklers))
            self.txtSprinklerStatus.Foreground = Brushes.ForestGreen

        # Restore inputs
        if hasattr(self, 'txtRiserHeight'):
            self.txtRiserHeight.Text = str(riser_height)

        if hasattr(self, 'cmbDropSize') and self.cmbDropSize.Items.Count > drop_dn_idx:
            self.cmbDropSize.SelectedIndex = drop_dn_idx

        # Render initial preview cleanly
        try:
            self.UpdatePreview()
        except Exception:
            pass

    def OnInputChanged(self, sender, args):
        try:
            self.UpdatePreview()
        except Exception:
            pass

    def UpdatePreview(self):
        """Renders high-clarity CAD blueprint schematic with Pill Badge Callouts."""
        if not hasattr(self, 'canvasPreview') or not self.canvasPreview:
            return

        canvas = self.canvasPreview
        canvas.Children.Clear()

        # Elegant color palette
        pipe_brush = SolidColorBrush(Color.FromRgb(239, 68, 68))      # Crimson Red
        fitting_brush = SolidColorBrush(Color.FromRgb(51, 65, 85))   # Slate Dark
        accent_blue = SolidColorBrush(Color.FromRgb(37, 99, 235))    # Royal Blue
        dim_gray = SolidColorBrush(Color.FromRgb(100, 116, 139))     # Slate Dim
        head_gold = SolidColorBrush(Color.FromRgb(245, 158, 11))     # Amber Head
        spray_blue = SolidColorBrush(Color.FromArgb(160, 59, 130, 246)) # Translucent Spray

        # Pill Badge Brushes
        badge_blue_bg = SolidColorBrush(Color.FromRgb(239, 246, 255))
        badge_blue_border = SolidColorBrush(Color.FromRgb(191, 219, 254))
        badge_blue_fg = SolidColorBrush(Color.FromRgb(29, 78, 216))

        badge_gray_bg = SolidColorBrush(Color.FromRgb(248, 250, 252))
        badge_gray_border = SolidColorBrush(Color.FromRgb(226, 232, 240))
        badge_gray_fg = SolidColorBrush(Color.FromRgb(71, 85, 105))

        # Parse inputs
        riser_h_val = 300.0
        try:
            if hasattr(self, 'txtRiserHeight') and self.txtRiserHeight.Text:
                riser_h_val = float(self.txtRiserHeight.Text.strip())
        except Exception:
            riser_h_val = 300.0

        drop_str = "DN25"
        if hasattr(self, 'cmbDropSize') and self.cmbDropSize.SelectedItem:
            txt = str(self.cmbDropSize.SelectedItem.Content)
            if "32" in txt:
                drop_str = "DN32"

        def add_line(x1, y1, x2, y2, stroke, thickness, dash=False, rounded=True):
            line = Line()
            line.X1 = x1; line.Y1 = y1; line.X2 = x2; line.Y2 = y2
            line.Stroke = stroke
            line.StrokeThickness = thickness
            if rounded:
                line.StrokeStartLineCap = PenLineCap.Round
                line.StrokeEndLineCap = PenLineCap.Round
            if dash:
                line.StrokeDashArray = DoubleCollection([3.0, 3.0])
            canvas.Children.Add(line)
            return line

        def add_badge(text, x, y, bg_brush, border_brush, fg_brush, font_size=9.5):
            b = Border()
            b.Background = bg_brush
            b.BorderBrush = border_brush
            b.BorderThickness = Thickness(1)
            b.CornerRadius = CornerRadius(3)
            b.Padding = Thickness(4, 1, 4, 1)

            tb = TextBlock()
            tb.Text = text
            tb.FontSize = font_size
            tb.FontWeight = FontWeights.SemiBold
            tb.Foreground = fg_brush
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

        def add_sprinkler_head(cx, cy):
            add_line(cx - 3, cy, cx + 3, cy, fitting_brush, 2)
            add_circle(cx, cy + 4, 3.5, head_gold, pipe_brush, 1.2)
            add_line(cx - 7, cy + 8.5, cx + 7, cy + 8.5, head_gold, 2.2)
            add_line(cx - 6, cy + 11, cx - 10, cy + 18, spray_blue, 1.2)
            add_line(cx, cy + 11, cx, cy + 19, spray_blue, 1.2)
            add_line(cx + 6, cy + 11, cx + 10, cy + 18, spray_blue, 1.2)

        if riser_h_val > 30.0:
            # ── MODE A: Elevated Branch with Riser Nipple ──
            # 1. Main Pipe at bottom
            add_line(25, 116, 135, 116, pipe_brush, 9)
            add_badge("Main Pipe", 42, 126, badge_gray_bg, badge_gray_border, badge_gray_fg)

            # 2. Riser Nipple going up
            add_line(80, 116, 80, 42, pipe_brush, 6)

            # Dimension on Riser
            add_line(48, 116, 48, 42, accent_blue, 1, dash=True)
            add_line(43, 42, 53, 42, accent_blue, 1.5)
            add_line(43, 116, 53, 116, accent_blue, 1.5)
            add_badge("H = {}mm".format(int(riser_h_val)), 6, 72, badge_blue_bg, badge_blue_border, badge_blue_fg)

            # 3. Top Tee Fitting
            add_circle(80, 42, 6.5, fitting_brush, pipe_brush, 1.5)

            # 4. Spool Pipe (120mm) + Reducer
            add_line(86, 42, 138, 42, pipe_brush, 5.5)
            add_circle(138, 42, 5, fitting_brush, pipe_brush, 1)
            add_badge("120mm Spool + Reducer", 92, 16, badge_blue_bg, badge_blue_border, badge_blue_fg)
            add_line(135, 27, 138, 38, badge_blue_border, 1) # Leader line

            # 5. Stepped Branch Pipe (DN32) to Sprinkler 1
            add_line(143, 42, 252, 42, pipe_brush, 4)
            add_circle(252, 42, 5, fitting_brush, pipe_brush, 1)

            # Drop Pipe 1
            drop_w = 3.5 if drop_str == "DN32" else 2.5
            add_line(252, 47, 252, 94, pipe_brush, drop_w)
            add_sprinkler_head(252, 95)
            add_badge("Drop " + drop_str, 260, 68, badge_gray_bg, badge_gray_border, badge_gray_fg)

            # 6. Branch to Final Sprinkler 2 (DN25)
            add_line(257, 42, 350, 42, pipe_brush, 2.8)
            add_circle(350, 42, 5, fitting_brush, pipe_brush, 1)
            add_line(350, 47, 350, 94, pipe_brush, drop_w)
            add_sprinkler_head(350, 95)
            add_badge("End 90° Elbow", 295, 16, badge_gray_bg, badge_gray_border, badge_gray_fg)
            add_line(338, 27, 350, 38, badge_gray_border, 1) # Leader line

        else:
            # ── MODE B: Horizontal Branch (Riser = 0) ──
            add_line(25, 82, 105, 82, pipe_brush, 9)
            add_badge("Main Pipe", 35, 96, badge_gray_bg, badge_gray_border, badge_gray_fg)

            # Horizontal Tee on Main
            add_circle(105, 82, 7.5, fitting_brush, pipe_brush, 1.8)
            add_badge("Horizontal Tee (Riser = 0)", 16, 16, badge_blue_bg, badge_blue_border, badge_blue_fg)
            add_line(95, 28, 105, 75, badge_blue_border, 1) # Clear leader line to Tee

            # 120mm Spool + Reducer
            add_line(112, 82, 162, 82, pipe_brush, 5.5)
            add_circle(162, 82, 5, fitting_brush, pipe_brush, 1)
            add_badge("120mm Spool + Reducer", 145, 42, badge_blue_bg, badge_blue_border, badge_blue_fg)
            add_line(160, 54, 162, 75, badge_blue_border, 1) # Clear leader line to Spool

            # Branch to Drop 1
            add_line(167, 82, 258, 82, pipe_brush, 4)
            add_circle(258, 82, 5, fitting_brush, pipe_brush, 1)

            drop_w = 3.5 if drop_str == "DN32" else 2.5
            add_line(258, 87, 258, 114, pipe_brush, drop_w)
            add_sprinkler_head(258, 115)
            add_badge("Drop " + drop_str, 266, 92, badge_gray_bg, badge_gray_border, badge_gray_fg)

            # Branch to Drop 2 (End)
            add_line(263, 82, 350, 82, pipe_brush, 2.8)
            add_circle(350, 82, 5, fitting_brush, pipe_brush, 1)
            add_line(350, 87, 350, 114, pipe_brush, drop_w)
            add_sprinkler_head(350, 115)

    def OnPickMain(self, sender, args):
        self.action = "PICK_MAIN"
        self.Close()

    def OnSelectSprinklers(self, sender, args):
        self.action = "SELECT_SPRINKLERS"
        self.Close()

    def OnGenerate(self, sender, args):
        if not self.main_pipe:
            show_warning(u"Please select a Main Pipe first!", "Missing Main Pipe")
            return

        if not self.selected_sprinklers:
            show_warning(u"Please select at least 1 Sprinkler head!", "Missing Sprinklers")
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
    riser_height = "300"
    drop_dn_idx = 0

    while True:
        win = PendentSprinklerWindow(
            main_pipe=main_pipe,
            selected_sprinklers=selected_sprinklers,
            riser_height=riser_height,
            drop_dn_idx=drop_dn_idx
        )
        win.ShowDialog()

        if win.action == "PICK_MAIN":
            riser_height = win.txtRiserHeight.Text if hasattr(win, 'txtRiserHeight') else "300"
            drop_dn_idx = win.cmbDropSize.SelectedIndex if hasattr(win, 'cmbDropSize') else 0
            try:
                ref = uidoc.Selection.PickObject(
                    UI.Selection.ObjectType.Element,
                    PipeSelectionFilter(),
                    "Select a Main Pipe (OST_PipeCurves)"
                )
                if ref:
                    elem = doc.GetElement(ref.ElementId)
                    if elem:
                        main_pipe = elem
            except RevitExceptions.OperationCanceledException:
                pass
            except Exception as ex:
                show_warning(u"Main Pipe Selection:\n{}".format(safe_unicode(ex)), "Selection Notice")

        elif win.action == "SELECT_SPRINKLERS":
            riser_height = win.txtRiserHeight.Text if hasattr(win, 'txtRiserHeight') else "300"
            drop_dn_idx = win.cmbDropSize.SelectedIndex if hasattr(win, 'cmbDropSize') else 0
            try:
                elems = uidoc.Selection.PickElementsByRectangle(
                    SprinklerSelectionFilter(),
                    "Drag a rectangle window to select Sprinklers (OST_Sprinklers)"
                )
                if elems:
                    selected_sprinklers = list(elems)
            except RevitExceptions.OperationCanceledException:
                pass
            except Exception as ex:
                show_warning(u"Sprinkler Selection:\n{}".format(safe_unicode(ex)), "Selection Notice")

        elif win.action == "GENERATE":
            riser_h_val = 300.0
            try:
                if hasattr(win, 'txtRiserHeight') and win.txtRiserHeight.Text:
                    riser_h_val = float(win.txtRiserHeight.Text.strip())
            except Exception:
                riser_h_val = 300.0

            selected_std = "TCVN 7336:2021 (Vietnam Standard)"

            drop_dn = 25
            if hasattr(win, 'cmbDropSize') and win.cmbDropSize.SelectedItem:
                txt = str(win.cmbDropSize.SelectedItem.Content)
                if "32" in txt:
                    drop_dn = 32

            # 1. Analyze and Cluster
            branches = cluster_sprinklers_by_main_pipe(
                main_pipe,
                selected_sprinklers,
                tolerance_mm=300.0
            )
            if not branches:
                show_warning(u"Could not detect any valid branch alignments with the selected Main Pipe.", "Topology Error")
                continue

            # 2. Execute in Revit TransactionGroup (Single Undo Step)
            tg = DB.TransactionGroup(doc, "Generate Pendent Sprinkler Network")
            tg.Start()
            t = DB.Transaction(doc, "Create Pendent Pipes & Fittings")
            try:
                t.Start()
                created_pipes, created_fittings, errors = generate_sprinkler_network(
                    doc,
                    main_pipe,
                    branches,
                    selected_std,
                    riser_height_mm=riser_h_val,
                    drop_dn=drop_dn
                )
                t.Commit()
                tg.Assimilate()

                msg = u"🎉 Pendent Sprinkler Network Created Successfully!\n\n"
                msg += u"• Sizing Standard: TCVN 7336:2021\n"
                msg += u"• Riser Nipple Height: {} mm\n".format(int(riser_h_val))
                msg += u"• Branch lines / Arm-overs created: {}\n".format(len(branches))
                msg += u"• Total Sprinklers connected: {}\n".format(len(selected_sprinklers))
                msg += u"• Pipe segments created: {}\n".format(len(created_pipes))
                msg += u"• Fittings placed: {}\n".format(len(created_fittings))

                if errors:
                    msg += u"\n⚠️ Notices:\n" + u"\n".join([safe_unicode(e) for e in errors[:3]])

                show_info(msg, "Sprinkler Connector Success")
                break

            except Exception as ex:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                if tg.HasStarted() and not tg.HasEnded():
                    tg.RollBack()
                show_error(u"Error while generating network:\n{}".format(safe_unicode(ex)), "Generation Error")
                break

        else:
            break


# ── Launch Entry ──────────────────────────────────────────────────────────────

run()