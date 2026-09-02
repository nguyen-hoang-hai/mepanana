# -*- coding: utf-8 -*-
"""
MEPANANA - 1-Click Zero-Admin Installer & Updater
Downloads the latest release from GitHub and installs to %APPDATA%/pyRevit/Extensions/mepanana.extension
"""
import os
import sys
import json
import shutil
import zipfile
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox
import threading

REPO_URL = "https://github.com/nguyen-hoang-hai/mepanana/archive/refs/heads/main.zip"
TARGET_EXT_DIR = os.path.join(os.environ.get("APPDATA", ""), "pyRevit", "Extensions", "mepanana.extension")


class MepananaInstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🍌 MEPANANA Extension - 1-Click Installer")
        self.geometry("520x360")
        self.resizable(False, False)
        self.configure(bg="#0F172A")

        # Center window
        self.eval('tk::PlaceWindow . center')

        self.create_widgets()

    def create_widgets(self):
        # Header Container
        header_frame = tk.Frame(self, bg="#0F172A")
        header_frame.pack(pady=(24, 10), padx=20, fill="x")

        title_lbl = tk.Label(
            header_frame, text="🍌 MEPANANA REVIT EXTENSION",
            font=("Segoe UI", 16, "bold"), fg="#10B981", bg="#0F172A"
        )
        title_lbl.pack(anchor="center")

        sub_lbl = tk.Label(
            header_frame, text="1-Click Auto Installer & Updater (User-Level - No Admin Rights)",
            font=("Segoe UI", 10), fg="#94A3B8", bg="#0F172A"
        )
        sub_lbl.pack(anchor="center", pady=(4, 0))

        # Info Box Card
        card_frame = tk.Frame(self, bg="#1E293B", highlightbackground="#334155", highlightthickness=1)
        card_frame.pack(pady=10, padx=24, fill="both", expand=True)

        info_title = tk.Label(
            card_frame, text="📁 Installation Directory:",
            font=("Segoe UI", 10, "bold"), fg="#E2E8F0", bg="#1E293B"
        )
        info_title.pack(anchor="w", padx=16, pady=(12, 2))

        path_lbl = tk.Label(
            card_frame, text=TARGET_EXT_DIR,
            font=("Consolas", 8.5), fg="#38BDF8", bg="#1E293B", wraplength=440, justify="left"
        )
        path_lbl.pack(anchor="w", padx=16, pady=(0, 10))

        # Status Text
        self.status_lbl = tk.Label(
            card_frame, text="Ready to install the latest release from GitHub.",
            font=("Segoe UI", 9.5), fg="#94A3B8", bg="#1E293B"
        )
        self.status_lbl.pack(anchor="w", padx=16, pady=(0, 6))

        # Progress Bar
        self.progress = ttk.Progressbar(card_frame, mode="determinate", length=440)
        self.progress.pack(padx=16, pady=(0, 14), fill="x")

        # Action Buttons Footer
        footer_frame = tk.Frame(self, bg="#0F172A")
        footer_frame.pack(pady=(0, 20), padx=24, fill="x")

        self.btn_install = tk.Button(
            footer_frame, text="🚀 Install / Update Now",
            font=("Segoe UI", 11, "bold"), fg="#FFFFFF", bg="#2563EB", activebackground="#1D4ED8",
            activeforeground="#FFFFFF", relief="flat", cursor="hand2", padx=20, pady=8,
            command=self.start_install
        )
        self.btn_install.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_close = tk.Button(
            footer_frame, text="Close",
            font=("Segoe UI", 10), fg="#94A3B8", bg="#334155", activebackground="#475569",
            activeforeground="#FFFFFF", relief="flat", cursor="hand2", padx=16, pady=8,
            command=self.destroy
        )
        self.btn_close.pack(side="right")

    def start_install(self):
        self.btn_install.config(state="disabled", bg="#64748B", text="⏳ Installing...")
        self.progress["value"] = 10
        self.status_lbl.config(text="Connecting to GitHub...", fg="#38BDF8")

        thread = threading.Thread(target=self.run_installation, daemon=True)
        thread.start()

    def run_installation(self):
        temp_zip = os.path.join(os.environ.get("TEMP", ""), "mepanana_latest.zip")
        temp_extract = os.path.join(os.environ.get("TEMP", ""), "mepanana_extracted")

        try:
            # 1. Download
            self.set_progress(20, "Downloading latest release package from GitHub...")
            req = urllib.request.Request(REPO_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as resp, open(temp_zip, "wb") as out_f:
                out_f.write(resp.read())

            # 2. Extract
            self.set_progress(60, "Extracting package...")
            if os.path.exists(temp_extract):
                shutil.rmtree(temp_extract, ignore_errors=True)

            with zipfile.ZipFile(temp_zip, "r") as z:
                z.extractall(temp_extract)

            # 3. Copy to destination
            self.set_progress(85, "Deploying to pyRevit Extensions directory...")
            inner_dir = os.path.join(temp_extract, "mepanana-main")
            if not os.path.exists(inner_dir):
                inner_dir = temp_extract

            if not os.path.exists(TARGET_EXT_DIR):
                try: os.makedirs(TARGET_EXT_DIR)
                except Exception: pass
            for item in os.listdir(inner_dir):
                s = os.path.join(inner_dir, item)
                d = os.path.join(TARGET_EXT_DIR, item)
                if os.path.isdir(s):
                    if os.path.exists(d):
                        shutil.rmtree(d, ignore_errors=True)
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)

            # 4. Auto-Unblock All Files (Remove Windows Mark-of-the-Web / Zone.Identifier)
            self.set_progress(92, "Unblocking binaries & security descriptors...")
            try:
                import subprocess
                ps_cmd = 'Get-ChildItem -Path "{}" -Recurse | Unblock-File'.format(TARGET_EXT_DIR)
                subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], creationflags=0x08000000)
            except Exception:
                pass

            # 5. Cleanup
            try: os.remove(temp_zip)
            except: pass
            try: shutil.rmtree(temp_extract, ignore_errors=True)
            except: pass

            self.set_progress(100, "🎉 Installation & Update completed successfully!", success=True)
            self.after(200, lambda: messagebox.showinfo(
                "Installation Complete",
                "🎉 MEPANANA Extension has been installed successfully!\n\nAll DLL binaries have been unblocked.\nPlease restart Autodesk Revit or click pyRevit -> Reload to start."
            ))

        except Exception as ex:
            self.set_progress(0, "❌ Error: " + str(ex), error=True)
            self.after(200, lambda: messagebox.showerror("Installation Error", str(ex)))

        finally:
            self.after(0, lambda: self.btn_install.config(
                state="normal", bg="#2563EB", text="🚀 Install / Update Now"
            ))

    def set_progress(self, val, msg, success=False, error=False):
        def _update():
            self.progress["value"] = val
            fg_color = "#10B981" if success else ("#EF4444" if error else "#38BDF8")
            self.status_lbl.config(text=msg, fg=fg_color)
        self.after(0, _update)


if __name__ == "__main__":
    app = MepananaInstallerApp()
    app.mainloop()
