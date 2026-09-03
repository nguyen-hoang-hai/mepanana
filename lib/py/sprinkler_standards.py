# -*- coding: utf-8 -*-
"""
Sprinkler Engineering Standards Reference Database & Interactive Modal
Part of mepanana.extension.
Provides exact NFPA 13 (2016, 2019/2022) & TCVN 7336:2021 engineering clauses,
code comparisons, and technical limits for all 6 Sprinkler Studio configurations.
"""
import os
import sys
import clr
clr.AddReference("System")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
import System
from System.Windows import Visibility, Point, FontWeights, Thickness, CornerRadius
from System.Windows.Controls import Canvas, TextBlock, Border, StackPanel, Grid, ColumnDefinition
from System.Windows.Media import Brushes, SolidColorBrush, Color
from pyrevit import forms
from py.ui import setup_window

def safe_unicode(val):
    if val is None:
        return u""
    try:
        if isinstance(val, unicode):
            return val
        return unicode(str(val), "utf-8", errors="replace")
    except Exception:
        try:
            return unicode(val)
        except Exception:
            return str(val)

# ── Standards Database (NFPA 13 & TCVN 7336:2021) ────────────────────────────

STANDARDS_DB = {
    "PENDENT": {
        "title": u"Pendent Sprinkler Studio",
        "modes": [
            {
                "key": "FLEX",
                "display": u"Mode 1: Flexible Sprinkler Hose Drop (Ống mềm trần treo)",
                "nfpa_edition": "NFPA 13 (2019/2022) Sec. 16.4.5 & NFPA 13 (2016) Sec. 9.2.3.4",
                "nfpa_rules": [
                    (
                        "Listing Requirement (Sec. 16.4.5.1)",
                        u"Cụm ống mềm nối đầu phun phải được kiểm định niêm yết (Listed per UL 2443 hoặc FM 1637) và lắp đặt nghiêm ngặt theo hướng dẫn kỹ thuật của nhà sản xuất."
                    ),
                    (
                        "Minimum Bend Radius (Sec. 16.4.5.2)",
                        u"Bán kính uốn cong của ống mềm không được nhỏ hơn giá trị niêm yết của nhà sản xuất (thông thường R ≥ 250 mm / 10 in.). Tuyệt đối không được vặn xoắn hoặc bẻ gập ống."
                    ),
                    (
                        "Ceiling Bracket Anchorage (Sec. 16.4.5.3)",
                        u"Đầu cút nối ren giảm (reducer nipple) bắt đầu phun phải được cố định vững chắc vào hệ khung trần treo (ASTM C635/C636) bằng bộ giá đỡ kim loại chuyên dụng để triệt tiêu lực giật khi xả nước áp lực cao."
                    ),
                    (
                        "Maximum Unsupported Length (Sec. 17.4.1.3)",
                        u"Chiều dài tự do không treo đỡ của ống mềm không được vượt quá 1,8 m (6 ft). Trường hợp vượt quá bắt buộc phải bố trí quang treo phụ độc lập vào trần kết cấu."
                    ),
                ],
                "tcvn_edition": "TCVN 7336:2021 Điều 5.3 & 6.7",
                "tcvn_rules": [
                    (
                        u"Khoảng cách đầu phun đến trần (Điều 5.3.1.2)",
                        u"Khoảng cách từ tâm phần tử nhạy cảm nhiệt của đầu phun sprinkler đến mặt phẳng trần treo nằm trong khoảng từ 0,08 m đến 0,30 m (lắp phẳng hoặc âm mép trần theo phê duyệt thiết bị)."
                    ),
                    (
                        u"Sử dụng ống mềm chuyên dụng (Điều 6.7.12)",
                        u"Cho phép sử dụng ống nối mềm bằng kim loại không gỉ chuyên dụng cho PCCC để nối từ ống phân phối nhánh đến đầu phun sprinkler lắp trên trần treo thạch cao hoặc khung kim loại."
                    ),
                    (
                        u"Yêu cầu ngàm giữ chống rung giật (Điều 6.7.13)",
                        u"Ống mềm phải có chứng nhận kiểm định PCCC và phải có cơ cấu kẹp giữ định vị chắc chắn vào xương trần/kết cấu để chống xô lệch góc phun khi hệ thống kích hoạt."
                    ),
                ],
                "specs": [
                    (u"Bán kính uốn tối thiểu (R_min)", u"R ≥ 250 mm (10 in.)"),
                    (u"Độ chênh cao khuyến nghị (ΔZ)", u"ΔZ ≥ 150 mm (chống gập ống chữ S)"),
                    (u"Kích thước ống danh nghĩa", u"DN25 (1 in.) / Cút ren K-Factor 5.6"),
                    (u"Áp suất làm việc danh định", u"P = 12 bar – 16 bar (175 – 200 psi)"),
                    (u"Độ dài ống mềm tiêu chuẩn", u"700 mm / 1000 mm / 1200 mm / 1500 mm"),
                ]
            },
            {
                "key": "RIGID",
                "display": u"Mode 2: Rigid Steel Return Bend Drop (Ống thép cứng chữ U)",
                "nfpa_edition": "NFPA 13 (2019/2022) Sec. 16.4.3 & Sec. 27.2",
                "nfpa_rules": [
                    (
                        "Return Bend Mandate (Sec. 16.4.3.1 - 16.4.3.2)",
                        u"Kết cấu ống uốn chữ U (Return Bend) là giải pháp bắt buộc đối với hệ thống dùng nước thô, nước giếng, nguồn nước có cặn hoặc hệ thống đường ống khô/luân phiên nhằm ngăn bùn cặn và rỉ sét lắng đọng làm nghẽn lỗ xả đầu phun."
                    ),
                    (
                        "Top of Branch Line Takeoff (Sec. 16.4.3.3)",
                        u"Điểm trích nhánh cho ống đứng (Riser Nipple) bắt buộc phải lấy từ đỉnh trên cùng (Crown/Top) của ống cấp chính, không được lấy ở đáy hoặc hông ống."
                    ),
                    (
                        "Pipe Schedule Hydraulic Sizing (Table 27.2.4.1)",
                        u"Kích thước ống nhánh: 1 đầu phun: tối thiểu DN25 (1 in.); 2 đầu phun: tối thiểu DN32 (1-1/4 in.); 3 đầu phun: tối thiểu DN40 (1-1/2 in.)."
                    ),
                ],
                "tcvn_edition": "TCVN 7336:2021 Điều 6.7 & Bảng 11",
                "tcvn_rules": [
                    (
                        u"Trích nhánh chống cặn bẩn (Điều 6.7.8 - 6.7.10)",
                        u"Khi lắp đầu phun Pendent ở hệ thống có nguy cơ đóng cặn hoặc hệ thống ống khô, điểm nối lấy nước phải đấu từ phía trên đường sinh đỉnh của ống cấp (ống chữ U hoặc ống đứng từ lưng ống). Tuyệt đối cấm lấy từ đáy ống."
                    ),
                    (
                        u"Bảng tính toán đường kính ống (Bảng 11)",
                        u"Quy định số lượng đầu phun tối đa theo đường kính danh nghĩa của ống cấp: 1 đầu phun đi ống DN25; 2 đầu phun đi ống DN32."
                    ),
                ],
                "specs": [
                    (u"Cao độ ống đứng lưng ống (H)", u"H = 200 mm – 400 mm (Mặc định 300 mm)"),
                    (u"Điểm lấy nhánh", u"Đỉnh ống cấp (Crown Takeoff / Olet)"),
                    (u"Cỡ ống nhánh giật cấp", u"DN32 (trên 1 đầu) → DN25 (đầu cuối)"),
                    (u"Vật liệu ống tiêu chuẩn", u"Ống thép tráng kẽm nhúng nóng ASTM A53"),
                ]
            }
        ]
    },

    "UPRIGHT": {
        "title": u"Upright Sprinkler Studio",
        "modes": [
            {
                "key": "DIRECT",
                "display": u"Direct Vertical Riser Up (Ống đứng nhú thẳng từ lưng ống)",
                "nfpa_edition": "NFPA 13 (2019/2022) Sec. 10.2 & Sec. 9.2.2",
                "nfpa_rules": [
                    (
                        "Deflector Position Below Ceilings (Sec. 10.2.6.1)",
                        u"Đối với kết cấu trần phẳng không dầm cản trở (Unobstructed Construction), khoảng cách từ tấm định hướng dòng (Deflector) của đầu phun Upright đến trần/mái: Tối thiểu 1 in. (25,4 mm), tối đa 12 in. (305 mm)."
                    ),
                    (
                        "Obstructed Construction Limit (Sec. 10.2.6.2)",
                        u"Đối với trần có dầm kết cấu lộ (Obstructed Construction), khoảng cách tối đa cho phép là 22 in. (559 mm)."
                    ),
                    (
                        "Direct Branch Line Connection (Sec. 9.2.2.1)",
                        u"Đầu phun Upright được phép lắp trực tiếp trên đỉnh ống nhánh thông qua đoạn ống đứng ngắn (Riser Nipple) nối ren hoặc Welded Olet."
                    ),
                ],
                "tcvn_edition": "TCVN 7336:2021 Điều 5.3 & 6.7",
                "tcvn_rules": [
                    (
                        u"Khoảng cách đến mặt trần/mái (Điều 5.3.1.2)",
                        u"Khoảng cách từ tấm định hướng dòng của đầu phun Upright tới mặt phẳng trần hoặc mái phải nằm trong giới hạn từ 0,08 m (80 mm) đến 0,30 m (300 mm) đối với trần phẳng. Mái dốc tối đa 0,40 m."
                    ),
                    (
                        u"Yêu cầu phương lắp đặt (Điều 6.7.6)",
                        u"Đầu phun Upright phải được lắp đặt thẳng đứng, hướng lên trên, trục tâm vuông góc với mặt phẳng trần hoặc sàn mái."
                    ),
                ],
                "specs": [
                    (u"Cao độ tấm tán nước dưới trần", u"80 mm – 300 mm (Chuẩn TCVN / NFPA)"),
                    (u"Chiều cao Riser Nipple (H)", u"H = 100 mm – 300 mm (Mặc định 150 mm)"),
                    (u"Đường kính ống đứng", u"DN25 (1 in.) – DN32 (1-1/4 in.)"),
                    (u"Vị trí đấu nối", u"Đỉnh tâm ống cấp (Crown Takeoff)"),
                ]
            }
        ]
    },

    "SIDEWALL": {
        "title": u"Sidewall Sprinkler Studio",
        "modes": [
            {
                "key": "RIGID",
                "display": u"Mode 1: Rigid Steel Wall Drop (Ống thép cứng luồn vách 90°)",
                "nfpa_edition": "NFPA 13 (2019/2022) Sec. 10.3 & Sec. 8.7",
                "nfpa_rules": [
                    (
                        "Distance Below Ceiling (Sec. 10.3.6.1)",
                        u"Tấm định hướng dòng của đầu phun Sidewall phải cách mặt dưới trần phẳng từ 4 in. (102 mm) đến 6 in. (152 mm), tối đa không quá 12 in. (305 mm)."
                    ),
                    (
                        "Distance from Back Wall (Sec. 10.3.6.2)",
                        u"Tấm định hướng dòng của đầu phun phải cách mặt phẳng tường mà nó được gắn từ 4 in. (102 mm) đến 6 in. (152 mm). Không được lắp sát tường dưới 100 mm gây cản trở quạt phun hình bán nguyệt."
                    ),
                    (
                        "Deflector Alignment (Sec. 10.3.6.3)",
                        u"Tấm định hướng dòng phải được bố trí song song tuyệt đối với mặt phẳng trần hoặc mái."
                    ),
                ],
                "tcvn_edition": "TCVN 7336:2021 Điều 5.3.2 & 6.7.5",
                "tcvn_rules": [
                    (
                        u"Cao độ đầu phun gắn tường (Điều 5.3.2)",
                        u"Khoảng cách từ tấm định hướng dòng của đầu phun sprinkler gắn tường đến mặt phẳng trần (hoặc sàn trên) phải nằm trong khoảng từ 0,10 m (100 mm) đến 0,15 m (150 mm)."
                    ),
                    (
                        u"Khoảng cách tới tường bên (Điều 5.3.2)",
                        u"Khoảng cách từ đầu phun tới mặt tường sau không quá 0,15 m (150 mm) và tối thiểu không dưới 0,08 m – 0,10 m để không va quệt cánh phun làm hẹp góc bao phủ."
                    ),
                    (
                        u"Định hướng mặt phẳng phun (Điều 6.7.5)",
                        u"Tấm định hướng dòng phải song song với trần nhà và hướng luồng nước phun ra khu vực bảo vệ theo thiết kế."
                    ),
                ],
                "specs": [
                    (u"Khoảng cách tâm đầu phun tới trần", u"100 mm – 150 mm (4 – 6 in.)"),
                    (u"Khoảng lùi tấm định hướng cách tường", u"100 mm (Mặc định Wall Offset)"),
                    (u"Đường kính ống thả vách", u"DN25 (1 in.) – DN32 (1-1/4 in.)"),
                    (u"Cấu hình phụ kiện", u"Co 90° thả trần + Co 90° đâm xuyên vách"),
                ]
            },
            {
                "key": "FLEX",
                "display": u"Mode 2: Flexible Sidewall Hose (Ống mềm xuyên vách thạch cao)",
                "nfpa_edition": "NFPA 13 (2019/2022) Sec. 16.4.5.1 & Sec. 16.4.5.3",
                "nfpa_rules": [
                    (
                        "Listed Wall-Mount Assembly (Sec. 16.4.5.1)",
                        u"Ống mềm nối đầu phun gắn tường phải được kiểm định niêm yết (UL 2443 / FM 1637) kèm bộ ngàm chuyên dụng cho kết cấu vách tường."
                    ),
                    (
                        "Rigid Stud Anchorage (Sec. 16.4.5.3)",
                        u"Bộ giá đỡ ống mềm gắn tường phải được bắt vít cố định chắc chắn vào xương kim loại (Drywall Studs) hoặc tường xây để chống mô-men xoắn ngang khi đầu phun hoạt động."
                    ),
                ],
                "tcvn_edition": "TCVN 7336:2021 Điều 6.7.12",
                "tcvn_rules": [
                    (
                        u"Ứng dụng ống mềm gắn tường (Điều 6.7.12)",
                        u"Cho phép sử dụng ống mềm PCCC luồn trong vách thạch cao nhẹ (phòng khách sạn, căn hộ) với điều kiện ống được kiểm định áp lực và có phụ kiện kẹp định vị vững chắc vào kết cấu vách."
                    ),
                ],
                "specs": [
                    (u"Bán kính uốn tối thiểu", u"R ≥ 250 mm (10 in.)"),
                    (u"Điểm neo giữ ống", u"Bát gá chuyên dụng bắt vào đố vách thạch cao"),
                    (u"Đường kính danh nghĩa", u"DN25 (1 in.)"),
                    (u"Chiều dài ống mềm", u"700 mm – 1200 mm"),
                ]
            }
        ]
    }
}


# ── Standards Reference Window Controller ────────────────────────────────────

class StandardsReferenceWindow(forms.WPFWindow):
    def __init__(self, tool_key="PENDENT", initial_mode_key=None):
        xaml_path = os.path.join(os.path.dirname(__file__), "standards_dialog.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        setup_window(self)

        self.tool_key = tool_key.upper()
        self.tool_data = STANDARDS_DB.get(self.tool_key, STANDARDS_DB["PENDENT"])

        # Setup Header Title
        if hasattr(self, 'txtToolTitle'):
            self.txtToolTitle.Text = self.tool_data["title"]

        # Populate Mode ComboBox
        if hasattr(self, 'cmbMode'):
            self.cmbMode.Items.Clear()
            selected_idx = 0
            for idx, mode in enumerate(self.tool_data["modes"]):
                self.cmbMode.Items.Add(mode["display"])
                if initial_mode_key and mode["key"].upper() == initial_mode_key.upper():
                    selected_idx = idx
            self.cmbMode.SelectedIndex = selected_idx
            self.cmbMode.SelectionChanged += self.OnModeSelectionChanged

        # Wire Action Buttons
        if hasattr(self, 'btnCopy'):
            self.btnCopy.Click += self.OnCopyNotes
        if hasattr(self, 'btnClose'):
            self.btnClose.Click += self.OnClose

        self.RenderSelectedMode()

    def GetCurrentMode(self):
        idx = self.cmbMode.SelectedIndex if hasattr(self, 'cmbMode') else 0
        if idx < 0 or idx >= len(self.tool_data["modes"]):
            idx = 0
        return self.tool_data["modes"][idx]

    def OnModeSelectionChanged(self, sender, args):
        self.RenderSelectedMode()
        if hasattr(self, 'txtStatus'):
            self.txtStatus.Text = ""

    def RenderSelectedMode(self):
        mode = self.GetCurrentMode()

        # Update Badges
        if hasattr(self, 'txtNFPAEdition'):
            self.txtNFPAEdition.Text = mode["nfpa_edition"]
        if hasattr(self, 'txtTCVNEdition'):
            self.txtTCVNEdition.Text = mode["tcvn_edition"]

        # Render NFPA Card
        if hasattr(self, 'panelNFPA'):
            self.panelNFPA.Children.Clear()
            for title, desc in mode["nfpa_rules"]:
                self.panelNFPA.Children.Add(self.CreateRuleItem(title, desc, is_nfpa=True))

        # Render TCVN Card
        if hasattr(self, 'panelTCVN'):
            self.panelTCVN.Children.Clear()
            for title, desc in mode["tcvn_rules"]:
                self.panelTCVN.Children.Add(self.CreateRuleItem(title, desc, is_nfpa=False))

        # Render Specs Card
        if hasattr(self, 'panelSpecs'):
            self.panelSpecs.Children.Clear()
            for param, val in mode["specs"]:
                self.panelSpecs.Children.Add(self.CreateSpecItem(param, val))

    def CreateRuleItem(self, title, desc, is_nfpa=True):
        b = Border()
        b.Margin = Thickness(0, 0, 0, 8)
        b.Padding = Thickness(10, 8, 10, 8)
        b.CornerRadius = CornerRadius(6)
        b.Background = SolidColorBrush(Color.FromRgb(248, 250, 252)) if is_nfpa else SolidColorBrush(Color.FromRgb(240, 253, 244))
        b.BorderBrush = SolidColorBrush(Color.FromRgb(226, 232, 240)) if is_nfpa else SolidColorBrush(Color.FromRgb(187, 247, 208))
        b.BorderThickness = Thickness(1)

        sp = StackPanel()
        sp.Orientation = System.Windows.Controls.Orientation.Vertical

        tb_title = TextBlock()
        tb_title.Text = title
        tb_title.FontWeight = FontWeights.Bold
        tb_title.FontSize = 11.5
        tb_title.Foreground = SolidColorBrush(Color.FromRgb(30, 41, 59))
        tb_title.Margin = Thickness(0, 0, 0, 3)

        tb_desc = TextBlock()
        tb_desc.Text = desc
        tb_desc.FontSize = 11.5
        tb_desc.Foreground = SolidColorBrush(Color.FromRgb(71, 85, 105))
        tb_desc.TextWrapping = System.Windows.TextWrapping.Wrap

        sp.Children.Add(tb_title)
        sp.Children.Add(tb_desc)
        b.Child = sp
        return b

    def CreateSpecItem(self, param, val):
        b = Border()
        b.Margin = Thickness(0, 0, 0, 6)
        b.Padding = Thickness(10, 6, 10, 6)
        b.CornerRadius = CornerRadius(4)
        b.Background = SolidColorBrush(Color.FromRgb(254, 252, 232))
        b.BorderBrush = SolidColorBrush(Color.FromRgb(254, 240, 138))
        b.BorderThickness = Thickness(1)

        g = Grid()
        cd1 = ColumnDefinition(); cd1.Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Star)
        cd2 = ColumnDefinition(); cd2.Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Auto)
        g.ColumnDefinitions.Add(cd1)
        g.ColumnDefinitions.Add(cd2)

        tb_p = TextBlock()
        tb_p.Text = param
        tb_p.FontWeight = FontWeights.SemiBold
        tb_p.FontSize = 11.5
        tb_p.Foreground = SolidColorBrush(Color.FromRgb(113, 63, 18))
        tb_p.VerticalAlignment = System.Windows.VerticalAlignment.Center

        tb_v = TextBlock()
        tb_v.Text = val
        tb_v.FontWeight = FontWeights.Bold
        tb_v.FontSize = 11.5
        tb_v.Foreground = SolidColorBrush(Color.FromRgb(180, 83, 9))
        tb_v.VerticalAlignment = System.Windows.VerticalAlignment.Center
        Grid.SetColumn(tb_v, 1)

        g.Children.Add(tb_p)
        g.Children.Add(tb_v)
        b.Child = g
        return b

    def OnCopyNotes(self, sender, args):
        mode = self.GetCurrentMode()
        lines = []
        lines.append(u"=== {} - {} ===".format(self.tool_data["title"], mode["display"]))
        lines.append(u"\n[NFPA 13 STANDARDS - {}]".format(mode["nfpa_edition"]))
        for t, d in mode["nfpa_rules"]:
            lines.append(u"• {}: {}".format(t, d))

        lines.append(u"\n[TCVN 7336:2021 QUY CHUẨN - {}]".format(mode["tcvn_edition"]))
        for t, d in mode["tcvn_rules"]:
            lines.append(u"• {}: {}".format(t, d))

        lines.append(u"\n[ENGINEERING SPECIFICATIONS]")
        for p, v in mode["specs"]:
            lines.append(u"• {}: {}".format(p, v))

        full_text = u"\n".join(lines)
        try:
            System.Windows.Clipboard.SetText(full_text)
            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"✓ Notes copied to clipboard!"
        except Exception as ex:
            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"Failed to copy: " + safe_unicode(ex)

    def OnClose(self, sender, args):
        self.Close()


# ── Public Show Function ──────────────────────────────────────────────────────

def show_standards_dialog(parent_window=None, tool_key="PENDENT", current_mode_key=None):
    """
    Opens the interactive Standards Reference Dialog modal.
    tool_key: 'PENDENT', 'UPRIGHT', or 'SIDEWALL'
    current_mode_key: 'FLEX', 'RIGID', 'DIRECT', 'ARM_OVER'
    """
    try:
        win = StandardsReferenceWindow(tool_key=tool_key, initial_mode_key=current_mode_key)
        if parent_window:
            win.Owner = parent_window
        win.ShowDialog()
    except Exception as ex:
        from py.ui import show_error
        show_error(u"Error opening Standards Reference Dialog:\n{}".format(safe_unicode(ex)), "Standards Guide")
