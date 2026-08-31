# 🍌 MEPANANA REVIT EXTENSION

> **High-Performance MEP Automation Suite for Autodesk Revit & pyRevit**

[![License](https://img.shields.io/badge/License-Proprietary-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Autodesk%20Revit%202020--2026-green.svg)]()
[![pyRevit](https://img.shields.io/badge/pyRevit-4.8%2B-orange.svg)](https://pyrevitlabs.notion.site/)

---

## ⚡ Quick 1-Click Installation

### Option 1: Standalone Installer (Recommended)
Download this repository and double-click **`Install_MEPANANA.exe`** at the root folder.
* ✅ Lightweight (34 KB) & Zero Admin privileges required.
* ✅ Automatically deploys to `%APPDATA%\pyRevit\Extensions\mepanana.extension`.

### Option 2: PowerShell One-Liner
Open **Windows PowerShell** and paste:
```powershell
irm https://raw.githubusercontent.com/nguyen-hoang-hai/mepanana/main/tools/installer/install.ps1 | iex
```

---

## 🛠️ Tool Suite Overview

| Panel | Tool | Short Description |
|---|---|---|
| **🔒 Security** | `Unlock` | Real-time online license authentication via Google Apps Script Webhook. |
| **📐 Modeling** | `CAD Blocks` | Convert 2D CAD blocks into 3D Revit MEP families automatically. |
| | `CAD Wire` | Convert 2D electrical wiring lines into native Revit Wire elements. |
| | `Sprinkler Stack` | Automated pipe sizing & placement for Pendent, Upright, and Sidewall Sprinklers per TCVN 7336:2021 & NFPA 13. |
| **🧭 Coordinate**| `Display Clash` | Visual clash detection & 3D clash spheres inspection. |
| **📊 Data** | `Family Cloud` | Cloud family browser and 1-click library downloader. |
| | `Schedule Link` | Bi-directional Excel synchronization for Revit schedules. |
| **⚙️ Management** | `Shortcut Manager` | Search, manage, and customize Revit keyboard shortcuts. |
| | `Update` | 1-Click GitHub release sync with native pyRevit update notifications. |

---

## 🛡️ Security & Enterprise Architecture

* **Fail-Closed Gatekeeper**: All tools remain locked until authenticated with valid credentials.
* **Brute-Force Shield**: Progressive exponential delay ($0.6\text{s} \rightarrow 3\text{s}$) with persistent 15-minute lockout protection stored on disk (`.mpn_auth_lock.dat`).
* **Session Persistence**: Authenticated sessions are preserved across pyRevit reloads.

---

## 👨‍💻 Author & Maintainer
* **Developer**: Nguyen Hoang Hai
* **Repository**: [https://github.com/nguyen-hoang-hai/mepanana](https://github.com/nguyen-hoang-hai/mepanana)
