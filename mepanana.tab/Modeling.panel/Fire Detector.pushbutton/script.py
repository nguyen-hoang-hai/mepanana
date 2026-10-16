# -*- coding: utf-8 -*-
"""
Fire Detector Studio - Auto Place Fire Detectors
Part of mepanana.extension.
- Chế độ 1: Quét PickBox (khoanh vùng hình chữ nhật 2 góc chéo, vẽ khung đỏ trực quan)
- Chế độ 2: Kẻ Line / Đa giác (Vẽ đường line đỏ trực tiếp theo từng cú click, nhấn ESC để hoàn thành)
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
from Autodesk.Revit.DB import (
    FilteredElementCollector, FamilySymbol, BuiltInCategory,
    CategoryType, ElementId, Structure, XYZ, Color as RevitColor,
    OverrideGraphicSettings, ViewType
)
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


# ── 3. View Plane & Live Visual Line Drawing ──────────────────────────────────

def get_view_plane_z(view):
    """
    Lấy cao độ Z chính xác tuyệt đối của mặt phẳng view hiện hành.
    Ưu tiên GenLevel của Plan View, fallback về SketchPlane hoặc Origin.
    """
    try:
        lvl = getattr(view, 'GenLevel', None)
        if lvl:
            return lvl.Elevation
    except Exception:
        pass
    try:
        sp = getattr(view, 'SketchPlane', None)
        if sp:
            plane = sp.GetPlane()
            if plane:
                return plane.Origin.Z
    except Exception:
        pass
    try:
        return view.Origin.Z
    except Exception:
        pass
    return 0.0


def create_temp_line(doc, view, p1, p2):
    """
    Vẽ đoạn DetailLine màu đỏ nổi bật giữa 2 điểm trên mặt bằng active view.
    Thử nghiệm đa tầng cao độ Z (view_z, p1.Z, 0.0) để đảm bảo luôn vẽ thành công 100%.
    """
    try:
        if view.ViewType == ViewType.ThreeD:
            return None

        dx = p2.X - p1.X
        dy = p2.Y - p1.Y
        if math.sqrt(dx * dx + dy * dy) < 1e-4:
            return None

        view_z = get_view_plane_z(view)
        curve = None
        for z in [view_z, getattr(p1, 'Z', 0.0), 0.0]:
            try:
                geom_line = DB.Line.CreateBound(
                    XYZ(p1.X, p1.Y, z),
                    XYZ(p2.X, p2.Y, z)
                )
                curve = doc.Create.NewDetailCurve(view, geom_line)
                if curve:
                    break
            except Exception:
                continue

        if not curve:
            return None

        try:
            ogs = OverrideGraphicSettings()
            ogs.SetProjectionLineColor(RevitColor(239, 68, 68))  # Đỏ rực #EF4444
            ogs.SetProjectionLineWeight(5)
            view.SetElementOverrides(curve.Id, ogs)
        except Exception:
            pass

        return curve.Id
    except Exception:
        return None


def create_temp_crosshair(doc, view, pt, size_ft=0.6):
    """Vẽ dấu chữ thập màu đỏ tại điểm click đầu tiên để người dùng thấy rõ điểm xuất phát."""
    ids = []
    try:
        if view.ViewType == ViewType.ThreeD:
            return ids

        view_z = get_view_plane_z(view)
        for z in [view_z, getattr(pt, 'Z', 0.0), 0.0]:
            try:
                l1 = DB.Line.CreateBound(XYZ(pt.X - size_ft, pt.Y, z), XYZ(pt.X + size_ft, pt.Y, z))
                l2 = DB.Line.CreateBound(XYZ(pt.X, pt.Y - size_ft, z), XYZ(pt.X, pt.Y + size_ft, z))
                c1 = doc.Create.NewDetailCurve(view, l1)
                c2 = doc.Create.NewDetailCurve(view, l2)
                if c1 and c2:
                    try:
                        ogs = OverrideGraphicSettings()
                        ogs.SetProjectionLineColor(RevitColor(239, 68, 68))
                        ogs.SetProjectionLineWeight(5)
                        view.SetElementOverrides(c1.Id, ogs)
                        view.SetElementOverrides(c2.Id, ogs)
                    except Exception:
                        pass
                    ids.extend([c1.Id, c2.Id])
                    break
            except Exception:
                continue
    except Exception:
        pass
    return ids


def create_temp_box(doc, view, xmin, ymin, xmax, ymax):
    """Vẽ khung chữ nhật màu đỏ bao quanh vùng PickBox."""
    ids = []
    view_z = get_view_plane_z(view)
    p1 = XYZ(xmin, ymin, view_z)
    p2 = XYZ(xmax, ymin, view_z)
    p3 = XYZ(xmax, ymax, view_z)
    p4 = XYZ(xmin, ymax, view_z)
    for a, b in [(p1, p2), (p2, p3), (p3, p4), (p4, p1)]:
        lid = create_temp_line(doc, view, a, b)
        if lid:
            ids.append(lid)
    return ids


def cleanup_temp_lines(doc, line_ids):
    """Xóa sạch các đường preview tạm để không lưu rác vào file dự án của người dùng."""
    if not line_ids:
        return
    try:
        t = DB.Transaction(doc, "MEPANANA - Clear Temp Lines")
        if t.Start() == DB.TransactionStatus.Started:
            for lid in line_ids:
                try:
                    doc.Delete(lid)
                except Exception:
                    pass
            t.Commit()
            uidoc.RefreshActiveView()
    except Exception:
        pass


# ── 4. Geometry Helpers ───────────────────────────────────────────────────────

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
                         poly_outer=None, raw_pts=None):
    """
    Chia lưới đều trong BoundingBox [x_min, y_min, x_max, y_max] với bước nhảy tối đa d_max_ft.
    Khoảng cách từ biên tường tới đầu báo ngoài cùng = S / 2 (theo TCVN 5738).
    Lọc bỏ các điểm nằm ngoài đa giác poly_outer.
    Nếu raw_pts là 2 điểm (đoạn kẻ line đơn), tự động rải đều dọc theo đường thẳng.
    """
    if raw_pts and len(raw_pts) == 2:
        p1 = raw_pts[0]
        p2 = raw_pts[1]
        dx = p2.X - p1.X
        dy = p2.Y - p1.Y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > 1e-3 and (abs(dx) < mm_to_ft(300) or abs(dy) < mm_to_ft(300)):
            n = int(math.ceil(dist / d_max_ft))
            if n < 1:
                n = 1
            step = dist / float(n)
            ux = dx / dist
            uy = dy / dist
            line_pts = []
            for i in range(n):
                d = step / 2.0 + i * step
                line_pts.append(XYZ(p1.X + ux * d, p1.Y + uy * d, z_ft))
            return line_pts

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
            if poly_outer is not None:
                if not is_point_in_polygon(gx, gy, poly_outer):
                    continue
            pts.append(XYZ(gx, gy, z_ft))
    return pts


# ── 5. Zone Data Classes ──────────────────────────────────────────────────────

class PickBoxZone(object):
    """Vùng chọn bằng thao tác kéo chuột 2 điểm chéo (PickBox)."""
    def __init__(self, box_ref, temp_line_ids=None):
        self.min_pt = box_ref.Min
        self.max_pt = box_ref.Max
        self.temp_line_ids = temp_line_ids or []

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


class LinePolygonZone(object):
    """
    Vùng chọn bằng cách click các điểm kẻ line liên tiếp, nhấn ESC để kết thúc.
    - Nếu >= 3 điểm: tạo thành đa giác khép kín (hỗ trợ phòng vuông, phòng L, hành lang gấp khúc...).
    - Nếu 2 điểm: tự động tạo Bounding Box hình chữ nhật giữa 2 điểm (hoặc rải dọc đường thẳng).
    """
    def __init__(self, pts, temp_line_ids=None):
        self.pts = pts  # list of XYZ
        self.temp_line_ids = temp_line_ids or []

    def get_bbox(self):
        xmin = min(p.X for p in self.pts)
        xmax = max(p.X for p in self.pts)
        ymin = min(p.Y for p in self.pts)
        ymax = max(p.Y for p in self.pts)
        return xmin, ymin, xmax, ymax

    def get_outer_polygon(self):
        if len(self.pts) >= 3:
            return [(p.X, p.Y) for p in self.pts]
        elif len(self.pts) == 2:
            xmin, ymin, xmax, ymax = self.get_bbox()
            return [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
        return None

    def get_inner_polygons(self):
        return []

    def describe(self):
        n = len(self.pts)
        xmin, ymin, xmax, ymax = self.get_bbox()
        w_mm = ft_to_mm(xmax - xmin)
        h_mm = ft_to_mm(ymax - ymin)
        if n >= 3:
            return u"Đa giác ({} điểm) · {:.0f} \u00d7 {:.0f} mm".format(n, w_mm, h_mm)
        else:
            return u"Đường line (2 điểm) · {:.0f} \u00d7 {:.0f} mm".format(w_mm, h_mm)


# ── 6. Robust Family Symbol Loader ────────────────────────────────────────────

DETECTOR_KEYWORDS = [
    u"detector", u"chay", u"smoke", u"heat", u"bao", u"fire",
    u"alarm", u"khoi", u"nhiet", u"fd", u"sd", u"hd"
]


def load_fire_detector_symbols(doc):
    """
    Tải toàn bộ FamilySymbol đầu báo cháy và thiết bị báo cháy trong dự án.
    Phương pháp 3 tầng bảo đảm 100% không bao giờ bỏ sót:
    - Tầng 1: Native Quick Filter theo BuiltInCategory.OST_FireAlarmDevices
    - Tầng 2: Các category MEP điện / an ninh liên quan (Electrical, Security, Comm, Generic)
    - Tầng 3: Quét toàn bộ FamilySymbol non-annotation trong dự án làm fallback
    """
    seen_ids = set()
    primary_symbols = []
    secondary_symbols = []
    fallback_symbols = []

    # ── TẦNG 1: OST_FireAlarmDevices ──────────────────────────────────────────
    try:
        col_fa = FilteredElementCollector(doc)\
                    .OfCategory(BuiltInCategory.OST_FireAlarmDevices)\
                    .WhereElementIsElementType()\
                    .ToElements()
        for s in col_fa:
            if isinstance(s, FamilySymbol) and s.Id not in seen_ids:
                seen_ids.add(s.Id)
                primary_symbols.append(s)
    except Exception:
        pass

    # ── TẦNG 2: Các Category MEP khác lọc theo từ khóa ────────────────────────
    other_cats = [
        BuiltInCategory.OST_ElectricalFixtures,
        BuiltInCategory.OST_SecurityDevices,
        BuiltInCategory.OST_CommunicationDevices,
        BuiltInCategory.OST_GenericModel,
    ]

    for cat_enum in other_cats:
        try:
            col = FilteredElementCollector(doc)\
                    .OfCategory(cat_enum)\
                    .WhereElementIsElementType()\
                    .ToElements()
            for s in col:
                if isinstance(s, FamilySymbol) and s.Id not in seen_ids:
                    seen_ids.add(s.Id)
                    fam_name = safe_unicode(getattr(s, 'FamilyName', ''))
                    type_name = safe_unicode(getattr(s, 'Name', ''))
                    full_str = (fam_name + u" " + type_name).lower()
                    if any(kw in full_str for kw in DETECTOR_KEYWORDS):
                        secondary_symbols.append(s)
                    else:
                        fallback_symbols.append(s)
        except Exception:
            pass

    # ── TẦNG 3: Quét tất cả FamilySymbol non-annotation nếu vẫn trống ─────────
    if not primary_symbols and not secondary_symbols:
        try:
            all_syms = FilteredElementCollector(doc)\
                        .OfClass(FamilySymbol)\
                        .WhereElementIsElementType()\
                        .ToElements()
            for s in all_syms:
                if s.Id not in seen_ids:
                    seen_ids.add(s.Id)
                    try:
                        if s.Category and s.Category.CategoryType == CategoryType.Annotation:
                            continue
                    except Exception:
                        pass
                    fam_name = safe_unicode(getattr(s, 'FamilyName', ''))
                    type_name = safe_unicode(getattr(s, 'Name', ''))
                    full_str = (fam_name + u" " + type_name).lower()
                    if any(kw in full_str for kw in DETECTOR_KEYWORDS):
                        secondary_symbols.append(s)
                    else:
                        fallback_symbols.append(s)
        except Exception:
            pass

    def _sym_sort_key(s):
        fn = safe_unicode(getattr(s, 'FamilyName', ''))
        tn = safe_unicode(getattr(s, 'Name', ''))
        return (fn + u" - " + tn).lower()

    primary_symbols.sort(key=_sym_sort_key)
    secondary_symbols.sort(key=_sym_sort_key)
    fallback_symbols.sort(key=_sym_sort_key)

    if primary_symbols:
        return primary_symbols + secondary_symbols
    elif secondary_symbols:
        return secondary_symbols + fallback_symbols[:40]
    else:
        return fallback_symbols


def get_symbol_label(sym):
    cat_name = safe_unicode(sym.Category.Name) if sym.Category else u"Device"
    fam_name = safe_unicode(getattr(sym, 'FamilyName', ''))
    type_name = safe_unicode(getattr(sym, 'Name', ''))
    return u"[{}] {} : {}".format(cat_name, fam_name, type_name)


# ── 7. WPF Window Controller ──────────────────────────────────────────────────

class FireDetectorWindow(forms.WPFWindow):
    def __init__(self, dark_mode=False, default_mode="PICKBOX"):
        self.dark_mode = dark_mode
        xaml_name = "ui_dark.xaml" if dark_mode else "ui_light.xaml"
        xaml_path = os.path.join(os.path.dirname(__file__), xaml_name)
        forms.WPFWindow.__init__(self, xaml_path)
        setup_modern_window(self, dark_mode=dark_mode)

        self.action = None
        self.zone   = None          # PickBoxZone / LinePolygonZone
        self.rmm    = RunningModeManager(self, dark_mode=dark_mode)
        self._current_mode = default_mode
        self._is_initializing = True

        # Thiết lập RadioButton ban đầu TRƯỚC KHI gắn sự kiện Checked
        if default_mode == "LINE":
            if hasattr(self, 'rbDrawLine'):
                self.rbDrawLine.IsChecked = True
        else:
            if hasattr(self, 'rbPickBox'):
                self.rbPickBox.IsChecked = True

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
        if hasattr(self, 'btnRefreshFamilies'):
            self.btnRefreshFamilies.Click += self.OnRefreshFamilies

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
        if hasattr(self, 'rbDrawLine'):
            self.rbDrawLine.Checked += self.OnZoneModeChanged

        # Family selection change
        if hasattr(self, 'cmbFamily'):
            self.cmbFamily.SelectionChanged += self.OnFamilyChanged

        # Text input changes for live count preview
        if hasattr(self, 'txtDMax'):
            self.txtDMax.TextChanged += self.OnInputChanged
        if hasattr(self, 'txtZOffset'):
            self.txtZOffset.TextChanged += self.OnInputChanged

        self._is_initializing = False
        self._sync_zone_status()

    # ── Family combo ──
    def _populate_family_combo(self, preserve_tag=None):
        if not hasattr(self, 'cmbFamily'):
            return
        self.cmbFamily.Items.Clear()
        if not self._symbols:
            from System.Windows.Controls import ComboBoxItem
            item = ComboBoxItem()
            item.Content = u"(Không tìm thấy Family đầu báo cháy trong dự án)"
            self.cmbFamily.Items.Add(item)
            self.cmbFamily.SelectedIndex = 0
            if hasattr(self, 'txtFamilyHint'):
                self.txtFamilyHint.Text = u"Vui lòng load Family (Fire Alarm Devices / Electrical) vào Revit rồi bấm '🔄 Tải lại'."
            return

        from System.Windows.Controls import ComboBoxItem
        selected_idx = 0
        for i, sym in enumerate(self._symbols):
            item = ComboBoxItem()
            item.Content = get_symbol_label(sym)
            item.Tag = get_id_value(sym)
            self.cmbFamily.Items.Add(item)
            if preserve_tag is not None and get_id_value(sym) == preserve_tag:
                selected_idx = i

        self.cmbFamily.SelectedIndex = selected_idx
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

    def OnRefreshFamilies(self, sender, args):
        cur_tag = None
        if hasattr(self, 'cmbFamily') and self.cmbFamily.SelectedItem:
            cur_tag = getattr(self.cmbFamily.SelectedItem, 'Tag', None)
        self._symbols = load_fire_detector_symbols(doc)
        self._populate_family_combo(preserve_tag=cur_tag)

    # ── Zone mode ──
    def OnZoneModeChanged(self, sender, args):
        # Tránh xóa self.zone khi cửa sổ đang khôi phục trạng thái ban đầu
        if getattr(self, '_is_initializing', False):
            return
        new_mode = self._get_zone_mode()
        if getattr(self, '_current_mode', None) != new_mode:
            self._current_mode = new_mode
            self.zone = None
            self._sync_zone_status()

    def _get_zone_mode(self):
        if hasattr(self, 'rbDrawLine') and self.rbDrawLine.IsChecked == True:
            return "LINE"
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
            raw_pts = getattr(self.zone, 'pts', None)
            pts = generate_grid_points(x0, y0, x1, y1, d_ft, z_ft,
                                       poly_outer=poly_outer,
                                       raw_pts=raw_pts)
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
    poly_outer = zone.get_outer_polygon()
    raw_pts = getattr(zone, 'pts', None)

    pts = generate_grid_points(x0, y0, x1, y1, d_max_ft, z_offset_ft,
                               poly_outer=poly_outer,
                               raw_pts=raw_pts)
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
        levels = list(FilteredElementCollector(doc)
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
            try:
                inst = doc.Create.NewFamilyInstance(
                    pt, symbol, active_level, Structure.StructuralType.NonStructural
                )
            except Exception:
                inst = doc.Create.NewFamilyInstance(
                    pt, symbol, Structure.StructuralType.NonStructural
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
    saved_zone       = None
    saved_d_max      = None
    saved_z_off      = None
    saved_sym_id     = None
    saved_mode       = "PICKBOX"
    saved_temp_lines = []

    while True:
        # Khởi tạo cửa sổ với đúng default_mode để không kích hoạt nhầm sự kiện wipe zone
        win = FireDetectorWindow(dark_mode=current_dark, default_mode=saved_mode)

        # Khôi phục trạng thái đã chọn trước đó
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

        # Xử lý đổi theme
        if getattr(win, 'switch_requested', False):
            current_dark = not current_dark
            saved_zone  = win.zone
            saved_d_max = win.txtDMax.Text if hasattr(win, 'txtDMax') else None
            saved_z_off = win.txtZOffset.Text if hasattr(win, 'txtZOffset') else None
            saved_mode  = win._get_zone_mode()
            if hasattr(win, 'cmbFamily') and win.cmbFamily.SelectedItem:
                saved_sym_id = getattr(win.cmbFamily.SelectedItem, 'Tag', None)
            continue

        action = win.action or "CLOSE"

        # Lưu lại cấu hình mới nhất
        saved_d_max = win.txtDMax.Text if hasattr(win, 'txtDMax') else None
        saved_z_off = win.txtZOffset.Text if hasattr(win, 'txtZOffset') else None
        saved_mode  = win._get_zone_mode()
        if hasattr(win, 'cmbFamily') and win.cmbFamily.SelectedItem:
            saved_sym_id = getattr(win.cmbFamily.SelectedItem, 'Tag', None)
        saved_zone  = win.zone

        # ── Chế độ 1: Quét PickBox (Hiển thị khung đỏ tức thì) ──
        if action == "PICK_ZONE_PICKBOX":
            cleanup_temp_lines(doc, saved_temp_lines)
            saved_temp_lines = []

            try:
                box_ref = uidoc.Selection.PickBox(
                    UI.Selection.PickBoxStyle.Enclosing,
                    u"Quét chọn 2 điểm góc chéo để xác định vùng hình chữ nhật"
                )
                if box_ref:
                    xmin = min(box_ref.Min.X, box_ref.Max.X)
                    xmax = max(box_ref.Min.X, box_ref.Max.X)
                    ymin = min(box_ref.Min.Y, box_ref.Max.Y)
                    ymax = max(box_ref.Min.Y, box_ref.Max.Y)

                    # Vẽ khung chữ nhật màu đỏ trực quan trên mặt bằng
                    t = DB.Transaction(doc, "MEPANANA - Preview PickBox")
                    try:
                        if t.Start() == DB.TransactionStatus.Started:
                            box_lines = create_temp_box(doc, doc.ActiveView, xmin, ymin, xmax, ymax)
                            saved_temp_lines.extend(box_lines)
                            t.Commit()
                            uidoc.RefreshActiveView()
                    except Exception:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()

                    saved_zone = PickBoxZone(box_ref, temp_line_ids=saved_temp_lines)
            except RevitExceptions.OperationCanceledException:
                pass
            except Exception as ex:
                show_warning(u"Thao tác PickBox:\n{}".format(safe_unicode(ex)), u"Thông báo")
            continue

        # ── Chế độ 2: Kẻ Line trực tiếp (Vẽ đường đỏ ngay khi click, ESC kết thúc) ──
        elif action == "PICK_ZONE_LINE":
            cleanup_temp_lines(doc, saved_temp_lines)
            saved_temp_lines = []

            pts = []
            active_view = doc.ActiveView
            snaps = (UI.Selection.ObjectSnapTypes.Endpoints |
                     UI.Selection.ObjectSnapTypes.Intersections |
                     UI.Selection.ObjectSnapTypes.Midpoints |
                     UI.Selection.ObjectSnapTypes.Nearest)

            prev_pt = None
            try:
                while True:
                    idx = len(pts) + 1
                    if idx == 1:
                        prompt = u"Click điểm thứ 1 (Điểm bắt đầu vẽ đường biên)"
                    else:
                        prompt = u"Click điểm thứ {} (Nhấn ESC để hoàn thành đường biên)".format(idx)

                    pt = uidoc.Selection.PickPoint(snaps, prompt)
                    pts.append(pt)

                    # Vẽ ngay lập tức lên màn hình để người dùng nhìn thấy đường line trực tiếp
                    t = DB.Transaction(doc, "MEPANANA - Draw Line Preview")
                    try:
                        if t.Start() == DB.TransactionStatus.Started:
                            if idx == 1:
                                m_ids = create_temp_crosshair(doc, active_view, pt)
                                saved_temp_lines.extend(m_ids)
                            else:
                                lid = create_temp_line(doc, active_view, prev_pt, pt)
                                if lid:
                                    saved_temp_lines.append(lid)
                            t.Commit()
                            uidoc.RefreshActiveView()
                    except Exception as ex_t:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()

                    prev_pt = pt

            except RevitExceptions.OperationCanceledException:
                # Người dùng nhấn phím ESC để chốt hoàn thành đường biên
                pass
            except Exception as ex:
                show_warning(u"Thao tác kẻ line:\n{}".format(safe_unicode(ex)), u"Thông báo")

            # Nếu từ 3 điểm trở lên, tự động vẽ đường đỏ khép kín nối điểm cuối về điểm đầu
            if len(pts) >= 3 and prev_pt:
                t = DB.Transaction(doc, "MEPANANA - Close Polygon")
                try:
                    if t.Start() == DB.TransactionStatus.Started:
                        lid = create_temp_line(doc, active_view, prev_pt, pts[0])
                        if lid:
                            saved_temp_lines.append(lid)
                        t.Commit()
                        uidoc.RefreshActiveView()
                except Exception:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()

            if len(pts) >= 2:
                saved_zone = LinePolygonZone(pts, temp_line_ids=saved_temp_lines)
            elif len(pts) == 1:
                cleanup_temp_lines(doc, saved_temp_lines)
                saved_temp_lines = []
                show_warning(u"Cần click ít nhất 2 điểm để tạo đường kẻ line (nhấn ESC khi hoàn thành).", u"Chưa đủ điểm")
            continue

        # ── Bố trí đầu báo & Xóa sạch đường tạm ──
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
                    # Xóa các đường preview tạm để giữ mô hình sạch sẽ
                    for lid in saved_temp_lines:
                        try:
                            doc.Delete(lid)
                        except Exception:
                            pass
                    saved_temp_lines = []

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
            # Người dùng bấm Đóng hoặc phím ESC
            cleanup_temp_lines(doc, saved_temp_lines)
            saved_temp_lines = []
            break


# ── 10. Entry Point ───────────────────────────────────────────────────────────
run()
