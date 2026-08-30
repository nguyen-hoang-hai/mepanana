# 🍌 MEPANANA MANIFESTO & DEVELOPER PLAYBOOK
> **Master Architectural Blueprint, Security Protocols & Tool Development Standard**

---

## 🏛️ 1. TRIẾT LÝ & QUY CHUẨN KIẾN TRÚC TỐI CAO (CORE PRINCIPLES)

1. **Brand Identity:** MEPANANA là bộ công cụ tự động hóa Revit chuyên nghiệp, hiện đại, tối ưu cho kỹ sư MEP & BIM Coordinator.
2. **Language Standard:** **100% Pure English** trên toàn bộ giao diện, nhãn, nút bấm, tooltip và hộp thoại cảnh báo.
3. **UI Uniformity:** Sử dụng độc quyền hệ thống tài nguyên lib/py/theme.xaml qua hàm setup_window(self) (Modern Light Slate Theme).
4. **Performance First:** Tách biệt các tác vụ tính toán nặng / xử lý hình học phức tạp sang C# compiled DLLs (CadExtractor.dll, MepananaAuth.dll).

---

## ⛔ 2. BẢO VỆ TUYỆT ĐỐI LÕI SECURITY (IMMUTABLE SECURITY CORE)

Khi thêm mới, nâng cấp hoặc sửa đổi bất kỳ công cụ nào trong tab \mepanana\:

### 🚫 CÁC FILE BẤT KHẢ XÂM PHẠM (DO NOT MODIFY):
* \lib/py/auth.py\
* \lib/py/MepananaAuth.dll\
* \startup.py\
* \hooks/app-init.py\
* \hooks/doc-opened.py\
* \hooks/view-activated.py\

### 💡 LÝ DO KỸ THUẬT:
* Hệ thống bảo mật trong \uth.py\ hoạt động theo cơ chế **quét cây động (Dynamic Traversal)** qua \Autodesk.Windows.ComponentManager.Ribbon\.
* Tự động nhận diện và khóa (\panel.IsEnabled = False\) mọi panel và pushbutton mới được thêm vào tab \mepanana\ khi chưa Unlock.
* Mọi hành vi can thiệp vào lõi Security sẽ gây lỗi nạp Ribbon, mất đồng bộ icon và gãy chu kỳ khởi động của Revit.

---

## 📋 3. QUY TRÌNH 4 BƯỚC XÂY DỰNG TOOL MỚI (STEP-BY-STEP WORKFLOW)

`
mepanana.tab\<Category>.panel\<Tool Name>.pushbutton\
├── bundle.yaml    (Metadata & Tooltip)
├── icon.png       (256x256 Transparent Gradient Typography)
├── script.py      (Controller & Gatekeeper)
└── ui.xaml        (WPF Card-based Interface)
`

### 🔹 Bước 1: Khởi tạo \undle.yaml\
`yaml
title: <Tool Title>
tooltip: <Concise, professional English description of what the tool accomplishes.>
`

### 🔹 Bước 2: Chốt chặn an toàn \script.py\ (Security Gatekeeper)
Dán đoạn mã chuẩn này ở ngay các dòng đầu tiên của \script.py\:
`python
# -*- coding: utf-8 -*-
import os
import sys

# 1. Nạp thư viện cốt lõi
lib_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from py.auth import require_auth, update_ribbon_state, is_authenticated

# 2. Chốt chặn bảo mật (Chống chạy lén khi chưa Login)
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()

from pyrevit import revit, DB, UI, forms
from py.ui import setup_window, show_info, show_warning, show_error
`

### 🔹 Bước 3: Chuẩn hóa Icon \icon.png\
* **Kích thước:** \256 x 256\ pixel, nền trong suốt 100% (32-bit ARGB PNG).
* **Nội dung:** 2 - 3 chữ cái viết tắt in hoa (Ví dụ: \SL\, \SM\, \C2R\).
* **Kích thước chữ:** Chiều cao chuẩn **\160px\**, căn giữa tuyệt đối trong canvas.
* **Dải màu Gradient đa sắc 7 tầng:**
  * Stop 0.00: \#15C27D\ (Emerald Green)
  * Stop 0.18: \#20CB66\ (Bright Green)
  * Stop 0.35: \#55C046\ (Lime Green)
  * Stop 0.50: \#B4BC1E\ (Yellow-Lime)
  * Stop 0.65: \#EBBF13\ (Gold)
  * Stop 0.80: \#F48712\ (Amber Orange)
  * Stop 1.00: \#F04A3C\ (Fiery Red)

### 🔹 Bước 4: Thiết kế giao diện \ui.xaml\ & Đóng form
* Sử dụng bộ DynamicResources trong \	heme.xaml\:
  * Nền: \Background="{DynamicResource WindowBgBrush}"\
  * Card: \Style="{DynamicResource CardStyle}"\
  * Tiêu đề mục: \Style="{DynamicResource SectionTitle}"\
  * Nhãn trường: \Style="{DynamicResource FieldLabel}"\
  * Nút chính: \Style="{DynamicResource PrimaryButton}"\
  * Nút phụ: \Style="{DynamicResource GhostButton}"\
* **Quy tắc chọn đối tượng Revit:** Luôn bọc \PickObject\ hoặc \PickElementsByRectangle\ trong \with forms.HideWindow(self):\ để tránh deadlock giao diện Modal.

---

## 📊 4. DANH MỤC THƯ VIỆN CHUẨN HÓA (\lib/py/\)

| Module | Chức năng chính |
| :--- | :--- |
| **\uth.py\** | Điều khiển trạng thái Ribbon, phân quyền và kết nối Google Sheets |
| **\	heme.xaml\** | Bảng màu, typography và bộ Style chuẩn cho toàn bộ giao diện WPF |
| **\ui.py\** | Cung cấp hàm \setup_window()\, \show_info()\, \show_warning()\, \show_error()\ |
| **\core.py\** | Quản lý Transaction an toàn (\SafeTransaction\), chuyển đổi đơn vị mm/feet |
| **\excel_io.py\** | Đọc và ghi file Excel \.xlsx\ độc lập siêu tốc độ |
| **\cad.py\ & \CadExtractor.dll\** | Trích xuất dữ liệu Block CAD từ bản vẽ DWG |
| **\shortcut_io.py\** | Quản lý lưu trữ và quét xung đột phím tắt |