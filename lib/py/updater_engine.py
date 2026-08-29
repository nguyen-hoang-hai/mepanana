# -*- coding: utf-8 -*-
"""
updater_engine.py - MEPANANA In-App Auto-Updater & GitHub Synchronizer
Part of mepanana.extension.
"""
import os
import sys
import json
import shutil
import zipfile
import urllib.request

GITHUB_REPO = "nguyen-hoang-hai/mepanana"
API_URL = "https://api.github.com/repos/{}/commits/main".format(GITHUB_REPO)
ZIP_URL = "https://github.com/{}/archive/refs/heads/main.zip".format(GITHUB_REPO)


def get_extension_root():
    """Returns the absolute root directory of mepanana.extension."""
    # lib/py/updater_engine.py -> lib/py -> lib -> mepanana.extension
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_local_version():
    """Reads current local version and commit hash from version.json or git."""
    root = get_extension_root()
    v_file = os.path.join(root, "version.json")
    if os.path.exists(v_file):
        try:
            with open(v_file, "r") as f:
                data = json.load(f)
                return {
                    "version": data.get("version", "1.0.0"),
                    "commit": data.get("commit", "Unknown"),
                    "date": data.get("date", "Unknown"),
                    "repo": data.get("repo", "https://github.com/{}".format(GITHUB_REPO))
                }
        except Exception:
            pass

    # Fallback default
    return {
        "version": "1.0.0",
        "commit": "Initial",
        "date": "2026-08-29",
        "repo": "https://github.com/{}".format(GITHUB_REPO)
    }


def check_cloud_version():
    """
    Queries GitHub Commits API for latest commit on main branch.
    Returns dict: {'sha': str, 'full_sha': str, 'message': str, 'date': str, 'author': str}
    """
    req = urllib.request.Request(API_URL, headers={"User-Agent": "MEPANANA-AutoUpdater"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            full_sha = data.get("sha", "")
            sha = full_sha[:7] if full_sha else "Unknown"
            commit_info = data.get("commit", {})
            msg = commit_info.get("message", "").strip()
            date = commit_info.get("author", {}).get("date", "")
            author = commit_info.get("author", {}).get("name", "")

            # Format readable date
            readable_date = date
            if "T" in date:
                parts = date.split("T")
                readable_date = parts[0] + " " + parts[1].replace("Z", " UTC")

            return {
                "sha": sha,
                "full_sha": full_sha,
                "message": msg,
                "date": readable_date,
                "raw_date": date,
                "author": author,
                "success": True
            }
    except Exception as ex:
        return {
            "success": False,
            "error": str(ex)
        }


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
        req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "MEPANANA-AutoUpdater"})
        with urllib.request.urlopen(req, timeout=20) as resp, open(temp_zip, "wb") as out_f:
            out_f.write(resp.read())

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

        if progress_callback: progress_callback(80, u"Updating extension files and components...")
        for target_dir in targets:
            os.makedirs(target_dir, exist_ok=True)
            for item in os.listdir(inner_dir):
                if item in [".git"]:
                    continue
                s = os.path.join(inner_dir, item)
                d = os.path.join(target_dir, item)
                if os.path.isdir(s):
                    if os.path.exists(d):
                        # Copy contents over
                        for sub_root, dirs, files in os.walk(s):
                            rel = os.path.relpath(sub_root, s)
                            dest_sub = os.path.join(d, rel)
                            os.makedirs(dest_sub, exist_ok=True)
                            for f in files:
                                shutil.copy2(os.path.join(sub_root, f), os.path.join(dest_sub, f))
                    else:
                        shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)

            # Update version.json in target
            new_v_data = {
                "version": "1.0.0",
                "commit": cloud_info.get("sha", "latest"),
                "date": cloud_info.get("raw_date", ""),
                "repo": "https://github.com/{}".format(GITHUB_REPO)
            }
            with open(os.path.join(target_dir, "version.json"), "w") as vf:
                json.dump(new_v_data, vf, indent=2)

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
