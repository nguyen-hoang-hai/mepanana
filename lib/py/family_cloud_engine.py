# -*- coding: utf-8 -*-
"""
family_cloud_engine.py — Core Engine for Family Cloud (FC)
Part of mepanana.extension.
- Manages OneDrive synced cloud library folder & catalog.json
- High-Performance OLE compound & binary stream embedded thumbnail extraction
- Multi-Layer Intelligent Revit Category detection for RFA files
- RFA version detection (via BasicFileInfo & binary headers)
- Loads families safely into active Revit projects via %TEMP% cache
"""
import os
import sys
import json
import shutil
import datetime
import re
import struct
import tempfile
import base64

try:
    unicode
except NameError:
    unicode = str

try:
    basestring
except NameError:
    basestring = str

try:
    import clr
    clr.AddReference("System")
    clr.AddReference("System.Drawing")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    import System
    from System.IO import MemoryStream, File
    from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
    from pyrevit import revit, DB, UI
    HAS_REVIT_API = True
except Exception:
    HAS_REVIT_API = False


# ── Standard MEP & Architectural Categories ──────────────────────────────────

STANDARD_CATEGORIES = [
    "Air Terminals",
    "Cable Trays",
    "Cable Tray Fittings",
    "Communication Devices",
    "Conduits",
    "Conduit Fittings",
    "Data Devices",
    "Doors",
    "Duct Accessories",
    "Duct Fittings",
    "Ducts",
    "Electrical Equipment",
    "Electrical Fixtures",
    "Fire Alarm Devices",
    "Furniture",
    "Generic Models",
    "Lighting Devices",
    "Lighting Fixtures",
    "Mechanical Equipment",
    "Nurse Call Devices",
    "Pipe Accessories",
    "Pipe Fittings",
    "Pipes",
    "Plumbing Fixtures",
    "Security Devices",
    "Signage",
    "Specialty Equipment",
    "Sprinklers",
    "Structural Columns",
    "Structural Framing",
    "Telephone Devices",
    "Walls",
    "Windows"
]

SORTED_CATEGORIES = sorted(STANDARD_CATEGORIES, key=len, reverse=True)


# ── Unicode-Safe File I/O Helpers for IronPython ─────────────────────────────

def read_file_bytes(file_path, max_bytes=None):
    """Safely reads binary bytes from a file path supporting full Unicode / Vietnamese characters."""
    if not file_path:
        return None
    try:
        if not isinstance(file_path, unicode):
            try: u_path = file_path.decode("utf-8")
            except Exception: u_path = unicode(file_path)
        else:
            u_path = file_path

        # Try .NET File API first (100% Unicode path safe in IronPython)
        try:
            from System.IO import File as DotNetFile
            all_bytes = DotNetFile.ReadAllBytes(u_path)
            if max_bytes is not None and len(all_bytes) > max_bytes:
                from System import Array, Byte
                truncated = Array.CreateInstance(Byte, max_bytes)
                Array.Copy(all_bytes, truncated, max_bytes)
                return bytes(bytearray(truncated))
            return bytes(bytearray(all_bytes))
        except Exception:
            pass

        # Fallback to standard Python open
        with open(u_path, "rb") as f:
            if max_bytes is not None:
                return f.read(max_bytes)
            return f.read()
    except Exception:
        return None


def write_file_bytes(file_path, data_bytes):
    """Safely writes binary bytes to a file path supporting full Unicode / Vietnamese characters."""
    if not file_path or data_bytes is None:
        return False
    try:
        if not isinstance(file_path, unicode):
            try: u_path = file_path.decode("utf-8")
            except Exception: u_path = unicode(file_path)
        else:
            u_path = file_path

        dest_dir = os.path.dirname(u_path)
        if dest_dir and not os.path.exists(dest_dir):
            try: os.makedirs(dest_dir)
            except Exception: pass

        try:
            from System.IO import File as DotNetFile
            from System import Array, Byte
            if isinstance(data_bytes, Array[Byte]):
                arr = data_bytes
            else:
                arr = Array[Byte](bytearray(data_bytes))
            DotNetFile.WriteAllBytes(u_path, arr)
            return True
        except Exception:
            pass

        with open(u_path, "wb") as f:
            f.write(data_bytes)
        return True
    except Exception:
        return False


# ── RFA Binary & OLE Thumbnail Extraction ────────────────────────────────────

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"
_PREVIEW_STREAMS = (
    "RevitPreview7.0",
    "RevitPreview6.0",
    "RevitPreview5.0",
    "RevitPreview4.0",
    "RevitPreview3.0",
    "RevitPreview2.0",
    "RevitPreview",
    "Preview",
    "Thumbnail",
    "Icon"
)

_storage_root_type = None
_storage_open_flags = None
_storage_opened = False


def _to_bytes(val):
    if val is None:
        return b""
    if isinstance(val, bytes):
        return val
    if isinstance(val, (bytearray, list, tuple)):
        return bytes(bytearray(val))
    if isinstance(val, str):
        try:
            return val.encode("latin1")
        except Exception:
            return val.encode("utf-8", "ignore")
    return bytes(val)


def _slice_png(data, start):
    pos = start + 8
    data_len = len(data)
    while pos + 12 <= data_len:
        try:
            length = struct.unpack(">I", data[pos:pos + 4])[0]
            chunk_type = data[pos + 4:pos + 8]
            pos += 12 + length
            if pos > data_len:
                return None
            if chunk_type == b"IEND" or chunk_type == "IEND":
                return data[start:pos]
        except Exception:
            break
    return None


def _extract_png_from_bytes(data):
    if not data:
        return None
    data = _to_bytes(data)
    idx = data.find(_PNG_SIG)
    if idx >= 0:
        png = _slice_png(data, idx)
        if png:
            return png
    return None


def _slice_jpeg(data, start):
    if start + 4 > len(data):
        return None
    # Real JPEG must have a valid marker byte right after \xff\xd8: \xff\xe0 (JFIF), \xff\xe1 (Exif), \xff\xdb, \xff\xc0, \xff\xc2
    if data[start:start + 2] != b"\xff\xd8" or data[start + 2:start + 3] != b"\xff":
        return None
    marker = data[start + 3:start + 4]
    if marker not in (b"\xe0", b"\xe1", b"\xdb", b"\xc0", b"\xc2", b"\xfe", b"\xee"):
        return None

    end = data.find(_JPEG_EOI, start + 4)
    if end < 0:
        return None
    candidate = data[start:end + 2]
    # Check minimum size for valid thumbnail (at least 512 bytes)
    if len(candidate) < 512:
        return None
    return candidate


def _extract_jpeg_from_bytes(data):
    if not data:
        return None
    data = _to_bytes(data)
    best = None
    best_len = 0
    search_from = 0
    while True:
        idx = data.find(b"\xff\xd8\xff", search_from)
        if idx < 0:
            break
        jpg = _slice_jpeg(data, idx)
        if jpg and len(jpg) > best_len:
            best = jpg
            best_len = len(jpg)
        search_from = idx + 3
    return best


def _maybe_inflate_truncated_gzip(raw):
    if not raw or len(raw) < 20:
        return None
    raw = _to_bytes(raw)
    if raw[0:2] != b"\x1f\x8b":
        return None
    try:
        import zlib
        for skip in (10, 12, 14, 16):
            if len(raw) <= skip:
                continue
            try:
                out = zlib.decompress(raw[skip:], -15)
                if out and len(out) > 32:
                    return out
            except Exception:
                continue
    except Exception:
        pass
    return None


def _extract_bmp_from_bytes(data):
    if not data or len(data) < 40:
        return None
    data = _to_bytes(data)
    if data.startswith(b"BM"):
        return data

    if data.startswith(b"\x28\x00\x00\x00"):
        try:
            import struct
            header_size, width, height, planes, bpp = struct.unpack("<IIIHH", data[0:16])
            if header_size == 40 and planes == 1:
                num_colors = 0
                if bpp <= 8:
                    num_colors = 1 << bpp
                offset = 14 + 40 + (num_colors * 4)
                file_size = 14 + len(data)
                file_header = b"BM" + struct.pack("<I", file_size) + b"\x00\x00\x00\x00" + struct.pack("<I", offset)
                return file_header + data
        except Exception:
            pass
    return None


def _extract_image_from_bytes(data):
    if not data:
        return None
    data = _to_bytes(data)
    png = _extract_png_from_bytes(data)
    if png:
        return png
    inflated = _maybe_inflate_truncated_gzip(data)
    if inflated:
        png2 = _extract_png_from_bytes(inflated)
        if png2:
            return png2
    jpg = _extract_jpeg_from_bytes(data)
    if jpg:
        return jpg
    bmp = _extract_bmp_from_bytes(data)
    if bmp:
        return bmp
    return None


def _init_storage_api():
    global _storage_root_type, _storage_open_flags, _storage_opened
    if _storage_opened:
        return _storage_root_type is not None
    _storage_opened = True
    try:
        clr.AddReference("WindowsBase")
        from System.IO.Packaging import StorageInfo
        from System.Reflection import BindingFlags

        sr_type = StorageInfo.Assembly.GetType("System.IO.Packaging.StorageRoot")
        if sr_type is None:
            return False

        _storage_root_type = sr_type
        _storage_open_flags = (
            BindingFlags.NonPublic | BindingFlags.Static |
            BindingFlags.Public | BindingFlags.InvokeMethod)
        return True
    except Exception:
        return False


def _read_stream_bytes(stream_info):
    from System import Array, Byte
    from System.IO import FileMode, FileAccess

    reader = stream_info.GetStream(FileMode.Open, FileAccess.Read)
    try:
        length = int(reader.Length)
        if length <= 0:
            return None
        buf = Array.CreateInstance(Byte, length)
        read = int(reader.Read(buf, 0, length))
        if read <= 0:
            return None
        return bytes(bytearray(buf))
    finally:
        reader.Close()


def _list_preview_stream_payloads(rfa_path):
    payloads = []
    if not _init_storage_api():
        return payloads
    try:
        from System import Array, Object, String
        from System.IO import FileMode, FileAccess, FileShare

        if not isinstance(rfa_path, unicode):
            try: u_rfa_path = rfa_path.decode("utf-8")
            except Exception: u_rfa_path = unicode(rfa_path)
        else:
            u_rfa_path = rfa_path

        args = Array[Object]([u_rfa_path, FileMode.Open, FileAccess.Read, FileShare.Read])
        st_info = _storage_root_type.InvokeMember(
            "Open", _storage_open_flags, None, None, args)
        if st_info is None:
            return payloads

        by_name = {}
        for stream_info in st_info.GetStreams():
            try:
                nm = stream_info.Name
                if not isinstance(nm, basestring):
                    nm = unicode(nm)
            except Exception:
                nm = u""
            by_name[nm] = stream_info

        seen = set()
        for wanted in _PREVIEW_STREAMS:
            si = by_name.get(wanted)
            if si is None:
                continue
            data = _read_stream_bytes(si)
            if data:
                seen.add(wanted)
                payloads.append(data)

        for name, si in by_name.items():
            try:
                if "preview" not in name.lower():
                    continue
            except Exception:
                continue
            if name in seen:
                continue
            data = _read_stream_bytes(si)
            if data and len(data) > 64:
                payloads.append(data)
    except Exception:
        pass
    return payloads


def extract_preview_png_bytes(rfa_path):
    if not rfa_path or not os.path.isfile(rfa_path):
        return None

    # 1. Try OLE stream extractor
    for blob in _list_preview_stream_payloads(rfa_path):
        img_bytes = _extract_image_from_bytes(blob)
        if img_bytes:
            return img_bytes

    # 2. Raw binary scan fallback
    try:
        file_data = read_file_bytes(rfa_path)
        if file_data:
            img_bytes = _extract_image_from_bytes(file_data)
            if img_bytes:
                return img_bytes
    except Exception:
        pass

    return None


def extract_and_save_thumbnail(rfa_path, output_png_path):
    if not os.path.exists(rfa_path):
        return False

    try:
        img_bytes = extract_preview_png_bytes(rfa_path)
        if img_bytes:
            return write_file_bytes(output_png_path, img_bytes)
    except Exception:
        pass

    return False


# ── Cloud Webhook Configuration ──────────────────────────────────────────────

DEFAULT_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbwdDk3-cIL3h7zxGAb6qKCvCirNt23nuHaaXBNaoFBmYcDnhwXygFdoxIvKri64mWn5Yg/exec"
WEBHOOK_CONFIG_FILE_NAME = "mepanana_family_cloud_webhook.txt"

def get_webhook_config_path():
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "pyRevit", WEBHOOK_CONFIG_FILE_NAME)


def get_webhook_url():
    cfg_file = get_webhook_config_path()
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r") as f:
                url = f.read().strip()
                if url.startswith("http"):
                    return url
        except Exception:
            pass
    return DEFAULT_WEBHOOK_URL


def set_webhook_url(url):
    try:
        cfg_file = get_webhook_config_path()
        cfg_dir = os.path.dirname(cfg_file)
        if not os.path.exists(cfg_dir):
            os.makedirs(cfg_dir)
        with open(cfg_file, "w") as f:
            f.write(url.strip() if url else DEFAULT_WEBHOOK_URL)

        # Purge local disk cache whenever webhook URL is updated or removed
        cache_path = get_catalog_cache_path()
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
            except Exception:
                pass

        return True, "Webhook URL updated successfully."
    except Exception as ex:
        return False, str(ex)


def is_cloud_connected():
    return bool(get_webhook_url())


# ── HTTP Webhook Client Layer ────────────────────────────────────────────────

def make_http_request(url, method="GET", json_body=None, timeout=60):
    """
    Cross-platform HTTP client for IronPython / .NET and CPython.
    """
    try:
        import clr
        clr.AddReference("System")
        import System
        from System.Net import HttpWebRequest, ServicePointManager, SecurityProtocolType, DecompressionMethods
        try:
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12 | SecurityProtocolType.Tls11 | SecurityProtocolType.Tls
            ServicePointManager.DefaultConnectionLimit = 10
            ServicePointManager.Expect100Continue = False
        except Exception:
            pass

        req = HttpWebRequest.Create(url)
        req.Method = method
        req.Proxy = None  # Crucial: bypasses Windows WPAD proxy search, saves ~800ms
        req.KeepAlive = True
        req.AllowAutoRedirect = True
        req.Timeout = int(timeout * 1000)
        req.UserAgent = "MepananaFamilyCloud/1.0"
        try:
            req.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate
        except Exception:
            pass

        if json_body and method == "POST":
            req.ContentType = "application/json; charset=utf-8"
            if isinstance(json_body, unicode):
                json_body_clean = json_body
            else:
                try: json_body_clean = json_body.decode("utf-8")
                except Exception: json_body_clean = unicode(json_body)
            payload_bytes = System.Text.Encoding.UTF8.GetBytes(json_body_clean)
            req.ContentLength = len(payload_bytes)
            stream = req.GetRequestStream()
            stream.Write(payload_bytes, 0, len(payload_bytes))
            stream.Close()

        resp = req.GetResponse()
        stream = resp.GetResponseStream()
        reader = System.IO.StreamReader(stream, System.Text.Encoding.UTF8)
        content = reader.ReadToEnd()
        reader.Close()
        stream.Close()
        resp.Close()
        return True, content
    except Exception as ex:
        try:
            try:
                import urllib.request as urllib_req
            except ImportError:
                import urllib2 as urllib_req

            headers = {"User-Agent": "MepananaFamilyCloud/1.0"}
            if json_body:
                headers["Content-Type"] = "application/json; charset=utf-8"
                if isinstance(json_body, unicode):
                    data = json_body.encode("utf-8")
                else:
                    data = json_body
                req = urllib_req.Request(url, data=data, headers=headers)
            else:
                req = urllib_req.Request(url, headers=headers)

            response = urllib_req.urlopen(req, timeout=timeout)
            content = response.read().decode("utf-8")
            return True, content
        except Exception as ex2:
            return False, str(ex2)


def generate_fallback_png_bytes(width=256, height=256):
    """Generates a valid 256x256 PNG in pure Python so Google Drive always receives a .png file."""
    import struct, zlib
    line = b"\x00" + (b"\xf8\xfa\xfc\xff" * width)
    raw_data = line * height
    compressed = zlib.compress(raw_data, 9)
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    def make_chunk(chunk_type, data):
        crc = zlib.crc32(chunk_type + data) & 0xffffffff
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)
    png = b"\x89PNG\r\n\x1a\n"
    png += make_chunk(b"IHDR", ihdr_data)
    png += make_chunk(b"IDAT", compressed)
    png += make_chunk(b"IEND", b"")
    return png


def upload_family_via_webhook(source_rfa_path, target_category=None, description="", webhook_url=None):
    if not webhook_url:
        webhook_url = get_webhook_url()
    if not webhook_url:
        return False, "Cloud Webhook URL is not configured."

    if not os.path.exists(source_rfa_path):
        return False, "File does not exist."

    # 1. Category & Version
    if not target_category or target_category == "Auto Detect":
        target_category = extract_rfa_category(source_rfa_path)

    ver_str = extract_rfa_version(source_rfa_path)
    file_size_bytes = os.path.getsize(source_rfa_path)
    file_size_str = format_file_size(file_size_bytes)
    base_name = os.path.basename(source_rfa_path)

    # 2. Encode RFA to Base64
    rfa_bytes = read_file_bytes(source_rfa_path)
    if not rfa_bytes:
        return False, u"Failed to read family file from disk."
    rfa_b64 = base64.b64encode(rfa_bytes).decode("ascii")

    # 3. Extract Thumbnail to Base64 (with guaranteed fallback so a PNG is ALWAYS created on Drive)
    img_bytes = extract_preview_png_bytes(source_rfa_path)
    if not img_bytes:
        img_bytes = generate_fallback_png_bytes()

    thumb_b64 = ""
    if img_bytes:
        thumb_b64 = base64.b64encode(img_bytes).decode("ascii")

    def _u(s):
        if s is None: return u""
        if isinstance(s, unicode): return s
        try: return s.decode("utf-8")
        except Exception:
            try: return unicode(s)
            except Exception: return s.decode("ascii", "ignore")

    # 4. Construct Payload
    payload = {
        "name": _u(base_name),
        "category": _u(target_category or "Generic Models"),
        "revit_version": _u(ver_str or "Unknown"),
        "file_size": _u(file_size_str or "0 KB"),
        "file_size_bytes": file_size_bytes,
        "description": _u(description or ""),
        "rfa_base64": rfa_b64,
        "thumb_base64": thumb_b64
    }

    payload_json = json.dumps(payload, ensure_ascii=True)
    success, res_txt = make_http_request(webhook_url, method="POST", json_body=payload_json, timeout=90)
    if not success:
        return False, u"Webhook Upload Failed:\n" + (_u(res_txt) if res_txt else u"")

    try:
        res_data = json.loads(res_txt)
        if res_data.get("status") == "success":
            # Save the locally-detected version to local DB so it's always correct
            # regardless of what the cloud catalog may return
            try:
                save_local_version(base_name, ver_str)
            except Exception:
                pass
            return True, _u(res_data.get("message", u"Uploaded successfully via Webhook!"))
        return False, _u(res_data.get("message", u"Upload rejected by Webhook."))
    except Exception:
        # Still save local version even on ambiguous response
        try:
            save_local_version(base_name, ver_str)
        except Exception:
            pass
        return True, u"Family uploaded successfully to Cloud Webhook!"


def download_file_from_url(url, dest_path):
    try:
        dest_dir = os.path.dirname(dest_path)
        if not os.path.exists(dest_dir):
            try: os.makedirs(dest_dir)
            except Exception: pass

        # 1. Try .NET WebClient (handles Google Drive TLS 1.2 & redirects seamlessly)
        try:
            import clr
            clr.AddReference("System")
            from System.Net import WebClient, ServicePointManager, SecurityProtocolType
            try: ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
            except Exception: pass
            wc = WebClient()
            wc.Headers.Add("User-Agent", "Mozilla/5.0 MepananaFamilyCloud")
            wc.DownloadFile(url, dest_path)
            if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                return True
        except Exception:
            pass

        # 2. Python urllib fallback
        try:
            import urllib.request as urllib_req
        except ImportError:
            import urllib2 as urllib_req

        req = urllib_req.Request(url, headers={"User-Agent": "Mozilla/5.0 MepananaFamilyCloud"})
        resp = urllib_req.urlopen(req, timeout=30)
        return write_file_bytes(dest_path, resp.read())
    except Exception:
        return False


# ── Multi-Layer Intelligent Category Detection ───────────────────────────────

def extract_rfa_category(rfa_path):
    """
    Multi-Layer Intelligent Revit Category Detector:
    Layer 1: Inspect full parent directory path hierarchy.
    Layer 2: Scan binary stream header (ASCII & UTF-16).
    Layer 3: Filename keyword & standard MEP abbreviation analysis.
    Layer 4: In-memory Revit API inspection.
    Fallback: 'Generic Models'.
    """
    if not rfa_path:
        return u"Generic Models"

    try:
        if not isinstance(rfa_path, unicode):
            try: u_rfa_path = rfa_path.decode("utf-8")
            except Exception: u_rfa_path = unicode(rfa_path)
        else:
            u_rfa_path = rfa_path

        # ── Layer 1: Parent Directory Hierarchy Inspection ──────────────────────
        norm_path = os.path.normpath(u_rfa_path).replace(u"/", u"\\")
        path_parts = [p.strip() for p in norm_path.split(u"\\") if p.strip()]

        for part in reversed(path_parts[:-1]):
            p_clean = part.lower().strip(u"@").strip(u"0123456789._ ")
            for cat in SORTED_CATEGORIES:
                u_cat = cat if isinstance(cat, unicode) else unicode(cat)
                cat_l = u_cat.lower()
                if cat_l == p_clean or cat_l == part.lower():
                    return u_cat
                if cat_l.endswith(u"s") and cat_l[:-1] == p_clean:
                    return u_cat

        # ── Layer 2: Binary Stream Header Scan (ASCII & UTF-16) ──────────────────
        if os.path.exists(u_rfa_path):
            try:
                header_data = read_file_bytes(u_rfa_path, max_bytes=512 * 1024)
                if header_data:
                    for cat in SORTED_CATEGORIES:
                        u_cat = cat if isinstance(cat, unicode) else unicode(cat)
                        if u_cat == u"Generic Models":
                            continue
                        if u_cat.encode('utf-8') in header_data or u_cat.encode('utf-16le') in header_data:
                            return u_cat
            except Exception:
                pass

        # ── Layer 3: Filename Keywords & MEP Domain Abbreviations ────────────────
        base_name = os.path.splitext(os.path.basename(u_rfa_path))[0].lower()
        if not isinstance(base_name, unicode):
            try: base_name = base_name.decode("utf-8")
            except Exception: base_name = unicode(base_name)

        keyword_map = [
            ([u"sprinkler", u"pendent", u"upright", u"sidewall"], u"Sprinklers"),
            ([u"speaker", u"camera", u"cctv", u"mic", u"bell", u"call", u"intercom", u"display", u"tv", u"bc"], u"Communication Devices"),
            ([u"switch", u"dimmer", u"sensor", u"pir", u"occupancy"], u"Lighting Devices"),
            ([u"light", u"lamp", u"luminaire", u"downlight", u"troffer", u"led", u"sconce", u"spot"], u"Lighting Fixtures"),
            ([u"socket", u"receptacle", u"outlet", u"plug", u"power"], u"Electrical Fixtures"),
            ([u"panel", u"mdb", u"db", u"switchboard", u"transformer", u"ups", u"generator", u"ats", u"substation"], u"Electrical Equipment"),
            ([u"chiller", u"ahu", u"fcu", u"pump", u"fan", u"boiler", u"cooling tower", u"vav", u"hvac"], u"Mechanical Equipment"),
            ([u"smoke detector", u"heat detector", u"fire alarm", u"horn", u"strobe", u"manual call"], u"Fire Alarm Devices"),
            ([u"diffuser", u"grille", u"register", u"louver", u"air terminal"], u"Air Terminals"),
            ([u"damper", u"attenuator", u"sound attenuator", u"silencer"], u"Duct Accessories"),
            ([u"duct elbow", u"duct tee", u"duct transition", u"duct bend", u"duct reducer"], u"Duct Fittings"),
            ([u"valve", u"strainer", u"water meter", u"check valve", u"gate valve", u"butterfly"], u"Pipe Accessories"),
            ([u"pipe elbow", u"pipe tee", u"pipe reducer", u"flange", u"coupling", u"takeoff"], u"Pipe Fittings"),
            ([u"tray bend", u"tray tee", u"tray cross", u"tray reducer", u"channel horizontal"], u"Cable Tray Fittings"),
            ([u"cable tray", u"ladder", u"trunking"], u"Cable Trays"),
            ([u"conduit fitting", u"conduit box", u"junction box"], u"Conduit Fittings"),
            ([u"conduit"], u"Conduits"),
            ([u"wc", u"toilet", u"basin", u"sink", u"urinal", u"shower", u"faucet", u"drain"], u"Plumbing Fixtures"),
            ([u"door"], u"Doors"),
            ([u"window"], u"Windows"),
            ([u"column"], u"Structural Columns"),
            ([u"beam", u"truss", u"framing"], u"Structural Framing"),
            ([u"wall"], u"Walls"),
            ([u"chair", u"table", u"desk", u"sofa", u"bed", u"furniture"], u"Furniture"),
        ]

        for keywords, target_cat in keyword_map:
            u_target = target_cat if isinstance(target_cat, unicode) else unicode(target_cat)
            for kw in keywords:
                u_kw = kw if isinstance(kw, unicode) else unicode(kw)
                if u_kw in base_name:
                    return u_target

        # ── Layer 4: Standard Name Matching on Filename ──────────────────────────
        for cat in SORTED_CATEGORIES:
            u_cat = cat if isinstance(cat, unicode) else unicode(cat)
            if u_cat == u"Generic Models":
                continue
            c_low = u_cat.lower()
            if c_low in base_name or (c_low.endswith(u"s") and c_low[:-1] in base_name):
                return u_cat

        # ── Layer 5: Revit API In-Memory Document Inspection (if idle) ───────────
        if HAS_REVIT_API and os.path.exists(u_rfa_path):
            try:
                from pyrevit import revit
                uiapp = getattr(revit, "uiapp", None)
                app = uiapp.Application if uiapp else None
                if app:
                    fam_doc = app.OpenDocumentFile(u_rfa_path)
                    try:
                        if fam_doc.IsFamilyDocument and fam_doc.OwnerFamily and fam_doc.OwnerFamily.FamilyCategory:
                            cat_name = fam_doc.OwnerFamily.FamilyCategory.Name
                            if cat_name:
                                return unicode(cat_name)
                    finally:
                        fam_doc.Close(False)
            except Exception:
                pass
    except Exception:
        pass

    return u"Generic Models"


def extract_rfa_version(rfa_path):
    """
    Extracts the true Revit format version from an RFA binary file.
    Uses direct binary scan — NOT the running Revit app version.

    - Layer 1: 32-bit and 16-bit Pascal length-prefixed year in UTF-16LE (Revit 2018–2026)
    - Layer 2: 'Format:', 'Autodesk Revit 20xx', 'Revit Build:' in UTF-16LE (Revit 2011–2017)
    - Layer 3: Text regex scan in Latin-1 / ASCII fallback
    """
    if not rfa_path or not os.path.exists(rfa_path):
        return u"Unknown"

    try:
        data = read_file_bytes(rfa_path, max_bytes=2048 * 1024)
        if not data:
            return u"Unknown"

        # Layer 1: Length-prefixed Pascal year in UTF-16LE
        # 32-bit int: \x04\x00\x00\x00 + '20xx' as UTF-16LE (standard in modern Revit 2018+)
        # 16-bit int: \x04\x00 + '20xx' as UTF-16LE
        for yr in range(2011, 2028):
            p32 = b"\x04\x00\x00\x00" + str(yr).encode("utf-16le")
            p16 = b"\x04\x00" + str(yr).encode("utf-16le")
            if p32 in data or p16 in data:
                return unicode(yr)

        # Layer 2: XML PartAtom <A:product-version>20xx</A:product-version>
        m_xml = re.search(r"product-version>(20[12]\d)<", data.decode("latin1", errors="ignore"))
        if m_xml:
            return unicode(m_xml.group(1))

        # Layer 3: 'Autodesk Revit 20xx', 'Format: 20xx', 'Revit Build: 20xx' in UTF-16LE
        u16_text = data.decode("utf-16le", errors="ignore")
        m = re.search(r"(?:Format:|Autodesk Revit|Revit Build:|Revit Version:|Revit)\s*(20[12]\d)", u16_text, re.I)
        if m:
            return unicode(m.group(1))

        # Layer 4: Latin-1 / ASCII fallback
        latin_text = data.decode("latin1", errors="ignore")
        m = re.search(r"(?:Format:|Autodesk Revit|Revit Build:|Revit Version:|Revit)\s*(20[12]\d)", latin_text, re.I)
        if m:
            return unicode(m.group(1))

    except Exception:
        pass

    return u"Unknown"


def format_file_size(size_bytes):
    if size_bytes < 1024:
        return u"{} B".format(size_bytes)
    elif size_bytes < 1024 * 1024:
        return u"{:.1f} KB".format(size_bytes / 1024.0)
    else:
        return u"{:.1f} MB".format(size_bytes / (1024.0 * 1024.0))


# ── Catalog & Upload Operations (100% Cloud Webhook) ─────────────────────────

def get_catalog_cache_path():
    local_appdata = os.environ.get("LOCALAPPDATA", os.environ.get("TEMP", ""))
    cache_dir = os.path.join(local_appdata, "mepanana", "FamilyCloud")
    if not os.path.exists(cache_dir):
        try:
            os.makedirs(cache_dir)
        except Exception:
            pass
    return os.path.join(cache_dir, "catalog_cache.json")


def get_thumbnail_cache_dir():
    local_appdata = os.environ.get("LOCALAPPDATA", os.environ.get("TEMP", ""))
    thumb_dir = os.path.join(local_appdata, "mepanana", "FamilyCloud", "Thumbnails")
    if not os.path.exists(thumb_dir):
        try:
            os.makedirs(thumb_dir)
        except Exception:
            pass
    return thumb_dir


def get_thumbnail_cache_path(fam_id_or_name):
    if not fam_id_or_name:
        clean_name = u"thumb"
    elif isinstance(fam_id_or_name, unicode):
        clean_name = fam_id_or_name
    else:
        try: clean_name = fam_id_or_name.decode("utf-8")
        except Exception: clean_name = unicode(fam_id_or_name)

    for ch in [u"\\", u"/", u"*", u"?", u":", u'"', u"<", u">", u"|"]:
        clean_name = clean_name.replace(ch, u"_")

    return os.path.join(get_thumbnail_cache_dir(), clean_name + u".png")


# ── Local Version Database ────────────────────────────────────────────────────
# Stores family_name → revit_version detected from RFA binary on this machine.
# This is the CLIENT-SIDE source of truth and always overrides cloud data.

def _get_version_db_path():
    try:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(this_dir, "version_db.json")
        return db_path
    except Exception:
        local_appdata = os.environ.get("LOCALAPPDATA", os.environ.get("TEMP", ""))
        return os.path.join(local_appdata, "mepanana", "FamilyCloud", "version_db.json")


_VERSION_DB_CACHE = None

def get_all_local_versions():
    """Returns the cached local version dictionary (loaded once into RAM)."""
    global _VERSION_DB_CACHE
    if _VERSION_DB_CACHE is not None:
        return _VERSION_DB_CACHE
    db_path = _get_version_db_path()
    try:
        if os.path.exists(db_path):
            with open(db_path, "r") as f:
                _VERSION_DB_CACHE = json.load(f)
                return _VERSION_DB_CACHE
    except Exception:
        pass
    _VERSION_DB_CACHE = {}
    return _VERSION_DB_CACHE


def save_local_version(family_name, version):
    """Save locally-detected RFA version for a family. Overrides cloud value."""
    if not family_name or not version:
        return
    if isinstance(family_name, unicode):
        u_name = family_name
    else:
        try: u_name = family_name.decode("utf-8")
        except Exception: u_name = unicode(family_name)

    key = os.path.splitext(u_name)[0] if u_name.lower().endswith(u".rfa") else u_name
    db = get_all_local_versions()
    db[key] = unicode(version)
    db_path = _get_version_db_path()
    try:
        with open(db_path, "w") as f:
            json.dump(db, f, indent=2, ensure_ascii=True)
    except Exception:
        pass


def get_local_version(family_name):
    """Get locally-detected RFA version for a family from RAM cache (0ms)."""
    if not family_name:
        return None
    if isinstance(family_name, unicode):
        u_name = family_name
    else:
        try: u_name = family_name.decode("utf-8")
        except Exception: u_name = unicode(family_name)

    key = os.path.splitext(u_name)[0] if u_name.lower().endswith(u".rfa") else u_name
    db = get_all_local_versions()
    return db.get(key)


def load_catalog(force_online=False, rebuild_drive=False):
    """
    High-Performance Hybrid Catalog Loader:
    - Reads from disk cache in 0.001s for instant UI display when connected.
    - If disconnected (no webhook URL), purges cache and returns empty list.
    - If force_online=True, fetches latest catalog from Webhook RAM cache (0.1s).
    - If rebuild_drive=True, sends ?refresh=true to rebuild catalog from real Drive files.
    """
    webhook_url = get_webhook_url()
    cache_path = get_catalog_cache_path()

    # If not connected, clear any leftover cache and return empty immediately
    if not webhook_url:
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
            except Exception:
                pass
        return {"version": "1.0", "families": [], "status": "no_webhook"}

    # 1. Instant Cache Return if not forced online
    if not force_online and not rebuild_drive and os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict) and "families" in data:
                    return data
        except Exception:
            pass

    # 2. Online Fetch via Cloud Webhook (Fast RAM / catalog.json fetch in 0.1s)
    fetch_url = webhook_url
    if rebuild_drive:
        sep = "&" if "?" in webhook_url else "?"
        fetch_url = "{}{}refresh=true".format(webhook_url, sep)

    success, res_txt = make_http_request(fetch_url, method="GET", timeout=15)
    if success:
        try:
            data = json.loads(res_txt)
            if isinstance(data, dict) and "families" in data:
                # Save to local disk cache
                try:
                    with open(cache_path, "w") as f:
                        json.dump(data, f)
                except Exception:
                    pass
                return data
        except Exception:
            pass

    # Fallback to local cache if online fetch failed
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict) and "families" in data:
                    return data
        except Exception:
            pass

    return {"version": "1.0", "families": [], "status": "offline"}


def delete_family_from_cloud(fam_name, cat_name):
    """
    Sends delete command to Cloud Webhook to trash files on Google Drive and rebuild catalog.
    """
    webhook_url = get_webhook_url()
    if not webhook_url:
        return False, "No Webhook URL configured."

    def _u(s):
        if s is None: return u""
        if isinstance(s, unicode): return s
        try: return s.decode("utf-8")
        except Exception:
            try: return unicode(s)
            except Exception: return s.decode("ascii", "ignore")

    payload = {
        "action": "delete",
        "name": _u(fam_name),
        "category": _u(cat_name or "Generic Models")
    }
    payload_json = json.dumps(payload, ensure_ascii=True)
    success, res_txt = make_http_request(webhook_url, method="POST", json_body=payload_json, timeout=30)
    if not success:
        return False, u"Delete request failed:\n" + _u(res_txt)

    # Invalidate local disk cache
    cache_path = get_catalog_cache_path()
    if os.path.exists(cache_path):
        try:
            os.remove(cache_path)
        except Exception:
            pass

    return True, u"Family '" + _u(fam_name) + u"' deleted successfully from Cloud Webhook!"


def upload_family_file(source_rfa_path, target_category=None, description="", library_root=None):
    """
    Uploads family directly to Google Drive via Cloud Webhook API.
    """
    webhook_url = get_webhook_url()
    if not webhook_url:
        return False, "Please configure your Cloud Webhook URL first (click Cloud Status at top right)."

    if not os.path.exists(source_rfa_path):
        return False, "Source RFA file not found."

    return upload_family_via_webhook(source_rfa_path, target_category, description, webhook_url)


def load_family_to_revit(doc, rfa_full_path_or_url, family_name=None):
    """
    Downloads/Copies the RFA file into %TEMP% directory first, then loads into Revit document.
    Supports both local file path and direct cloud download URL!
    """
    if doc is None:
        try:
            from pyrevit import revit
            doc = revit.doc
        except Exception:
            pass

    if not doc or not rfa_full_path_or_url:
        return False, u"No active Revit project found. Please open a Revit project first."

    # 1. Copy or Download to %TEMP%\mepanana_families\
    temp_dir = os.path.join(tempfile.gettempdir(), "mepanana_families")
    if not os.path.exists(temp_dir):
        try:
            os.makedirs(temp_dir)
        except Exception:
            pass

    # Preserve exact family name
    if family_name and (isinstance(family_name, unicode) or str(family_name).strip()):
        if isinstance(family_name, str):
            try: fam_name = family_name.decode("utf-8")
            except Exception: fam_name = unicode(family_name)
        else:
            fam_name = unicode(family_name)
        fam_name = fam_name.strip()
        if fam_name.lower().endswith(u".rfa"):
            fam_name = fam_name[:-4]
    else:
        fam_base = os.path.basename(rfa_full_path_or_url.split('?')[0])
        fam_name = os.path.splitext(fam_base)[0]
        if not isinstance(fam_name, unicode):
            try: fam_name = fam_name.decode("utf-8")
            except Exception: fam_name = unicode(fam_name)
        if fam_name.lower() == u"uc" or not fam_name:
            fam_name = u"Cloud_Family"

    fam_file_name = fam_name + u".rfa"
    temp_rfa_path = os.path.join(temp_dir, fam_file_name)

    # If it is a web URL, download it first
    if rfa_full_path_or_url.startswith("http://") or rfa_full_path_or_url.startswith("https://"):
        download_ok = download_file_from_url(rfa_full_path_or_url, temp_rfa_path)
        if not download_ok or not os.path.exists(temp_rfa_path):
            return False, "Failed to download family file from Cloud Webhook."
    else:
        if not os.path.exists(rfa_full_path_or_url):
            return False, u"File does not exist on disk:\n" + unicode(rfa_full_path_or_url)
        try:
            shutil.copy2(rfa_full_path_or_url, temp_rfa_path)
        except Exception:
            temp_rfa_path = rfa_full_path_or_url

    # 2. Perform Load in Revit Transaction safely
    try:
        t = DB.Transaction(doc, "Load Family from Cloud")
        t.Start()

        class FamilyLoadOptions(DB.IFamilyLoadOptions):
            def OnFamilyFound(self, familyInUse, overwriteParameterValues):
                return True
            def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
                return True

        try:
            doc.LoadFamily(temp_rfa_path, FamilyLoadOptions())
        except Exception:
            doc.LoadFamily(temp_rfa_path)

        t.Commit()
        return True, u"Family '" + fam_name + u"' successfully loaded into project!"
    except Exception as ex:
        try: err_txt = unicode(ex)
        except Exception: err_txt = str(ex).decode("utf-8", "ignore")
        return False, u"Error loading family:\n" + err_txt