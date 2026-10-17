# MEPANANA SECURITY SYSTEM ARCHIVE
> Lưu trữ hệ thống bảo mật & tính năng Unlock của MEPANANA Extension (Lưu trữ ngày: 17/10/2026).
> Theo chỉ đạo trực tiếp của tác giả: Toàn bộ tool được mở khóa tự do (unlocked by default). Tính năng bảo mật này được lưu trữ cho tới khi có yêu cầu tái kích hoạt.

## 📁 Nội dung lưu trữ
1. `0_Security.panel/`: Thư mục panel ribbon chứa nút **Unlock** (`Unlock.pushbutton`), bundle, icon và script điều khiển phiên làm việc.
2. `auth_original.py`: Toàn bộ logic xác thực trực tuyến qua Google Apps Script Webhook, đồng bộ Google Sheets, xác thực DLL (`MepananaAuth.dll`), cơ chế chống brute-force và quản lý trạng thái ribbon.
3. `startup_original.py`: Script khởi động tự động khóa ribbon trên sự kiện `Idling` của Revit khi khởi chạy.
4. `hooks_original/`: Bộ hook kiểm tra phiên bản quyền truy cập (`app-init.py`, `doc-opened.py`, `view-activated.py`).

---

## 🔄 Hướng dẫn khôi phục hệ thống bảo mật (Khi tác giả yêu cầu)
Khi cần kích hoạt lại cơ chế mật khẩu và khóa ribbon:
1. Chép lại thư mục `0_Security.panel` về lại `mepanana.tab/0_Security.panel`.
2. Chép đè file `auth_original.py` vào `lib/py/auth.py`.
3. Chép đè file `startup_original.py` vào `startup.py`.
4. Chép đè toàn bộ các file trong `hooks_original/` vào thư mục `hooks/`.
5. Trong `lib/py/tool_visibility_engine.py`, thêm lại `"Unlock"` vào `PROTECTED_TOOLS`.
6. Cập nhật lại quy tắc trong `GEMINI.md` về trạng thái bảo vệ nghiêm ngặt.
