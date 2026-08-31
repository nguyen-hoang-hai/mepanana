# -*- coding: utf-8 -*-
"""
updater_engine.py - MEPANANA In-App Auto-Updater & GitHub Synchronizer
Part of mepanana.extension.
Fully compatible with IronPython 2.7, pyRevit, and CPython 3.x.
"""
import os
import sys
import json
import time
import shutil
import zipfile
import datetime

try:
    unicode
except NameError:
    unicode = str

try:
    import clr
    clr.AddReference("System")
    import System
    from System.Net import WebClient, ServicePointManager, SecurityProtocolType
    from System.Threading import ThreadPool, WaitCallback
    HAS_DOTNET_NET = True
except Exception:
    HAS_DOTNET_NET = False

from py.core import safe_unicode

GITHUB_REPO = "nguyen-hoang-hai/mepanana"
API_URL = "https://api.github.com/repos/{}/commits/main".format(GITHUB_REPO)
RAW_VERSION_URL = "https://raw.githubusercontent.com/{}/main/version.json".format(GITHUB_REPO)
ZIP_URL = "https://github.com/{}/archive/refs/heads/main.zip".format(GITHUB_REPO)


def format_vietnam_time(iso_str):
    """
    Converts UTC ISO timestamp to Vietnam Time (GMT+7).
    e.g. '2026-08-29T16:08:09Z' -> '2026-08-29 · 23:08'
    """
    if not iso_str or iso_str == "Unknown":
        return "Unknown"
    try:
        clean_str = str(iso_str).replace("Z", "").split(".")[0]
        if "T" in clean_str:
            dt_utc = datetime.datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S")
        elif " " in clean_str:
            dt_utc = datetime.datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
        else:
            return str(iso_str)

        dt_vn = dt_utc + datetime.timedelta(hours=7)
        return dt_vn.strftime("%Y-%m-%d · %H:%M")
    except Exception:
        return str(iso_str)


def get_extension_root():
    """Returns the absolute root directory of mepanana.extension."""
    # lib/py/updater_engine.py -> lib/py -> lib -> mepanana.extension
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_local_version():
    """Reads current local version and commit hash from version.json."""
    root = get_extension_root()
    v_file = os.path.join(root, "version.json")
    if os.path.exists(v_file):
        try:
            with open(v_file, "r") as f:
                data = json.load(f)
                raw_d = data.get("date", "Unknown")
                return {
                    "version": data.get("version", "1.0.0"),
                    "commit": data.get("commit", "Unknown"),
                    "date": format_vietnam_time(raw_d),
                    "raw_date": raw_d,
                    "repo": data.get("repo", "https://github.com/{}".format(GITHUB_REPO))
                }
        except Exception:
            pass

    return {
        "version": "1.0.0",
        "commit": "Initial",
        "date": "2026-08-29",
        "raw_date": "2026-08-29",
        "repo": "https://github.com/{}".format(GITHUB_REPO)
    }


def _http_get_string(url):
    """Cross-compatible HTTP GET string method."""
    if HAS_DOTNET_NET:
        try:
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        except Exception:
            pass
        wc = WebClient()
        wc.Headers.Add("User-Agent", "MEPANANA-AutoUpdater")
        return wc.DownloadString(url)
    else:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "MEPANANA-AutoUpdater"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode("utf-8")
        except ImportError:
            import urllib2
            req = urllib2.Request(url, headers={"User-Agent": "MEPANANA-AutoUpdater"})
            resp = urllib2.urlopen(req, timeout=10)
            return resp.read().decode("utf-8")


def _http_download_file(url, target_path):
    """Cross-compatible file downloader."""
    if HAS_DOTNET_NET:
        try:
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        except Exception:
            pass
        wc = WebClient()
        wc.Headers.Add("User-Agent", "MEPANANA-AutoUpdater")
        wc.DownloadFile(url, target_path)
    else:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "MEPANANA-AutoUpdater"})
            with urllib.request.urlopen(req, timeout=20) as resp, open(target_path, "wb") as out_f:
                out_f.write(resp.read())
        except ImportError:
            import urllib2
            req = urllib2.Request(url, headers={"User-Agent": "MEPANANA-AutoUpdater"})
            resp = urllib2.urlopen(req, timeout=20)
            with open(target_path, "wb") as out_f:
                out_f.write(resp.read())


def check_cloud_version():
    """
    Queries GitHub for latest version info.
    Attempts CDN raw.githubusercontent.com first (Rate-Limit free),
    falling back to GitHub REST API if necessary.
    Returns dict: {'sha': str, 'full_sha': str, 'message': str, 'date': str, 'author': str}
    """
    # 1. Try RAW_VERSION_URL first (0 rate limit)
    try:
        raw_v_text = _http_get_string(RAW_VERSION_URL)
        if raw_v_text and len(raw_v_text) > 10:
            v_data = json.loads(raw_v_text)
            commit_sha = v_data.get("commit", "latest")
            raw_d = v_data.get("date", "")
            return {
                "sha": commit_sha[:7] if commit_sha else "latest",
                "full_sha": commit_sha,
                "message": v_data.get("changelog", "Bản phát hành MEPANANA"),
                "date": format_vietnam_time(raw_d),
                "raw_date": raw_d,
                "author": "MEPANANA Team",
                "success": True
            }
    except Exception:
        pass

    # 2. Fallback to GitHub Commits API
    try:
        raw_json = _http_get_string(API_URL)
        data = json.loads(raw_json)
        full_sha = data.get("sha", "")
        sha = full_sha[:7] if full_sha else "Unknown"
        commit_info = data.get("commit", {})
        msg = commit_info.get("message", "").strip()
        date = commit_info.get("author", {}).get("date", "")
        author = commit_info.get("author", {}).get("name", "")

        vn_date = format_vietnam_time(date)

        return {
            "sha": sha,
            "full_sha": full_sha,
            "message": msg,
            "date": vn_date,
            "raw_date": date,
            "author": author,
            "success": True
        }
    except Exception as ex:
        return {
            "success": False,
            "error": safe_unicode(ex)
        }


def set_ribbon_update_badge(has_update, commit_info=None):
    """
    Updates the Update pushbutton on the Revit Ribbon with a visual badge 🔴.
    Thread-safe and executes on the WPF UI Dispatcher thread.
    """
    try:
        import clr
        clr.AddReference("AdWindows")
        import System
        from Autodesk.Windows import ComponentManager

        ribbon = ComponentManager.Ribbon
        if not ribbon or not ribbon.Tabs:
            return False

        def _apply():
            try:
                for tab in ribbon.Tabs:
                    tab_id = str(getattr(tab, "Id", "")).lower()
                    tab_title = str(getattr(tab, "Title", "")).lower()
                    if "mepanana" in tab_id or "mepanana" in tab_title:
                        for panel in tab.Panels:
                            if not panel.Source or not panel.Source.Items:
                                continue
                            for item in panel.Source.Items:
                                item_id = str(getattr(item, "Id", "")).lower()
                                item_text = str(getattr(item, "Text", "")).lower()
                                if "update" in item_id or "update" in item_text:
                                    if has_update:
                                        sha = ""
                                        if commit_info and isinstance(commit_info, dict):
                                            sha = commit_info.get("sha", "")
                                        item.Text = u"Update 🔴"
                                        if sha:
                                            item.ToolTip = u"✨ Có bản cập nhật mới (Commit: {})! Bấm để nâng cấp ngay.".format(sha)
                                        else:
                                            item.ToolTip = u"✨ Có bản cập nhật mới trên GitHub! Bấm để nâng cấp ngay."
                                    else:
                                        item.Text = u"Update"
                                        item.ToolTip = u"Kiểm tra và đồng bộ phiên bản MEPANANA mới nhất từ GitHub."
                                    ribbon.UpdateLayout()
                                    return True
            except Exception:
                pass
            return False

        dispatcher = ribbon.Dispatcher
        if dispatcher:
            if dispatcher.CheckAccess():
                return _apply()
            else:
                dispatcher.Invoke(System.Action(_apply))
        else:
            return _apply()
    except Exception:
        pass
    return False


def check_updates_in_background(force=False, callback=None):
    """
    Checks GitHub commits in a background worker and sets the Ribbon badge 🔴.
    Caches results in %TEMP% for 2 hours to avoid redundant API calls.
    """
    if not HAS_DOTNET_NET:
        return

    try:
        cache_file = os.path.join(os.environ.get("TEMP", ""), "mepanana_update_cache.json")

        if not force and os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    cache = json.load(f)
                last_check = cache.get("timestamp", 0)
                # 2 hours cache (7200 seconds)
                if time.time() - last_check < 7200:
                    has_up = cache.get("has_update", False)
                    c_info = cache.get("cloud_info", {})
                    set_ribbon_update_badge(has_up, c_info)
                    if callback:
                        callback(has_up, c_info)
                    return
            except Exception:
                pass

        def _bg_task(state):
            try:
                local_v = get_local_version()
                cloud_v = check_cloud_version()
                if cloud_v.get("success"):
                    local_sha = str(local_v.get("commit", "")).lower()
                    cloud_sha = str(cloud_v.get("sha", "")).lower()
                    has_update = bool(cloud_sha and cloud_sha != local_sha)

                    set_ribbon_update_badge(has_update, cloud_v)

                    # Save to cache
                    try:
                        with open(cache_file, "w") as f:
                            json.dump({
                                "timestamp": time.time(),
                                "has_update": has_update,
                                "cloud_info": cloud_v
                            }, f)
                    except Exception:
                        pass

                    if callback:
                        callback(has_update, cloud_v)
            except Exception:
                pass

        ThreadPool.QueueUserWorkItem(WaitCallback(_bg_task))
    except Exception:
        pass


def safe_makedirs(path):
    """Safely creates directories in Python 2.7 / IronPython without exist_ok."""
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except Exception:
            pass


def download_and_install_update(progress_callback=None):
    """
    Downloads latest repository zip from GitHub, extracts, and updates extension files.
    progress_callback(percent: int, status_msg: str)
    """
    temp_zip = os.path.join(os.environ.get("TEMP", ""), "mepanana_cloud_update.zip")
    temp_extract = os.path.join(os.environ.get("TEMP", ""), "mepanana_cloud_extract")

    try:
        # 1. Fetch Cloud Version Info
        if progress_callback: progress_callback(10, u"Checking latest cloud commit on GitHub...")
        cloud_info = check_cloud_version()
        if not cloud_info.get("success"):
            raise RuntimeError(u"Failed to connect to GitHub: {}".format(cloud_info.get("error")))

        # 2. Download ZIP
        if progress_callback: progress_callback(30, u"Downloading latest update archive from GitHub...")
        _http_download_file(ZIP_URL, temp_zip)

        # 3. Extract ZIP
        if progress_callback: progress_callback(60, u"Extracting and verifying update package...")
        if os.path.exists(temp_extract):
            shutil.rmtree(temp_extract, ignore_errors=True)

        with zipfile.ZipFile(temp_zip, "r") as z:
            z.extractall(temp_extract)

        inner_dir = os.path.join(temp_extract, "mepanana-main")
        if not os.path.exists(inner_dir):
            inner_dir = temp_extract

        # 4. Target Directories to Update
        targets = [get_extension_root()]
        appdata_ext = os.path.join(os.environ.get("APPDATA", ""), "pyRevit", "Extensions", "mepanana.extension")
        if os.path.abspath(appdata_ext) not in [os.path.abspath(t) for t in targets] and os.path.exists(appdata_ext):
            targets.append(appdata_ext)

        def _safe_copy_file(src_path, dst_path):
            try:
                if os.path.exists(dst_path) and dst_path.lower().endswith(".dll"):
                    old_bak = dst_path + ".old"
                    if os.path.exists(old_bak):
                        try:
                            os.remove(old_bak)
                        except Exception:
                            pass
                    try:
                        os.rename(dst_path, old_bak)
                    except Exception:
                        pass
                shutil.copy2(src_path, dst_path)
            except Exception:
                pass

        if progress_callback: progress_callback(80, u"Updating extension files and components...")
        for target_dir in targets:
            safe_makedirs(target_dir)
            for item in os.listdir(inner_dir):
                if item in [".git"]:
                    continue
                s = os.path.join(inner_dir, item)
                d = os.path.join(target_dir, item)
                if os.path.isdir(s):
                    for sub_root, dirs, files in os.walk(s):
                        rel = os.path.relpath(sub_root, s)
                        dest_sub = os.path.join(d, rel)
                        safe_makedirs(dest_sub)
                        for f in files:
                            src_file = os.path.join(sub_root, f)
                            dst_file = os.path.join(dest_sub, f)
                            _safe_copy_file(src_file, dst_file)
                else:
                    _safe_copy_file(s, d)

            new_v_data = {
                "version": "1.0.0",
                "commit": cloud_info.get("sha", "latest"),
                "date": cloud_info.get("raw_date", ""),
                "repo": "https://github.com/{}".format(GITHUB_REPO)
            }
            try:
                with open(os.path.join(target_dir, "version.json"), "w") as vf:
                    json.dump(new_v_data, vf, indent=2)
            except Exception:
                pass

        # Reset ribbon badge since update is complete
        try:
            set_ribbon_update_badge(False)
            cache_file = os.path.join(os.environ.get("TEMP", ""), "mepanana_update_cache.json")
            if os.path.exists(cache_file):
                os.remove(cache_file)
        except Exception:
            pass

        # 5. Cleanup
        try: os.remove(temp_zip)
        except: pass
        try: shutil.rmtree(temp_extract, ignore_errors=True)
        except: pass

        if progress_callback: progress_callback(100, u"Update completed successfully!")
        return cloud_info

    except Exception as ex:
        try: os.remove(temp_zip)
        except: pass
        try: shutil.rmtree(temp_extract, ignore_errors=True)
        except: pass
        raise
