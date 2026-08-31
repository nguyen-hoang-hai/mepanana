/**
 * ═════════════════════════════════════════════════════════════════════════════
 *  MEPANANA ZERO-EXPOSURE AUTH WEBHOOK (BẢO MẬT TUYỆT ĐỐI GOOGLE SHEET)
 * ═════════════════════════════════════════════════════════════════════════════
 *  HƯỚNG DẪN TRIỂN KHAI TRONG 1 PHÚT:
 *  1. Truy cập https://script.google.com -> Bấm "New project" (Dự án mới).
 *  2. Dán toàn bộ nội dung code này vào tệp Code.gs.
 *  3. Đặt AUTH_SPREADSHEET_ID trỏ tới Google Sheet riêng tư của bạn (chế độ Private / Restricted).
 *  4. Bấm nút "Deploy" (Triển khai) ở góc trên bên phải -> Chọn "New deployment".
 *  5. Chọn loại: "Web app" (Ứng dụng web).
 *     - Description: Mepanana Auth Webhook
 *     - Execute as: "Me" (Tôi)
 *     - Who has access: "Anyone" (Bất kỳ ai)
 *  6. Bấm "Deploy" -> Cấp quyền truy cập Google Drive/Spreadsheet khi được hỏi.
 *  7. Copy đường link "Web app URL" (có đuôi /exec) và dán vào AUTH_WEBHOOK_URL trong auth.py!
 * ═════════════════════════════════════════════════════════════════════════════
 */

var AUTH_SPREADSHEET_ID = "1xP1AwtlAMnY7kUJ-xpecB6TMS_g91UShTgFDaFO_bkg";
var AUTH_SECRET_TOKEN   = "mepanana_auth_sec_2026";

function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({
    status: "online",
    service: "Mepanana Auth Webhook",
    message: "Service is active and ready for authentication requests."
  })).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return ContentService.createTextOutput(JSON.stringify({
        status: "error",
        message: "No payload received."
      })).setMimeType(ContentService.MimeType.JSON);
    }
    
    var data = JSON.parse(e.postData.contents);
    if (data.token !== AUTH_SECRET_TOKEN) {
      return ContentService.createTextOutput(JSON.stringify({
        status: "error",
        message: "Unauthorized token."
      })).setMimeType(ContentService.MimeType.JSON);
    }
    
    var inputPwd = (data.password || "").trim();
    if (!inputPwd) {
      return ContentService.createTextOutput(JSON.stringify({
        status: "failed",
        message: "Password cannot be empty."
      })).setMimeType(ContentService.MimeType.JSON);
    }
    
    // Read Private Spreadsheet directly using server-side credentials
    var ss = SpreadsheetApp.openById(AUTH_SPREADSHEET_ID);
    var sheet = ss.getSheets()[0];
    var rows = sheet.getDataRange().getValues();
    
    for (var i = 1; i < rows.length; i++) {
      var name = String(rows[i][0] || "").trim();
      var key  = String(rows[i][1] || "").trim();
      
      if (key && (key === inputPwd || key.toLowerCase() === inputPwd.toLowerCase())) {
        return ContentService.createTextOutput(JSON.stringify({
          status: "success",
          user: name,
          message: "Authenticated successfully"
        })).setMimeType(ContentService.MimeType.JSON);
      }
    }
    
    return ContentService.createTextOutput(JSON.stringify({
      status: "failed",
      message: "Invalid credentials"
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch(err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}
