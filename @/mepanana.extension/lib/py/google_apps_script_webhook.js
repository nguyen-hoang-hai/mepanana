/**
 * ═════════════════════════════════════════════════════════════════════════════
 *  MEPANANA FAMILY CLOUD - SERVERLESS GOOGLE DRIVE WEBHOOK ENGINE
 * ═════════════════════════════════════════════════════════════════════════════
 *  HƯỚNG DẪN TRIỂN KHAI TRONG 1 PHÚT:
 *  1. Truy cập https://script.google.com -> Bấm "New project" (Dự án mới).
 *  2. Dán toàn bộ nội dung code này vào tệp Code.gs.
 *  3. Bấm nút "Deploy" (Triển khai) ở góc trên bên phải -> Chọn "New deployment".
 *  4. Chọn loại: "Web app" (Ứng dụng web).
 *     - Description: Mepanana Family Cloud Webhook
 *     - Execute as: "Me" (Tôi)
 *     - Who has access: "Anyone" (Bất kỳ ai)
 *  5. Bấm "Deploy" -> Cấp quyền truy cập Google Drive khi được hỏi.
 *  6. Copy đường link "Web app URL" (có đuôi /exec) và dán vào tool Revit!
 * ═════════════════════════════════════════════════════════════════════════════
 */

var ROOT_FOLDER_NAME = "mepanana_family_cloud";

function doGet(e) {
  try {
    var isRefresh = e && e.parameter && (e.parameter.refresh === "true" || e.parameter.action === "rebuild");
    var isClear = e && e.parameter && e.parameter.action === "clear";
    var cache = CacheService.getScriptCache();
    var rootFolder = getOrCreateFolder(ROOT_FOLDER_NAME);
    // Declare catalogFile ONCE here so all branches below can use it
    var catalogFile = getOrCreateCatalogFile(rootFolder);

    // Clear action
    if (isClear) {
      var emptyCatalog = { version: "1.0", updated_at: Utilities.formatDate(new Date(), "GMT+7", "yyyy-MM-dd HH:mm:ss"), families: [] };
      catalogFile.setContent(JSON.stringify(emptyCatalog, null, 2));
      cache.remove("catalog_json");
      return ContentService.createTextOutput(JSON.stringify(emptyCatalog)).setMimeType(ContentService.MimeType.JSON);
    }
    
    // 1. Instant Cache Fetch (0.01s - 0.05s)
    if (!isRefresh) {
      var cachedCatalog = cache.get("catalog_json");
      if (cachedCatalog) {
        return ContentService.createTextOutput(cachedCatalog)
          .setMimeType(ContentService.MimeType.JSON);
      }
      try {
        var catalogStr = catalogFile.getBlob().getDataAsString();
        if (catalogStr && catalogStr.length > 5) {
          safeCachePut("catalog_json", catalogStr, 21600);
          return ContentService.createTextOutput(catalogStr).setMimeType(ContentService.MimeType.JSON);
        }
      } catch(readErr) {}
    }

    // 2. Only rebuild from Drive folders if explicitly requested (?refresh=true)
    var freshCatalog = rebuildCatalogFromDrive(rootFolder);
    return ContentService.createTextOutput(JSON.stringify(freshCatalog, null, 2))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString(),
      families: []
    })).setMimeType(ContentService.MimeType.JSON);
  }
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
    var rootFolder = getOrCreateFolder(ROOT_FOLDER_NAME);
    
    // ── Handle Action: DELETE ───────────────────────────────────────────────
    if (data.action === "delete") {
      var famName = data.name || "";
      var catName = data.category || "";
      var famBaseName = famName.replace(/\.rfa$/i, "");
      var rfaFileName = famBaseName + ".rfa";
      var thumbFileName = famBaseName + ".png";
      
      // 1. Move to Trash in Subfolder
      if (catName) {
        var subFolders = rootFolder.getFoldersByName(catName);
        while (subFolders.hasNext()) {
          var targetSub = subFolders.next();
          var rfaFiles = targetSub.getFilesByName(rfaFileName);
          while (rfaFiles.hasNext()) {
            rfaFiles.next().setTrashed(true);
          }
          var thumbFiles = targetSub.getFilesByName(thumbFileName);
          while (thumbFiles.hasNext()) {
            thumbFiles.next().setTrashed(true);
          }
        }
      }
      
      // 2. Explicitly remove from catalog.json and RAM Cache
      var catalogFile = getOrCreateCatalogFile(rootFolder);
      var catalog = { version: "1.0", updated_at: Utilities.formatDate(new Date(), "GMT+7", "yyyy-MM-dd HH:mm:ss"), families: [] };
      try {
        var curData = JSON.parse(catalogFile.getBlob().getDataAsString());
        if (curData && curData.families) catalog.families = curData.families;
      } catch(e) {}

      catalog.families = catalog.families.filter(function(f) {
        return f.name !== famBaseName && f.name !== famName && f.id !== (catName + "_" + famBaseName);
      });
      catalog.updated_at = Utilities.formatDate(new Date(), "GMT+7", "yyyy-MM-dd HH:mm:ss");
      var updatedCatalogStr = JSON.stringify(catalog, null, 2);
      catalogFile.setContent(updatedCatalogStr);
      safeCachePut("catalog_json", updatedCatalogStr, 21600);
      
      return ContentService.createTextOutput(JSON.stringify({
        status: "success",
        message: "Family '" + famBaseName + "' deleted from Cloud Webhook.",
        catalog: catalog
      })).setMimeType(ContentService.MimeType.JSON);
    }

    // ── Handle Action: UPDATE_VERSION ───────────────────────────────────────
    if (data.action === "update_version") {
      var famName = data.name || "";
      var catName = data.category || "";
      var newVer = data.revit_version || "Unknown";
      var famBaseName = famName.replace(/\.rfa$/i, "");
      
      var catalogFile = getOrCreateCatalogFile(rootFolder);
      var catalog = { version: "1.0", updated_at: Utilities.formatDate(new Date(), "GMT+7", "yyyy-MM-dd HH:mm:ss"), families: [] };
      try {
        var curData = JSON.parse(catalogFile.getBlob().getDataAsString());
        if (curData && curData.families) catalog.families = curData.families;
      } catch(e) {}

      for (var i = 0; i < catalog.families.length; i++) {
        var f = catalog.families[i];
        if (f.name === famBaseName || f.name === famName || f.id === (catName + "_" + famBaseName)) {
          f.revit_version = newVer;
        }
      }
      catalog.updated_at = Utilities.formatDate(new Date(), "GMT+7", "yyyy-MM-dd HH:mm:ss");
      var updatedCatalogStr = JSON.stringify(catalog, null, 2);
      catalogFile.setContent(updatedCatalogStr);
      safeCachePut("catalog_json", updatedCatalogStr, 21600);
      
      return ContentService.createTextOutput(JSON.stringify({
        status: "success",
        message: "Version updated to " + newVer,
        catalog: catalog
      })).setMimeType(ContentService.MimeType.JSON);
    }

    // ── Handle Action: UPLOAD ───────────────────────────────────────────────
    var categoryName = data.category || "Generic Models";
    var catFolder = getOrCreateSubFolder(rootFolder, categoryName);
    
    var fileName = data.name || "Unnamed_Family.rfa";
    if (!fileName.toLowerCase().endsWith(".rfa")) {
      fileName += ".rfa";
    }
    var famBaseName = fileName.replace(/\.rfa$/i, "");
    
    // 1. Save RFA File
    var rfaBytes = Utilities.base64Decode(data.rfa_base64);
    var rfaBlob = Utilities.newBlob(rfaBytes, "application/octet-stream", fileName);
    
    var existingFiles = catFolder.getFilesByName(fileName);
    while (existingFiles.hasNext()) {
      existingFiles.next().setTrashed(true);
    }
    var savedRfa = catFolder.createFile(rfaBlob);
    savedRfa.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    
    var downloadUrl = "https://drive.google.com/uc?export=download&id=" + savedRfa.getId();
    
    // 2. Save Thumbnail if provided
    var thumbUrl = "";
    if (data.thumb_base64) {
      var thumbName = famBaseName + ".png";
      var thumbBytes = Utilities.base64Decode(data.thumb_base64);
      var thumbBlob = Utilities.newBlob(thumbBytes, "image/png", thumbName);
      
      var exThumbs = catFolder.getFilesByName(thumbName);
      while (exThumbs.hasNext()) {
        exThumbs.next().setTrashed(true);
      }
      var savedThumb = catFolder.createFile(thumbBlob);
      savedThumb.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
      thumbUrl = "https://drive.google.com/uc?export=view&id=" + savedThumb.getId();
    }
    
    // 3. Save / Update Entry in Catalog with Full Client Metadata
    var catalogFile = getOrCreateCatalogFile(rootFolder);
    var catalog = { version: "1.0", updated_at: Utilities.formatDate(new Date(), "GMT+7", "yyyy-MM-dd HH:mm:ss"), families: [] };
    try {
      var curCat = JSON.parse(catalogFile.getBlob().getDataAsString());
      if (curCat && curCat.families) catalog.families = curCat.families;
    } catch(e) {}

    var relPath = categoryName + "/" + fileName;
    catalog.families = catalog.families.filter(function(f) {
      return f.rfa_path !== relPath && f.id !== (categoryName + "_" + famBaseName);
    });

    var newFamily = {
      id: categoryName + "_" + famBaseName,
      name: famBaseName,
      category: categoryName,
      revit_version: (data.revit_version && data.revit_version !== "") ? data.revit_version : "Unknown",
      file_size: data.file_size || "1.0 MB",
      file_size_bytes: data.file_size_bytes || 1024,
      rfa_path: relPath,
      download_url: downloadUrl,
      thumb_url: thumbUrl,
      uploaded_at: Utilities.formatDate(new Date(), "GMT+7", "yyyy-MM-dd HH:mm"),
      description: data.description || ""
    };

    catalog.families.push(newFamily);
    catalog.updated_at = Utilities.formatDate(new Date(), "GMT+7", "yyyy-MM-dd HH:mm:ss");
    var updatedCatalogStr = JSON.stringify(catalog, null, 2);
    catalogFile.setContent(updatedCatalogStr);
    safeCachePut("catalog_json", updatedCatalogStr, 21600);
    
    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      message: "Family '" + famBaseName + "' uploaded successfully to Cloud Webhook!"
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

function rebuildCatalogFromDrive(rootFolder) {
  var catalogFile = getOrCreateCatalogFile(rootFolder);
  var oldCatalogMap = {};
  try {
    var oldCat = JSON.parse(catalogFile.getBlob().getDataAsString());
    if (oldCat && oldCat.families) {
      for (var i = 0; i < oldCat.families.length; i++) {
        var oldF = oldCat.families[i];
        if (oldF && oldF.rfa_path) {
          oldCatalogMap[oldF.rfa_path] = oldF;
        }
      }
    }
  } catch(e) {}

  var catalog = {
    version: "1.0",
    updated_at: Utilities.formatDate(new Date(), "GMT+7", "yyyy-MM-dd HH:mm:ss"),
    families: []
  };
  
  var subFolders = rootFolder.getFolders();
  while (subFolders.hasNext()) {
    var catFolder = subFolders.next();
    if (catFolder.isTrashed()) continue;
    var catName = catFolder.getName();
    
    var files = catFolder.getFiles();
    while (files.hasNext()) {
      var file = files.next();
      if (file.isTrashed()) continue;
      var fileName = file.getName();
      
      if (fileName.toLowerCase().endsWith(".rfa")) {
        var famBaseName = fileName.replace(/\.rfa$/i, "");
        var relPath = catName + "/" + fileName;
        var existingEntry = oldCatalogMap[relPath] || {};
        var downloadUrl = "https://drive.google.com/uc?export=download&id=" + file.getId();
        
        var thumbUrl = existingEntry.thumb_url || "";
        var thumbBase64 = existingEntry.thumb_base64 || "";

        if (!thumbBase64) {
          var thumbFiles = catFolder.getFilesByName(famBaseName + ".png");
          while (thumbFiles.hasNext()) {
            var tFile = thumbFiles.next();
            if (!tFile.isTrashed()) {
              thumbUrl = "https://drive.google.com/uc?export=view&id=" + tFile.getId();
              try {
                thumbBase64 = Utilities.base64Encode(tFile.getBlob().getBytes());
              } catch(e) {}
              break;
            }
          }
        }

        // Always extract version from actual binary blob for accuracy.
        // Fall back to stored value only if extraction fails.
        var detectedVer = "Unknown";
        try {
          detectedVer = extractVersionFromRfaBlob(file.getBlob());
        } catch(blobErr) {}
        if (!detectedVer || detectedVer === "Unknown") {
          detectedVer = existingEntry.revit_version || "Unknown";
        }
        
        catalog.families.push({
          id: catName + "_" + famBaseName,
          name: famBaseName,
          category: catName,
          revit_version: detectedVer,
          file_size: (file.getSize() / (1024 * 1024)).toFixed(1) + " MB",
          file_size_bytes: file.getSize(),
          rfa_path: relPath,
          download_url: downloadUrl,
          thumb_url: thumbUrl,
          uploaded_at: existingEntry.uploaded_at || Utilities.formatDate(file.getLastUpdated(), "GMT+7", "yyyy-MM-dd HH:mm"),
          description: existingEntry.description || ""
        });
      }
    }
  }
  
  var catalogStr = JSON.stringify(catalog, null, 2);
  catalogFile.setContent(catalogStr);
  safeCachePut("catalog_json", catalogStr, 21600);
  return catalog;
}

function extractVersionFromRfaBlob(blob) {
  try {
    var bytes = blob.getBytes();
    var maxLen = Math.min(bytes.length - 20, 300000);

    // 1. Check 32-bit and 16-bit Pascal length-prefixed strings: \x04\x00\x00\x00 or \x04\x00 + '20xx' in UTF-16LE
    for (var i = 0; i < maxLen - 12; i++) {
      // 32-bit integer length prefix: 04 00 00 00
      if (bytes[i] === 4 && bytes[i+1] === 0 && bytes[i+2] === 0 && bytes[i+3] === 0) {
        if (bytes[i+4] === 50 && bytes[i+5] === 0 && bytes[i+6] === 48 && bytes[i+7] === 0) {
          var d3_32 = String.fromCharCode(bytes[i+8] & 0xFF);
          var d4_32 = String.fromCharCode(bytes[i+10] & 0xFF);
          var yr_32 = "20" + d3_32 + d4_32;
          if (/^20[12]\d$/.test(yr_32)) return yr_32;
        }
      }
      // 16-bit integer length prefix: 04 00
      if (bytes[i] === 4 && bytes[i+1] === 0) {
        if (bytes[i+2] === 50 && bytes[i+3] === 0 && bytes[i+4] === 48 && bytes[i+5] === 0) {
          var d3_16 = String.fromCharCode(bytes[i+6] & 0xFF);
          var d4_16 = String.fromCharCode(bytes[i+8] & 0xFF);
          var yr_16 = "20" + d3_16 + d4_16;
          if (/^20[12]\d$/.test(yr_16)) return yr_16;
        }
      }
    }

    // 2. Check 'Format:' or 'Revit' in UTF-16LE
    for (var i = 0; i < maxLen - 20; i += 2) {
      // Look for "Format" in UTF-16LE: F=70, o=111, r=114, m=109, a=97, t=116
      if (bytes[i] === 70 && bytes[i+2] === 111 && bytes[i+4] === 114 && bytes[i+6] === 109 && bytes[i+8] === 97 && bytes[i+10] === 116) {
        for (var j = i + 12; j < Math.min(i + 60, maxLen); j += 2) {
          if (bytes[j] === 50 && bytes[j+2] === 48) {
            var d3 = String.fromCharCode(bytes[j+4] & 0xFF);
            var d4 = String.fromCharCode(bytes[j+6] & 0xFF);
            var yr = "20" + d3 + d4;
            if (/^20[12]\d$/.test(yr)) return yr;
          }
        }
      }
      // Look for "Revit" in UTF-16LE: R=82, e=101, v=118, i=105, t=116
      if (bytes[i] === 82 && bytes[i+2] === 101 && bytes[i+4] === 118 && bytes[i+6] === 105 && bytes[i+8] === 116) {
        for (var k = i + 10; k < Math.min(i + 60, maxLen); k += 2) {
          if (bytes[k] === 50 && bytes[k+2] === 48) {
            var e3 = String.fromCharCode(bytes[k+4] & 0xFF);
            var e4 = String.fromCharCode(bytes[k+6] & 0xFF);
            var yr2 = "20" + e3 + e4;
            if (/^20[12]\d$/.test(yr2)) return yr2;
          }
        }
      }
    }

    // 3. Check build timestamp (e.g. 20190808) in UTF-16LE
    for (var i = 0; i < maxLen - 20; i += 2) {
      if (bytes[i] === 50 && bytes[i+2] === 48) {
        var d3 = String.fromCharCode(bytes[i+4] & 0xFF);
        var d4 = String.fromCharCode(bytes[i+6] & 0xFF);
        var yr = "20" + d3 + d4;
        if (/^20[12]\d$/.test(yr)) {
          var m1 = String.fromCharCode(bytes[i+8] & 0xFF);
          var m2 = String.fromCharCode(bytes[i+10] & 0xFF);
          if ((m1 === '0' || m1 === '1') && /^\d$/.test(m2)) {
            return yr;
          }
        }
      }
    }
  } catch(e) {}
  return "Unknown";
}

function getOrCreateFolder(folderName) {
  var folders = DriveApp.getFoldersByName(folderName);
  if (folders.hasNext()) return folders.next();
  var f = DriveApp.createFolder(folderName);
  f.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return f;
}

function getOrCreateSubFolder(parentFolder, subName) {
  var subs = parentFolder.getFoldersByName(subName);
  if (subs.hasNext()) return subs.next();
  var sub = parentFolder.createFolder(subName);
  sub.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return sub;
}

function getOrCreateCatalogFile(rootFolder) {
  var files = rootFolder.getFilesByName("catalog.json");
  if (files.hasNext()) return files.next();
  var emptyCat = { version: "1.0", updated_at: "", families: [] };
  var f = rootFolder.createFile("catalog.json", JSON.stringify(emptyCat, null, 2), "application/json");
  f.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return f;
}

function safeCachePut(key, str, seconds) {
  try {
    if (str && str.length < 95000) {
      CacheService.getScriptCache().put(key, str, seconds || 21600);
    }
  } catch (e) {}
}