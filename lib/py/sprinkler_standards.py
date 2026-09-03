# -*- coding: utf-8 -*-
"""
Sprinkler Engineering Standards Reference Database & Interactive Modal
Part of mepanana.extension.
Provides exact NFPA 13 (2016, 2019/2022) & TCVN 7336:2021 engineering clauses,
bilingual formatting (Tiếng Việt trên, Tiếng Anh in nghiêng dưới),
code comparisons, and technical limits for all Sprinkler Studio tools.
"""
import os
import sys
import clr
clr.AddReference("System")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
import System
from System.Windows import Visibility, Point, FontWeights, FontStyles, Thickness, CornerRadius
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

# ── Standards Database (Bilingual: Tiếng Việt trên, Tiếng Anh in nghiêng dưới) ──

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
                        u"Chứng chỉ kiểm định niêm yết (Sec. 16.4.5.1)",
                        "Listing Requirement (Sec. 16.4.5.1)",
                        u"Cụm ống mềm nối đầu phun phải được kiểm định niêm yết (Listed per UL 2443 hoặc FM 1637) và lắp đặt nghiêm ngặt theo hướng dẫn kỹ thuật của nhà sản xuất.",
                        "Flexible sprinkler hose fittings shall be listed (UL 2443 or FM 1637) and installed per manufacturer instructions."
                    ),
                    (
                        u"Bán kính uốn tối thiểu (Sec. 16.4.5.2)",
                        "Minimum Bend Radius (Sec. 16.4.5.2)",
                        u"Bán kính uốn cong của ống mềm không được nhỏ hơn giá trị niêm yết của nhà sản xuất (thông thường R ≥ 250 mm / 10 in.). Tuyệt đối không được vặn xoắn hoặc bẻ gập ống.",
                        "Bending radius shall not be less than manufacturer listed minimum bend radius (typically R >= 250 mm / 10 in.). No kinking or twisting."
                    ),
                    (
                        u"Giá đỡ ngàm cố định khung trần (Sec. 16.4.5.3)",
                        "Ceiling Bracket Anchorage (Sec. 16.4.5.3)",
                        u"Đầu cút nối ren giảm (reducer nipple) bắt đầu phun phải được cố định vững chắc vào hệ khung trần treo (ASTM C635/C636) bằng bộ giá đỡ kim loại chuyên dụng để triệt tiêu lực giật khi xả nước.",
                        "Sprinkler reducer nipple must be rigidly secured to ceiling grid (ASTM C635/C636) with listed bracket assembly."
                    ),
                    (
                        u"Chiều dài tự do không treo đỡ (Sec. 17.4.1.3)",
                        "Maximum Unsupported Length (Sec. 17.4.1.3)",
                        u"Chiều dài tự do không treo đỡ của ống mềm không được vượt quá 1,8 m (6 ft). Trường hợp vượt quá bắt buộc phải bố trí quang treo phụ độc lập vào trần kết cấu.",
                        "Max unsupported length shall not exceed 6 ft (1.8 m); otherwise independent structural hanger is required."
                    ),
                ],
                "tcvn_edition": "TCVN 7336:2021 Điều 5.3 & 6.7",
                "tcvn_rules": [
                    (
                        u"Khoảng cách đầu phun đến trần (Điều 5.3.1.2)",
                        "Clearance to Ceiling (Clause 5.3.1.2)",
                        u"Khoảng cách từ tâm phần tử nhạy cảm nhiệt của đầu phun sprinkler đến mặt phẳng trần treo nằm trong khoảng từ 0,08 m đến 0,30 m (lắp phẳng hoặc âm mép trần theo phê duyệt thiết bị).",
                        "Distance from thermal element center to ceiling plane shall be between 0.08 m and 0.30 m."
                    ),
                    (
                        u"Sử dụng ống mềm chuyên dụng (Điều 6.7.12)",
                        "Flexible Hose Authorization (Clause 6.7.12)",
                        u"Cho phép sử dụng ống nối mềm bằng kim loại không gỉ chuyên dụng cho PCCC để nối từ ống phân phối nhánh đến đầu phun sprinkler lắp trên trần treo thạch cao hoặc khung kim loại.",
                        "Stainless steel flexible sprinkler hoses approved for fire protection are permitted for branchline connections in suspended ceilings."
                    ),
                    (
                        u"Yêu cầu ngàm giữ chống rung giật (Điều 6.7.13)",
                        "Anti-Vibration Anchorage (Clause 6.7.13)",
                        u"Ống mềm phải có chứng nhận kiểm định PCCC và phải có cơ cấu kẹp giữ định vị chắc chắn vào xương trần/kết cấu để chống xô lệch góc phun khi hệ thống kích hoạt.",
                        "Must possess fire safety certification and rigid clamp brackets attached to ceiling runners to resist discharge torque."
                    ),
                ],
                "specs": [
                    (u"Bán kính uốn tối thiểu", "Minimum bend radius (R_min)", u"R ≥ 250 mm (10 in.)"),
                    (u"Độ chênh cao khuyến nghị", "Recommended height offset (ΔZ)", u"ΔZ ≥ 150 mm (Anti-kink S-Curve)"),
                    (u"Kích thước ống danh nghĩa", "Nominal pipe size", u"DN25 (1 in.) / K-Factor 5.6"),
                    (u"Áp suất làm việc danh định", "Working test pressure", u"P = 12 bar – 16 bar (175 – 200 psi)"),
                ]
            },
            {
                "key": "RIGID",
                "display": u"Mode 2: Rigid Steel Return Bend Drop (Ống thép cứng chữ U)",
                "nfpa_edition": "NFPA 13 (2019/2022) Sec. 16.4.3 & Sec. 27.2",
                "nfpa_rules": [
                    (
                        u"Bắt buộc kết cấu uốn chữ U (Sec. 16.4.3.1 - 16.4.3.2)",
                        "Return Bend Mandate (Sec. 16.4.3.1 - 16.4.3.2)",
                        u"Kết cấu ống uốn chữ U (Return Bend) là giải pháp bắt buộc đối với hệ thống dùng nước thô, nước giếng, nguồn nước có cặn hoặc hệ thống đường ống khô nhằm ngăn bùn cặn và rỉ sét làm nghẽn đầu phun.",
                        "Return bends shall be used when pendent sprinklers are supplied from raw water or dry pipe systems to prevent sediment from clogging sprinklers."
                    ),
                    (
                        u"Trích nhánh từ đỉnh lưng ống (Sec. 16.4.3.3)",
                        "Top of Branch Line Takeoff (Sec. 16.4.3.3)",
                        u"Điểm trích nhánh cho ống đứng (Riser Nipple) bắt buộc phải lấy từ đỉnh trên cùng (Crown/Top) của ống cấp chính, không được lấy ở đáy hoặc hông ống.",
                        "Takeoffs for return bends or risers shall be from the top of the branch line, never from the bottom."
                    ),
                    (
                        u"Bảng định cỡ ống thủy lực (Table 27.2.4.1)",
                        "Hydraulic Sizing Schedule (Table 27.2.4.1)",
                        u"Kích thước ống nhánh: 1 đầu phun: tối thiểu DN25 (1 in.); 2 đầu phun: tối thiểu DN32 (1-1/4 in.); 3 đầu phun: tối thiểu DN40 (1-1/2 in.).",
                        "Branch line sizing: 1 sprinkler = DN25 (1 in.); 2 sprinklers = DN32 (1-1/4 in.); 3 sprinklers = DN40 (1-1/2 in.)."
                    ),
                ],
                "tcvn_edition": "TCVN 7336:2021 Điều 6.7 & Bảng 11",
                "tcvn_rules": [
                    (
                        u"Trích nhánh chống cặn bẩn (Điều 6.7.8 - 6.7.10)",
                        "Sediment Prevention Takeoff (Clause 6.7.8 - 6.7.10)",
                        u"Khi lắp đầu phun Pendent ở hệ thống có nguy cơ đóng cặn hoặc hệ thống ống khô, điểm nối lấy nước phải đấu từ phía trên đường sinh đỉnh của ống cấp. Cấm lấy từ đáy ống.",
                        "Takeoffs must connect from above the crown centerline of the supply pipe to avoid sediment deposition."
                    ),
                    (
                        u"Bảng tính toán đường kính ống (Bảng 11)",
                        "Pipe Diameter Schedule (Table 11)",
                        u"Quy định số lượng đầu phun tối đa theo đường kính danh nghĩa của ống cấp: 1 đầu phun đi ống DN25; 2 đầu phun đi ống DN32.",
                        "Maximum allowable sprinkler count per pipe diameter: 1 head = DN25; 2 heads = DN32."
                    ),
                ],
                "specs": [
                    (u"Cao độ ống đứng lưng ống (H)", "Riser nipple height (H)", u"H = 200 mm – 400 mm (Default 300 mm)"),
                    (u"Điểm lấy nhánh", "Takeoff connection point", u"Đỉnh ống cấp (Crown Takeoff / Olet)"),
                    (u"Cỡ ống nhánh giật cấp", "Stepped branch sizing", u"DN32 (trên 1 đầu) → DN25 (đầu cuối)"),
                    (u"Vật liệu ống tiêu chuẩn", "Standard pipe material", u"Ống thép tráng kẽm nhúng nóng ASTM A53"),
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
                        u"Khoảng cách đĩa tán nước dưới trần phẳng (Sec. 10.2.6.1)",
                        "Deflector Position Below Ceilings (Sec. 10.2.6.1)",
                        u"Đối với kết cấu trần phẳng không dầm cản trở (Unobstructed Construction), khoảng cách từ tấm định hướng dòng (Deflector) của đầu phun Upright đến trần/mái: Tối thiểu 1 in. (25,4 mm), tối đa 12 in. (305 mm).",
                        "For unobstructed construction, the distance between the deflector of an upright sprinkler and the ceiling shall be a minimum of 1 in. (25.4 mm) and a maximum of 12 in. (305 mm)."
                    ),
                    (
                        u"Giới hạn trần dầm kết cấu lộ (Sec. 10.2.6.2)",
                        "Obstructed Construction Limit (Sec. 10.2.6.2)",
                        u"Đối với trần có dầm kết cấu lộ (Obstructed Construction), khoảng cách tối đa cho phép là 22 in. (559 mm).",
                        "For obstructed construction, the maximum distance below the ceiling shall be 22 in. (559 mm)."
                    ),
                    (
                        u"Đấu nối trực tiếp đỉnh ống nhánh (Sec. 9.2.2.1)",
                        "Direct Branch Line Connection (Sec. 9.2.2.1)",
                        u"Đầu phun Upright được phép lắp trực tiếp trên đỉnh ống nhánh thông qua đoạn ống đứng ngắn (Riser Nipple) nối ren hoặc Welded Olet.",
                        "Upright sprinklers are permitted to be installed directly on top of branch lines via short riser nipples or welded olets."
                    ),
                ],
                "tcvn_edition": "TCVN 7336:2021 Điều 5.3 & 6.7",
                "tcvn_rules": [
                    (
                        u"Khoảng cách đến mặt trần/mái (Điều 5.3.1.2)",
                        "Clearance to Ceiling / Roof (Clause 5.3.1.2)",
                        u"Khoảng cách từ tấm định hướng dòng của đầu phun Upright tới mặt phẳng trần hoặc mái phải nằm trong giới hạn từ 0,08 m (80 mm) đến 0,30 m (300 mm) đối với trần phẳng. Mái dốc tối đa 0,40 m.",
                        "Distance from upright deflector to ceiling/roof plane shall be within 0.08 m (80 mm) to 0.30 m (300 mm) for flat ceilings, max 0.40 m for sloped roofs."
                    ),
                    (
                        u"Yêu cầu phương lắp đặt (Điều 6.7.6)",
                        "Installation Orientation (Clause 6.7.6)",
                        u"Đầu phun Upright phải được lắp đặt thẳng đứng, hướng lên trên, trục tâm vuông góc với mặt phẳng trần hoặc sàn mái.",
                        "Upright sprinklers must be mounted vertically upright, with their centerline perpendicular to the ceiling/roof plane."
                    ),
                ],
                "specs": [
                    (u"Cao độ tấm tán nước dưới trần", "Deflector clearance below ceiling", u"80 mm – 300 mm (Chuẩn TCVN / NFPA)"),
                    (u"Chiều cao Riser Nipple (H)", "Riser Nipple height (H)", u"H = 100 mm – 300 mm (Default 150 mm)"),
                    (u"Đường kính ống đứng", "Riser pipe nominal diameter", u"DN25 (1 in.) – DN32 (1-1/4 in.)"),
                    (u"Vị trí đấu nối", "Takeoff connection point", u"Đỉnh tâm ống cấp (Crown Takeoff)"),
                ]
            }
        ]
    },

    "SIDEWALL": {
        "title": u"Sidewall Sprinkler Studio",
        "modes": [
            {
                "key": "RIGID",
                "display": u"Rigid Steel Wall Drop (Ống thép cứng luồn vách 90°)",
                "nfpa_edition": "NFPA 13 (2019/2022) Sec. 10.3 & Sec. 8.7",
                "nfpa_rules": [
                    (
                        u"Khoảng cách dưới trần (Sec. 10.3.6.1)",
                        "Distance Below Ceilings (Sec. 10.3.6.1)",
                        u"Tấm định hướng dòng của đầu phun Sidewall phải cách mặt dưới trần phẳng từ 102 mm đến 152 mm (4 in. đến 6 in.), tối đa không quá 305 mm (12 in.).",
                        "Deflectors of sidewall sprinklers shall be located 4 in. to 6 in. (102 mm to 152 mm) below unobstructed ceilings, with a maximum of 12 in. (305 mm)."
                    ),
                    (
                        u"Khoảng cách đến tường sau (Sec. 10.3.6.2)",
                        "Distance from Back Wall (Sec. 10.3.6.2)",
                        u"Tấm định hướng dòng của đầu phun phải cách mặt phẳng tường gắn từ 102 mm đến 152 mm (4 in. đến 6 in.). Không lắp quá sát tường làm biến dạng chùm quạt phun bán nguyệt.",
                        "Deflectors of sidewall sprinklers shall be located 4 in. to 6 in. (102 mm to 152 mm) from the wall on which they are mounted to preserve the parabolic crescent spray pattern."
                    ),
                    (
                        u"Định hướng mặt phẳng tán nước (Sec. 10.3.6.3)",
                        "Deflector Alignment (Sec. 10.3.6.3)",
                        u"Tấm định hướng dòng phải được bố trí song song tuyệt đối với mặt phẳng trần hoặc mái nhà.",
                        "Deflectors of sidewall sprinklers shall be aligned parallel to the ceiling or roof deck."
                    ),
                ],
                "tcvn_edition": "TCVN 7336:2021 Điều 5.3.2 & 6.7.5",
                "tcvn_rules": [
                    (
                        u"Cao độ đầu phun gắn tường (Điều 5.3.2)",
                        "Wall Sprinkler Elevation (Clause 5.3.2)",
                        u"Khoảng cách từ tấm định hướng dòng của đầu phun sprinkler gắn tường đến mặt phẳng trần (hoặc sàn trên) phải nằm trong khoảng từ 0,10 m (100 mm) đến 0,15 m (150 mm).",
                        "Distance from the deflector of wall-mounted sprinklers to the ceiling or floor slab above shall be within 0.10 m (100 mm) to 0.15 m (150 mm)."
                    ),
                    (
                        u"Khoảng cách tới tường sau (Điều 5.3.2)",
                        "Clearance from Back Wall (Clause 5.3.2)",
                        u"Khoảng cách từ đầu phun tới mặt tường sau không quá 0,15 m (150 mm) và tối thiểu không dưới 0,08 m – 0,10 m để không va quệt làm hẹp góc bao phủ bảo vệ.",
                        "Distance from sprinkler to back wall shall not exceed 0.15 m (150 mm) and not less than 0.08 m - 0.10 m to prevent spray pattern obstruction."
                    ),
                    (
                        u"Định hướng luồng phun (Điều 6.7.5)",
                        "Discharge Direction (Clause 6.7.5)",
                        u"Tấm định hướng dòng phải song song với trần nhà và hướng luồng nước phun ra khu vực bảo vệ theo thiết kế.",
                        "Deflector plate must be parallel to the ceiling and direct water flow outward into the designated protection zone."
                    ),
                ],
                "specs": [
                    (u"Khoảng cách tâm đầu phun tới trần", "Deflector clearance below ceiling", u"100 mm – 150 mm (4 – 6 in.)"),
                    (u"Khoảng lùi tấm định hướng cách tường", "Deflector offset from back wall", u"100 mm (Standard Wall Offset)"),
                    (u"Đường kính ống thả vách", "Wall drop pipe diameter", u"DN25 (1 in.) – DN32 (1-1/4 in.)"),
                    (u"Cấu hình phụ kiện kết nối", "Fittings configuration", u"Co 90° thả trần + Co 90° đâm xuyên vách / 90° Drop Elbow + 90° Wall Elbow"),
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

        # If single mode (e.g. UPRIGHT or SIDEWALL), collapse mode switcher
        if hasattr(self, 'borderModeSwitcher'):
            if len(self.tool_data["modes"]) <= 1:
                self.borderModeSwitcher.Visibility = Visibility.Collapsed
            else:
                self.borderModeSwitcher.Visibility = Visibility.Visible

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

        # Render NFPA Card (Bilingual: Tiếng Việt trên, Tiếng Anh dưới in nghiêng)
        if hasattr(self, 'panelNFPA'):
            self.panelNFPA.Children.Clear()
            for rule in mode["nfpa_rules"]:
                self.panelNFPA.Children.Add(self.CreateBilingualRuleItem(rule, is_nfpa=True))

        # Render TCVN Card (Bilingual: Tiếng Việt trên, Tiếng Anh dưới in nghiêng)
        if hasattr(self, 'panelTCVN'):
            self.panelTCVN.Children.Clear()
            for rule in mode["tcvn_rules"]:
                self.panelTCVN.Children.Add(self.CreateBilingualRuleItem(rule, is_nfpa=False))

        # Render Specs Card (Bilingual: Tiếng Việt trên, Tiếng Anh dưới in nghiêng)
        if hasattr(self, 'panelSpecs'):
            self.panelSpecs.Children.Clear()
            for spec in mode["specs"]:
                self.panelSpecs.Children.Add(self.CreateBilingualSpecItem(spec))

    def CreateBilingualRuleItem(self, rule, is_nfpa=True):
        if len(rule) >= 4:
            title_vi, title_en, desc_vi, desc_en = rule[0], rule[1], rule[2], rule[3]
        else:
            title_vi, title_en, desc_vi, desc_en = rule[0], "", rule[1], ""

        b = Border()
        b.Margin = Thickness(0, 0, 0, 8)
        b.Padding = Thickness(10, 8, 10, 8)
        b.CornerRadius = CornerRadius(6)
        b.Background = SolidColorBrush(Color.FromRgb(248, 250, 252)) if is_nfpa else SolidColorBrush(Color.FromRgb(240, 253, 244))
        b.BorderBrush = SolidColorBrush(Color.FromRgb(226, 232, 240)) if is_nfpa else SolidColorBrush(Color.FromRgb(187, 247, 208))
        b.BorderThickness = Thickness(1)

        sp = StackPanel()
        sp.Orientation = System.Windows.Controls.Orientation.Vertical

        # 1. Title (Tiếng Việt trên, Tiếng Anh dưới)
        tb_title = TextBlock()
        tb_title.Text = title_vi
        tb_title.FontWeight = FontWeights.Bold
        tb_title.FontSize = 11.5
        tb_title.Foreground = SolidColorBrush(Color.FromRgb(30, 41, 59))
        sp.Children.Add(tb_title)

        if title_en:
            tb_title_en = TextBlock()
            tb_title_en.Text = title_en
            tb_title_en.FontStyle = FontStyles.Italic
            tb_title_en.FontSize = 10.5
            tb_title_en.Foreground = SolidColorBrush(Color.FromRgb(100, 116, 139))
            tb_title_en.Margin = Thickness(0, 1, 0, 4)
            sp.Children.Add(tb_title_en)
        else:
            tb_title.Margin = Thickness(0, 0, 0, 3)

        # 2. Vietnamese Content (TIẾNG VIỆT TRÊN)
        tb_desc_vi = TextBlock()
        tb_desc_vi.Text = desc_vi
        tb_desc_vi.FontSize = 11.5
        tb_desc_vi.Foreground = SolidColorBrush(Color.FromRgb(51, 65, 85))
        tb_desc_vi.TextWrapping = System.Windows.TextWrapping.Wrap
        tb_desc_vi.Margin = Thickness(0, 0, 0, 3)
        sp.Children.Add(tb_desc_vi)

        # 3. English Content (TIẾNG ANH DƯỚI, IN NGHIÊNG)
        if desc_en:
            tb_desc_en = TextBlock()
            tb_desc_en.Text = desc_en
            tb_desc_en.FontStyle = FontStyles.Italic
            tb_desc_en.FontSize = 11.0
            tb_desc_en.Foreground = SolidColorBrush(Color.FromRgb(100, 116, 139))
            tb_desc_en.TextWrapping = System.Windows.TextWrapping.Wrap
            sp.Children.Add(tb_desc_en)

        b.Child = sp
        return b

    def CreateBilingualSpecItem(self, spec):
        if len(spec) >= 3:
            param_vi, param_en, val = spec[0], spec[1], spec[2]
        else:
            param_vi, param_en, val = spec[0], "", spec[1]

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

        sp = StackPanel()
        sp.Orientation = System.Windows.Controls.Orientation.Vertical
        sp.VerticalAlignment = System.Windows.VerticalAlignment.Center

        # Tiếng Việt trên
        tb_p = TextBlock()
        tb_p.Text = param_vi
        tb_p.FontWeight = FontWeights.SemiBold
        tb_p.FontSize = 11.5
        tb_p.Foreground = SolidColorBrush(Color.FromRgb(113, 63, 18))
        sp.Children.Add(tb_p)

        # Tiếng Anh dưới, in nghiêng
        if param_en:
            tb_p_en = TextBlock()
            tb_p_en.Text = param_en
            tb_p_en.FontStyle = FontStyles.Italic
            tb_p_en.FontSize = 10.5
            tb_p_en.Foreground = SolidColorBrush(Color.FromRgb(146, 64, 14))
            sp.Children.Add(tb_p_en)

        g.Children.Add(sp)

        tb_v = TextBlock()
        tb_v.Text = val
        tb_v.FontWeight = FontWeights.Bold
        tb_v.FontSize = 11.5
        tb_v.Foreground = SolidColorBrush(Color.FromRgb(180, 83, 9))
        tb_v.VerticalAlignment = System.Windows.VerticalAlignment.Center
        Grid.SetColumn(tb_v, 1)
        g.Children.Add(tb_v)

        b.Child = g
        return b

    def OnCopyNotes(self, sender, args):
        mode = self.GetCurrentMode()
        lines = []
        lines.append(u"=== {} - {} ===".format(self.tool_data["title"], mode["display"]))
        lines.append(u"\n[NFPA 13 STANDARDS - {}]".format(mode["nfpa_edition"]))
        for r in mode["nfpa_rules"]:
            if len(r) >= 4:
                lines.append(u"• {}: {}".format(r[0], r[2]))
                lines.append(u"  ({}: {})".format(r[1], r[3]))
            else:
                lines.append(u"• {}: {}".format(r[0], r[1]))

        lines.append(u"\n[TCVN 7336:2021 QUY CHUẨN - {}]".format(mode["tcvn_edition"]))
        for r in mode["tcvn_rules"]:
            if len(r) >= 4:
                lines.append(u"• {}: {}".format(r[0], r[2]))
                lines.append(u"  ({}: {})".format(r[1], r[3]))
            else:
                lines.append(u"• {}: {}".format(r[0], r[1]))

        lines.append(u"\n[ENGINEERING SPECIFICATIONS]")
        for s in mode["specs"]:
            if len(s) >= 3:
                lines.append(u"• {} ({}): {}".format(s[0], s[1], s[2]))
            else:
                lines.append(u"• {}: {}".format(s[0], s[1]))

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
    current_mode_key: 'FLEX', 'RIGID', 'DIRECT'
    """
    try:
        win = StandardsReferenceWindow(tool_key=tool_key, initial_mode_key=current_mode_key)
        if parent_window:
            win.Owner = parent_window
        win.ShowDialog()
    except Exception as ex:
        from py.ui import show_error
        show_error(u"Error opening Standards Reference Dialog:\n{}".format(safe_unicode(ex)), "Standards Guide")
