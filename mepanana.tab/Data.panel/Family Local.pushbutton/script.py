# -*- coding: utf-8 -*-
"""
Family Local (FL) — Local & Network Revit Family Library Studio
Part of mepanana.extension.
- Fast recursive scanning of local & network drives for .rfa families.
- High-Performance OLE compound & binary stream embedded thumbnail extraction.
- Category & Revit version auto-detection with smart compatibility filtering.
- 1-Click loading and batch loading with progress bar and dispatcher slicing.
"""
__title__ = "Family Local"
__doc__   = "Browse, preview, and batch load Revit families from your local or network library directory."

# ── 6-Line Security Gatekeeper Boilerplate ───────────────────────────────────
from py.auth import require_auth, update_ribbon_state, is_authenticated
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        import sys
        sys.exit()

import os
import sys
import json
import time
import subprocess

from pyrevit import forms, revit, script, DB, UI
from py.core import get_doc, get_uidoc, safe_unicode
from py.ui import (
    setup_window, show_info, show_warning, show_error, show_success,
    show_confirm, do_events, yield_dispatcher_every
)
from py.family_cloud_engine import (
    extract_preview_png_bytes, extract_rfa_category, extract_rfa_version,
    STANDARD_CATEGORIES
)

import clr
clr.AddReference("System")
clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
import System
from System.IO import MemoryStream
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Media import SolidColorBrush, Color
from System.Windows import Visibility


# ── Configuration & Persistence ───────────────────────────────────────────────

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", ""), "pyRevit", "mepanana")
CONFIG_FILE = os.path.join(CONFIG_DIR, "family_local_config.json")

def load_saved_folder():
    """Loads the last used family folder from user settings."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                p = data.get("library_path", "")
                if p and os.path.isdir(p):
                    return p
    except Exception:
        pass
    # Fallback to user's Documents folder
    docs_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Documents")
    return docs_dir if os.path.exists(docs_dir) else "C:\\"

def save_saved_folder(folder_path):
    """Saves the last used family folder to user settings."""
    try:
        if not os.path.exists(CONFIG_DIR):
            os.makedirs(CONFIG_DIR)
        with open(CONFIG_FILE, "w") as f:
            json.dump({"library_path": folder_path}, f)
    except Exception:
        pass


# ── Family Load Options Handler ──────────────────────────────────────────────

class SafeFamilyLoadOptions(DB.IFamilyLoadOptions):
    """Auto-overwrites parameters on load without prompting."""
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        try:
            overwriteParameterValues.Value = True
        except Exception:
            pass
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        try:
            overwriteParameterValues.Value = True
        except Exception:
            pass
        return True


# ── UI Data Model ─────────────────────────────────────────────────────────────

class LocalFamilyItem(object):
    """View model for a single local .rfa family card matching Family Cloud standards."""
    def __init__(self, rfa_path, active_revit_year=2024):
        self.RfaPath = rfa_path
        self.Name = os.path.splitext(os.path.basename(rfa_path))[0]
        
        # File Size
        try:
            self.FileSize = os.path.getsize(rfa_path)
            if self.FileSize > 1024 * 1024:
                self.FileSizeStr = "{:.1f} MB".format(self.FileSize / (1024.0 * 1024.0))
            else:
                self.FileSizeStr = "{:.0f} KB".format(self.FileSize / 1024.0)
        except Exception:
            self.FileSize = 0
            self.FileSizeStr = "Unknown"

        # Revit Version & Category
        self.Version = extract_rfa_version(rfa_path)
        self.Category = extract_rfa_category(rfa_path)

        # Version Badge Color Coding
        if self.Version > 0:
            self.VersionLabel = "{}".format(self.Version)
            if self.Version > active_revit_year:
                # Incompatible (Higher than active Revit)
                self.VersionBadgeBg = SolidColorBrush(Color.FromRgb(254, 226, 226)) # Light Red
                self.VersionBadgeFg = SolidColorBrush(Color.FromRgb(220, 38, 38))   # Red Text
                self.IsCompatible = False
            else:
                # Compatible
                self.VersionBadgeBg = SolidColorBrush(Color.FromRgb(219, 234, 254)) # Light Blue
                self.VersionBadgeFg = SolidColorBrush(Color.FromRgb(29, 78, 216))   # Blue Text
                self.IsCompatible = True
        else:
            self.VersionLabel = "Universal"
            self.VersionBadgeBg = SolidColorBrush(Color.FromRgb(241, 245, 249))
            self.VersionBadgeFg = SolidColorBrush(Color.FromRgb(71, 85, 105))
            self.IsCompatible = True

        # Extract & Build WPF Thumbnail Image (using .NET Byte Array)
        self.ThumbnailImage = None
        try:
            raw_bytes = extract_preview_png_bytes(rfa_path)
            if raw_bytes:
                self.ThumbnailImage = self._bytes_to_bitmapimage(raw_bytes)
        except Exception:
            pass

        # Selection State
        self.IsSelected = False

        # Tooltip Text
        self.TooltipText = u"Name: {}\nCategory: {}\nVersion: {}\nSize: {}\nPath: {}".format(
            self.Name, self.Category, self.VersionLabel, self.FileSizeStr, self.RfaPath
        )

    def _bytes_to_bitmapimage(self, raw_bytes):
        """Converts raw PNG/JPEG bytes to a frozen WPF BitmapImage."""
        if not raw_bytes:
            return None
        try:
            arr = System.Array[System.Byte](bytearray(raw_bytes))
            ms = MemoryStream(arr)
            bmp = BitmapImage()
            bmp.BeginInit()
            bmp.CacheOption = BitmapCacheOption.OnLoad
            bmp.StreamSource = ms
            bmp.EndInit()
            bmp.Freeze()
            return bmp
        except Exception:
            return None


class CategoryItem(object):
    """View model for category list in sidebar."""
    def __init__(self, name, count):
        self.Name = name
        self.DisplayName = name
        self.Count = count


# ── Main Window Controller ───────────────────────────────────────────────────

class FamilyLocalWindow(forms.WPFWindow):
    """Interactive WPF Studio for browsing, filtering and loading local families."""
    def __init__(self, doc):
        xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        setup_window(self)

        self.doc = doc
        
        # Determine Active Revit Version Year
        self.active_revit_year = 2024
        try:
            from pyrevit import HOST_APP
            if HOST_APP and HOST_APP.version:
                self.active_revit_year = int(HOST_APP.version)
        except Exception:
            pass

        self.all_families = []
        self.filtered_families = []
        self.current_folder = load_saved_folder()

        if hasattr(self, 'txtFolderPath'):
            self.txtFolderPath.Text = self.current_folder

        # Wire Up Event Handlers
        if hasattr(self, 'btnBrowseFolder'):
            self.btnBrowseFolder.Click += self.OnBrowseFolder
        if hasattr(self, 'btnRescan'):
            self.btnRescan.Click += self.OnRescan
        if hasattr(self, 'btnOpenExplorer'):
            self.btnOpenExplorer.Click += self.OnOpenExplorer
        if hasattr(self, 'txtSearch'):
            self.txtSearch.TextChanged += self.OnSearchChanged
        if hasattr(self, 'chkCompatibleOnly'):
            self.chkCompatibleOnly.Checked += self.OnFilterChanged
            self.chkCompatibleOnly.Unchecked += self.OnFilterChanged
        if hasattr(self, 'cmbVersionFilter'):
            self.cmbVersionFilter.SelectionChanged += self.OnFilterChanged
        if hasattr(self, 'listCategories'):
            self.listCategories.SelectionChanged += self.OnCategorySelectionChanged
        if hasattr(self, 'chkSelectAll'):
            self.chkSelectAll.Click += self.OnSelectAllClick
        if hasattr(self, 'btnBatchLoadTop'):
            self.btnBatchLoadTop.Click += self.OnBatchLoad
        if hasattr(self, 'btnClose'):
            self.btnClose.Click += lambda s, e: self.Close()

        # Connect Dynamic Card Loading Event via ItemsControl
        if hasattr(self, 'itemsCards'):
            self.itemsCards.AddHandler(
                System.Windows.Controls.Button.ClickEvent,
                System.Windows.RoutedEventHandler(self.OnCardButtonClick)
            )
            self.itemsCards.AddHandler(
                System.Windows.Controls.CheckBox.ClickEvent,
                System.Windows.RoutedEventHandler(self.OnCardCheckboxClick)
            )

        # Initial Directory Scan
        self.ScanDirectory(self.current_folder)

    # ── Directory Scanning & Indexing ─────────────────────────────────────────

    def ScanDirectory(self, folder_path):
        """Recursively scans folder for .rfa files and extracts metadata & thumbnails."""
        if not folder_path or not os.path.isdir(folder_path):
            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = "Please select a valid directory containing Revit families."
            return

        self.current_folder = folder_path
        save_saved_folder(folder_path)

        # UI Visuals: Show progress bar during indexing
        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = Visibility.Visible
            self.progressBar.Value = 0
        if hasattr(self, 'txtStatus'):
            self.txtStatus.Text = "Scanning directory for .rfa families..."
        do_events()

        # 1. Discover all .rfa files
        rfa_paths = []
        try:
            for root, dirs, files in os.walk(folder_path):
                for f in files:
                    if f.lower().endswith(".rfa") and not f.startswith("."):
                        # Skip Revit automatic backup files (e.g. Family.0001.rfa)
                        name_no_ext = os.path.splitext(f)[0]
                        if len(name_no_ext) > 5 and name_no_ext[-5] == '.' and name_no_ext[-4:].isdigit():
                            continue
                        rfa_paths.append(os.path.join(root, f))
        except Exception as ex:
            show_error(u"Error scanning folder:\n{}".format(safe_unicode(ex)), "Scan Error")
            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = Visibility.Collapsed
            return

        total_files = len(rfa_paths)
        if total_files == 0:
            self.all_families = []
            self.PopulateCategories([])
            self.PopulateVersionFilter([])
            self.ApplyFilters()
            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = "No .rfa families found in selected folder."
            if hasattr(self, 'txtLibraryStats'):
                self.txtLibraryStats.Text = "0 Families"
            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = Visibility.Collapsed
            return

        # 2. Extract metadata & thumbnails with 60 FPS Dispatcher Slicing
        items = []
        total_bytes = 0
        for idx, rfa_path in enumerate(rfa_paths):
            try:
                item = LocalFamilyItem(rfa_path, active_revit_year=self.active_revit_year)
                items.append(item)
                total_bytes += item.FileSize
            except Exception:
                pass

            if hasattr(self, 'progressBar'):
                pct = int((float(idx + 1) / total_files) * 100)
                self.progressBar.Value = pct
            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = "Extracting thumbnails & metadata ({}/{})...".format(idx + 1, total_files)

            yield_dispatcher_every(idx + 1, batch_size=15)

        self.all_families = items

        # 3. Update Library Stats Badge
        if hasattr(self, 'txtLibraryStats'):
            size_mb = total_bytes / (1024.0 * 1024.0)
            if size_mb > 1024:
                size_str = "{:.1f} GB".format(size_mb / 1024.0)
            else:
                size_str = "{:.1f} MB".format(size_mb)
            self.txtLibraryStats.Text = "{} Families ({})".format(len(items), size_str)

        # 4. Build Category & Version Filters
        self.PopulateCategories(items)
        self.PopulateVersionFilter(items)

        # 5. Apply Initial Filters & Render Cards
        self.ApplyFilters()

        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = Visibility.Collapsed
        if hasattr(self, 'txtStatus'):
            self.txtStatus.Text = "Ready. Scanned {} families.".format(len(items))

    # ── Category & Version Filter Builders ────────────────────────────────────

    def PopulateCategories(self, items):
        """Populates the left categories sidebar with dynamic item counts."""
        if not hasattr(self, 'listCategories'):
            return

        cat_counts = {}
        for it in items:
            cat = it.Category or "Generic Models"
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        cat_list = [CategoryItem("All Categories", len(items))]
        for cat_name in sorted(cat_counts.keys()):
            cat_list.append(CategoryItem(cat_name, cat_counts[cat_name]))

        self.listCategories.ItemsSource = cat_list
        self.listCategories.SelectedIndex = 0

    def PopulateVersionFilter(self, items):
        """Populates the version filter dropdown."""
        if not hasattr(self, 'cmbVersionFilter'):
            return

        versions = set()
        for it in items:
            if it.Version > 0:
                versions.add(it.Version)

        self.cmbVersionFilter.Items.Clear()
        self.cmbVersionFilter.Items.Add("All Versions")
        for v in sorted(list(versions), reverse=True):
            self.cmbVersionFilter.Items.Add(str(v))

        self.cmbVersionFilter.SelectedIndex = 0

    # ── Filtering & Searching ─────────────────────────────────────────────────

    def OnSearchChanged(self, sender, args):
        self.ApplyFilters()

    def OnFilterChanged(self, sender, args):
        self.ApplyFilters()

    def OnCategorySelectionChanged(self, sender, args):
        self.ApplyFilters()

    def ApplyFilters(self):
        """Applies Search, Category, Version, and Compatibility filters simultaneously."""
        search_query = self.txtSearch.Text.strip().lower() if hasattr(self, 'txtSearch') and self.txtSearch.Text else ""
        compatible_only = self.chkCompatibleOnly.IsChecked == True if hasattr(self, 'chkCompatibleOnly') else False

        selected_cat = "All Categories"
        if hasattr(self, 'listCategories') and self.listCategories.SelectedItem:
            selected_cat = self.listCategories.SelectedItem.Name

        selected_ver = "All Versions"
        if hasattr(self, 'cmbVersionFilter') and self.cmbVersionFilter.SelectedItem:
            selected_ver = str(self.cmbVersionFilter.SelectedItem)

        filtered = []
        for it in self.all_families:
            # 1. Search Query Filter
            if search_query:
                if search_query not in it.Name.lower() and search_query not in it.Category.lower():
                    continue

            # 2. Category Filter
            if selected_cat != "All Categories" and it.Category != selected_cat:
                continue

            # 3. Version Filter
            if selected_ver != "All Versions" and it.VersionLabel != selected_ver:
                continue

            # 4. Compatibility Filter
            if compatible_only and not it.IsCompatible:
                continue

            filtered.append(it)

        self.filtered_families = filtered

        # Update Cards View
        if hasattr(self, 'itemsCards'):
            self.itemsCards.ItemsSource = None
            self.itemsCards.ItemsSource = filtered

        # Update Found Badge
        if hasattr(self, 'txtFoundCount'):
            self.txtFoundCount.Text = "{} families found".format(len(filtered))

        self.UpdateBatchLoadButtonState()

    # ── Selection & Batch Load Handlers ───────────────────────────────────────

    def OnSelectAllClick(self, sender, args):
        is_chk = self.chkSelectAll.IsChecked == True
        for it in self.filtered_families:
            it.IsSelected = is_chk
        if hasattr(self, 'itemsCards'):
            self.itemsCards.Items.Refresh()
        self.UpdateBatchLoadButtonState()

    def OnCardCheckboxClick(self, sender, args):
        self.UpdateBatchLoadButtonState()

    def UpdateBatchLoadButtonState(self):
        selected_count = sum(1 for it in self.all_families if it.IsSelected)
        if hasattr(self, 'txtBatchLoadTopCount'):
            self.txtBatchLoadTopCount.Text = u"Load Selected ({})".format(selected_count)
        if hasattr(self, 'btnBatchLoadTop'):
            self.btnBatchLoadTop.IsEnabled = (selected_count > 0)

    # ── Folder Picker & Navigation ────────────────────────────────────────────

    def OnBrowseFolder(self, sender, args):
        """Opens Windows FolderBrowserDialog to pick a family library directory."""
        import System.Windows.Forms as WinForms
        dialog = WinForms.FolderBrowserDialog()
        dialog.Description = "Select your Revit Family Library Directory"
        dialog.SelectedPath = self.current_folder if os.path.isdir(self.current_folder) else "C:\\"
        dialog.ShowNewFolderButton = True

        if dialog.ShowDialog() == WinForms.DialogResult.OK:
            chosen = dialog.SelectedPath
            if chosen and os.path.isdir(chosen):
                if hasattr(self, 'txtFolderPath'):
                    self.txtFolderPath.Text = chosen
                self.ScanDirectory(chosen)

    def OnRescan(self, sender, args):
        folder = self.txtFolderPath.Text.strip() if hasattr(self, 'txtFolderPath') else ""
        if folder and os.path.isdir(folder):
            self.ScanDirectory(folder)
        else:
            show_warning("Please enter a valid folder path first.", "Invalid Path")

    def OnOpenExplorer(self, sender, args):
        folder = self.txtFolderPath.Text.strip() if hasattr(self, 'txtFolderPath') else ""
        if folder and os.path.isdir(folder):
            try:
                os.startfile(folder)
            except Exception:
                subprocess.Popen(["explorer", folder])
        else:
            show_warning("Folder does not exist or has not been selected.", "Open Explorer")

    # ── Family Loading Actions (1-Click & Batch) ──────────────────────────────

    def OnCardButtonClick(self, sender, args):
        """Handles 1-Click '📥 Load' button click directly on a card."""
        btn = args.OriginalSource
        if btn and hasattr(btn, 'Tag') and btn.Tag:
            rfa_path = str(btn.Tag)
            self.LoadSingleFamily(rfa_path)

    def LoadSingleFamily(self, rfa_path):
        """Loads a single .rfa family into the active Revit document."""
        if not os.path.exists(rfa_path):
            show_error(u"File not found:\n{}".format(rfa_path), "Missing File")
            return

        fam_name = os.path.splitext(os.path.basename(rfa_path))[0]
        opt = SafeFamilyLoadOptions()

        t = DB.Transaction(self.doc, "Load Family: {}".format(fam_name))
        try:
            t.Start()
            clr_family = clr.Reference[DB.Family]()
            ok = self.doc.LoadFamily(rfa_path, opt, clr_family)
            t.Commit()

            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"🎉 Family '{}' loaded successfully!".format(fam_name)
            show_success(
                u"Family '{}' has been loaded successfully into your active project!".format(fam_name),
                "Family Loaded"
            )
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            show_error(u"Failed to load family '{}':\n{}".format(fam_name, safe_unicode(ex)), "Load Error")

    def OnBatchLoad(self, sender, args):
        """Batch loads all checked families with live progress bar and 60 FPS dispatcher."""
        selected_items = [it for it in self.all_families if it.IsSelected]
        if not selected_items:
            show_warning("Please select at least 1 family to load.", "Empty Selection")
            return

        # Check for higher Revit version warnings
        higher_count = sum(1 for it in selected_items if not it.IsCompatible and it.Version > self.active_revit_year)
        if higher_count > 0:
            if not show_confirm(
                u"⚠️ {} of the selected families were created in a newer Revit version (> {}).\n\n"
                u"Revit cannot open families from future versions. Do you want to proceed and load the compatible ones?".format(
                    higher_count, self.active_revit_year
                ),
                "Version Warning"
            ):
                return

        # Execute Batch Loading
        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = Visibility.Visible
            self.progressBar.Value = 0
        if hasattr(self, 'btnBatchLoadTop'):
            self.btnBatchLoadTop.IsEnabled = False

        opt = SafeFamilyLoadOptions()
        success_count = 0
        failed_count = 0
        errors = []

        tg = DB.TransactionGroup(self.doc, "MEPANANA - Batch Load Local Families")
        tg.Start()

        try:
            for idx, it in enumerate(selected_items):
                fam_name = it.Name
                if hasattr(self, 'txtStatus'):
                    self.txtStatus.Text = u"Loading ({}/{}): {}...".format(idx + 1, len(selected_items), fam_name)
                if hasattr(self, 'progressBar'):
                    pct = int((float(idx + 1) / len(selected_items)) * 100)
                    self.progressBar.Value = pct

                t = DB.Transaction(self.doc, "Load Family {}".format(fam_name))
                try:
                    t.Start()
                    clr_family = clr.Reference[DB.Family]()
                    ok = self.doc.LoadFamily(it.RfaPath, opt, clr_family)
                    t.Commit()
                    success_count += 1
                except Exception as ex:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                    failed_count += 1
                    errors.append(u"{}: {}".format(fam_name, safe_unicode(ex)))

                yield_dispatcher_every(idx + 1, batch_size=5)

            tg.Assimilate()

            msg = u"🎉 Batch Loading Complete!\n\n"
            msg += u"• Loaded Successfully: {} families\n".format(success_count)
            if failed_count > 0:
                msg += u"• Skipped / Failed: {} families\n".format(failed_count)
                if errors:
                    msg += u"\n⚠️ Error summary:\n• " + u"\n• ".join(errors[:3])

            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"Completed: {} loaded, {} failed.".format(success_count, failed_count)

            show_info(msg, "Batch Loading Summary")

        except Exception as ex:
            if tg.HasStarted() and not tg.HasEnded():
                tg.RollBack()
            show_error(u"Error during batch load:\n{}".format(safe_unicode(ex)), "Batch Load Error")

        finally:
            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = Visibility.Collapsed
            if hasattr(self, 'btnBatchLoadTop'):
                self.btnBatchLoadTop.IsEnabled = True


# ── Launch Entry ──────────────────────────────────────────────────────────────

def run():
    doc = get_doc()
    if not doc:
        show_warning("Please open a Revit project before launching Family Local.", "No Active Project")
        return

    win = FamilyLocalWindow(doc)
    win.ShowDialog()

if __name__ == "__main__":
    run()
