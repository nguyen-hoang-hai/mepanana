using System;
using System.Collections;
using System.Collections.Generic;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Autodesk.Windows;

namespace MepananaSecurity
{
    public class AuthResult
    {
        public bool IsValid { get; set; }
        public string User { get; set; }
        public int FailCount { get; set; }
        public int RemainingAttempts { get; set; }
        public bool IsLockedOut { get; set; }
    }

    public static class AuthManager
    {
        private static readonly byte[] SecretKey = Encoding.UTF8.GetBytes("mepanana_2024_internal_key");
        private static readonly Dictionary<string, string> Credentials = new Dictionary<string, string>();
        
        // Cache original full-color icons by Button object and by Button ID string
        private static readonly Dictionary<string, ImageSource> ColorIconCacheById = new Dictionary<string, ImageSource>(StringComparer.OrdinalIgnoreCase);
        private static readonly Dictionary<RibbonButton, ImageSource> ColorIconCacheByBtn = new Dictionary<RibbonButton, ImageSource>();

        public const string DefaultSheetId = "1xP1AwtlAMnY7kUJ-xpecB6TMS_g91UShTgFDaFO_bkg";

        public static bool IsAuthenticated { get; private set; }
        public static string CurrentUser { get; private set; }
        public static int FailCount { get; private set; }
        public const int MaxFailedAttempts = 5;

        static AuthManager()
        {
            IsAuthenticated = false;
            CurrentUser = "";
            FailCount = 0;
        }

        public static void RegisterPassword(string plainPassword, string userName)
        {
            if (string.IsNullOrEmpty(plainPassword)) return;
            string hash = HashPassword(plainPassword.Trim());
            Credentials[hash] = userName.Trim();
        }

        private static string HashPassword(string plainPassword)
        {
            using (var hmac = new HMACSHA256(SecretKey))
            {
                byte[] hash = hmac.ComputeHash(Encoding.UTF8.GetBytes(plainPassword));
                var sb = new StringBuilder();
                foreach (byte b in hash)
                    sb.Append(b.ToString("x2"));
                return sb.ToString();
            }
        }

        public static bool SyncFromGoogleSheet(string sheetId)
        {
            if (string.IsNullOrEmpty(sheetId)) sheetId = DefaultSheetId;
            string url = "https://docs.google.com/spreadsheets/d/" + sheetId + "/gviz/tq?tqx=out:csv";

            try
            {
                ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072 | SecurityProtocolType.Tls;
                using (var client = new WebClient())
                {
                    client.Encoding = Encoding.UTF8;
                    client.Headers.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)");
                    string csv = client.DownloadString(url);
                    if (string.IsNullOrEmpty(csv)) return false;

                    string[] lines = csv.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.RemoveEmptyEntries);
                    if (lines.Length <= 1) return false;

                    for (int i = 1; i < lines.Length; i++)
                    {
                        var parts = ParseCsvLine(lines[i]);
                        if (parts.Count >= 2)
                        {
                            string name = parts[0].Trim('"', ' ', '\t');
                            string key  = parts[1].Trim('"', ' ', '\t');
                            if (!string.IsNullOrEmpty(name) && !string.IsNullOrEmpty(key))
                            {
                                RegisterPassword(key, name);
                            }
                        }
                    }
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        private static List<string> ParseCsvLine(string line)
        {
            var list = new List<string>();
            bool inQuotes = false;
            var sb = new StringBuilder();
            for (int i = 0; i < line.Length; i++)
            {
                char c = line[i];
                if (c == '"') inQuotes = !inQuotes;
                else if (c == ',' && !inQuotes)
                {
                    list.Add(sb.ToString());
                    sb.Length = 0;
                }
                else sb.Append(c);
            }
            list.Add(sb.ToString());
            return list;
        }

        public static AuthResult VerifyPassword(string inputPassword)
        {
            var res = new AuthResult();

            if (FailCount >= MaxFailedAttempts)
            {
                res.IsValid = false;
                res.User = "";
                res.FailCount = FailCount;
                res.RemainingAttempts = 0;
                res.IsLockedOut = true;
                return res;
            }

            if (string.IsNullOrEmpty(inputPassword))
            {
                FailCount++;
                res.IsValid = false;
                res.User = "";
                res.FailCount = FailCount;
                res.RemainingAttempts = Math.Max(0, MaxFailedAttempts - FailCount);
                res.IsLockedOut = FailCount >= MaxFailedAttempts;
                return res;
            }

            try { SyncFromGoogleSheet(DefaultSheetId); } catch { }

            string hash = HashPassword(inputPassword.Trim());
            string matchedUser;
            if (Credentials.TryGetValue(hash, out matchedUser))
            {
                FailCount = 0;
                IsAuthenticated = true;
                CurrentUser = matchedUser;

                res.IsValid = true;
                res.User = matchedUser;
                res.FailCount = 0;
                res.RemainingAttempts = MaxFailedAttempts;
                res.IsLockedOut = false;

                UpdateRibbon(true, CurrentUser);
                return res;
            }

            FailCount++;
            res.IsValid = false;
            res.User = "";
            res.FailCount = FailCount;
            res.RemainingAttempts = Math.Max(0, MaxFailedAttempts - FailCount);
            res.IsLockedOut = FailCount >= MaxFailedAttempts;
            return res;
        }

        public static void SetLockState(bool state, string user)
        {
            IsAuthenticated = state;
            CurrentUser = state ? user : "";
            UpdateRibbon(state, CurrentUser);
        }

        public static int UpdateRibbon(bool enable, string user)
        {
            try
            {
                var ribbon = ComponentManager.Ribbon;
                if (ribbon == null || ribbon.Tabs == null) return 0;

                int updatedCount = 0;
                foreach (var tab in ribbon.Tabs)
                {
                    string tabId = (tab.Id ?? "").ToLower();
                    string tabTitle = (tab.Title ?? "").ToLower();

                    if (tabId.Contains("mepanana") || tabTitle.Contains("mepanana"))
                    {
                        for (int pIdx = 0; pIdx < tab.Panels.Count; pIdx++)
                        {
                            var panel = tab.Panels[pIdx];
                            if (panel == null || panel.Source == null) continue;

                            string panelId = (panel.Source.Id ?? panel.Source.Name ?? "").ToLower();
                            string panelTitle = (panel.Source.Title ?? "").ToLower();

                            bool isSecurity = pIdx == 0 || panelId.Contains("security") || panelTitle.Contains("security");

                            if (isSecurity)
                            {
                                panel.IsEnabled = true;
                                string newTitle = (enable && !string.IsNullOrEmpty(user)) ? user : "Security";
                                panel.Source.Title = newTitle;
                                try { panel.Title = newTitle; } catch { }

                                UpdateSecurityButtons(panel.Source.Items, enable);
                            }
                            else
                            {
                                panel.IsEnabled = enable;
                                TraverseAndSetTools(panel.Source.Items, enable, ref updatedCount);

                                if (panel.Source.SlideOutPanelItemsView != null)
                                {
                                    TraverseAndSetTools(panel.Source.SlideOutPanelItemsView, enable, ref updatedCount);
                                }
                            }
                        }
                    }
                }
                return updatedCount;
            }
            catch
            {
                return 0;
            }
        }

        private static void UpdateSecurityButtons(IEnumerable items, bool enable)
        {
            if (items == null) return;
            foreach (var obj in items)
            {
                if (obj == null) continue;
                var btn = obj as RibbonButton;
                if (btn != null)
                {
                    btn.IsEnabled = true;
                    btn.Text = enable ? "Lock" : "Unlock";
                    try { btn.ShowImage = true; } catch { }
                    try { btn.ShowText = true; } catch { }
                }

                // Check nested
                var propItems = obj.GetType().GetProperty("Items") ?? obj.GetType().GetProperty("Panels");
                if (propItems != null)
                {
                    var childEnum = propItems.GetValue(obj, null) as IEnumerable;
                    if (childEnum != null) UpdateSecurityButtons(childEnum, enable);
                }
            }
        }

        private static void TraverseAndSetTools(IEnumerable items, bool enable, ref int count)
        {
            if (items == null) return;

            foreach (var obj in items)
            {
                if (obj == null) continue;

                var btn = obj as RibbonButton;
                if (btn != null)
                {
                    btn.IsEnabled = enable;

                    // Cache color image on first sight
                    string key = (btn.Id ?? btn.Text ?? btn.Name ?? "").Trim();
                    if (btn.LargeImage != null)
                    {
                        if (!ColorIconCacheByBtn.ContainsKey(btn))
                        {
                            // If this is the very first time we see it and it is not already grayscale
                            ColorIconCacheByBtn[btn] = btn.LargeImage;
                            if (!string.IsNullOrEmpty(key)) ColorIconCacheById[key] = btn.LargeImage;
                        }
                    }

                    ImageSource orig = null;
                    if (ColorIconCacheByBtn.ContainsKey(btn)) orig = ColorIconCacheByBtn[btn];
                    else if (!string.IsNullOrEmpty(key) && ColorIconCacheById.ContainsKey(key)) orig = ColorIconCacheById[key];
                    else if (btn.LargeImage != null) orig = btn.LargeImage;

                    if (orig != null)
                    {
                        if (enable)
                        {
                            btn.LargeImage = orig;
                        }
                        else
                        {
                            btn.LargeImage = ToGrayscaleWithTransparency(orig);
                        }
                        try { btn.ShowImage = true; } catch { }
                        try { btn.ShowText = true; } catch { }
                    }
                    count++;
                }
                else
                {
                    var rItem = obj as RibbonItem;
                    if (rItem != null) rItem.IsEnabled = enable;
                }

                // Deep traversal for RibbonRowPanel, RibbonRow, RibbonFoldPanel, RibbonSplitButton
                var type = obj.GetType();
                var pItems = type.GetProperty("Items");
                if (pItems != null)
                {
                    var childEnum = pItems.GetValue(obj, null) as IEnumerable;
                    if (childEnum != null) TraverseAndSetTools(childEnum, enable, ref count);
                }

                var pPanels = type.GetProperty("Panels");
                if (pPanels != null)
                {
                    var childEnum = pPanels.GetValue(obj, null) as IEnumerable;
                    if (childEnum != null) TraverseAndSetTools(childEnum, enable, ref count);
                }

                var pChildren = type.GetProperty("Children");
                if (pChildren != null)
                {
                    var childEnum = pChildren.GetValue(obj, null) as IEnumerable;
                    if (childEnum != null) TraverseAndSetTools(childEnum, enable, ref count);
                }
            }
        }

        private static ImageSource ToGrayscaleWithTransparency(ImageSource source)
        {
            var bmp = source as BitmapSource;
            if (bmp == null) return source;

            try
            {
                var formattedBmp = new FormatConvertedBitmap();
                formattedBmp.BeginInit();
                formattedBmp.Source = bmp;
                formattedBmp.DestinationFormat = PixelFormats.Bgra32;
                formattedBmp.EndInit();

                int width = formattedBmp.PixelWidth;
                int height = formattedBmp.PixelHeight;
                int stride = width * 4;
                byte[] pixels = new byte[height * stride];
                formattedBmp.CopyPixels(pixels, stride, 0);

                for (int i = 0; i < pixels.Length; i += 4)
                {
                    byte b = pixels[i];
                    byte g = pixels[i + 1];
                    byte r = pixels[i + 2];
                    byte a = pixels[i + 3];

                    if (a > 0)
                    {
                        byte gray = (byte)(0.299 * r + 0.587 * g + 0.114 * b);
                        pixels[i]     = gray;
                        pixels[i + 1] = gray;
                        pixels[i + 2] = gray;
                        pixels[i + 3] = (byte)(a * 0.65);
                    }
                }

                var writeableBmp = new WriteableBitmap(width, height, formattedBmp.DpiX, formattedBmp.DpiY, PixelFormats.Bgra32, null);
                writeableBmp.WritePixels(new Int32Rect(0, 0, width, height), pixels, stride, 0);
                writeableBmp.Freeze();
                return writeableBmp;
            }
            catch
            {
                return source;
            }
        }
    }
}