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

import clr
clr.AddReference("System")
clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
import System
from System import Uri, UriKind
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

from py.core import safe_unicode
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
        self.RawData = raw_data
        self.Name = raw_data.get("name", "Unknown Family")
        self.Category = raw_data.get("category", "Generic Models")
        self.HostYear = host_year
        self.IsSelected = False

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
        self.Description = raw_data.get("description", "")
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

    def _bytes_to_bitmapimage(self, raw_bytes):
        """Convert raw bytes to frozen WPF BitmapImage."""
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

    def _load_thumbnail(self, raw_data):
        fam_name = raw_data.get("name", "")
        disk_thumb_path = get_thumbnail_cache_path(fam_name)

        # 1. Check Local Disk Cache first (instant, no network)
        if os.path.exists(disk_thumb_path) and os.path.getsize(disk_thumb_path) > 0:
            try:
                raw_bytes = File.ReadAllBytes(disk_thumb_path)
                bmp = self._bytes_to_bitmapimage(bytes(bytearray(raw_bytes)))
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
                    # Persist to disk cache for next time
                    try:
                        File.WriteAllBytes(disk_thumb_path, System.Array[System.Byte](bytearray(raw_bytes)))
                    except Exception:
                        pass
                    return bmp
            except Exception:
                pass

        # 3. No thumbnail available now — will attempt async download from thumb_url later
        return None

    def try_load_from_disk(self):
        """Try to load thumbnail from disk cache (called after async download completes)."""
        disk_thumb_path = get_thumbnail_cache_path(self.Name)
        if os.path.exists(disk_thumb_path) and os.path.getsize(disk_thumb_path) > 0:
            try:
                raw_bytes = File.ReadAllBytes(disk_thumb_path)
                bmp = self._bytes_to_bitmapimage(bytes(bytearray(raw_bytes)))
                if bmp:
                    self.ThumbnailImage = bmp
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
        if hasattr(self, 'chkSelectAll'):
            self.chkSelectAll.Click += self.OnSelectAllClick
        if hasattr(self, 'btnBatchLoad'):
            self.btnBatchLoad.Click += self.OnBatchLoadClick
        if hasattr(self, 'btnBatchDelete'):
            self.btnBatchDelete.Click += self.OnBatchDeleteClick

        # Upload Tab Handlers
        if hasattr(self, 'btnBrowseRfa'):
            self.btnBrowseRfa.Click += self.OnBrowseRfaClick
        if hasattr(self, 'btnExecuteUpload'):
            self.btnExecuteUpload.Click += self.OnExecuteUploadClick

        # 3. Always fetch fresh catalog from webhook on startup (reads from RAM cache, ~0.1s)
        self.ReloadLibrary(force_online=True)

    # ── Tab Navigation ────────────────────────────────────────────────────────

    def OnTabChanged(self, sender, args):
        if not hasattr(self, 'panelBrowse'): return

        is_browse = bool(self.rbTabBrowse.IsChecked)
        self.panelBrowse.Visibility = System.Windows.Visibility.Visible if is_browse else System.Windows.Visibility.Collapsed
        self.panelUpload.Visibility = System.Windows.Visibility.Visible if not is_browse else System.Windows.Visibility.Collapsed

        if is_browse:
            self.ReloadLibrary(force_online=True)

    # ── Library Loading & Filtering ───────────────────────────────────────────

    def _set_cloud_status(self, state):
        """Updates the top-right status badge (Syncing / Online / Connect Cloud)."""
        if not hasattr(self, 'txtCloudStatus') or not hasattr(self, 'dotCloudStatus'):
            return

        from System.Windows.Media import SolidColorBrush, Color
        if state == "syncing":
            self.txtCloudStatus.Text = u"Syncing..."
            self.txtCloudStatus.Foreground = SolidColorBrush(Color.FromRgb(37, 99, 235))
            self.dotCloudStatus.Fill = SolidColorBrush(Color.FromRgb(37, 99, 235))
            if hasattr(self, 'borderCloudStatus'):
                self.borderCloudStatus.Background = SolidColorBrush(Color.FromRgb(239, 246, 255))
                self.borderCloudStatus.BorderBrush = SolidColorBrush(Color.FromRgb(191, 219, 254))
        elif state == "online":
            self.txtCloudStatus.Text = u"Cloud Online"
            self.txtCloudStatus.Foreground = SolidColorBrush(Color.FromRgb(21, 128, 61))
            self.dotCloudStatus.Fill = SolidColorBrush(Color.FromRgb(22, 163, 74))
            if hasattr(self, 'borderCloudStatus'):
                self.borderCloudStatus.Background = SolidColorBrush(Color.FromRgb(240, 253, 244))
                self.borderCloudStatus.BorderBrush = SolidColorBrush(Color.FromRgb(187, 247, 208))
        else: # offline / connect
            self.txtCloudStatus.Text = u"Connect Cloud"
            self.txtCloudStatus.Foreground = SolidColorBrush(Color.FromRgb(180, 83, 9))
            self.dotCloudStatus.Fill = SolidColorBrush(Color.FromRgb(217, 119, 6))
            if hasattr(self, 'borderCloudStatus'):
                self.borderCloudStatus.Background = SolidColorBrush(Color.FromRgb(255, 251, 235))
                self.borderCloudStatus.BorderBrush = SolidColorBrush(Color.FromRgb(253, 230, 138))

    def OnEmptyUploadClick(self, sender, args):
        """Switches to the Upload Family tab from the empty state button."""
        if hasattr(self, 'rbTabUpload'):
            self.rbTabUpload.IsChecked = True

    def ReloadLibrary(self, force_online=False, rebuild_drive=False):
        webhook_url = get_webhook_url()
        if not webhook_url:
            self._set_cloud_status("connect")
        else:
            self._set_cloud_status("syncing")

        # Show Syncing state
        if hasattr(self, 'scrollCards'):
            self.scrollCards.Visibility = System.Windows.Visibility.Collapsed
        if hasattr(self, 'panelEmptyState'):
            self.panelEmptyState.Visibility = System.Windows.Visibility.Collapsed
        if hasattr(self, 'panelSyncingState'):
            self.panelSyncingState.Visibility = System.Windows.Visibility.Visible
        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = System.Windows.Visibility.Visible
            self.progressBar.IsIndeterminate = True
        if hasattr(self, 'txtStatus'):
            self.txtStatus.Text = u"Syncing with Cloud Library..."
        do_events()

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

        if webhook_url:
            self._set_cloud_status("online")
        else:
            self._set_cloud_status("connect")

        # Async download missing thumbnails in background (non-blocking)
        self._download_missing_thumbnails_async()

    def PopulateCategoriesList(self):
        if not hasattr(self, 'listCategories'): return

        self._is_updating = True
        try:
            cat_counts = {}
            for f in self.all_families:
                c = f.Category
                cat_counts[c] = cat_counts.get(c, 0) + 1

            items = [CategoryDisplayItem(u"All Categories", "ALL", len(self.all_families))]
            for cat_name in sorted(cat_counts.keys()):
                items.append(CategoryDisplayItem(cat_name, cat_name, cat_counts[cat_name]))

            self.listCategories.ItemsSource = items
            self.listCategories.SelectedIndex = 0
            self.active_category = "ALL"
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

        if hasattr(self, 'txtLibraryStatus'):
            self.txtLibraryStatus.Text = u"{} Families Found".format(len(filtered))

        # Switch between Cards Grid, Empty State, and Syncing State
        if hasattr(self, 'panelSyncingState'):
            self.panelSyncingState.Visibility = System.Windows.Visibility.Collapsed
        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = System.Windows.Visibility.Collapsed
            self.progressBar.IsIndeterminate = False

        if len(filtered) == 0:
            if hasattr(self, 'scrollCards'):
                self.scrollCards.Visibility = System.Windows.Visibility.Collapsed
            if hasattr(self, 'panelEmptyState'):
                self.panelEmptyState.Visibility = System.Windows.Visibility.Visible

            if len(self.all_families) == 0:
                if hasattr(self, 'txtEmptyTitle'):
                    self.txtEmptyTitle.Text = u"Cloud Library is Empty"
                if hasattr(self, 'txtEmptySubtitle'):
                    self.txtEmptySubtitle.Text = u"No Revit families uploaded yet. Upload your first .rfa family to get started!"
                if hasattr(self, 'btnEmptyUpload'):
                    self.btnEmptyUpload.Visibility = System.Windows.Visibility.Visible
            else:
                if hasattr(self, 'txtEmptyTitle'):
                    self.txtEmptyTitle.Text = u"No Matching Families Found"
                if hasattr(self, 'txtEmptySubtitle'):
                    self.txtEmptySubtitle.Text = u"Try clearing your search query or selecting a different category/version filter."
                if hasattr(self, 'btnEmptyUpload'):
                    self.btnEmptyUpload.Visibility = System.Windows.Visibility.Collapsed

            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"Cloud library is empty." if len(self.all_families) == 0 else u"No families matched your filter."
        else:
            if hasattr(self, 'scrollCards'):
                self.scrollCards.Visibility = System.Windows.Visibility.Visible
            if hasattr(self, 'panelEmptyState'):
                self.panelEmptyState.Visibility = System.Windows.Visibility.Collapsed
            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"Ready"

        self._update_batch_buttons()

    def OnCardCheckboxClick(self, sender, args):
        """Called when a checkbox on any family card is clicked."""
        self._update_batch_buttons()

    def OnSelectAllClick(self, sender, args):
        """Selects or deselects all currently filtered/visible family cards."""
        is_checked = bool(self.chkSelectAll.IsChecked) if hasattr(self, 'chkSelectAll') else False
        filtered = self._get_current_filtered_families()
        for f in filtered:
            f.IsSelected = is_checked

        # Refresh UI bindings so card checkboxes reflect state
        if hasattr(self, 'itemsFamilyCards'):
            self.itemsFamilyCards.Items.Refresh()

        self._update_batch_buttons()

    def _get_current_filtered_families(self):
        """Returns the list of families matching current search and category filters."""
        if hasattr(self, 'itemsFamilyCards') and self.itemsFamilyCards.ItemsSource:
            return list(self.itemsFamilyCards.ItemsSource)
        return []

    def _update_batch_buttons(self):
        """Updates the Batch Load & Batch Delete button texts, states, and counts."""
        selected = [f for f in self.all_families if getattr(f, 'IsSelected', False)]
        sel_count = len(selected)

        if hasattr(self, 'txtBatchLoadCount'):
            self.txtBatchLoadCount.Text = u"Load ({})".format(sel_count) if sel_count > 0 else u"Load (0)"
        elif hasattr(self, 'btnBatchLoad'):
            self.btnBatchLoad.Content = u"📥 Load ({})".format(sel_count)

        if hasattr(self, 'btnBatchLoad'):
            self.btnBatchLoad.IsEnabled = (sel_count > 0)

        if hasattr(self, 'txtBatchDeleteCount'):
            self.txtBatchDeleteCount.Text = u"Delete ({})".format(sel_count) if sel_count > 0 else u"Delete"
        elif hasattr(self, 'btnBatchDelete'):
            self.btnBatchDelete.Content = u"🗑️ Delete ({})".format(sel_count) if sel_count > 0 else u"🗑️ Delete"

        if hasattr(self, 'btnBatchDelete'):
            self.btnBatchDelete.IsEnabled = (sel_count > 0)

        # Update Select All checkbox state
        if hasattr(self, 'chkSelectAll'):
            filtered = self._get_current_filtered_families()
            if filtered and len(filtered) > 0 and all(getattr(f, 'IsSelected', False) for f in filtered):
                self.chkSelectAll.IsChecked = True
            else:
                self.chkSelectAll.IsChecked = False

    def OnBatchLoadClick(self, sender, args):
        """Batch loads all selected compatible families into active Revit project."""
        selected = [f for f in self.all_families if getattr(f, 'IsSelected', False)]
        if not selected:
            show_warning(u"Please select at least 1 family to load!", title="No Family Selected")
            return

        # Pre-Flight Smart Compatibility Check for selected families
        incompatibles = [
            f for f in selected
            if not getattr(f, 'IsCompatible', True) and getattr(f, 'HostYear', None) and getattr(f, 'NumericVersion', None)
        ]
        if incompatibles:
            incompat_names = u"\n• ".join([u"{} (Revit {})".format(f.Name, f.NumericVersion) for f in incompatibles[:4]])
            if len(incompatibles) > 4:
                incompat_names += u"\n... and {} more families".format(len(incompatibles) - 4)

            confirm_msg = u"⚠️ Detected {} incompatible family file(s) with your current Revit (Revit {}):\n\n• {}\n\nThese incompatible families will be skipped. Do you want to continue loading the remaining {} compatible family file(s)?".format(
                len(incompatibles), HOST_REVIT_YEAR, incompat_names, len(selected) - len(incompatibles)
            )
            if not show_confirm(confirm_msg, title="Revit Version Compatibility Warning"):
                return

        compatibles = [f for f in selected if getattr(f, 'IsCompatible', True)]
        if not compatibles:
            show_warning(u"None of the selected families are compatible with your current Revit version.", title="Cannot Load Families")
            return

        # 4-Step Lifecycle per GEMINI.md ProgressBar standard
        if hasattr(self, 'btnBatchLoad'): self.btnBatchLoad.IsEnabled = False
        if hasattr(self, 'btnBatchDelete'): self.btnBatchDelete.IsEnabled = False
        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = System.Windows.Visibility.Visible
            self.progressBar.Value = 0

        total = len(compatibles)
        success_count = 0
        failed_items = []

        try:
            for idx, item in enumerate(compatibles):
                pct = int((float(idx) / total) * 100.0)
                if hasattr(self, 'progressBar'): self.progressBar.Value = pct
                if hasattr(self, 'txtStatus'):
                    self.txtStatus.Text = u"Loading ({}/{}): {}...".format(idx + 1, total, item.Name)
                do_events()

                target = getattr(item, "DownloadUrl", "") or getattr(item, "RfaFullPath", "")
                if not target:
                    failed_items.append(u"{}: Target file path missing".format(item.Name))
                    continue

                success, msg = load_family_to_revit(doc, target, family_name=item.Name)
                if success:
                    success_count += 1
                else:
                    failed_items.append(u"{}: {}".format(item.Name, msg))

                pct_done = int((float(idx + 1) / total) * 100.0)
                if hasattr(self, 'progressBar'): self.progressBar.Value = pct_done
                do_events()

            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"Finished loading {}/{} families into project.".format(success_count, total)

            summary = u"🎉 Successfully loaded {}/{} families into active Revit project!".format(success_count, total)
            if failed_items:
                summary += u"\n\n⚠️ Failed to load {} family file(s):\n• ".format(len(failed_items)) + u"\n• ".join(failed_items[:3])

            show_success(summary, title="Batch Load Complete")

        except Exception as ex:
            show_error(u"Unexpected error during batch load:\n{}".format(safe_unicode(ex)), title="Batch Load Error")
        finally:
            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = System.Windows.Visibility.Collapsed
            self._update_batch_buttons()

    def OnBatchDeleteClick(self, sender, args):
        """Batch deletes all selected families from Cloud Library."""
        selected = [f for f in self.all_families if getattr(f, 'IsSelected', False)]
        if not selected:
            show_warning(u"Please select at least 1 family to delete!", title="No Family Selected")
            return

        names_preview = u"\n• ".join([f.Name for f in selected[:5]])
        if len(selected) > 5:
            names_preview += u"\n... and {} more families".format(len(selected) - 5)

        confirm_msg = u"Are you sure you want to PERMANENTLY DELETE the following {} families from Cloud Library?\n\n• {}\n\n⚠️ This action will delete the files from Cloud Storage and cannot be undone.".format(
            len(selected), names_preview
        )
        if not show_confirm(confirm_msg, title="Confirm Batch Delete"):
            return

        if hasattr(self, 'btnBatchLoad'): self.btnBatchLoad.IsEnabled = False
        if hasattr(self, 'btnBatchDelete'): self.btnBatchDelete.IsEnabled = False
        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = System.Windows.Visibility.Visible
            self.progressBar.Value = 0

        total = len(selected)
        deleted_count = 0
        failed_items = []

        try:
            for idx, item in enumerate(selected):
                pct = int((float(idx) / total) * 100.0)
                if hasattr(self, 'progressBar'): self.progressBar.Value = pct
                if hasattr(self, 'txtStatus'):
                    self.txtStatus.Text = u"Deleting ({}/{}): {}...".format(idx + 1, total, item.Name)
                do_events()

                success, msg = delete_family_from_cloud(item.Name, item.Category)
                if success:
                    deleted_count += 1
                    try:
                        thumb_path = get_thumbnail_cache_path(item.Name)
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)
                    except Exception:
                        pass
                else:
                    failed_items.append(u"{}: {}".format(item.Name, msg))

                pct_done = int((float(idx + 1) / total) * 100.0)
                if hasattr(self, 'progressBar'): self.progressBar.Value = pct_done
                do_events()

            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"Successfully deleted {}/{} families from cloud.".format(deleted_count, total)

            summary = u"🗑️ Successfully deleted {}/{} families from Cloud Library!".format(deleted_count, total)
            if failed_items:
                summary += u"\n\n⚠️ Failed to delete {} family file(s):\n• ".format(len(failed_items)) + u"\n• ".join(failed_items[:3])

            show_success(summary, title="Batch Delete Complete")
            self.ReloadLibrary(force_online=True)

        except Exception as ex:
            show_error(u"Unexpected error during batch delete:\n{}".format(safe_unicode(ex)), title="Batch Delete Error")
        finally:
            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = System.Windows.Visibility.Collapsed
            self._update_batch_buttons()

    def _download_missing_thumbnails_async(self):
        """
        Background download of thumbnails for cards that have a thumb_url
        but no cached disk thumbnail and no base64 data in catalog.
        Uses ThreadPool to avoid blocking UI thread.
        On completion, re-runs ApplyFilter via Dispatcher to refresh bindings.
        """
        cards_to_download = [
            c for c in self.all_families
            if c.ThumbnailImage is None and c._thumb_url and c._thumb_url.startswith("http")
        ]
        if not cards_to_download:
            return

        dispatcher = self.Dispatcher
        all_families_ref = self.all_families

        def bg_download(state):
            any_loaded = False
            for card in cards_to_download:
                try:
                    dest = get_thumbnail_cache_path(card.Name)
                    ok = download_file_from_url(card._thumb_url, dest)
                    if ok:
                        card.try_load_from_disk()
                        any_loaded = True
                except Exception:
                    pass

            if any_loaded and dispatcher:
                def on_ui():
                    try:
                        # Re-apply filter to rebind ItemsSource so WPF picks up new ThumbnailImage values
                        self.ApplyFilter()
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
        self.ReloadLibrary(force_online=True, rebuild_drive=True)

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

            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = System.Windows.Visibility.Visible
                self.progressBar.Value = 30
            if hasattr(self, 'txtStatus'):
                self.txtStatus.Text = u"Loading {} into project...".format(item.Name)
            do_events()

            success, msg = load_family_to_revit(doc, target, family_name=item.Name)

            if hasattr(self, 'progressBar'):
                self.progressBar.Value = 100
            do_events()

            if success:
                if hasattr(self, 'txtStatus'):
                    self.txtStatus.Text = u"Successfully loaded {} into project.".format(item.Name)
                show_success(msg, title="Family Loaded")
            else:
                if hasattr(self, 'txtStatus'):
                    self.txtStatus.Text = u"Failed to load {} into project.".format(item.Name)
                show_error(msg, title="Load Error")
        except Exception as ex:
            show_error(u"Unexpected error loading family:\n{}".format(safe_unicode(ex)), title="Load Error")
        finally:
            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = System.Windows.Visibility.Collapsed

    def OnDeleteFamilyClick(self, sender, args):
        try:
            item = sender.CommandParameter or sender.DataContext
            if not item:
                return

            if show_confirm(u"Are you sure you want to permanently delete '{}' from the Cloud Library?".format(item.Name), title="Delete Family"):
                if hasattr(self, 'progressBar'):
                    self.progressBar.Visibility = System.Windows.Visibility.Visible
                    self.progressBar.Value = 30
                if hasattr(self, 'txtStatus'):
                    self.txtStatus.Text = u"Deleting {} from cloud...".format(item.Name)
                do_events()

                success, msg = delete_family_from_cloud(item.Name, item.Category)

                if hasattr(self, 'progressBar'):
                    self.progressBar.Value = 100
                do_events()

                if success:
                    # Also clear local thumbnail cache for this family
                    try:
                        thumb_path = get_thumbnail_cache_path(item.Name)
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)
                    except Exception:
                        pass
                    if hasattr(self, 'txtStatus'):
                        self.txtStatus.Text = u"Successfully deleted {} from cloud.".format(item.Name)
                    show_success(msg, title="Family Deleted")
                    self.ReloadLibrary(force_online=True)
                else:
                    if hasattr(self, 'txtStatus'):
                        self.txtStatus.Text = u"Failed to delete {} from cloud.".format(item.Name)
                    show_error(msg, title="Delete Error")
        except Exception as ex:
            show_error(u"Unexpected error deleting family:\n{}".format(safe_unicode(ex)), title="Delete Error")
        finally:
            if hasattr(self, 'progressBar'):
                self.progressBar.Visibility = System.Windows.Visibility.Collapsed

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
            self.btnExecuteUpload.Content = u"☁️ Uploading to Cloud..."
        if hasattr(self, 'progressBar'):
            self.progressBar.Visibility = System.Windows.Visibility.Visible
            self.progressBar.IsIndeterminate = True
        if hasattr(self, 'txtStatus'):
            self.txtStatus.Text = u"Uploading {} to Cloud Library...".format(os.path.basename(src_path))

        def bg_upload(state):
            try:
                success, msg = upload_family_file(src_path, cat, desc)
                def on_done():
                    if hasattr(self, 'btnExecuteUpload'):
                        self.btnExecuteUpload.IsEnabled = True
                        self.btnExecuteUpload.Content = orig_content
                    if hasattr(self, 'progressBar'):
                        self.progressBar.Visibility = System.Windows.Visibility.Collapsed
                        self.progressBar.IsIndeterminate = False
                    if success:
                        if hasattr(self, 'txtStatus'):
                            self.txtStatus.Text = u"Successfully uploaded to Cloud Library."
                        show_success(msg, "Upload Complete")
                        if hasattr(self, 'txtUploadFilePath'): self.txtUploadFilePath.Text = ""
                        if hasattr(self, 'txtUploadDescription'): self.txtUploadDescription.Text = ""
                        if hasattr(self, 'borderDetectInfo'):
                            self.borderDetectInfo.Visibility = System.Windows.Visibility.Collapsed
                        if hasattr(self, 'rbTabBrowse'):
                            self.rbTabBrowse.IsChecked = True
                        self.ReloadLibrary(force_online=True)
                    else:
                        if hasattr(self, 'txtStatus'):
                            self.txtStatus.Text = u"Failed to upload family to Cloud Library."
                        show_error(msg, "Upload Failed")
                if self.Dispatcher:
                    self.Dispatcher.Invoke(System.Action(on_done))
            except Exception as ex:
                def on_fail():
                    if hasattr(self, 'btnExecuteUpload'):
                        self.btnExecuteUpload.IsEnabled = True
                        self.btnExecuteUpload.Content = orig_content
                    if hasattr(self, 'progressBar'):
                        self.progressBar.Visibility = System.Windows.Visibility.Collapsed
                        self.progressBar.IsIndeterminate = False
                    if hasattr(self, 'txtStatus'):
                        self.txtStatus.Text = u"Upload error: {}".format(safe_unicode(ex))
                    show_error(safe_unicode(ex), "Upload Error")
                if self.Dispatcher:
                    self.Dispatcher.Invoke(System.Action(on_fail))

        from System.Threading import ThreadPool, WaitCallback
        ThreadPool.QueueUserWorkItem(WaitCallback(bg_upload))


# ── Launch Entry ──────────────────────────────────────────────────────────────

def run():
    win = FamilyCloudWindow()
    win.ShowDialog()


if __name__ == "__main__":
    run()