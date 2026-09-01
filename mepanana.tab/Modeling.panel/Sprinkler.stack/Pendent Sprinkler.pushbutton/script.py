# -*- coding: utf-8 -*-
"""
Pendent Sprinkler Studio - Dual-Mode Controller Script (Flex Hose & Rigid Drop)
Part of mepanana.extension.
- Mode 1 (Flex Hose): NFPA 13 compliant 3D S-Curve Flexible Sprinkler Hose with automatic ΔZ >= 150mm check.
- Mode 2 (Rigid Drop): TCVN 7336 / NFPA 13 Riser Nipple & Stepped Hydraulic Branchlines.
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
from Autodesk.Revit.DB.Plumbing import FlexPipeType, PipeType
from pyrevit import revit, DB, UI, forms
from py.core import get_id_value, safe_unicode, mm_to_ft, ft_to_mm
from py.ui import setup_window, show_info, show_warning, show_error, do_events
from py.sprinkler_engine import (
    cluster_sprinklers_by_main_pipe,
    generate_sprinkler_network,
    create_flex_drop_connection,
    create_rigid_drop_connection,
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
    def __init__(self, main_pipe=None, selected_sprinklers=None, is_flex_mode=True, riser_height="300", drop_dn_idx=0):
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
        if hasattr(self, 'rbFlex'):
            self.rbFlex.Checked += self.OnModeChanged
        if hasattr(self, 'rbRigid'):
            self.rbRigid.Checked += self.OnModeChanged

        # Wire Live Reactivity inputs
        if hasattr(self, 'txtRiserHeight'):
            self.txtRiserHeight.TextChanged += self.OnInputChanged
        if hasattr(self, 'cmbDropSize'):
            self.cmbDropSize.SelectionChanged += self.OnInputChanged

        # Restore Mode
        if hasattr(self, 'rbFlex') and hasattr(self, 'rbRigid'):
            if is_flex_mode:
                self.rbFlex.IsChecked = True
            else:
                self.rbRigid.IsChecked = True

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

        # Update mode UI & initial preview
        self.SyncModeUI()
        try:
            self.UpdatePreview()
        except Exception:
            pass

    def OnModeChanged(self, sender, args):
        self.SyncModeUI()
        try:
            self.UpdatePreview()
        except Exception:
            pass

    def SyncModeUI(self):
        is_flex = hasattr(self, 'rbFlex') and (self.rbFlex.IsChecked == True)
        if hasattr(self, 'panelRiser'):
            self.panelRiser.Opacity = 0.35 if is_flex else 1.0
        if hasattr(self, 'txtRiserHeight'):
            self.txtRiserHeight.IsEnabled = not is_flex
        if hasattr(self, 'lblRiserHeight'):
            self.lblRiserHeight.Opacity = 0.4 if is_flex else 1.0
        if hasattr(self, 'txtModeNote'):
            if is_flex:
                self.txtModeNote.Text = u"* Automatic minimum drop check (ΔZ ≥ 150mm / R ≥ 250mm per NFPA 13)"
            else:
                self.txtModeNote.Text = u"* Stepped hydraulic pipe schedule & riser nipple (TCVN 7336 / NFPA 13)"
        if hasattr(self, 'txtPreviewTag'):
            self.txtPreviewTag.Text = u"⚡ Mode: Flex Hose S-Curve" if is_flex else u"⚡ Mode: Rigid Steel Drop"

    def OnInputChanged(self, sender, args):
        try:
            self.UpdatePreview()
        except Exception:
            pass

    def UpdatePreview(self):
        """Renders high-clarity CAD blueprint schematic for both Flex Hose and Rigid Pipe."""
        if not hasattr(self, 'canvasPreview') or not self.canvasPreview:
            return

        canvas = self.canvasPreview
        canvas.Children.Clear()

        is_flex = hasattr(self, 'rbFlex') and (self.rbFlex.IsChecked == True)

        # Elegant color palette
        pipe_brush = SolidColorBrush(Color.FromRgb(239, 68, 68))        # Crimson Red
        rigid_blue = SolidColorBrush(Color.FromRgb(59, 130, 246))       # Sky Blue
        fitting_brush = SolidColorBrush(Color.FromRgb(51, 65, 85))     # Slate Dark
        dim_gray = SolidColorBrush(Color.FromRgb(100, 116, 139))       # Slate Dim
        head_gold = SolidColorBrush(Color.FromRgb(245, 158, 11))       # Amber Head
        spray_blue = SolidColorBrush(Color.FromArgb(160, 59, 130, 246)) # Translucent Spray

        # Pill Badge Brushes
        badge_red_bg = SolidColorBrush(Color.FromRgb(254, 242, 242))
        badge_red_border = SolidColorBrush(Color.FromRgb(254, 202, 202))
        badge_red_fg = SolidColorBrush(Color.FromRgb(220, 38, 38))

        badge_blue_bg = SolidColorBrush(Color.FromRgb(239, 246, 255))
        badge_blue_border = SolidColorBrush(Color.FromRgb(191, 219, 254))
        badge_blue_fg = SolidColorBrush(Color.FromRgb(29, 78, 216))

        badge_gray_bg = SolidColorBrush(Color.FromRgb(248, 250, 252))
        badge_gray_border = SolidColorBrush(Color.FromRgb(226, 232, 240))
        badge_gray_fg = SolidColorBrush(Color.FromRgb(71, 85, 105))

        # Parse drop size
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

        if is_flex:
            # ── MODE 1: MASTERPIECE G-FLEX25N-T700 GS FIRE SAFETY SCHEMATIC ──
            brass_brush = SolidColorBrush(Color.FromRgb(217, 119, 6))      # Amber/Brass #D97706
            brass_dark = SolidColorBrush(Color.FromRgb(180, 83, 9))        # Dark Brass #B45309
            hose_core = SolidColorBrush(Color.FromRgb(248, 113, 113))      # Vibrant Coral Red #F87171
            hose_border = SolidColorBrush(Color.FromRgb(185, 28, 28))      # Deep Red #B91C1C
            corrugation_brush = SolidColorBrush(Color.FromArgb(180, 71, 85, 105)) # Steel Ribs #475569
            steel_bracket = SolidColorBrush(Color.FromRgb(148, 163, 184))  # Bracket Slate #94A3B8

            # 1. Top Banner Badges (Pristine non-overlapping top row)
            add_badge("Supply Branch", 15, 6, badge_gray_bg, badge_gray_border, badge_gray_fg)
            add_badge("90° Takeoff", 105, 6, badge_blue_bg, badge_blue_border, badge_blue_fg)
            add_badge("🌀 G-FLEX Hose (" + drop_str + ")", 195, 6, badge_red_bg, badge_red_border, badge_red_fg)

            # 2. Branchline Supply (Horizontal Red Pipe at Y=36)
            add_line(15, 36, 95, 36, pipe_brush, 10)
            add_circle(15, 36, 5, fitting_brush, pipe_brush, 1.2)
            add_circle(95, 36, 5, fitting_brush, pipe_brush, 1.2)

            # 3. Mechanical Tee & Brass Takeoff Nipple (Shoots 90° horizontally)
            add_circle(55, 36, 7.5, fitting_brush, brass_dark, 1.8)
            add_line(55, 36, 90, 36, brass_brush, 6, rounded=False)
            add_circle(90, 36, 5, brass_dark, brass_brush, 1.5)

            # 4. Parametric Bézier G-FLEX Corrugated Hose
            p0 = (90.0, 36.0)
            p1 = (195.0, 36.0)
            p2 = (255.0, 52.0)
            p3 = (255.0, 108.0)

            sample_pts = []
            sample_normals = []
            num_samples = 32
            for s_idx in range(num_samples + 1):
                t = float(s_idx) / float(num_samples)
                bx = (1-t)**3 * p0[0] + 3*(1-t)**2 * t * p1[0] + 3*(1-t) * t**2 * p2[0] + t**3 * p3[0]
                by = (1-t)**3 * p0[1] + 3*(1-t)**2 * t * p1[1] + 3*(1-t) * t**2 * p2[1] + t**3 * p3[1]
                sample_pts.append((bx, by))

                dx = 3*(1-t)**2 * (p1[0]-p0[0]) + 6*(1-t)*t * (p2[0]-p1[0]) + 3*t**2 * (p3[0]-p2[0])
                dy = 3*(1-t)**2 * (p1[1]-p0[1]) + 6*(1-t)*t * (p2[1]-p1[1]) + 3*t**2 * (p3[1]-p2[1])
                l = (dx*dx + dy*dy)**0.5
                if l < 1e-6:
                    sample_normals.append((0.0, 1.0))
                else:
                    sample_normals.append((-dy/l, dx/l))

            # Outer hose contour
            for i in range(len(sample_pts) - 1):
                pa = sample_pts[i]; pb = sample_pts[i+1]
                add_line(pa[0], pa[1], pb[0], pb[1], hose_border, 5.8, rounded=True)
            # Inner hose core
            for i in range(len(sample_pts) - 1):
                pa = sample_pts[i]; pb = sample_pts[i+1]
                add_line(pa[0], pa[1], pb[0], pb[1], hose_core, 3.8, rounded=True)

            # Corrugation metallic ribs across the hose
            for i in range(2, len(sample_pts) - 2, 2):
                c_pt = sample_pts[i]
                c_n = sample_normals[i]
                r_x1 = c_pt[0] - c_n[0] * 3.0
                r_y1 = c_pt[1] - c_n[1] * 3.0
                r_x2 = c_pt[0] + c_n[0] * 3.0
                r_y2 = c_pt[1] + c_n[1] * 3.0
                add_line(r_x1, r_y1, r_x2, r_y2, corrugation_brush, 1.2, rounded=False)

            # 5. Ceiling Grid & Mounting Bracket
            add_line(170, 112, 340, 112, dim_gray, 1, dash=True)
            add_line(210, 109, 300, 109, steel_bracket, 3.5, rounded=True)
            add_circle(215, 109, 2.5, brass_brush, brass_dark, 1)
            add_circle(295, 109, 2.5, brass_brush, brass_dark, 1)

            # Reducer Nipple into bracket
            add_line(255, 102, 255, 112, brass_brush, 6, rounded=False)
            add_circle(255, 111, 4.5, brass_dark, brass_brush, 1.2)

            # 6. Sprinkler Pendent Head
            add_sprinkler_head(255, 112)

            # 7. Lower Annotations (Strictly separated zones)
            add_badge("NFPA 13: R ≥ 250mm", 75, 80, badge_gray_bg, badge_gray_border, badge_gray_fg)
            add_badge("90° Vertical Drop", 272, 70, badge_blue_bg, badge_blue_border, badge_blue_fg)
            add_badge("Ceiling Grid", 335, 104, badge_gray_bg, badge_gray_border, badge_gray_fg, font_size=8.5)

        else:
            # ── MODE 2: RIGID STEEL PIPE DROP (RISER NIPPLE) ──────────────────
            riser_h_val = 300.0
            try:
                if hasattr(self, 'txtRiserHeight') and self.txtRiserHeight.Text:
                    riser_h_val = float(self.txtRiserHeight.Text.strip())
            except Exception:
                riser_h_val = 300.0

            # 1. Main Pipe at bottom
            add_line(25, 116, 135, 116, rigid_blue, 9)
            add_badge("Main Pipe", 42, 126, badge_gray_bg, badge_gray_border, badge_gray_fg)

            # 2. Riser Nipple going up
            add_line(80, 116, 80, 42, rigid_blue, 6)
            add_badge("H = {}mm".format(int(riser_h_val)), 6, 72, badge_blue_bg, badge_blue_border, badge_blue_fg)

            # 3. Top Tee Fitting
            add_circle(80, 42, 6.5, fitting_brush, rigid_blue, 1.5)

            # 4. Spool Pipe + Reducer
            add_line(86, 42, 138, 42, rigid_blue, 5.5)
            add_circle(138, 42, 5, fitting_brush, rigid_blue, 1)

            # 5. Stepped Branch Pipe (DN32) to Sprinkler 1
            add_line(143, 42, 252, 42, rigid_blue, 4)
            add_circle(252, 42, 5, fitting_brush, rigid_blue, 1)

            # Drop Pipe 1
            drop_w = 3.5 if drop_str == "DN32" else 2.5
            add_line(252, 47, 252, 94, rigid_blue, drop_w)
            add_sprinkler_head(252, 95)
            add_badge("Drop " + drop_str, 260, 68, badge_gray_bg, badge_gray_border, badge_gray_fg)

            # 6. Branch to Final Sprinkler 2 (DN25)
            add_line(257, 42, 350, 42, rigid_blue, 2.8)
            add_circle(350, 42, 5, fitting_brush, rigid_blue, 1)
            add_line(350, 47, 350, 94, rigid_blue, drop_w)
            add_sprinkler_head(350, 95)
            add_badge("End 90° Elbow", 295, 16, badge_gray_bg, badge_gray_border, badge_gray_fg)

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
    is_flex_mode = True
    riser_height = "300"
    drop_dn_idx = 0

    while True:
        win = PendentSprinklerWindow(
            main_pipe=main_pipe,
            selected_sprinklers=selected_sprinklers,
            is_flex_mode=is_flex_mode,
            riser_height=riser_height,
            drop_dn_idx=drop_dn_idx
        )
        win.ShowDialog()

        # Capture user choices
        is_flex_mode = hasattr(win, 'rbFlex') and (win.rbFlex.IsChecked == True)
        riser_height = win.txtRiserHeight.Text if hasattr(win, 'txtRiserHeight') else "300"
        drop_dn_idx = win.cmbDropSize.SelectedIndex if hasattr(win, 'cmbDropSize') else 0

        if win.action == "PICK_MAIN":
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
            drop_dn = 25 if drop_dn_idx == 0 else 32

            riser_h_val = 300.0
            try:
                riser_h_val = float(riser_height.strip())
            except Exception:
                riser_h_val = 300.0

            selected_std = "TCVN 7336:2021 (Vietnam Standard)"

            # 1. Cluster sprinklers into branch rows/columns
            branches = cluster_sprinklers_by_main_pipe(
                main_pipe,
                selected_sprinklers,
                tolerance_mm=300.0
            )
            if not branches:
                show_warning(u"Could not detect any valid branch alignments with the selected Main Pipe.", "Topology Error")
                continue

            flex_type_id = None
            if is_flex_mode:
                flex_types = list(DB.FilteredElementCollector(doc).OfClass(FlexPipeType).ToElements())
                if not flex_types:
                    show_error(
                        u"The project does not contain any FlexPipeType.\n\n"
                        u"Please load or create at least one Flexible Pipe Type in Revit (Piping System) before running!",
                        "Missing FlexPipeType"
                    )
                    continue
                flex_type_id = flex_types[0].Id

            # 2. Execute network creation with branchlines and drops
            tg = DB.TransactionGroup(doc, "MEPANANA - Pendent Sprinkler System")
            tg.Start()
            t = DB.Transaction(doc, "Generate Sprinkler Network & Drops")
            try:
                t.Start()
                created_pipes, created_fittings, errors = generate_sprinkler_network(
                    doc,
                    main_pipe,
                    branches,
                    selected_std,
                    riser_height_mm=riser_h_val,
                    drop_dn=drop_dn,
                    is_flex_mode=is_flex_mode,
                    flex_pipe_type_id=flex_type_id
                )
                t.Commit()
                tg.Assimilate()

                mode_str = u"Flexible Hose (G-FLEX S-Curve - NFPA 13)" if is_flex_mode else u"Rigid Steel Pipe Drop (TCVN 7336)"
                msg = u"🎉 Pendent Sprinkler Network Created Successfully!\n\n"
                msg += u"• Connection Mode: {}\n".format(mode_str)
                msg += u"• Sizing Standard: {}\n".format(selected_std)
                msg += u"• Drop Pipe Size: DN{}\n".format(drop_dn)
                msg += u"• Riser Nipple Height: {} mm\n".format(int(riser_h_val))
                msg += u"• Branch lines created: {}\n".format(len(branches))
                msg += u"• Total Sprinklers connected: {}\n".format(len(selected_sprinklers))
                msg += u"• Pipe segments created: {}\n".format(len(created_pipes))
                msg += u"• Fittings placed (Tees / Elbows / Reducers): {}\n".format(len(created_fittings))

                if errors:
                    msg += u"\n⚠️ Notices ({}/{} heads skipped):\n• ".format(
                        len(errors), len(selected_sprinklers)
                    ) + u"\n• ".join(errors[:4])

                show_info(msg, "Pendent Sprinkler Studio - Complete")
                break

            except Exception as ex:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                if tg.HasStarted() and not tg.HasEnded():
                    tg.RollBack()
                show_error(u"Error while generating sprinkler system:\n{}".format(safe_unicode(ex)), "Generation Error")
                break

        else:
            break


# ── Launch Entry ──────────────────────────────────────────────────────────────

run()