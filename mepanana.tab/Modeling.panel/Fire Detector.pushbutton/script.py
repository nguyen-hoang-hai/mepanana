# -*- coding: utf-8 -*-
"""
Fire Detector Studio - Auto Place Fire Detectors
Part of mepanana.extension.
- Chế độ 1: PickBox (hình chữ nhật, hỗ trợ kéo chuột mọi hướng)
- Chế độ 2: Room / Space (boundary polygon tự động tessellate góc cong, trừ cột/lỗ mở)
- Chế độ 3: Filled Region (vùng bao hatch vẽ tay)
Thuật toán: Lưới phân bố đều + Ray-Casting đa giác theo TCVN 5738:2021.
KHÔNG sử dụng gatekeeper auth (mở tự do theo yêu cầu).
"""
import os
import sys
import math

# ── 1. Dynamic Lib Resolution ─────────────────────────────────────────────────
cur_dir = os.path.dirname(__file__)
while cur_dir and not os.path.exists(os.path.join(cur_dir, "lib", "py", "core.py")):
    parent = os.path.dirname(cur_dir)
    if parent == cur_dir:
        break
    cur_dir = parent
lib_path = os.path.join(cur_dir, "lib")
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# ── 2. Imports ────────────────────────────────────────────────────────────────
import clr
clr.AddReference("System")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
import System
import Autodesk.Revit.Exceptions as RevitExceptions
from System.Windows import Visibility
from System.Windows.Media import Brushes, SolidColorBrush, Color
from pyrevit import revit, DB, UI, forms
from py.core import get_id_value, safe_unicode, mm_to_ft, ft_to_mm, SafeTransaction
from py.ui import setup_modern_window, is_dark_theme, show_info, show_warning, show_error, do_events, RunningModeManager

doc   = revit.doc
uidoc = revit.uidoc
if not doc:
    show_warning(u"Vui lòng mở Revit project trước khi sử dụng Fire Detector Studio.", u"Cảnh báo")
    sys.exit()


# ── 3. Geometry Helpers ───────────────────────────────────────────────────────

def is_point_in_polygon(px, py, poly_pts):
    """
    Ray-Casting algorithm: Kiểm tra điểm (px, py) có nằm trong đa giác poly_pts hay không.
    poly_pts: danh sách tuple [(x1, y1), (x2, y2), ...]
    """
    n = len(poly_pts)
    if n < 3:
        return False
    inside = False
    p1x, p1y = poly_pts[0]
    for i in range(1, n + 1):
        p2x, p2y = poly_pts[i % n]
        if py > min(p1y, p2y):
            if py <= max(p1y, p2y):
                if px <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (py - p1y) * (p2x - p1x) / float(p2y - p1y) + p1x
                    if p1x == p2x or px <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def generate_grid_points(x_min, y_min, x_max, y_max, d_max_ft, z_ft,
                         poly_outer=None, poly_inners=None):
    """
    Chia lưới đều trong BoundingBox [x_min, y_min, x_max, y_max] với bước nhảy tối đa d_max_ft.
    Khoảng cách từ biên tường tới đầu báo ngoài cùng = S / 2 (theo TCVN 5738).
    Lọc bỏ các điểm nằm ngoài đa giác poly_outer hoặc rơi vào lỗ mở/cột poly_inners.
    """
    length = x_max - x_min
    width  = y_max - y_min
    if length <= 1e-9 or width <= 1e-9:
        return []
    nx = int(math.ceil(length / d_max_ft))
    ny = int(math.ceil(width / d_max_ft))
    if nx < 1:
        nx = 1
    if ny < 1:
        ny = 1
    sx = length / float(nx)
    sy = width  / float(ny)
    pts = []
    for i in range(nx):
        for j in range(ny):
            gx = x_min + sx / 2.0 + i * sx
            gy = y_min + sy / 2.0 + j * sy
            # Filter by outer polygon boundary
            if poly_outer is not None:
                if not is_point_in_polygon(gx, gy, poly_outer):
                    continue
            # Exclude inner polygon holes (cột, giếng kỹ thuật)
            if poly_inners:
                skip = False
                for inner in poly_inners:
                    if is_point_in_polygon(gx, gy, inner):
                        skip = True
                        break
                if skip:
                    continue
            pts.append(DB.XYZ(gx, gy, z_ft))
    return pts


# ── 4. Selection Filters ──────────────────────────────────────────────────────

class RoomSelectionFilter(UI.Selection.ISelectionFilter):
    """Filter cho Room và MEP Space."""
    def AllowElement(self, elem):
        try:
            return isinstance(elem, (DB.Architecture.Room, DB.Mechanical.Space))
        except Exception:
            return False

    def AllowReference(self, ref, point):
        return True


class FilledRegionFilter(UI.Selection.ISelectionFilter):
    """Filter cho FilledRegion."""
    def AllowElement(self, elem):
        try:
            return isinstance(elem, DB.FilledRegion)
        except Exception:
            return False

    def AllowReference(self, ref, point):
        return True


# ── 5. Zone Data Classes ──────────────────────────────────────────────────────

class PickBoxZone(object):
    """Vùng chọn bằng thao tác kéo chuột 2 điểm chéo (PickBox)."""
    def __init__(self, box_ref):
        self.min_pt = box_ref.Min
        self.max_pt = box_ref.Max

    def get_bbox(self):
        xmin = min(self.min_pt.X, self.max_pt.X)
        xmax = max(self.min_pt.X, self.max_pt.X)
        ymin = min(self.min_pt.Y, self.max_pt.Y)
        ymax = max(self.min_pt.Y, self.max_pt.Y)
        return xmin, ymin, xmax, ymax

    def get_outer_polygon(self):
        xmin, ymin, xmax, ymax = self.get_bbox()
        return [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]

    def get_inner_polygons(self):
        return []

    def describe(self):
        xmin, ymin, xmax, ymax = self.get_bbox()
        w_mm = ft_to_mm(xmax - xmin)
        h_mm = ft_to_mm(ymax - ymin)
        return u"PickBox {:.0f} \u00d7 {:.0f} mm".format(w_mm, h_mm)


class RoomZone(object):
    """Vùng phòng kiến trúc Room hoặc MEP Space."""
    def __init__(self, room):
        self.room = room

    def _get_segments(self):
        opts = DB.SpatialElementBoundaryOptions()
        opts.SpatialElementBoundaryLocation = DB.SpatialElementBoundaryLocation.Finish
        return self.room.GetBoundarySegments(opts)

    def get_bbox(self):
        bb = self.room.get_BoundingBox(None)
        if bb:
            xmin = min(bb.Min.X, bb.Max.X)
            xmax = max(bb.Min.X, bb.Max.X)
            ymin = min(bb.Min.Y, bb.Max.Y)
            ymax = max(bb.Min.Y, bb.Max.Y)
            return xmin, ymin, xmax, ymax
        return 0, 0, 0, 0

    def get_outer_polygon(self):
        segs = self._get_segments()
        if not segs or len(segs) == 0:
            return None
        outer = segs[0]
        pts = []
        for seg in outer:
            curve = seg.GetCurve()
            tess = curve.Tessellate()
            for p in tess[:-1]:
                pts.append((p.X, p.Y))
        return pts if len(pts) >= 3 else None

    def get_inner_polygons(self):
        segs = self._get_segments()
        if not segs or len(segs) <= 1:
            return []
        inners = []
        for loop in segs[1:]:
            pts = []
            for seg in loop:
                curve = seg.GetCurve()
                tess = curve.Tessellate()
                for p in tess[:-1]:
                    pts.append((p.X, p.Y))
            if len(pts) >= 3:
                inners.append(pts)
        return inners

    def describe(self):
        try:
            name_p = self.room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
            name = safe_unicode(name_p.AsString() if name_p else u"Room")
            num_p = self.room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
            num = safe_unicode(num_p.AsString() if num_p else u"")
            if num:
                return u"Room {}: {}".format(num, name)
            return u"Room {}".format(name)
        except Exception:
            return u"Room #{}".format(get_id_value(self.room))


class FilledRegionZone(object):
    """Vùng hatch hoặc đường bao khép kín từ FilledRegion."""
    def __init__(self, region):
        self.region = region

    def get_bbox(self):
        bb = self.region.get_BoundingBox(None)
        if bb:
            xmin = min(bb.Min.X, bb.Max.X)
            xmax = max(bb.Min.X, bb.Max.X)
            ymin = min(bb.Min.Y, bb.Max.Y)
            ymax = max(bb.Min.Y, bb.Max.Y)
            return xmin, ymin, xmax, ymax
        return 0, 0, 0, 0

    def get_outer_polygon(self):
        loops = list(self.region.GetBoundaries())
        if not loops:
            return None
        pts = []
        for curve in loops[0]:
            tess = curve.Tessellate()
            for p in tess[:-1]:
                pts.append((p.X, p.Y))
        return pts if len(pts) >= 3 else None

    def get_inner_polygons(self):
        loops = list(self.region.GetBoundaries())
        if len(loops) <= 1:
            return []
        inners = []
        for loop in loops[1:]:
            pts = []
            for curve in loop:
                tess = curve.Tessellate()
                for p in tess[:-1]:
                    pts.append((p.X, p.Y))
            if len(pts) >= 3:
                inners.append(pts)
        return inners

    def describe(self):
        return u"Filled Region #{}".format(get_id_value(self.region))


# ── 6. Family Symbol Loader ───────────────────────────────────────────────────

FIRE_DETECTOR_CATS = [
    int(DB.BuiltInCategory.OST_FireAlarmDevices),
    int(DB.BuiltInCategory.OST_ElectricalFixtures),
    int(DB.BuiltInCategory.OST_CommunicationDevices),
    int(DB.BuiltInCategory.OST_SecurityDevices),
    int(DB.BuiltInCategory.OST_GenericModel),
]

DETECTOR_KEYWORDS = [
    u"detector", u"chay", u"smoke", u"heat", u"bao", u"fire",
    u"alarm", u"khoi", u"nhiet", u"fd", u"sd", u"hd"
]


def load_fire_detector_symbols(doc):
    """
    Tìm tất cả FamilySymbol phù hợp cho đầu báo cháy.
    Ưu tiên OST_FireAlarmDevices, sau đó lọc theo từ khóa thông minh.
    """
    primary_symbols = []
    secondary_symbols = []
    fallback_symbols = []

    try:
        collector = DB.FilteredElementCollector(doc)\
                      .OfClass(DB.FamilySymbol)\
                      .WhereElementIsElementType()
        for sym in collector:
            try:
                cat = sym.Category
                if cat is None:
                    continue
                cat_id = get_id_value(cat)
                if cat_id not in FIRE_DETECTOR_CATS:
                    continue

                full_name = (safe_unicode(sym.FamilyName) + u" " + safe_unicode(sym.Name)).lower()
                is_detector_cat = (cat_id == int(DB.BuiltInCategory.OST_FireAlarmDevices))
                has_keyword = any(kw in full_name for kw in DETECTOR_KEYWORDS)

                if is_detector_cat:
                    primary_symbols.append(sym)
                elif has_keyword:
                    secondary_symbols.append(sym)
                else:
                    fallback_symbols.append(sym)
            except Exception:
                continue

        sort_key = lambda s: (safe_unicode(s.FamilyName) + u" - " + safe_unicode(s.Name)).lower()
        primary_symbols.sort(key=sort_key)
        secondary_symbols.sort(key=sort_key)

        # Nếu có primary hoặc secondary, chỉ hiển thị nhóm liên quan
        if primary_symbols or secondary_symbols:
            return primary_symbols + secondary_symbols

        # Trường hợp dự án mẫu không đặt tên chuẩn, đưa toàn bộ fallback
        fallback_symbols.sort(key=sort_key)
        return fallback_symbols
    except Exception:
        pass
    return []


def get_symbol_label(sym):
    return u"{} - {}".format(safe_unicode(sym.FamilyName), safe_unicode(sym.Name))


# ── 7. WPF Window Controller ──────────────────────────────────────────────────

class FireDetectorWindow(forms.WPFWindow):
    def __init__(self, dark_mode=False):
        self.dark_mode = dark_mode
        xaml_name = "ui_dark.xaml" if dark_mode else "ui_light.xaml"
        xaml_path = os.path.join(os.path.dirname(__file__), xaml_name)
        forms.WPFWindow.__init__(self, xaml_path)
        setup_modern_window(self, dark_mode=dark_mode)

        self.action = None
        self.zone   = None          # PickBoxZone / RoomZone / FilledRegionZone
        self.rmm    = RunningModeManager(self, dark_mode=dark_mode)

        # Load family symbols
        self._symbols = load_fire_detector_symbols(doc)
        self._populate_family_combo()

        # Wire UI event handlers
        if hasattr(self, 'btnToggleTheme'):
            self.btnToggleTheme.Click += self.OnToggleTheme
        if hasattr(self, 'btnClose'):
            self.btnClose.Click += self.OnClose
        if hasattr(self, 'btnFooterClose'):
            self.btnFooterClose.Click += self.OnClose
        if hasattr(self, 'btnPickZone'):
            self.btnPickZone.Click += self.OnPickZone
        if hasattr(self, 'btnGenerate'):
            self.btnGenerate.Click += self.OnGenerate
        if hasattr(self, 'btnStopRunning'):
            self.btnStopRunning.Click += self.OnStopRunning

        # Preset D_max buttons
        if hasattr(self, 'btnPreset9000'):
            self.btnPreset9000.Click += self.OnPreset9000
        if hasattr(self, 'btnPreset7500'):
            self.btnPreset7500.Click += self.OnPreset7500
        if hasattr(self, 'btnPreset5400'):
            self.btnPreset5400.Click += self.OnPreset5400
        if hasattr(self, 'btnPreset4500'):
            self.btnPreset4500.Click += self.OnPreset4500

        # Zone mode radio buttons
        if hasattr(self, 'rbPickBox'):
            self.rbPickBox.Checked += self.OnZoneModeChanged
        if hasattr(self, 'rbRoom'):
            self.rbRoom.Checked += self.OnZoneModeChanged
        if hasattr(self, 'rbRegion'):
            self.rbRegion.Checked += self.OnZoneModeChanged

        # Family selection change
        if hasattr(self, 'cmbFamily'):
            self.cmbFamily.SelectionChanged += self.OnFamilyChanged

        # Text input changes for live count preview
        if hasattr(self, 'txtDMax'):
            self.txtDMax.TextChanged += self.OnInputChanged
        if hasattr(self, 'txtZOffset'):
            self.txtZOffset.TextChanged += self.OnInputChanged

        self._sync_zone_status()

    # ── Family combo ──
    def _populate_family_combo(self):
        if not hasattr(self, 'cmbFamily'):
            return
        self.cmbFamily.Items.Clear()
        if not self._symbols:
            from System.Windows.Controls import ComboBoxItem
            item = ComboBoxItem()
            item.Content = u"(Chưa tải Family đầu báo cháy vào dự án)"
            self.cmbFamily.Items.Add(item)
            self.cmbFamily.SelectedIndex = 0
            return
        from System.Windows.Controls import ComboBoxItem
        for sym in self._symbols:
            item = ComboBoxItem()
            item.Content = get_symbol_label(sym)
            item.Tag = get_id_value(sym)
            self.cmbFamily.Items.Add(item)
        self.cmbFamily.SelectedIndex = 0
        self._update_family_hint()

    def _update_family_hint(self):
        if not hasattr(self, 'txtFamilyHint') or not hasattr(self, 'cmbFamily'):
            return
        idx = self.cmbFamily.SelectedIndex
        if 0 <= idx < len(self._symbols):
            sym = self._symbols[idx]
            placement_type = safe_unicode(str(sym.Family.FamilyPlacementType))
            cat_name = safe_unicode(sym.Category.Name) if sym.Category else u"?"
            self.txtFamilyHint.Text = u"Host: {}  |  Category: {}".format(placement_type, cat_name)
        else:
            self.txtFamilyHint.Text = u"Vui lòng chọn family từ danh sách trên."

    def OnFamilyChanged(self, sender, args):
        self._update_family_hint()

    # ── Zone mode ──
    def OnZoneModeChanged(self, sender, args):
        self.zone = None
        self._sync_zone_status()

    def _get_zone_mode(self):
        if hasattr(self, 'rbRoom') and self.rbRoom.IsChecked == True:
            return "ROOM"
        if hasattr(self, 'rbRegion') and self.rbRegion.IsChecked == True:
            return "REGION"
        return "PICKBOX"

    def _sync_zone_status(self):
        if not hasattr(self, 'txtZoneStatus'):
            return
        if self.zone is None:
            self.txtZoneStatus.Text = u"Chưa chọn vùng"
            gray = SolidColorBrush(Color.FromRgb(148, 163, 184))
            self.txtZoneStatus.Foreground = gray
        else:
            self.txtZoneStatus.Text = self.zone.describe()
            green = SolidColorBrush(Color.FromRgb(21, 128, 61))
            self.txtZoneStatus.Foreground = green
        self._update_preview_count()

    def _get_d_max_ft(self):
        d_max_mm = 9000.0
        try:
            if hasattr(self, 'txtDMax') and self.txtDMax.Text:
                d_max_mm = float(self.txtDMax.Text.strip())
        except Exception:
            d_max_mm = 9000.0
        return mm_to_ft(max(500.0, d_max_mm))

    def _get_z_offset_ft(self):
        z_mm = 2800.0
        try:
            if hasattr(self, 'txtZOffset') and self.txtZOffset.Text:
                z_mm = float(self.txtZOffset.Text.strip())
        except Exception:
            z_mm = 2800.0
        return mm_to_ft(z_mm)

    def OnInputChanged(self, sender, args):
        self._update_preview_count()

    def _update_preview_count(self):
        if not hasattr(self, 'txtPointCount') or not hasattr(self, 'txtZoneSummary'):
            return
        if self.zone is None:
            self.txtZoneSummary.Text = u"—"
            self.txtPointCount.Text  = u"—"
            return
        try:
            self.txtZoneSummary.Text = self.zone.describe()
            d_ft = self._get_d_max_ft()
            z_ft = self._get_z_offset_ft()
            x0, y0, x1, y1 = self.zone.get_bbox()
            poly_outer = self.zone.get_outer_polygon()
            poly_inners = self.zone.get_inner_polygons()
            pts = generate_grid_points(x0, y0, x1, y1, d_ft, z_ft,
                                       poly_outer=poly_outer,
                                       poly_inners=poly_inners)
            self.txtPointCount.Text = u"≈ {} đầu báo".format(len(pts))
        except Exception:
            self.txtPointCount.Text = u"Lỗi tính toán"

    # ── Preset Buttons ──
    def _set_d_max(self, value_mm):
        if hasattr(self, 'txtDMax'):
            self.txtDMax.Text = str(value_mm)
        self._update_preview_count()

    def OnPreset9000(self, sender, args):
        self._set_d_max(9000)

    def OnPreset7500(self, sender, args):
        self._set_d_max(7500)

    def OnPreset5400(self, sender, args):
        self._set_d_max(5400)

    def OnPreset4500(self, sender, args):
        self._set_d_max(4500)

    # ── Pick Zone ──
    def OnPickZone(self, sender, args):
        mode = self._get_zone_mode()
        self.action = "PICK_ZONE_" + mode
        self.Close()

    # ── Generate ──
    def OnGenerate(self, sender, args):
        if self.zone is None:
            show_warning(u"Vui lòng chọn vùng bố trí trước!", u"Thiếu vùng")
            return
        idx = self.cmbFamily.SelectedIndex if hasattr(self, 'cmbFamily') else -1
        if idx < 0 or idx >= len(self._symbols):
            show_warning(u"Vui lòng chọn Family Symbol đầu báo cháy!", u"Thiếu Family")
            return
        self.action = "GENERATE"
        self.Close()

    # ── Theme Toggle ──
    def OnToggleTheme(self, sender, args):
        self.switch_requested = True
        self.Close()

    # ── Close ──
    def OnClose(self, sender, args):
        self.action = "CLOSE"
        self.Close()

    # ── Stop Running ──
    def OnStopRunning(self, sender, args):
        if hasattr(self, 'rmm'):
            self.rmm.request_stop()


# ── 8. Core Placement Function ────────────────────────────────────────────────

def place_detectors(doc, symbol, zone, d_max_ft, z_offset_ft):
    """
    Đặt FamilyInstance tại mỗi điểm grid trong zone.
    Gán thông số cao độ Offset so với Level tương ứng.
    Trả về (placed_count, errors).
    """
    x0, y0, x1, y1 = zone.get_bbox()
    poly_outer  = zone.get_outer_polygon()
    poly_inners = zone.get_inner_polygons()

    pts = generate_grid_points(x0, y0, x1, y1, d_max_ft, z_offset_ft,
                               poly_outer=poly_outer,
                               poly_inners=poly_inners)
    if not pts:
        return 0, [u"Không có điểm grid trong vùng đã chọn."]

    # Kích hoạt symbol nếu chưa active
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()

    # Ưu tiên lấy Level của active view, nếu không có thì tìm Level gần nhất
    active_level = None
    try:
        active_level = doc.ActiveView.GenLevel
    except Exception:
        active_level = None

    if not active_level:
        levels = list(DB.FilteredElementCollector(doc)
                        .OfClass(DB.Level)
                        .WhereElementIsNotElementType()
                        .ToElements())
        best_level = None
        best_diff  = float("inf")
        for lvl in levels:
            diff = abs(lvl.Elevation - z_offset_ft)
            if diff < best_diff:
                best_diff  = diff
                best_level = lvl
        active_level = best_level

    if active_level is None:
        return 0, [u"Không tìm thấy Level nào trong project để gán thiết bị."]

    placed = 0
    errors = []

    for pt in pts:
        try:
            inst = doc.Create.NewFamilyInstance(
                pt, symbol, active_level, DB.Structure.StructuralType.NonStructural
            )
            # Gán cao độ Offset so với Level
            offset_param = inst.get_Parameter(DB.BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM)
            if not offset_param or offset_param.IsReadOnly:
                offset_param = inst.get_Parameter(DB.BuiltInParameter.INSTANCE_ELEVATION_PARAM)
            if offset_param and not offset_param.IsReadOnly:
                offset_param.Set(z_offset_ft)

            placed += 1
        except Exception as ex:
            errors.append(safe_unicode(ex))

    return placed, errors


# ── 9. Interactive Loop ───────────────────────────────────────────────────────

def run():
    current_dark = is_dark_theme()
    try:
        if __shiftclick__:
            current_dark = not current_dark
    except Exception:
        pass

    # Persistent state across dialog re-openings
    saved_zone   = None
    saved_d_max  = None
    saved_z_off  = None
    saved_sym_id = None

    while True:
        win = FireDetectorWindow(dark_mode=current_dark)

        # Restore state
        if saved_zone is not None:
            win.zone = saved_zone
            win._sync_zone_status()
        if saved_d_max is not None and hasattr(win, 'txtDMax'):
            win.txtDMax.Text = saved_d_max
        if saved_z_off is not None and hasattr(win, 'txtZOffset'):
            win.txtZOffset.Text = saved_z_off
        if saved_sym_id is not None and hasattr(win, 'cmbFamily'):
            for i in range(win.cmbFamily.Items.Count):
                item = win.cmbFamily.Items[i]
                if getattr(item, 'Tag', None) == saved_sym_id:
                    win.cmbFamily.SelectedIndex = i
                    break

        win.ShowDialog()

        # Handle theme toggle
        if getattr(win, 'switch_requested', False):
            current_dark = not current_dark
            saved_zone  = win.zone
            saved_d_max = win.txtDMax.Text if hasattr(win, 'txtDMax') else None
            saved_z_off = win.txtZOffset.Text if hasattr(win, 'txtZOffset') else None
            if hasattr(win, 'cmbFamily') and win.cmbFamily.SelectedItem:
                saved_sym_id = getattr(win.cmbFamily.SelectedItem, 'Tag', None)
            continue

        action = win.action or "CLOSE"

        # Capture latest settings
        saved_d_max = win.txtDMax.Text if hasattr(win, 'txtDMax') else None
        saved_z_off = win.txtZOffset.Text if hasattr(win, 'txtZOffset') else None
        if hasattr(win, 'cmbFamily') and win.cmbFamily.SelectedItem:
            saved_sym_id = getattr(win.cmbFamily.SelectedItem, 'Tag', None)
        saved_zone  = win.zone

        # ── Pick Zone Actions ──
        if action == "PICK_ZONE_PICKBOX":
            try:
                box_ref = uidoc.Selection.PickBox(
                    UI.Selection.PickBoxStyle.Enclosing,
                    u"Quét chọn 2 điểm góc chéo để xác định vùng hình chữ nhật"
                )
                if box_ref:
                    saved_zone = PickBoxZone(box_ref)
            except RevitExceptions.OperationCanceledException:
                pass
            except Exception as ex:
                show_warning(u"Thao tác PickBox:\n{}".format(safe_unicode(ex)), u"Thông báo")
            continue

        elif action == "PICK_ZONE_ROOM":
            try:
                ref = uidoc.Selection.PickObject(
                    UI.Selection.ObjectType.Element,
                    RoomSelectionFilter(),
                    u"Click chọn Room hoặc MEP Space trên mặt bằng"
                )
                if ref:
                    elem = doc.GetElement(ref.ElementId)
                    if elem:
                        saved_zone = RoomZone(elem)
            except RevitExceptions.OperationCanceledException:
                pass
            except Exception as ex:
                show_warning(u"Thao tác chọn Room:\n{}".format(safe_unicode(ex)), u"Thông báo")
            continue

        elif action == "PICK_ZONE_REGION":
            try:
                ref = uidoc.Selection.PickObject(
                    UI.Selection.ObjectType.Element,
                    FilledRegionFilter(),
                    u"Click chọn Filled Region trên mặt bằng"
                )
                if ref:
                    elem = doc.GetElement(ref.ElementId)
                    if elem:
                        saved_zone = FilledRegionZone(elem)
            except RevitExceptions.OperationCanceledException:
                pass
            except Exception as ex:
                show_warning(u"Thao tác chọn Filled Region:\n{}".format(safe_unicode(ex)), u"Thông báo")
            continue

        # ── Generate Detectors ──
        elif action == "GENERATE":
            zone = win.zone
            sym_idx = win.cmbFamily.SelectedIndex if hasattr(win, 'cmbFamily') else -1
            symbol  = win._symbols[sym_idx] if 0 <= sym_idx < len(win._symbols) else None

            if zone is None or symbol is None:
                show_warning(u"Thiếu thông tin vùng hoặc Family. Vui lòng kiểm tra lại.", u"Thông báo")
                continue

            d_max_ft = mm_to_ft(float(win.txtDMax.Text.strip() or "9000"))
            z_ft     = mm_to_ft(float(win.txtZOffset.Text.strip() or "2800"))

            try:
                with SafeTransaction(doc, u"MEPANANA - Auto Place Fire Detectors"):
                    placed, errors = place_detectors(doc, symbol, zone, d_max_ft, z_ft)

                msg = u"🔥 Bố trí đầu báo cháy hoàn tất!\n\n"
                msg += u"• Family: {}\n".format(get_symbol_label(symbol))
                msg += u"• Vùng: {}\n".format(zone.describe())
                msg += u"• Khoảng cách D_max: {} mm\n".format(win.txtDMax.Text.strip())
                msg += u"• Cao độ lắp đặt: {} mm\n".format(win.txtZOffset.Text.strip())
                msg += u"• Số lượng đầu báo đã đặt: {}\n".format(placed)

                if errors:
                    msg += u"\n⚠️ Lưu ý ({} lỗi):\n• {}".format(
                        len(errors), u"\n• ".join(errors[:4]))

                show_info(msg, u"Fire Detector Studio - Hoàn tất")
                break

            except Exception as ex:
                show_error(u"Lỗi khi bố trí đầu báo cháy:\n{}".format(safe_unicode(ex)),
                           u"Lỗi Generation")
                break

        else:
            # User clicked Close or ESC
            break


# ── 10. Entry Point ───────────────────────────────────────────────────────────
run()
