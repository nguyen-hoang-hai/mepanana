# -*- coding: utf-8 -*-
"""
Family Cloud (FC) - Controller Script
Part of mepanana.extension.
- Cloud Library Manager for Revit Families synchronized with OneDrive
- Auto-organized Category directories, RFA version detection & high-res thumbnail preview
- 1-Click Load into active Revit Project
"""
import os
import sys

# 1. Dynamic Lib Resolution
cur_dir = os.path.dirname(__file__)
while cur_dir and not os.path.exists(os.path.join(cur_dir, "lib", "py", "auth.py")):
    parent = os.path.dirname(cur_dir)
    if parent == cur_dir:
        break
    cur_dir = parent
lib_path = os.path.join(cur_dir, "lib")
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from py.auth import require_auth, update_ribbon_state, is_authenticated

# 2. Security Gatekeeper
if not is_authenticated():
    update_ribbon_state(False)
    if not require_auth():
        sys.exit()

try:
    from py.updater_engine import check_updates_in_background
    check_updates_in_background()
except Exception:
    pass

import clr
clr.AddReference("System")
clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
import System
from System.Windows import Thickness, Visibility
from System.Windows.Input import Key, Keyboard
from System.Windows.Forms import OpenFileDialog, DialogResult
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.IO import MemoryStream, File

import re
from pyrevit import revit, DB, UI, forms, HOST_APP

HOST_REVIT_YEAR = None
try:
    if HOST_APP and hasattr(HOST_APP, "version"):
        HOST_REVIT_YEAR = int(str(HOST_APP.version).strip()[:4])
except Exception:
    pass

from py.ui import setup_window, show_info, show_success, show_warning, show_error, show_confirm, do_events
from py.family_cloud_engine import (
    STANDARD_CATEGORIES,
    get_webhook_url,
    is_cloud_connected,
    load_catalog,
    upload_family_file,
    delete_family_from_cloud,
    load_family_to_revit,
    get_thumbnail_cache_path,
    download_file_from_url,
    get_local_version,
    extract_rfa_category,
    extract_rfa_version,
    format_file_size,
    extract_preview_png_bytes
)

doc   = revit.doc
uidoc = revit.uidoc


# ── UI Data Item Models ──────────────────────────────────────────────────────

class CategoryDisplayItem(System.Object):
    def __init__(self, display_name, raw_name, count=0):
        self.DisplayName = display_name
        self.RawName = raw_name
        self.Count = count


class VersionDisplayItem(System.Object):
    def __init__(self, display_name, raw_version):
        self.DisplayName = display_name
        self.RawVersion = raw_version

    def ToString(self):
        return self.DisplayName

    def __repr__(self):
        return self.DisplayName


class FamilyCardItem(System.Object):
    def __init__(self, raw_data, host_year=HOST_REVIT_YEAR):
        self.IsSelected = False
        self.CardBorderBrush = "#E2E8F0"
        self.CardBorderThickness = Thickness(1)
        self.CardBackground = "#FFFFFF"

        self.RawData = raw_data
        self.Name = raw_data.get("name", "Unknown Family")
        self.Category = raw_data.get("category", "Generic Models")
        self.HostYear = host_year

        # Priority: local version DB (from RFA binary detection) > cloud version
        # Cloud version can be wrong/stale — local detection is always authoritative
        cloud_ver = raw_data.get("revit_version") or ""
        local_ver = get_local_version(self.Name)
        if local_ver and local_ver not in ("Unknown", ""):
            self.RevitVersion = local_ver
        elif cloud_ver and cloud_ver not in ("Unknown", ""):
            self.RevitVersion = cloud_ver
        else:
            self.RevitVersion = local_ver or cloud_ver or "Unknown"

        self.FileSize = raw_data.get("file_size", "0 KB")
        self.Description = str(raw_data.get("description", "") or "").strip()
        if self.Description:
            self.DescriptionVisibility = Visibility.Visible
        else:
            self.DescriptionVisibility = Visibility.Collapsed

        # Category-Specific Placeholder Icon
        cat_lower = self.Category.lower()
        if any(k in cat_lower for k in ["electric", "light", "power", "panel", "conduit", "cable", "switch", "generator"]):
            self.CategoryIcon = u"⚡"
        elif any(k in cat_lower for k in ["air", "duct", "mech", "hvac", "vent", "fan", "terminal"]):
            self.CategoryIcon = u"💨"
        elif any(k in cat_lower for k in ["pipe", "plumb", "water", "drain", "pump", "valve", "fixture"]):
            self.CategoryIcon = u"🚰"
        elif any(k in cat_lower for k in ["fire", "sprinkler", "alarm", "protect"]):
            self.CategoryIcon = u"🔥"
        elif any(k in cat_lower for k in ["door", "window", "wall", "room", "arch"]):
            self.CategoryIcon = u"🚪"
        else:
            self.CategoryIcon = u"📦"

        self.DownloadUrl = raw_data.get("download_url", "")
        self.RfaFullPath = raw_data.get("rfa_path", "")

        # ── Smart Compatibility Shield Logic ─────────────────────────────────
        self.IsCompatible = True
        self.NumericVersion = None
        try:
            m = re.search(r"(20[12]\d)", str(self.RevitVersion))
            if m:
                self.NumericVersion = int(m.group(1))
                if self.HostYear and self.NumericVersion > self.HostYear:
                    self.IsCompatible = False
        except Exception:
            pass

        if self.IsCompatible:
            self.VersionBadgeBg = "#DCFCE7"  # Soft green
            self.VersionBadgeFg = "#15803D"  # Dark green
            self.VersionBadgeText = self.RevitVersion
            if self.HostYear:
                self.VersionToolTip = u"Compatible with your Revit {}".format(self.HostYear)
            else:
                self.VersionToolTip = u"Revit Family Version: {}".format(self.RevitVersion)
            
            # Action Button Style: Solid Royal Blue Primary
            self.ButtonBg = "#2563EB"
            self.ButtonBorder = "#1D4ED8"
            self.ButtonFg = "#FFFFFF"
            self.ButtonIcon = u"📥"
            self.ButtonText = u"Load into Project"
            self.LoadButtonToolTip = u"Load this family into the active project"
        else:
            self.VersionBadgeBg = "#FEE2E2"  # Soft red
            self.VersionBadgeFg = "#B91C1C"  # Dark red
            self.VersionBadgeText = u"⚠️ {}".format(self.RevitVersion)
            self.VersionToolTip = u"⚠️ Incompatible: Created in Revit {} (Your Revit is {})".format(
                self.NumericVersion, self.HostYear
            )
            
            # Action Button Style: Muted Disabled/Warning Gray
            self.ButtonBg = "#F1F5F9"
            self.ButtonBorder = "#CBD5E1"
            self.ButtonFg = "#64748B"
            self.ButtonIcon = u"⛔"
            self.ButtonText = u"Incompatible"
            self.LoadButtonToolTip = u"Cannot load Revit {} family into Revit {}.\nRevit does not support backwards compatibility.\nClick for more details.".format(
                self.NumericVersion, self.HostYear
            )

        # Store thumb_url for async download
        self._thumb_url = raw_data.get("thumb_url", "")
        self.ThumbnailImage = self._load_thumbnail(raw_data)
        if self.ThumbnailImage is not None:
            self.ThumbnailVisibility = Visibility.Visible
            self.PlaceholderVisibility = Visibility.Collapsed
        else:
            self.ThumbnailVisibility = Visibility.Collapsed
            self.PlaceholderVisibility = Visibility.Visible

    def set_selected(self, val):
        self.IsSelected = bool(val)
        if self.IsSelected:
            self.CardBorderBrush = "#2563EB"
            self.CardBorderThickness = Thickness(2)
            self.CardBackground = "#F0F7FF"
        else:
            self.CardBorderBrush = "#E2E8F0"
            self.CardBorderThickness = Thickness(1)
            self.CardBackground = "#FFFFFF"

    def _bytes_to_bitmapimage(self, raw_bytes):
        """Convert raw bytes to frozen WPF BitmapImage."""
        if not raw_bytes:
            return None
        try:
            if isinstance(raw_bytes, System.Array[System.Byte]):
                arr = raw_bytes
            else:
                arr = System.Array[System.Byte](bytearray(raw_bytes))
            ms = MemoryStream(arr)
            ms.Position = 0
            bmp = BitmapImage()
            bmp.BeginInit()
            bmp.CacheOption = BitmapCacheOption.OnLoad
            bmp.StreamSource = ms
            bmp.EndInit()
            bmp.Freeze()
            return bmp
        except Exception:
            return None

    def _load_thumbnail(self, raw_data):
        fam_name = raw_data.get("name", "")
        disk_thumb_path = get_thumbnail_cache_path(fam_name)

        # 1. Check Local Disk Cache first (instant, 0ms)
        if os.path.exists(disk_thumb_path) and os.path.getsize(disk_thumb_path) > 0:
            try:
                raw_bytes = File.ReadAllBytes(disk_thumb_path)
                bmp = self._bytes_to_bitmapimage(raw_bytes)
                if bmp:
                    return bmp
            except Exception:
                pass

        # 2. Base64 thumbnail from Cloud Webhook catalog JSON (no network needed)
        b64 = raw_data.get("thumb_base64")
        if b64 and len(b64) > 20:
            try:
                import base64 as _b64
                raw_bytes = _b64.b64decode(b64)
                bmp = self._bytes_to_bitmapimage(raw_bytes)
                if bmp:
                    try:
                        File.WriteAllBytes(disk_thumb_path, System.Array[System.Byte](bytearray(raw_bytes)))
                    except Exception:
                        pass
                    return bmp
            except Exception:
                pass

        # 3. Check if local RFA file exists to extract directly
        local_rfa_candidates = []
        rfa_p = raw_data.get("rfa_path", "")
        if rfa_p and os.path.exists(rfa_p):
            local_rfa_candidates.append(rfa_p)

        temp_rfa = os.path.join(tempfile.gettempdir(), "mepanana_families", fam_name + ".rfa")
        if os.path.exists(temp_rfa):
            local_rfa_candidates.append(temp_rfa)

        for loc_path in local_rfa_candidates:
            try:
                img_bytes = extract_preview_png_bytes(loc_path)
                if img_bytes:
                    bmp = self._bytes_to_bitmapimage(img_bytes)
                    if bmp:
                        try:
                            File.WriteAllBytes(disk_thumb_path, System.Array[System.Byte](bytearray(img_bytes)))
                        except Exception:
                            pass
                        return bmp
            except Exception:
                pass

        # 4. No thumbnail available now — will attempt async download from thumb_url or RFA later
        return None

    def try_load_from_disk(self):
        """Try to load thumbnail from disk cache (called after async download completes)."""
        disk_thumb_path = get_thumbnail_cache_path(self.Name)
        if os.path.exists(disk_thumb_path) and os.path.getsize(disk_thumb_path) > 0:
            try:
                raw_bytes = File.ReadAllBytes(disk_thumb_path)
                bmp = self._bytes_to_bitmapimage(raw_bytes)
                if bmp:
                    self.ThumbnailImage = bmp
                    self.ThumbnailVisibility = Visibility.Visible
                    self.PlaceholderVisibility = Visibility.Collapsed
                    return True
            except Exception:
                pass
        return False


# ── Main WPF Window ──────────────────────────────────────────────────────────

class FamilyCloudWindow(forms.WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        setup_window(self)

        self._is_updating = False
        self.all_families = []
        self.active_category = "ALL"

        # 1. Populate Upload Categories ComboBox
        if hasattr(self, 'cmbUploadCategory'):
            self.cmbUploadCategory.ItemsSource = STANDARD_CATEGORIES
            self.cmbUploadCategory.SelectedIndex = 0

        # 2. Wire Event Handlers
        if hasattr(self, 'rbTabBrowse'):
            self.rbTabBrowse.Checked += self.OnTabChanged
        if hasattr(self, 'rbTabUpload'):
            self.rbTabUpload.Checked += self.OnTabChanged

        if hasattr(self, 'btnRefresh'):
            self.btnRefresh.Click += self.OnRefreshClick
        if hasattr(self, 'txtSearch'):
            self.txtSearch.TextChanged += self.OnSearchChanged
        if hasattr(self, 'cmbVersionFilter'):
            self.cmbVersionFilter.SelectionChanged += self.OnVersionFilterChanged
        if hasattr(self, 'chkCompatibleOnly'):
            self.chkCompatibleOnly.Checked += self.OnCompatibilityFilterChanged
            self.chkCompatibleOnly.Unchecked += self.OnCompatibilityFilterChanged
        if hasattr(self, 'listCategories'):
            self.listCategories.SelectionChanged += self.OnCategorySelectionChanged

        # Multi-Selection Action Bar Handlers
        if hasattr(self, 'btnSelectAll'):
            self.btnSelectAll.Click += self.OnSelectAllClick
        if hasattr(self, 'btnBatchLoad'):
            self.btnBatchLoad.Click += self.OnBatchLoadClick
        if hasattr(self, 'btnBatchDelete'):
            self.btnBatchDelete.Click += self.OnBatchDeleteClick

        # Upload Tab Handlers
        if hasattr(self, 'btnBrowseRfa'):
            self.btnBrowseRfa.Click += self.OnBrowseRfaClick
        if hasattr(self, 'btnExecuteUpload'):
            self.btnExecuteUpload.Click += self.OnExecuteUploadClick

        # Wire Loaded event so the window appears on screen INSTANTLY (< 0.05s)
        self.Loaded += self.OnWindowLoaded
        
        # Instant initial render from local disk cache (< 0.01s)
        self.ReloadLibrary(force_online=False)

    def OnWindowLoaded(self, sender, args):
        """Fires once the window is physically visible on screen. Triggers live background cloud sync."""
        self.ReloadLibraryAsync(force_online=True)

    # ── Tab Navigation ────────────────────────────────────────────────────────

    def OnTabChanged(self, sender, args):
        if not hasattr(self, 'panelBrowse'): return

        is_browse = bool(self.rbTabBrowse.IsChecked)
        self.panelBrowse.Visibility = System.Windows.Visibility.Visible if is_browse else System.Windows.Visibility.Collapsed
        self.panelUpload.Visibility = System.Windows.Visibility.Visible if not is_browse else System.Windows.Visibility.Collapsed

        if is_browse:
            self.ReloadLibraryAsync(force_online=True)

    # ── Library Loading & Filtering ───────────────────────────────────────────

    def ReloadLibrary(self, force_online=False, rebuild_drive=False):
        """Synchronous catalog loader for instant local cache reading on startup."""
        webhook_url = get_webhook_url()
        catalog_data = load_catalog(force_online=force_online, rebuild_drive=rebuild_drive)

        self.all_families = []
        for raw in catalog_data.get("families", []):
            try:
                card = FamilyCardItem(raw)
                self.all_families.append(card)
            except Exception:
                pass

        self.PopulateCategoriesList()
        self.PopulateVersionFilter()
        self.ApplyFilter()

        if hasattr(self, 'txtCloudStatus') and hasattr(self, 'dotCloudStatus'):
            from System.Windows.Media import SolidColorBrush, Color
            if not webhook_url:
                self.txtCloudStatus.Text = u"Connect Cloud"
                self.txtCloudStatus.Foreground = SolidColorBrush(Color.FromRgb(217, 119, 6))
                self.dotCloudStatus.Fill = SolidColorBrush(Color.FromRgb(217, 119, 6))
            else:
                self.txtCloudStatus.Text = u"Cloud Online"
                self.txtCloudStatus.Foreground = SolidColorBrush(Color.FromRgb(21, 128, 61))
                self.dotCloudStatus.Fill = SolidColorBrush(Color.FromRgb(22, 163, 74))

    def ReloadLibraryAsync(self, force_online=True, rebuild_drive=False):
        """
        Asynchronous cloud catalog sync in background.
        UI remains 100% interactive and usable while ProgressBar is animating.
        """
        self._is_loading = True

        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = System.Windows.Visibility.Visible
            self.progressBar.IsIndeterminate = True

        if hasattr(self, 'btnRefresh'):
            self.btnRefresh.IsEnabled = False
            self.btnRefresh.Content = u"⏳ Syncing..."

        if hasattr(self, 'txtCloudStatus') and hasattr(self, 'dotCloudStatus'):
            from System.Windows.Media import SolidColorBrush, Color
            self.txtCloudStatus.Text = u"Syncing..."
            self.txtCloudStatus.Foreground = SolidColorBrush(Color.FromRgb(37, 99, 235))
            self.dotCloudStatus.Fill = SolidColorBrush(Color.FromRgb(37, 99, 235))

        if hasattr(self, 'panelPlaceholder') and len(self.all_families) == 0:
            self.panelPlaceholder.Visibility = System.Windows.Visibility.Visible
            if hasattr(self, 'txtPlaceholderIcon'): self.txtPlaceholderIcon.Text = u"☁️"
            if hasattr(self, 'txtPlaceholderText'): self.txtPlaceholderText.Text = u"Loading Cloud Families..."
            if hasattr(self, 'txtPlaceholderSub'):  self.txtPlaceholderSub.Text = u"Please wait while fetching library data..."

        dispatcher = self.Dispatcher
        webhook_url = get_webhook_url()

        def bg_worker(state):
            try:
                catalog_data = load_catalog(force_online=force_online, rebuild_drive=rebuild_drive)
                new_cards = []
                for raw in catalog_data.get("families", []):
                    try:
                        card = FamilyCardItem(raw)
                        new_cards.append(card)
                    except Exception:
                        pass

                def on_sync_done():
                    try:
                        self._is_loading = False
                        self.all_families = new_cards
                        self.PopulateCategoriesList()
                        self.PopulateVersionFilter()
                        self.ApplyFilter()

                        if hasattr(self, 'txtCloudStatus') and hasattr(self, 'dotCloudStatus'):
                            from System.Windows.Media import SolidColorBrush, Color
                            if not webhook_url:
                                self.txtCloudStatus.Text = u"Connect Cloud"
                                self.txtCloudStatus.Foreground = SolidColorBrush(Color.FromRgb(217, 119, 6))
                                self.dotCloudStatus.Fill = SolidColorBrush(Color.FromRgb(217, 119, 6))
                            else:
                                self.txtCloudStatus.Text = u"Cloud Online"
                                self.txtCloudStatus.Foreground = SolidColorBrush(Color.FromRgb(21, 128, 61))
                                self.dotCloudStatus.Fill = SolidColorBrush(Color.FromRgb(22, 163, 74))

                        # Start async downloading missing thumbnails
                        self._download_missing_thumbnails_async()
                    finally:
                        self._is_loading = False
                        if hasattr(self, 'progressBar'):
                            self.progressBar.IsIndeterminate = False
                            self.progressBar.Visibility = System.Windows.Visibility.Collapsed
                        if hasattr(self, 'btnRefresh'):
                            self.btnRefresh.IsEnabled = True
                            self.btnRefresh.Content = u"🔄 Refresh"

                if dispatcher:
                    dispatcher.Invoke(System.Action(on_sync_done))

            except Exception as ex:
                print("Background sync error: " + str(ex))
                def on_sync_error():
                    self._is_loading = False
                    self.ApplyFilter()
                    if hasattr(self, 'progressBar'):
                        self.progressBar.IsIndeterminate = False
                        self.progressBar.Visibility = System.Windows.Visibility.Collapsed
                    if hasattr(self, 'btnRefresh'):
                        self.btnRefresh.IsEnabled = True
                        self.btnRefresh.Content = u"🔄 Refresh"
                if dispatcher:
                    dispatcher.Invoke(System.Action(on_sync_error))

        from System.Threading import ThreadPool, WaitCallback
        ThreadPool.QueueUserWorkItem(WaitCallback(bg_worker))

    def PopulateCategoriesList(self):
        if not hasattr(self, 'listCategories'): return

        current_selected_raw = self.active_category
        self._is_updating = True
        try:
            cat_counts = {}
            for f in self.all_families:
                c = f.Category
                cat_counts[c] = cat_counts.get(c, 0) + 1

            items = [CategoryDisplayItem(u"All Categories", "ALL", len(self.all_families))]
            sel_index = 0
            for idx, cat_name in enumerate(sorted(cat_counts.keys())):
                items.append(CategoryDisplayItem(cat_name, cat_name, cat_counts[cat_name]))
                if cat_name == current_selected_raw:
                    sel_index = idx + 1

            self.listCategories.ItemsSource = items
            self.listCategories.SelectedIndex = sel_index
        finally:
            self._is_updating = False

    def PopulateVersionFilter(self):
        if not hasattr(self, 'cmbVersionFilter'): return

        self._is_updating = True
        try:
            ver_counts = {}
            for f in self.all_families:
                v = f.RevitVersion
                ver_counts[v] = ver_counts.get(v, 0) + 1

            items = [VersionDisplayItem(u"All Versions ({})".format(len(self.all_families)), "ALL")]
            for ver_name in sorted(ver_counts.keys(), reverse=True):
                items.append(VersionDisplayItem(u"Revit {} ({})".format(ver_name, ver_counts[ver_name]), ver_name))

            self.cmbVersionFilter.ItemsSource = items
            self.cmbVersionFilter.SelectedIndex = 0
        finally:
            self._is_updating = False

    def OnCategorySelectionChanged(self, sender, args):
        if self._is_updating: return
        if hasattr(self, 'listCategories') and self.listCategories.SelectedItem:
            selected_item = self.listCategories.SelectedItem
            self.active_category = getattr(selected_item, "RawName", "ALL")
            self.ApplyFilter()

    def OnSearchChanged(self, sender, args):
        if self._is_updating: return
        self.ApplyFilter()

    def OnVersionFilterChanged(self, sender, args):
        if self._is_updating: return
        self.ApplyFilter()

    def OnCompatibilityFilterChanged(self, sender, args):
        if self._is_updating: return
        self.ApplyFilter()

    def ApplyFilter(self):
        query = self.txtSearch.Text.strip().lower() if hasattr(self, 'txtSearch') else ""
        sel_cat = self.active_category
        if hasattr(self, 'listCategories') and self.listCategories.SelectedItem:
            sel_cat = getattr(self.listCategories.SelectedItem, "RawName", self.active_category)

        sel_ver = "ALL"
        if hasattr(self, 'cmbVersionFilter') and self.cmbVersionFilter.SelectedItem:
            sel_ver = getattr(self.cmbVersionFilter.SelectedItem, "RawVersion", "ALL")

        compat_only = bool(self.chkCompatibleOnly.IsChecked) if hasattr(self, 'chkCompatibleOnly') else False

        filtered = []
        for f in self.all_families:
            if compat_only and not getattr(f, 'IsCompatible', True):
                continue
            if sel_cat != "ALL" and f.Category != sel_cat:
                continue
            if sel_ver != "ALL" and f.RevitVersion != sel_ver:
                continue
            if query and query not in f.Name.lower() and query not in f.Category.lower():
                continue
            filtered.append(f)

        if hasattr(self, 'itemsFamilyCards'):
            self.itemsFamilyCards.ItemsSource = filtered

        # ── Placeholder & Status Messages ──────────────────────────────────
        is_loading = getattr(self, '_is_loading', False)

        if hasattr(self, 'panelPlaceholder'):
            if len(filtered) == 0:
                self.panelPlaceholder.Visibility = System.Windows.Visibility.Visible

                if is_loading:
                    if hasattr(self, 'txtPlaceholderIcon'): self.txtPlaceholderIcon.Text = u"☁️"
                    if hasattr(self, 'txtPlaceholderText'): self.txtPlaceholderText.Text = u"Syncing Cloud Families..."
                    if hasattr(self, 'txtPlaceholderSub'):  self.txtPlaceholderSub.Text = u"Connecting to cloud storage and fetching latest library..."
                elif len(self.all_families) == 0:
                    if hasattr(self, 'txtPlaceholderIcon'): self.txtPlaceholderIcon.Text = u"📦"
                    if hasattr(self, 'txtPlaceholderText'): self.txtPlaceholderText.Text = u"No Families in Cloud Library"
                    if hasattr(self, 'txtPlaceholderSub'):  self.txtPlaceholderSub.Text = u"Your cloud library is empty. Switch to 'Upload Family' tab to add your first family!"
                else:
                    if hasattr(self, 'txtPlaceholderIcon'): self.txtPlaceholderIcon.Text = u"🔍"
                    if hasattr(self, 'txtPlaceholderText'): self.txtPlaceholderText.Text = u"No Matching Families"
                    if hasattr(self, 'txtPlaceholderSub'):  self.txtPlaceholderSub.Text = u"No families match your search query or category filter. Try clearing your search."
            else:
                self.panelPlaceholder.Visibility = System.Windows.Visibility.Collapsed

        if hasattr(self, 'txtLibraryStatus'):
            if is_loading and len(filtered) == 0:
                self.txtLibraryStatus.Text = u"⚡ Syncing Cloud Families..."
            else:
                self.txtLibraryStatus.Text = u"{} Families Found".format(len(filtered))

        self.UpdateSelectionState()

    # ── Multi-Selection & Batch Actions ────────────────────────────────────────

    def OnCardCheckClick(self, sender, args):
        """Fires when user clicks the CheckBox on a family card directly."""
        card = getattr(sender, "DataContext", None)
        if card and isinstance(card, FamilyCardItem):
            card.set_selected(not card.IsSelected)
            self.UpdateSelectionState()
            if hasattr(self, 'itemsFamilyCards') and self.itemsFamilyCards:
                self.itemsFamilyCards.Items.Refresh()

    def OnCardPreviewMouseDown(self, sender, args):
        """
        Fires when a family card is clicked.
        If Ctrl key is held down, toggles card selection.
        """
        if Keyboard.IsKeyDown(Key.LeftCtrl) or Keyboard.IsKeyDown(Key.RightCtrl):
            card = getattr(sender, "DataContext", None)
            if card and isinstance(card, FamilyCardItem):
                card.set_selected(not card.IsSelected)
                self.UpdateSelectionState()
                if hasattr(self, 'itemsFamilyCards') and self.itemsFamilyCards:
                    self.itemsFamilyCards.Items.Refresh()
                args.Handled = True

    def UpdateSelectionState(self):
        """Updates toolbar selection counter and enable states for batch buttons."""
        selected = [c for c in self.all_families if getattr(c, "IsSelected", False)]
        sel_cnt = len(selected)

        if hasattr(self, 'btnBatchLoad'):
            self.btnBatchLoad.IsEnabled = (sel_cnt > 0)
            self.btnBatchLoad.Content = u"📥 Load Selected ({})".format(sel_cnt)

        if hasattr(self, 'btnBatchDelete'):
            self.btnBatchDelete.IsEnabled = (sel_cnt > 0)
            self.btnBatchDelete.Content = u"🗑️ Delete Selected ({})".format(sel_cnt)

        if hasattr(self, 'txtSelectionCount'):
            if sel_cnt > 0:
                self.txtSelectionCount.Text = u"✨ Selected {} families ready for batch action".format(sel_cnt)
            else:
                self.txtSelectionCount.Text = u"💡 Hold Ctrl + Click to select multiple families"

        if hasattr(self, 'btnSelectAll'):
            filtered = list(self.itemsFamilyCards.ItemsSource) if hasattr(self, 'itemsFamilyCards') and self.itemsFamilyCards and self.itemsFamilyCards.ItemsSource else []
            if filtered and len(filtered) > 0 and all(getattr(c, "IsSelected", False) for c in filtered):
                self.btnSelectAll.Content = u"✖️ Clear Selection"
            else:
                self.btnSelectAll.Content = u"☑️ Select All"

    def OnSelectAllClick(self, sender, args):
        """Selects all visible cards or clears selection."""
        filtered = list(self.itemsFamilyCards.ItemsSource) if hasattr(self, 'itemsFamilyCards') and self.itemsFamilyCards and self.itemsFamilyCards.ItemsSource else []
        if not filtered:
            return

        all_selected = all(getattr(c, "IsSelected", False) for c in filtered)
        target_val = not all_selected
        for card in filtered:
            card.set_selected(target_val)

        self.UpdateSelectionState()
        if hasattr(self, 'itemsFamilyCards') and self.itemsFamilyCards:
            self.itemsFamilyCards.Items.Refresh()

    def OnBatchLoadClick(self, sender, args):
        """Loads all selected compatible families into the active Revit project."""
        selected = [c for c in self.all_families if getattr(c, "IsSelected", False)]
        if not selected:
            return

        incompatible = [c for c in selected if not getattr(c, "IsCompatible", True) and getattr(c, "NumericVersion", None)]
        to_load = [c for c in selected if getattr(c, "IsCompatible", True)]

        if incompatible:
            msg = u"{} of the {} selected families are created in a newer Revit version (Revit {}) and cannot be loaded into your Revit {}.\n\nDo you want to proceed loading the {} compatible families?".format(
                len(incompatible), len(selected), incompatible[0].NumericVersion, HOST_REVIT_YEAR, len(to_load)
            )
            if not show_confirm(msg, title="Compatibility Shield"):
                return

        if not to_load:
            show_warning(u"None of the selected families are compatible with your current Revit version.", title="Batch Load Notice")
            return

        # Setup Progress Bar
        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = Visibility.Visible
            self.progressBar.Minimum = 0
            self.progressBar.Maximum = len(to_load)
            self.progressBar.Value = 0
            self.progressBar.IsIndeterminate = False

        if hasattr(self, 'btnBatchLoad'):
            self.btnBatchLoad.IsEnabled = False

        loaded_count = 0
        failed_count = 0

        try:
            for idx, item in enumerate(to_load):
                if hasattr(self, 'progressBar'):
                    self.progressBar.Value = idx
                if hasattr(self, 'txtLibraryStatus'):
                    self.txtLibraryStatus.Text = u"⚡ Loading ({}/{}): {}...".format(idx + 1, len(to_load), item.Name)
                do_events()

                target = getattr(item, "DownloadUrl", "") or getattr(item, "RfaFullPath", "")
                if target:
                    try:
                        success, msg = load_family_to_revit(doc, target, family_name=item.Name)
                        if success:
                            loaded_count += 1
                        else:
                            failed_count += 1
                    except Exception:
                        failed_count += 1

            if hasattr(self, 'progressBar'):
                self.progressBar.Value = len(to_load)
            do_events()

            if loaded_count > 0:
                show_success(u"Successfully loaded {} families into your project.".format(loaded_count), title="Batch Load Complete")
            if failed_count > 0:
                show_warning(u"Failed to load {} families.".format(failed_count), title="Batch Load Warning")
        finally:
            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = Visibility.Collapsed
            self.UpdateSelectionState()
            self.ApplyFilter()

    def OnBatchDeleteClick(self, sender, args):
        """Deletes all selected families from Cloud Library with confirmation."""
        selected = [c for c in self.all_families if getattr(c, "IsSelected", False)]
        if not selected:
            return

        if not show_confirm(u"Are you sure you want to permanently delete {} selected families from the Cloud Library?\n\nThis will remove the files from Cloud storage.".format(len(selected)), title="Confirm Batch Delete"):
            return

        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = Visibility.Visible
            self.progressBar.Minimum = 0
            self.progressBar.Maximum = len(selected)
            self.progressBar.Value = 0
            self.progressBar.IsIndeterminate = False

        if hasattr(self, 'btnBatchDelete'):
            self.btnBatchDelete.IsEnabled = False

        del_count = 0
        try:
            for idx, item in enumerate(selected):
                if hasattr(self, 'progressBar'):
                    self.progressBar.Value = idx
                if hasattr(self, 'txtLibraryStatus'):
                    self.txtLibraryStatus.Text = u"🗑️ Deleting ({}/{}): {}...".format(idx + 1, len(selected), item.Name)
                do_events()

                try:
                    success, msg = delete_family_from_cloud(item.Name, item.Category)
                    if success:
                        del_count += 1
                        thumb_path = get_thumbnail_cache_path(item.Name)
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)
                except Exception:
                    pass

            if hasattr(self, 'progressBar'):
                self.progressBar.Value = len(selected)
            do_events()

            show_success(u"Successfully deleted {} families from Cloud Library.".format(del_count), title="Batch Delete Complete")
        finally:
            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = Visibility.Collapsed
            self.ReloadLibraryAsync(force_online=True, rebuild_drive=True)

    def _download_missing_thumbnails_async(self):
        """
        Background download & extraction of thumbnails for cards that don't have one yet.
        Uses ThreadPool to avoid blocking UI thread.
        """
        cards_to_download = [
            c for c in self.all_families
            if c.ThumbnailImage is None
        ]
        if not cards_to_download:
            return

        dispatcher = self.Dispatcher

        def bg_download(state):
            any_loaded = False
            for card in cards_to_download:
                try:
                    dest = get_thumbnail_cache_path(card.Name)

                    # Option 1: Direct thumb_url
                    if card._thumb_url and card._thumb_url.startswith("http"):
                        if download_file_from_url(card._thumb_url, dest) and card.try_load_from_disk():
                            any_loaded = True
                            continue

                    # Option 2: Download RFA to temp and extract OLE preview
                    dl_url = card.DownloadUrl or card.RfaFullPath
                    if dl_url and dl_url.startswith("http"):
                        temp_rfa = os.path.join(tempfile.gettempdir(), "mepanana_families", card.Name + ".rfa")
                        if not os.path.exists(temp_rfa):
                            download_file_from_url(dl_url, temp_rfa)
                        if os.path.exists(temp_rfa):
                            img_bytes = extract_preview_png_bytes(temp_rfa)
                            if img_bytes:
                                File.WriteAllBytes(dest, System.Array[System.Byte](bytearray(img_bytes)))
                                if card.try_load_from_disk():
                                    any_loaded = True
                                    continue
                except Exception:
                    pass

            if any_loaded and dispatcher:
                def on_ui():
                    try:
                        if hasattr(self, 'itemsFamilyCards') and self.itemsFamilyCards:
                            self.itemsFamilyCards.Items.Refresh()
                    except Exception:
                        pass
                try:
                    dispatcher.Invoke(System.Action(on_ui))
                except Exception:
                    pass

        try:
            from System.Threading import ThreadPool, WaitCallback
            ThreadPool.QueueUserWorkItem(WaitCallback(bg_download))
        except Exception:
            pass

    def OnRefreshClick(self, sender, args):
        self.ReloadLibraryAsync(force_online=True, rebuild_drive=True)

    # ── Load Family Action ────────────────────────────────────────────────────

    def OnLoadFamilyClick(self, sender, args):
        try:
            item = sender.CommandParameter or sender.DataContext
            if not item:
                show_warning(u"Could not identify the selected family file.", title="Load Notice")
                return

            # Pre-Flight Smart Compatibility Shield Check
            if not getattr(item, 'IsCompatible', True) and getattr(item, 'HostYear', None) and getattr(item, 'NumericVersion', None):
                show_warning(
                    u"⛔ Incompatible Revit Version!\n\n"
                    u"• Family: {} (Revit {})\n"
                    u"• Your Current Revit: Revit {}\n\n"
                    u"Autodesk Revit does not support loading families saved in a newer version into an older version.\n\n"
                    u"💡 Solution: Please open your project in Revit {} or newer, or ask the author to export/save for Revit {}.".format(
                        item.Name, item.NumericVersion, item.HostYear, item.NumericVersion, item.HostYear
                    ),
                    title="Compatibility Shield Blocked"
                )
                return

            target = getattr(item, "DownloadUrl", "") or getattr(item, "RfaFullPath", "")
            if not target:
                show_warning(u"File target path or download URL is missing.", title="Load Error")
                return

            success, msg = load_family_to_revit(doc, target, family_name=item.Name)
            if success:
                show_success(msg, title="Family Loaded")
            else:
                show_error(msg, title="Load Error")
        except Exception as ex:
            show_error(u"Unexpected error loading family:\n{}".format(str(ex)), title="Load Error")

    def OnDeleteFamilyClick(self, sender, args):
        try:
            item = sender.CommandParameter or sender.DataContext
            if not item:
                return

            if show_confirm(u"Are you sure you want to permanently delete '{}' from the Cloud Library?".format(item.Name), title="Delete Family"):
                success, msg = delete_family_from_cloud(item.Name, item.Category)
                if success:
                    # Also clear local thumbnail cache for this family
                    try:
                        thumb_path = get_thumbnail_cache_path(item.Name)
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)
                    except Exception:
                        pass
                    show_success(msg, title="Family Deleted")
                    self.ReloadLibrary(force_online=True)
                else:
                    show_error(msg, title="Delete Error")
        except Exception as ex:
            show_error(u"Unexpected error deleting family:\n{}".format(str(ex)), title="Delete Error")

    # ── Upload Workflow with Automatic Category Detection ─────────────────────

    def OnBrowseRfaClick(self, sender, args):
        dlg = OpenFileDialog()
        dlg.Filter = "Revit Family Files (*.rfa)|*.rfa|All Files (*.*)|*.*"
        dlg.Title = "Select Revit Family (.rfa) to Upload"
        if dlg.ShowDialog() == DialogResult.OK:
            selected_path = dlg.FileName
            self.txtUploadFilePath.Text = selected_path

            # 1. Automatic Exact Category Detection via Revit API / compound inspection
            detected_category = extract_rfa_category(selected_path)
            detected_version = extract_rfa_version(selected_path)
            file_size_bytes = os.path.getsize(selected_path) if os.path.exists(selected_path) else 0
            file_size_str = format_file_size(file_size_bytes)

            # 2. Select in ComboBox
            matched = False
            for i, cat in enumerate(STANDARD_CATEGORIES):
                if cat.lower() == detected_category.lower():
                    self.cmbUploadCategory.SelectedIndex = i
                    matched = True
                    break

            if not matched:
                new_cats = list(self.cmbUploadCategory.ItemsSource)
                new_cats.insert(0, detected_category)
                self.cmbUploadCategory.ItemsSource = new_cats
                self.cmbUploadCategory.SelectedIndex = 0

            # 3. Show Live Detection Pill
            if hasattr(self, 'borderDetectInfo') and hasattr(self, 'txtDetectInfo'):
                self.txtDetectInfo.Text = u"⚡ Auto-detected: Category: {} | Revit {} | {}".format(
                    detected_category, detected_version, file_size_str
                )
                self.borderDetectInfo.Visibility = System.Windows.Visibility.Visible

    def OnExecuteUploadClick(self, sender, args):
        if not is_cloud_connected():
            show_warning(
                u"Please connect your Cloud Webhook first!\n\n"
                u"Click the 'Connect Cloud' button at the top right to paste your Google Apps Script Webhook URL.",
                title="Webhook Required"
            )
            return

        src_path = self.txtUploadFilePath.Text.strip() if hasattr(self, 'txtUploadFilePath') else ""
        if not src_path or not os.path.exists(src_path):
            show_warning(u"Please select a valid .rfa file to upload!", title="File Required")
            return

        cat = str(self.cmbUploadCategory.SelectedItem) if hasattr(self, 'cmbUploadCategory') and self.cmbUploadCategory.SelectedItem else "Generic Models"
        desc = self.txtUploadDescription.Text.strip() if hasattr(self, 'txtUploadDescription') else ""

        # Visual feedback during upload
        orig_content = self.btnExecuteUpload.Content if hasattr(self, 'btnExecuteUpload') else "Upload"
        if hasattr(self, 'btnExecuteUpload'):
            self.btnExecuteUpload.IsEnabled = False
            self.btnExecuteUpload.Content = u"Uploading to Cloud..."

        def bg_upload(state):
            try:
                success, msg = upload_family_file(src_path, cat, desc)
                def on_done():
                    if hasattr(self, 'btnExecuteUpload'):
                        self.btnExecuteUpload.IsEnabled = True
                        self.btnExecuteUpload.Content = orig_content
                    if success:
                        show_success(msg, "Upload Complete")
                        if hasattr(self, 'txtUploadFilePath'): self.txtUploadFilePath.Text = ""
                        if hasattr(self, 'txtUploadDescription'): self.txtUploadDescription.Text = ""
                        if hasattr(self, 'borderDetectInfo'):
                            self.borderDetectInfo.Visibility = System.Windows.Visibility.Collapsed
                        if hasattr(self, 'rbTabBrowse'):
                            self.rbTabBrowse.IsChecked = True
                        self.ReloadLibrary(force_online=True)
                    else:
                        show_error(msg, "Upload Failed")
                if self.Dispatcher:
                    self.Dispatcher.Invoke(System.Action(on_done))
            except Exception as ex:
                def on_fail():
                    if hasattr(self, 'btnExecuteUpload'):
                        self.btnExecuteUpload.IsEnabled = True
                        self.btnExecuteUpload.Content = orig_content
                    show_error(str(ex), "Upload Error")
                if self.Dispatcher:
                    self.Dispatcher.Invoke(System.Action(on_fail))

        from System.Threading import ThreadPool, WaitCallback
        ThreadPool.QueueUserWorkItem(WaitCallback(bg_upload))


# ── Launch Entry ──────────────────────────────────────────────────────────────

def run():
    win = FamilyCloudWindow()
    win.ShowDialog()

run()