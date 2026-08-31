using System;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MepananaInstaller
{
    public class InstallerForm : Form
    {
        private const string ZipUrl = "https://github.com/nguyen-hoang-hai/mepanana/archive/refs/heads/main.zip";
        private static readonly string TargetExtDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "pyRevit", "Extensions", "mepanana.extension"
        );

        private Label lblTitle;
        private Label lblSubtitle;
        private Panel cardPanel;
        private Label lblDestTitle;
        private Label lblDestPath;
        private Label lblStatus;
        private ProgressBar progressBar;
        private Button btnInstall;
        private Button btnClose;

        public InstallerForm()
        {
            InitializeComponent();
        }

        private void InitializeComponent()
        {
            this.Text = "MEPANANA Extension - 1-Click Installer";
            this.Size = new Size(540, 370);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = true;
            this.BackColor = Color.FromArgb(15, 23, 42); // Slate-900

            // Title
            lblTitle = new Label
            {
                Text = "MEPANANA REVIT EXTENSION",
                Font = new Font("Segoe UI", 16, FontStyle.Bold),
                ForeColor = Color.FromArgb(16, 185, 129), // Emerald-500
                BackColor = Color.Transparent,
                TextAlign = ContentAlignment.MiddleCenter,
                Dock = DockStyle.Top,
                Height = 35
            };

            // Subtitle
            lblSubtitle = new Label
            {
                Text = "1-Click Auto Installer & Updater (User-Level - No Admin Rights)",
                Font = new Font("Segoe UI", 9.5f),
                ForeColor = Color.FromArgb(148, 163, 184), // Slate-400
                BackColor = Color.Transparent,
                TextAlign = ContentAlignment.MiddleCenter,
                Dock = DockStyle.Top,
                Height = 25
            };

            // Card Panel
            cardPanel = new Panel
            {
                Location = new Point(20, 75),
                Size = new Size(485, 175),
                BackColor = Color.FromArgb(30, 41, 59), // Slate-800
                BorderStyle = BorderStyle.FixedSingle
            };

            lblDestTitle = new Label
            {
                Text = "Installation Directory:",
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold),
                ForeColor = Color.FromArgb(226, 232, 240),
                Location = new Point(16, 14),
                AutoSize = true
            };

            lblDestPath = new Label
            {
                Text = TargetExtDir,
                Font = new Font("Consolas", 8.5f),
                ForeColor = Color.FromArgb(56, 189, 248), // Sky-400
                Location = new Point(16, 38),
                Size = new Size(450, 32),
                AutoEllipsis = true
            };

            lblStatus = new Label
            {
                Text = "Ready to install the latest release from GitHub.",
                Font = new Font("Segoe UI", 9.5f),
                ForeColor = Color.FromArgb(148, 163, 184),
                Location = new Point(16, 80),
                Size = new Size(450, 24)
            };

            progressBar = new ProgressBar
            {
                Location = new Point(16, 115),
                Size = new Size(450, 22),
                Minimum = 0,
                Maximum = 100,
                Value = 0
            };

            cardPanel.Controls.Add(lblDestTitle);
            cardPanel.Controls.Add(lblDestPath);
            cardPanel.Controls.Add(lblStatus);
            cardPanel.Controls.Add(progressBar);

            // Install Button
            btnInstall = new Button
            {
                Text = "Install / Update Now",
                Font = new Font("Segoe UI", 10.5f, FontStyle.Bold),
                ForeColor = Color.White,
                BackColor = Color.FromArgb(37, 99, 235), // Blue-600
                FlatStyle = FlatStyle.Flat,
                Location = new Point(20, 268),
                Size = new Size(370, 42),
                Cursor = Cursors.Hand
            };
            btnInstall.FlatAppearance.BorderSize = 0;
            btnInstall.Click += async (s, e) => await StartInstallationAsync();

            // Close Button
            btnClose = new Button
            {
                Text = "Close",
                Font = new Font("Segoe UI", 10f),
                ForeColor = Color.FromArgb(148, 163, 184),
                BackColor = Color.FromArgb(51, 65, 85),
                FlatStyle = FlatStyle.Flat,
                Location = new Point(400, 268),
                Size = new Size(105, 42),
                Cursor = Cursors.Hand
            };
            btnClose.FlatAppearance.BorderSize = 0;
            btnClose.Click += (s, e) => this.Close();

            // Assemble Form
            this.Controls.Add(cardPanel);
            this.Controls.Add(lblSubtitle);
            this.Controls.Add(lblTitle);
            this.Controls.Add(btnInstall);
            this.Controls.Add(btnClose);
            this.Padding = new Padding(0, 15, 0, 0);
        }

        private async Task StartInstallationAsync()
        {
            btnInstall.Enabled = false;
            btnInstall.BackColor = Color.FromArgb(100, 116, 139);
            btnInstall.Text = "Installing...";
            btnClose.Enabled = false;

            string tempZip = Path.Combine(Path.GetTempPath(), "mepanana_latest.zip");
            string tempExtract = Path.Combine(Path.GetTempPath(), "mepanana_extracted");

            try
            {
                ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12 | (SecurityProtocolType)3072;

                // Step 1: Download
                lblStatus.Text = "Connecting to GitHub & downloading latest release...";
                lblStatus.ForeColor = Color.FromArgb(56, 189, 248);
                progressBar.Value = 15;

                using (var wc = new WebClient())
                {
                    wc.Headers.Add("User-Agent", "MEPANANA-Installer-Exe");
                    wc.DownloadProgressChanged += (s, e) =>
                    {
                        int p = 15 + (int)(e.ProgressPercentage * 0.45);
                        progressBar.Value = Math.Min(60, p);
                    };
                    await wc.DownloadFileTaskAsync(new Uri(ZipUrl), tempZip);
                }

                // Step 2: Extract
                lblStatus.Text = "Extracting package...";
                progressBar.Value = 65;

                await Task.Run(() =>
                {
                    if (Directory.Exists(tempExtract))
                    {
                        try { Directory.Delete(tempExtract, true); } catch { }
                    }
                    ZipFile.ExtractToDirectory(tempZip, tempExtract);
                });

                // Step 3: Copy to %APPDATA%/pyRevit/Extensions/mepanana.extension
                lblStatus.Text = "Deploying files to pyRevit Extensions directory...";
                progressBar.Value = 85;

                await Task.Run(() =>
                {
                    string innerDir = Path.Combine(tempExtract, "mepanana-main");
                    if (!Directory.Exists(innerDir))
                        innerDir = tempExtract;

                    if (!Directory.Exists(TargetExtDir))
                        Directory.CreateDirectory(TargetExtDir);

                    CopyDirectory(innerDir, TargetExtDir);

                    try { File.Delete(tempZip); } catch { }
                    try { Directory.Delete(tempExtract, true); } catch { }
                });

                progressBar.Value = 100;
                lblStatus.Text = "Installation & Update completed successfully!";
                lblStatus.ForeColor = Color.FromArgb(16, 185, 129);

                MessageBox.Show(
                    "MEPANANA Revit Extension has been installed successfully!\n\nPlease launch Autodesk Revit or click pyRevit -> Reload to start.",
                    "Installation Complete",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information
                );

                this.Close();
            }
            catch (Exception ex)
            {
                progressBar.Value = 0;
                lblStatus.Text = "Error: " + ex.Message;
                lblStatus.ForeColor = Color.FromArgb(239, 68, 68);

                MessageBox.Show(
                    "Installation failed:\n" + ex.Message,
                    "Installation Error",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
            }
            finally
            {
                btnInstall.Enabled = true;
                btnInstall.BackColor = Color.FromArgb(37, 99, 235);
                btnInstall.Text = "Install / Update Now";
                btnClose.Enabled = true;
            }
        }

        private static void CopyDirectory(string sourceDir, string destinationDir)
        {
            var dir = new DirectoryInfo(sourceDir);
            DirectoryInfo[] dirs = dir.GetDirectories();

            if (!Directory.Exists(destinationDir))
                Directory.CreateDirectory(destinationDir);

            foreach (FileInfo file in dir.GetFiles())
            {
                string targetFilePath = Path.Combine(destinationDir, file.Name);
                try
                {
                    file.CopyTo(targetFilePath, true);
                }
                catch
                {
                    // Ignore in-use files locked by active Revit session
                }
            }

            foreach (DirectoryInfo subDir in dirs)
            {
                string newDestDir = Path.Combine(destinationDir, subDir.Name);
                CopyDirectory(subDir.FullName, newDestDir);
            }
        }

        [STAThread]
        public static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm());
        }
    }
}
