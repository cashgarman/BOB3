using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace Bob
{
    static class BobSetupUi
    {
        static readonly Color Bg = Color.FromArgb(17, 19, 24);
        static readonly Color Panel = Color.FromArgb(28, 31, 38);
        static readonly Color Accent = Color.FromArgb(34, 197, 94);
        static readonly Color TextColor = Color.FromArgb(229, 231, 235);
        static readonly Color Muted = Color.FromArgb(107, 114, 128);
        const int StepCount = 11;
        const int PageWelcome = 0;
        const int PageExisting = 1;
        const int PageLicense = 2;
        const int PageOptions = 3;
        const int PageHotkey = 4;
        const int PageLlm = 5;
        const int PageStartup = 6;
        const int PageProgress = 7;
        const long RequiredInstallBytes = 15L * 1024 * 1024 * 1024;
        [STAThread]
        static int Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            using (var form = new SetupForm())
            {
                Application.Run(form);
                return form.ExitCode;
            }
        }

        sealed class InstallErrorInfo
        {
            public string Title;
            public string Summary;
            public string Details;
            public string HowToFix;
        }

        sealed class ThemedMessageBox : Form
        {
            static readonly Color ErrorAccent = Color.FromArgb(248, 113, 113);
            static readonly Color WarningAccent = Color.FromArgb(251, 191, 36);

            readonly Label _title = new Label { AutoSize = false, Height = 28, Font = new Font("Segoe UI", 13, FontStyle.Bold) };
            readonly Label _summary = new Label { AutoSize = false };
            readonly RichTextBox _body = new RichTextBox
            {
                ReadOnly = true,
                BorderStyle = BorderStyle.None,
                ScrollBars = RichTextBoxScrollBars.Vertical,
                Font = new Font("Segoe UI", 10),
            };
            readonly Button _ok = new Button { Text = "OK", Width = 96, Height = 32, DialogResult = DialogResult.OK };
            readonly Button _cancel = new Button { Text = "Cancel", Width = 96, Height = 32, DialogResult = DialogResult.Cancel };

            ThemedMessageBox()
            {
                FormBorderStyle = FormBorderStyle.FixedDialog;
                StartPosition = FormStartPosition.CenterParent;
                MaximizeBox = false;
                MinimizeBox = false;
                ShowInTaskbar = false;
                BackColor = Bg;
                ForeColor = TextColor;
                ClientSize = new Size(520, 380);
                Padding = new Padding(20);
            }

            public static DialogResult ShowError(IWin32Window owner, InstallErrorInfo info)
            {
                using (var dlg = new ThemedMessageBox())
                    return dlg.Show(owner, info.Title ?? "Setup failed", info.Summary, info.Details, info.HowToFix, ErrorAccent, false);
            }

            public static DialogResult ShowWarning(IWin32Window owner, string title, string summary, string details, string howToFix)
            {
                using (var dlg = new ThemedMessageBox())
                    return dlg.Show(owner, title, summary, details, howToFix, WarningAccent, false);
            }

            public static DialogResult ShowConfirm(IWin32Window owner, string title, string summary, string details)
            {
                using (var dlg = new ThemedMessageBox())
                    return dlg.Show(owner, title, summary, details, null, WarningAccent, true);
            }

            DialogResult Show(
                IWin32Window owner,
                string title,
                string summary,
                string details,
                string howToFix,
                Color accent,
                bool confirm)
            {
                Text = "BOB Setup";
                _title.Text = title;
                _title.ForeColor = accent;
                _title.Location = new Point(20, 16);
                _title.Width = 480;
                _summary.Text = summary ?? "";
                _summary.ForeColor = TextColor;
                _summary.Location = new Point(20, 50);
                _summary.Width = 480;
                _summary.Height = 44;
                _body.BackColor = Panel;
                _body.ForeColor = TextColor;
                _body.Location = new Point(20, 100);
                _body.Size = new Size(480, 220);
                _body.Text = BuildBodyText(details, howToFix);
                ApplyBodyTheme();
                _ok.FlatStyle = FlatStyle.Flat;
                _ok.BackColor = Panel;
                _ok.ForeColor = TextColor;
                _ok.FlatAppearance.BorderColor = Color.FromArgb(55, 65, 81);
                if (confirm)
                    _ok.Text = "Yes";
                _ok.Location = new Point(confirm ? 300 : 404, 332);
                Controls.Add(_title);
                Controls.Add(_summary);
                Controls.Add(_body);
                Controls.Add(_ok);
                AcceptButton = _ok;
                if (confirm)
                {
                    _cancel.FlatStyle = FlatStyle.Flat;
                    _cancel.BackColor = Panel;
                    _cancel.ForeColor = TextColor;
                    _cancel.FlatAppearance.BorderColor = Color.FromArgb(55, 65, 81);
                    _cancel.Location = new Point(404, 332);
                    Controls.Add(_cancel);
                    CancelButton = _cancel;
                }
                return ShowDialog(owner);
            }

            static string BuildBodyText(string details, string howToFix)
            {
                var parts = new List<string>();
                if (!string.IsNullOrWhiteSpace(details))
                    parts.Add("What happened\r\n" + details.Trim());
                if (!string.IsNullOrWhiteSpace(howToFix))
                    parts.Add("How to fix it\r\n" + howToFix.Trim());
                return string.Join("\r\n\r\n", parts.ToArray());
            }

            void ApplyBodyTheme()
            {
                _body.SelectAll();
                _body.SelectionColor = TextColor;
                _body.SelectionBackColor = Panel;
                _body.SelectionLength = 0;
            }
        }

        sealed class SetupForm : Form
        {
            readonly string _payloadDir;
            readonly string _progressPath;
            readonly string _cancelPath;
            string _installLogPath;
            long _logTailPosition;
            readonly Panel _header = new Panel { Height = 96, Dock = DockStyle.Top, BackColor = Panel };
            readonly PictureBox _logo = new PictureBox { SizeMode = PictureBoxSizeMode.Zoom, Size = new Size(64, 64) };
            readonly Label _brand = new Label { Text = "BOB", AutoSize = true, Font = new Font("Segoe UI", 22, FontStyle.Bold) };
            readonly Label _subtitle = new Label { AutoSize = false, Height = 22, Width = 520, Font = new Font("Segoe UI", 10) };
            readonly Panel _body = new Panel { Dock = DockStyle.Fill, Padding = new Padding(24) };
            readonly Panel _footer = new Panel { Height = 56, Dock = DockStyle.Bottom, BackColor = Panel };
            readonly Button _back = new Button { Text = "Back", Width = 96, Height = 32 };
            readonly Button _next = new Button { Text = "Next", Width = 96, Height = 32 };
            readonly Button _cancel = new Button { Text = "Cancel", Width = 96, Height = 32 };

            readonly Panel _welcome = new Panel { Dock = DockStyle.Fill, Visible = true };
            readonly Panel _existing = new Panel { Dock = DockStyle.Fill, Visible = false };
            readonly CheckedListBox _existingList = new CheckedListBox
            {
                CheckOnClick = true,
                BorderStyle = BorderStyle.None,
                BackColor = Panel,
                ForeColor = TextColor,
                Width = 580,
                Height = 220,
            };
            readonly Label _existingHelp = new Label { AutoSize = false, Height = 56 };
            readonly Label _existingStatus = new Label { AutoSize = false, Height = 28 };
            readonly Button _removeExisting = new Button { Text = "Remove selected", Width = 140, Height = 32 };
            readonly List<ExistingBobInstall> _existingInstalls = new List<ExistingBobInstall>();
            volatile bool _scanningExisting;
            volatile bool _removingExisting;
            readonly Panel _license = new Panel { Dock = DockStyle.Fill, Visible = false };
            readonly Panel _options = new Panel { Dock = DockStyle.Fill, Visible = false };
            readonly Panel _hotkey = new Panel { Dock = DockStyle.Fill, Visible = false };
            readonly Panel _llm = new Panel { Dock = DockStyle.Fill, Visible = false };
            readonly Panel _startup = new Panel { Dock = DockStyle.Fill, Visible = false };
            readonly Panel _progress = new Panel { Dock = DockStyle.Fill, Visible = false };
            readonly Button _hotkeyBtn = new Button { Height = 36, Width = 420 };
            readonly Label _hotkeyHint = new Label { AutoSize = false, Height = 48 };
            readonly ComboBox _llmCombo = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 420 };
            readonly Label _llmHint = new Label { AutoSize = false, Height = 72 };
            readonly CheckBox _startWithWindows = new CheckBox { Text = "Start BOB when Windows starts", AutoSize = true, Checked = true };
            readonly CheckBox _launchBob = new CheckBox { Text = "Launch BOB when setup finishes", AutoSize = true, Checked = true, Visible = false };
            readonly Dictionary<string, string> _llmLabelsToModels = new Dictionary<string, string>(StringComparer.Ordinal);
            string _hotkeySpec = "ctrl+shift+space";
            bool _recordingHotkey;
            readonly RichTextBox _licenseBox = new RichTextBox { ReadOnly = true, BorderStyle = BorderStyle.None, Dock = DockStyle.Fill };
            readonly TextBox _folder = new TextBox { Width = 360 };
            readonly Button _browse = new Button { Text = "Browse…", Width = 88, Height = 28 };
            readonly CheckBox _desktop = new CheckBox { Text = "Create desktop shortcut", AutoSize = true };
            readonly Label _folderHelp = new Label { AutoSize = false, Height = 36 };
            readonly Label _diskSpace = new Label { AutoSize = false, Height = 44 };
            readonly Label _stepLabel = new Label { AutoSize = false, Height = 32, Font = new Font("Segoe UI", 10, FontStyle.Bold) };
            readonly Label _taskLabel = new Label { AutoSize = false, Height = 32 };
            readonly Label _detailLabel = new Label { AutoSize = false, Height = 36 };
            readonly ProgressBar _overall = new ProgressBar { Height = 22, Style = ProgressBarStyle.Continuous };
            readonly ProgressBar _stage = new ProgressBar { Height = 22, Style = ProgressBarStyle.Continuous };
            readonly Label _logLabel = new Label { Text = "Command log", AutoSize = false, Height = 20 };
            readonly TextBox _logBox = new TextBox
            {
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                WordWrap = true,
                BorderStyle = BorderStyle.None,
                Font = new Font("Consolas", 9f),
            };
            readonly System.Windows.Forms.Timer _poll = new System.Windows.Forms.Timer { Interval = 200 };

            int _page;
            volatile bool _installing;
            volatile bool _installFailed;
            volatile bool _installCancelled;
            volatile bool _cancelRequested;
            string _installError;
            string _installRoot;
            string _msiPath;
            int _lastCompletedStep;
            volatile bool _suppressCancelChecks;
            Process _activeProcess;
            readonly object _processLock = new object();
            int _trackedStep;
            DateTime _stepStartedAt = DateTime.MinValue;
            DateTime _installStartedAt = DateTime.MinValue;
            public int ExitCode { get; private set; }

            public SetupForm()
            {
                Text = "BOB Setup";
                StartPosition = FormStartPosition.CenterScreen;
                ClientSize = new Size(640, 560);
                MinimumSize = new Size(640, 560);
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false;
                KeyPreview = true;
                BackColor = Bg;
                ForeColor = TextColor;

                string exePath = Application.ExecutablePath ?? "";
                try
                {
                    _payloadDir = EmbeddedPayload.ResolvePayloadDir(exePath);
                }
                catch (Exception ex)
                {
                    _payloadDir = Path.GetDirectoryName(exePath) ?? AppDomain.CurrentDomain.BaseDirectory;
                    MessageBox.Show(
                        "BOB Setup could not extract its embedded installer files.\r\n\r\n" + ex.Message,
                        "BOB Setup",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                    ExitCode = 1;
                    Load += delegate { Close(); };
                    return;
                }
                string setupStateDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "BOB",
                    "setup");
                try { Directory.CreateDirectory(setupStateDir); } catch { }
                _progressPath = Path.Combine(setupStateDir, "bob-install.json");
                _cancelPath = Path.Combine(setupStateDir, "bob-install.cancel");
                _installLogPath = Path.Combine(setupStateDir, "bob-install.log");
                Environment.SetEnvironmentVariable("BOB_INSTALL_PROGRESS", _progressPath);
                Environment.SetEnvironmentVariable("BOB_INSTALL_CANCEL", _cancelPath);
                Environment.SetEnvironmentVariable("BOB_INSTALL_LOG", _installLogPath);
                Environment.SetEnvironmentVariable("BOB_SETUP_UI", "1");
                ClearCancelState();

                BuildHeader();
                BuildWelcome();
                BuildExisting();
                BuildLicense();
                BuildOptions();
                BuildHotkey();
                BuildLlm();
                BuildStartup();
                BuildProgress();
                BuildFooter();
                Controls.Add(_body);
                Controls.Add(_footer);
                Controls.Add(_header);

                _back.Click += delegate
                {
                    if (_page == PageLicense)
                    {
                        ShowPage(_existingInstalls.Count > 0 ? PageExisting : PageWelcome);
                        return;
                    }
                    if (_page > PageWelcome)
                        ShowPage(_page - 1);
                };
                _next.Click += delegate { OnNext(); };
                _cancel.Click += delegate { OnCancel(); };
                _browse.Click += delegate { BrowseFolder(); };
                _folder.TextChanged += delegate { UpdateDiskSpace(); };
                _poll.Tick += delegate { PollProgress(); };
                KeyDown += OnSetupKeyDown;
                FormClosing += OnFormClosing;

                var defaultFolder = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Programs",
                    "BOB");
                _folder.Text = defaultFolder;
                UpdateDiskSpace();
                LoadLogo();
                LoadLicense();
                StyleButton(_back);
                StyleButton(_next);
                StyleButton(_cancel);
                ShowPage(PageWelcome);
                Load += delegate { BeginScanExistingInstalls(); };
            }

            void BuildHeader()
            {
                _logo.Location = new Point(20, 12);
                _brand.Location = new Point(96, 18);
                _brand.ForeColor = TextColor;
                _subtitle.Location = new Point(98, 54);
                _subtitle.ForeColor = Muted;
                _subtitle.Text = "Local voice assistant";
                _header.Controls.Add(_logo);
                _header.Controls.Add(_brand);
                _header.Controls.Add(_subtitle);
            }

            void BuildWelcome()
            {
                var title = MakeTitle("Welcome");
                var text = MakeBody(
                    "This installer will set up BOB, Ollama (if needed), Python 3.12, Python packages, and speech models.\n\n"
                    + "You can choose where BOB and all of its dependencies are installed on the next pages.\n\n"
                    + "An internet connection is required for the first install.");
                _welcome.Controls.Add(title);
                _welcome.Controls.Add(text);
                _body.Controls.Add(_welcome);
            }

            void BuildExisting()
            {
                var title = MakeTitle("Existing installations");
                _existingHelp.Text =
                    "Other BOB copies were found on this PC. Remove them before installing to avoid duplicate Apps & Features entries and wasted disk space.";
                _existingHelp.ForeColor = Muted;
                _existingHelp.Location = new Point(0, 44);
                _existingHelp.Width = 580;
                _existingList.Location = new Point(0, 104);
                _existingStatus.ForeColor = Muted;
                _existingStatus.Location = new Point(0, 332);
                _existingStatus.Width = 580;
                _removeExisting.Location = new Point(0, 364);
                StyleButton(_removeExisting);
                _removeExisting.Click += delegate { RemoveSelectedExistingInstalls(); };
                _existing.Controls.Add(title);
                _existing.Controls.Add(_existingHelp);
                _existing.Controls.Add(_existingList);
                _existing.Controls.Add(_existingStatus);
                _existing.Controls.Add(_removeExisting);
                _body.Controls.Add(_existing);
            }

            void BuildLicense()
            {
                var title = MakeTitle("License agreement");
                _licenseBox.BackColor = Panel;
                _licenseBox.ForeColor = TextColor;
                _licenseBox.Location = new Point(0, 44);
                _licenseBox.Size = new Size(580, 300);
                _license.Controls.Add(title);
                _license.Controls.Add(_licenseBox);
                _body.Controls.Add(_license);
            }

            void BuildOptions()
            {
                var title = MakeTitle("Choose install location");
                _folderHelp.Text = "BOB, Python, packages, models, and data will all live under this folder.";
                _folderHelp.ForeColor = Muted;
                _diskSpace.ForeColor = Muted;
                _folder.BackColor = Panel;
                _folder.ForeColor = TextColor;
                _folder.BorderStyle = BorderStyle.FixedSingle;
                _folder.Location = new Point(0, 52);
                _browse.Location = new Point(370, 50);
                _desktop.Location = new Point(0, 92);
                _folderHelp.Location = new Point(0, 124);
                _folderHelp.Width = 580;
                _diskSpace.Location = new Point(0, 164);
                _diskSpace.Width = 580;
                _options.Controls.Add(title);
                _options.Controls.Add(_folder);
                _options.Controls.Add(_browse);
                _options.Controls.Add(_desktop);
                _options.Controls.Add(_folderHelp);
                _options.Controls.Add(_diskSpace);
                _body.Controls.Add(_options);
            }

            void BuildHotkey()
            {
                var title = MakeTitle("Listen shortcut");
                _hotkeyHint.Text = "Click the button, then press the key combination you want to use to start and stop listening.";
                _hotkeyHint.ForeColor = Muted;
                _hotkeyBtn.Text = _hotkeySpec.ToUpperInvariant();
                _hotkeyBtn.Location = new Point(0, 52);
                _hotkeyBtn.FlatStyle = FlatStyle.Flat;
                _hotkeyBtn.BackColor = Panel;
                _hotkeyBtn.ForeColor = TextColor;
                _hotkeyBtn.FlatAppearance.BorderColor = Color.FromArgb(55, 65, 81);
                _hotkeyBtn.Click += delegate
                {
                    if (_recordingHotkey)
                    {
                        _recordingHotkey = false;
                        _hotkeyBtn.Text = _hotkeySpec.ToUpperInvariant();
                        _hotkeyHint.Text = "Click the button, then press the key combination you want to use to start and stop listening.";
                        return;
                    }
                    _recordingHotkey = true;
                    _hotkeyBtn.Text = "Press any key…";
                    _hotkeyHint.Text = "Waiting for a key. Click the button again to cancel.";
                };
                _hotkeyHint.Location = new Point(0, 96);
                _hotkeyHint.Width = 580;
                _hotkey.Controls.Add(title);
                _hotkey.Controls.Add(_hotkeyBtn);
                _hotkey.Controls.Add(_hotkeyHint);
                _body.Controls.Add(_hotkey);
            }

            void BuildLlm()
            {
                var title = MakeTitle("AI model");
                _llmHint.ForeColor = Muted;
                _llmCombo.Location = new Point(0, 52);
                _llmCombo.BackColor = Panel;
                _llmCombo.ForeColor = TextColor;
                _llmCombo.FlatStyle = FlatStyle.Flat;
                _llmHint.Location = new Point(0, 92);
                _llmHint.Width = 580;
                _llm.Controls.Add(title);
                _llm.Controls.Add(_llmCombo);
                _llm.Controls.Add(_llmHint);
                _body.Controls.Add(_llm);
            }

            void BuildStartup()
            {
                var title = MakeTitle("Startup");
                _startWithWindows.ForeColor = TextColor;
                _startWithWindows.Location = new Point(0, 52);
                var help = MakeBody("You can change this later from the BOB tray menu.");
                help.ForeColor = Muted;
                help.Location = new Point(0, 84);
                help.Height = 48;
                _startup.Controls.Add(title);
                _startup.Controls.Add(_startWithWindows);
                _startup.Controls.Add(help);
                _body.Controls.Add(_startup);
            }

            void UpdateDiskSpace()
            {
                string path = _folder.Text.Trim();
                if (string.IsNullOrEmpty(path))
                {
                    _diskSpace.Text = "Requires about 15 GB free for the app, Python packages, and speech models.";
                    _diskSpace.ForeColor = Muted;
                    if (_page == PageOptions)
                        _next.Enabled = false;
                    return;
                }

                try
                {
                    string root = Path.GetPathRoot(path);
                    if (string.IsNullOrEmpty(root))
                    {
                        _diskSpace.Text = "Requires about 15 GB free. Enter a valid install path.";
                        _diskSpace.ForeColor = Muted;
                        if (_page == PageOptions)
                            _next.Enabled = false;
                        return;
                    }

                    var drive = new DriveInfo(root);
                    long free = drive.AvailableFreeSpace;
                    bool ok = free >= RequiredInstallBytes;
                    string driveLabel = drive.Name.TrimEnd('\\');
                    string freeText = FormatBytes(free);
                    _diskSpace.Text = ok
                        ? string.Format(
                            CultureInfo.InvariantCulture,
                            "Requires about 15 GB free. {0} has {1} available.",
                            driveLabel,
                            freeText)
                        : string.Format(
                            CultureInfo.InvariantCulture,
                            "Requires about 15 GB free, but {0} only has {1} available. Choose another location or free up space.",
                            driveLabel,
                            freeText);
                    _diskSpace.ForeColor = ok ? Muted : Color.FromArgb(248, 113, 113);
                    if (_page == PageOptions)
                        _next.Enabled = ok;
                }
                catch
                {
                    _diskSpace.Text = "Requires about 15 GB free for the app, Python packages, and speech models.";
                    _diskSpace.ForeColor = Muted;
                    if (_page == PageOptions)
                        _next.Enabled = !string.IsNullOrWhiteSpace(_folder.Text);
                }
            }

            void BeginScanExistingInstalls()
            {
                if (_scanningExisting)
                    return;
                _scanningExisting = true;
                ThreadPool.QueueUserWorkItem(delegate
                {
                    List<ExistingBobInstall> found;
                    try
                    {
                        found = ExistingInstallScanner.FindAll();
                    }
                    catch
                    {
                        found = new List<ExistingBobInstall>();
                    }
                    BeginInvoke((Action)delegate
                    {
                        _scanningExisting = false;
                        _existingInstalls.Clear();
                        _existingInstalls.AddRange(found);
                        if (_page == PageWelcome)
                            _next.Enabled = true;
                        if (_page == PageExisting)
                            UpdateExistingUi();
                    });
                });
            }

            void UpdateExistingUi()
            {
                _existingList.Items.Clear();
                foreach (var install in _existingInstalls)
                {
                    int index = _existingList.Items.Add(install.DisplayLabel);
                    _existingList.SetItemChecked(index, true);
                }
                if (_scanningExisting)
                    _existingStatus.Text = "Scanning for existing BOB installations…";
                else if (_existingInstalls.Count == 0)
                    _existingStatus.Text = "No other BOB installations were found.";
                else
                    _existingStatus.Text = _existingInstalls.Count + " installation(s) found. All are selected for removal.";
                _removeExisting.Enabled = !_removingExisting && !_scanningExisting && _existingInstalls.Count > 0;
                _existingList.Enabled = !_removingExisting && !_scanningExisting;
            }

            void RemoveSelectedExistingInstalls()
            {
                if (_removingExisting || _existingList.CheckedIndices.Count == 0)
                    return;
                var selected = new List<ExistingBobInstall>();
                foreach (int index in _existingList.CheckedIndices)
                    selected.Add(_existingInstalls[index]);
                var answer = ThemedMessageBox.ShowConfirm(
                    this,
                    "Remove selected installations?",
                    "Remove " + selected.Count + " BOB installation(s)?",
                    "This unregisters BOB from Windows and deletes the install folders where possible.\r\n"
                    + "Apps & Features entries under HKLM may require running BobSetup.exe as Administrator.");
                if (answer != DialogResult.OK)
                    return;
                _removingExisting = true;
                UpdateExistingUi();
                _next.Enabled = false;
                ThreadPool.QueueUserWorkItem(delegate
                {
                    var failures = new List<string>();
                    bool needsElevation = false;
                    foreach (var install in selected)
                    {
                        var result = ExistingInstallRemover.Remove(install, delegate(string line)
                        {
                            try { BeginInvoke((Action)delegate { LogLine(line); }); } catch { }
                        });
                        if (!result.Success)
                        {
                            failures.Add(install.DisplayLabel + ": " + (result.Message ?? "failed"));
                            if (result.NeedsElevation)
                                needsElevation = true;
                        }
                    }
                    var remaining = ExistingInstallScanner.FindAll();
                    BeginInvoke((Action)delegate
                    {
                        _removingExisting = false;
                        _existingInstalls.Clear();
                        _existingInstalls.AddRange(remaining);
                        UpdateExistingUi();
                        _next.Enabled = true;
                        if (failures.Count > 0)
                        {
                            string howToFix = needsElevation
                                ? "Some entries are registered machine-wide (HKLM). Right-click BobSetup.exe → Run as administrator, return to this page, and remove again.\r\n\r\nOr run cleanup-bob-installs.ps1 -RegistryOnly as Administrator."
                                : "Close programs using those folders, then try Remove selected again.";
                            ThemedMessageBox.ShowWarning(
                                this,
                                "Some removals failed",
                                failures.Count + " installation(s) could not be fully removed.",
                                string.Join("\r\n", failures.ToArray()),
                                howToFix);
                        }
                        else if (_existingInstalls.Count == 0)
                        {
                            _existingStatus.Text = "All selected installations were removed.";
                        }
                    });
                });
            }

            void BuildProgress()
            {
                var title = MakeTitle("Installing BOB");
                title.Text = "Setup progress";
                _stepLabel.ForeColor = Accent;
                _taskLabel.ForeColor = TextColor;
                _detailLabel.ForeColor = Muted;
                _stepLabel.Location = new Point(0, 44);
                _stepLabel.Width = 580;
                _taskLabel.Location = new Point(0, 78);
                _taskLabel.Width = 580;
                _overall.Location = new Point(0, 114);
                _overall.Width = 580;
                _stage.Location = new Point(0, 146);
                _stage.Width = 580;
                _detailLabel.Location = new Point(0, 176);
                _detailLabel.Width = 580;
                _logLabel.ForeColor = Muted;
                _logLabel.Location = new Point(0, 214);
                _logLabel.Width = 580;
                _logBox.BackColor = Panel;
                _logBox.ForeColor = TextColor;
                _logBox.Location = new Point(0, 236);
                _logBox.Size = new Size(580, 164);
                _progress.Controls.Add(title);
                _progress.Controls.Add(_stepLabel);
                _progress.Controls.Add(_taskLabel);
                _progress.Controls.Add(_overall);
                _progress.Controls.Add(_stage);
                _progress.Controls.Add(_detailLabel);
                _launchBob.ForeColor = TextColor;
                _launchBob.Location = new Point(0, 408);
                _progress.Controls.Add(_logLabel);
                _progress.Controls.Add(_logBox);
                _progress.Controls.Add(_launchBob);
                _body.Controls.Add(_progress);
            }

            void BuildFooter()
            {
                _footer.Controls.Add(_cancel);
                _footer.Controls.Add(_next);
                _footer.Controls.Add(_back);
                _cancel.Anchor = AnchorStyles.Right;
                _next.Anchor = AnchorStyles.Right;
                _back.Anchor = AnchorStyles.Right;
                LayoutFooter();
                _footer.Resize += delegate { LayoutFooter(); };
            }

            void LayoutFooter()
            {
                int y = 12;
                _cancel.Location = new Point(_footer.Width - 108, y);
                _next.Location = new Point(_footer.Width - 212, y);
                _back.Location = new Point(_footer.Width - 316, y);
            }

            Label MakeTitle(string text)
            {
                return new Label
                {
                    Text = text,
                    AutoSize = false,
                    Height = 32,
                    Width = 580,
                    Font = new Font("Segoe UI", 14, FontStyle.Bold),
                    ForeColor = TextColor,
                };
            }

            Label MakeBody(string text)
            {
                return new Label
                {
                    Text = text,
                    AutoSize = false,
                    Location = new Point(0, 44),
                    Size = new Size(580, 280),
                    ForeColor = TextColor,
                };
            }

            void StyleButton(Button button)
            {
                button.FlatStyle = FlatStyle.Flat;
                button.BackColor = Panel;
                button.ForeColor = TextColor;
                button.FlatAppearance.BorderColor = Color.FromArgb(55, 65, 81);
            }

            void LoadLogo()
            {
                foreach (var candidate in new[]
                {
                    Path.Combine(_payloadDir, "logo.png"),
                    Path.Combine(_payloadDir, "assets", "logo.png"),
                })
                {
                    if (!File.Exists(candidate))
                        continue;
                    try
                    {
                        using (var img = Image.FromFile(candidate))
                            _logo.Image = new Bitmap(img);
                        break;
                    }
                    catch { }
                }
            }

            void LoadLicense()
            {
                var path = Path.Combine(_payloadDir, "license.rtf");
                if (File.Exists(path))
                    _licenseBox.LoadFile(path, RichTextBoxStreamType.RichText);
                else
                    _licenseBox.Text = "BOB installer license";
                ApplyLicenseTheme();
            }

            void ApplyLicenseTheme()
            {
                _licenseBox.BackColor = Panel;
                _licenseBox.ForeColor = TextColor;
                _licenseBox.SelectAll();
                _licenseBox.SelectionColor = TextColor;
                _licenseBox.SelectionBackColor = Panel;
                _licenseBox.SelectionLength = 0;
            }

            void ShowPage(int page)
            {
                _page = page;
                _welcome.Visible = page == PageWelcome;
                _existing.Visible = page == PageExisting;
                _license.Visible = page == PageLicense;
                _options.Visible = page == PageOptions;
                _hotkey.Visible = page == PageHotkey;
                _llm.Visible = page == PageLlm;
                _startup.Visible = page == PageStartup;
                _progress.Visible = page == PageProgress;
                _back.Enabled = page > PageWelcome && page < PageProgress && !_installing && !_removingExisting;
                _cancel.Enabled = !_installCancelled && (!_installing || page == PageProgress);
                _cancel.Text = _installing ? "Cancel install" : "Cancel";
                _subtitle.Text = page == PageExisting ? "Remove old copies before installing."
                    : page == PageHotkey ? "Choose a shortcut to start and stop listening."
                    : page == PageLlm ? "Pick the Ollama model BOB should use."
                    : page == PageStartup ? "Choose whether BOB starts with Windows."
                    : "Local voice assistant";
                if (page == PageWelcome)
                {
                    _next.Text = "Next";
                    _next.Enabled = !_scanningExisting;
                }
                else if (page == PageExisting)
                {
                    _next.Text = _existingInstalls.Count > 0 ? "Continue" : "Next";
                    _next.Enabled = !_removingExisting && !_scanningExisting;
                    UpdateExistingUi();
                }
                else if (page == PageLicense)
                {
                    _next.Text = "Accept";
                    _next.Enabled = true;
                }
                else if (page == PageOptions)
                {
                    _next.Text = "Next";
                    UpdateDiskSpace();
                }
                else if (page == PageHotkey)
                {
                    _next.Text = "Next";
                    _next.Enabled = !string.IsNullOrWhiteSpace(_hotkeySpec);
                }
                else if (page == PageLlm)
                {
                    _next.Text = "Next";
                    PopulateLlmChoices();
                    _next.Enabled = _llmCombo.SelectedIndex >= 0;
                }
                else if (page == PageStartup)
                {
                    _next.Text = "Install";
                    _next.Enabled = true;
                }
                else
                {
                    _next.Text = "Close";
                    _next.Enabled = !_installing && (_installFailed || _installCancelled || ExitCode == 0);
                    _launchBob.Visible = !_installing && ExitCode == 0 && !_installFailed && !_installCancelled;
                }
            }

            void OnCancel()
            {
                if (_installing)
                {
                    var answer = ThemedMessageBox.ShowConfirm(
                        this,
                        "Cancel installation?",
                        "Stop the installation?",
                        "The current step will be interrupted and any partially installed BOB files will be removed.");
                    if (answer != DialogResult.OK)
                        return;
                    RequestCancel();
                    return;
                }
                Close();
            }

            void OnFormClosing(object sender, FormClosingEventArgs e)
            {
                if (_installing && !_cancelRequested)
                {
                    e.Cancel = true;
                    OnCancel();
                }
            }

            void RequestCancel()
            {
                _cancelRequested = true;
                try { File.WriteAllText(_cancelPath, "1"); } catch { }
                KillActiveProcess();
                SetProgress(0, "Cancelling…", _overall.Value / 100.0, null, null, null, null);
            }

            void ClearCancelState()
            {
                _cancelRequested = false;
                TryDelete(_progressPath);
                TryDelete(_cancelPath);
                TryDelete(_installLogPath);
                _logTailPosition = 0;
                if (InvokeRequired)
                    BeginInvoke(new Action(delegate { _logBox.Clear(); }));
                else
                    _logBox.Clear();
            }

            void LogCommand(string fileName, string args)
            {
                LogLine("> " + fileName + (string.IsNullOrEmpty(args) ? "" : " " + args));
            }

            void LogPhase(int step, string message)
            {
                LogLine(string.Format(CultureInfo.InvariantCulture, "[step {0}] {1}", step, message));
            }

            void LogProcessOutput(string line)
            {
                if (string.IsNullOrWhiteSpace(line))
                    return;
                LogLine("  " + line.TrimEnd());
            }

            void LogLine(string line)
            {
                if (InvokeRequired)
                {
                    BeginInvoke(new Action<string>(LogLine), line);
                    return;
                }
                if (_logBox.TextLength > 0)
                    _logBox.AppendText(Environment.NewLine);
                _logBox.AppendText(line);
                _logBox.SelectionStart = _logBox.TextLength;
                _logBox.ScrollToCaret();
            }

            void TailInstallLog()
            {
                if (string.IsNullOrEmpty(_installLogPath) || !File.Exists(_installLogPath))
                    return;
                try
                {
                    using (var fs = new FileStream(_installLogPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                    {
                        if (_logTailPosition > fs.Length)
                            _logTailPosition = 0;
                        fs.Seek(_logTailPosition, SeekOrigin.Begin);
                        using (var reader = new StreamReader(fs, Encoding.UTF8, true, 1024, true))
                        {
                            string chunk = reader.ReadToEnd();
                            _logTailPosition = fs.Position;
                            if (string.IsNullOrEmpty(chunk))
                                return;
                            _logBox.AppendText(chunk);
                            _logBox.SelectionStart = _logBox.TextLength;
                            _logBox.ScrollToCaret();
                        }
                    }
                }
                catch
                {
                }
            }

            void OnNext()
            {
                if (_page == PageWelcome)
                {
                    if (_existingInstalls.Count > 0)
                        ShowPage(PageExisting);
                    else
                        ShowPage(PageLicense);
                    return;
                }
                if (_page == PageExisting)
                {
                    if (_existingInstalls.Count > 0)
                    {
                        var answer = ThemedMessageBox.ShowConfirm(
                            this,
                            "Keep existing installations?",
                            _existingInstalls.Count + " BOB installation(s) are still present.",
                            "You can remove them now with Remove selected, or continue and keep the old copies on disk.");
                        if (answer != DialogResult.OK)
                            return;
                    }
                    ShowPage(PageLicense);
                    return;
                }
                if (_page < PageStartup)
                {
                    if (_page == PageHotkey && string.IsNullOrWhiteSpace(_hotkeySpec))
                    {
                        ThemedMessageBox.ShowWarning(
                            this,
                            "Shortcut required",
                            "Choose a listen shortcut before continuing.",
                            "BOB needs a keyboard shortcut to start and stop listening.",
                            "Click the shortcut button on this page, then press the key combination you want to use.");
                        return;
                    }
                    if (_page == PageLlm && _llmCombo.SelectedIndex < 0)
                    {
                        ThemedMessageBox.ShowWarning(
                            this,
                            "AI model required",
                            "Choose an AI model before continuing.",
                            "BOB uses an Ollama model for conversation.",
                            "Pick a model from the list. The recommended option is usually best for your GPU.");
                        return;
                    }
                    ShowPage(_page + 1);
                    return;
                }
                if (_page == PageStartup)
                {
                    BeginInstall();
                    return;
                }
                if (_launchBob.Checked)
                    LaunchBob();
                Close();
            }

            void PopulateLlmChoices()
            {
                if (_llmCombo.Items.Count > 0)
                    return;
                _llmLabelsToModels.Clear();
                int? vram = DetectVramMb();
                string recommended = RecommendLlmModel(vram);
                string reason = vram.HasValue
                    ? string.Format(CultureInfo.InvariantCulture, "Detected {0} MB GPU memory. BOB will download the selected model with Ollama during setup.", vram.Value)
                    : "No NVIDIA GPU detected. BOB will use the smallest model and can fall back to CPU.";
                _llmHint.Text = reason + "\n\nYou can change the model later in BOB settings.";
                int selected = 0;
                for (int i = 0; i < LlmCatalog.Length; i++)
                {
                    var item = LlmCatalog[i];
                    string label = item.Name;
                    if (item.Name == recommended)
                        label += "  — recommended";
                    else if (vram.HasValue && vram.Value < item.MinMb)
                        label += "  — needs more VRAM";
                    _llmCombo.Items.Add(label);
                    _llmLabelsToModels[label] = item.Name;
                    if (item.Name == recommended)
                        selected = i;
                }
                if (_llmCombo.Items.Count > 0)
                    _llmCombo.SelectedIndex = selected;
            }

            string SelectedLlmModel()
            {
                string label = _llmCombo.SelectedItem as string;
                if (!string.IsNullOrEmpty(label) && _llmLabelsToModels.ContainsKey(label))
                    return _llmLabelsToModels[label];
                return "qwen3:4b";
            }

            void OnSetupKeyDown(object sender, KeyEventArgs e)
            {
                if (!_recordingHotkey || _page != PageHotkey)
                    return;
                if (IsModifierKey(e.KeyCode))
                    return;
                e.Handled = true;
                e.SuppressKeyPress = true;
                var parts = new List<string>();
                if (e.Control)
                    parts.Add("ctrl");
                if (e.Alt)
                    parts.Add("alt");
                if (e.Shift)
                    parts.Add("shift");
                string key = KeyToName(e.KeyCode);
                if (string.IsNullOrEmpty(key))
                    return;
                parts.Add(key);
                _hotkeySpec = string.Join("+", parts).ToLowerInvariant();
                _hotkeyBtn.Text = _hotkeySpec.ToUpperInvariant();
                _hotkeyHint.Text = "Click the button to change this shortcut.";
                _recordingHotkey = false;
            }

            void LaunchBob()
            {
                if (string.IsNullOrEmpty(_installRoot))
                    return;
                string exe = Path.Combine(_installRoot, ".venv", "Scripts", "Bob.exe");
                string target = File.Exists(exe) ? exe : Path.Combine(_installRoot, ".venv", "Scripts", "pythonw.exe");
                try
                {
                    var start = new ProcessStartInfo
                    {
                        FileName = target,
                        WorkingDirectory = _installRoot,
                        UseShellExecute = false,
                    };
                    if (!string.Equals(Path.GetFileName(target), "Bob.exe", StringComparison.OrdinalIgnoreCase))
                        start.Arguments = "-m bob";
                    Process.Start(start);
                }
                catch
                {
                }
            }

            void BrowseFolder()
            {
                using (var dialog = new FolderBrowserDialog())
                {
                    dialog.Description = "Choose where BOB and its dependencies should be installed";
                    dialog.SelectedPath = _folder.Text;
                    if (dialog.ShowDialog(this) == DialogResult.OK)
                    {
                        _folder.Text = dialog.SelectedPath;
                        UpdateDiskSpace();
                    }
                }
            }

            void BeginInstall()
            {
                var root = _folder.Text.Trim().TrimEnd('\\', '/');
                if (string.IsNullOrEmpty(root))
                {
                    ThemedMessageBox.ShowWarning(
                        this,
                        "Install folder required",
                        "Choose where BOB should be installed.",
                        "The installer needs a destination folder for BOB, Python, packages, and models.",
                        "Enter a path or click Browse… to pick a folder with at least 15 GB free.");
                    return;
                }
                try
                {
                    string driveRoot = Path.GetPathRoot(root);
                    if (!string.IsNullOrEmpty(driveRoot))
                    {
                        var drive = new DriveInfo(driveRoot);
                        if (drive.AvailableFreeSpace < RequiredInstallBytes)
                        {
                            ThemedMessageBox.ShowWarning(
                                this,
                                "Not enough disk space",
                                string.Format(
                                    CultureInfo.InvariantCulture,
                                    "This drive only has {0} free.",
                                    FormatBytes(drive.AvailableFreeSpace)),
                                "BOB needs about 15 GB for the app, Python packages, and speech models.",
                                "Choose a different install location, free up space on this drive, or move large files elsewhere before continuing.");
                            return;
                        }
                    }
                }
                catch
                {
                }
                _installing = true;
                _installFailed = false;
                _installCancelled = false;
                _installError = null;
                _installRoot = root;
                _lastCompletedStep = 0;
                _msiPath = Path.Combine(_payloadDir, "Bob.msi");
                _installStartedAt = DateTime.UtcNow;
                _trackedStep = 0;
                ClearCancelState();
                LogLine("=== BOB install started ===");
                LogLine("Install folder: " + root);
                LogLine("Log file: " + _installLogPath);
                ShowPage(PageProgress);
                _poll.Start();
                var desktop = _desktop.Checked ? 1 : 0;
                ThreadPool.QueueUserWorkItem(delegate { RunInstall(root, desktop); });
            }

            void RunInstall(string root, int desktopShortcut)
            {
                try
                {
                    ThrowIfCancelled();
                    Directory.CreateDirectory(root);
                    LogPhase(1, "Checking whether Ollama is installed");
                    SetProgress(1, "Checking whether Ollama is installed…", 0.02, null, null, null, null);
                    if (!IsOllamaAvailable())
                    {
                        LogPhase(1, "Downloading and installing Ollama");
                        SetProgress(1, "Downloading and installing Ollama…", 0.05, 0.1, null, null, null);
                        int code = RunExe(Path.Combine(_payloadDir, "InstallOllama.exe"), "");
                        ThrowIfCancelled();
                        if (code == 2)
                            throw new OperationCanceledException("Installation cancelled.");
                        if (code != 0)
                            throw new InvalidOperationException("Ollama setup failed with exit code " + code);
                    }
                    _lastCompletedStep = 1;
                    LogPhase(1, "Ollama is ready");
                    SetProgress(1, "Ollama is ready", 0.10, 1.0, null, null, null);

                    ThrowIfCancelled();
                    LogPhase(2, "Copying BOB application files");
                    SetProgress(2, "Copying BOB application files…", 0.12, 0.05, null, null, null);
                    if (!File.Exists(_msiPath))
                        throw new FileNotFoundException("Bob.msi was not found in the installer payload.", _msiPath);
                    int msiCode = RunMsi(_msiPath, root, desktopShortcut);
                    ThrowIfCancelled();
                    if (msiCode != 0)
                        throw new InvalidOperationException("Bob file install failed with exit code " + msiCode);
                    _lastCompletedStep = 2;
                    LogPhase(2, "BOB application files installed");
                    SetProgress(2, "BOB application files installed", 0.25, 1.0, null, null, null);

                    ThrowIfCancelled();
                    LogPhase(3, "Setting up Python and BOB dependencies");
                    SetProgress(3, "Setting up Python and BOB dependencies…", 0.28, 0.02, null, null, null);
                    string post = Path.Combine(_payloadDir, "RunPostInstall.exe");
                    int postCode = RunExe(post, "--root " + Quote(root) + " --desktop-shortcut " + desktopShortcut);
                    ThrowIfCancelled();
                    if (postCode == 2)
                        throw new OperationCanceledException("Installation cancelled.");
                    if (postCode != 0)
                        throw new InvalidOperationException(ReadProgressDetail()
                            ?? ("Dependency setup failed with exit code " + postCode));
                    _lastCompletedStep = 3;
                    LogPhase(3, "Python and dependencies installed");
                    SetProgress(3, "Python and dependencies installed", 0.82, 1.0, null, null, null);

                    ThrowIfCancelled();
                    LogPhase(4, "Downloading AI and speech models");
                    string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
                    string wizard = Path.Combine(root, "packaging", "setup_wizard.py");
                    if (!File.Exists(python))
                        throw new FileNotFoundException("Python was not found after install.", python);
                    if (!File.Exists(wizard))
                        throw new FileNotFoundException("Setup script was not found after install.", wizard);
                    string wizArgs = Quote(wizard)
                        + " --root " + Quote(root)
                        + " --quiet"
                        + " --hotkey " + Quote(_hotkeySpec)
                        + " --llm-model " + Quote(SelectedLlmModel())
                        + " --start-with-windows " + (_startWithWindows.Checked ? "true" : "false");
                    int wizCode = RunExe(python, wizArgs);
                    ThrowIfCancelled();
                    if (wizCode == 2)
                        throw new OperationCanceledException("Installation cancelled.");
                    if (wizCode != 0)
                        throw new InvalidOperationException(ReadProgressDetail()
                            ?? ("Model download failed with exit code " + wizCode));
                    _lastCompletedStep = StepCount;
                    LogLine("=== BOB install completed successfully ===");
                    SetProgress(StepCount, "BOB is ready", 1.0, 1.0, null, null, null);
                    ExitCode = 0;
                }
                catch (OperationCanceledException)
                {
                    _installCancelled = true;
                    ExitCode = 2;
                    RollbackInstall();
                    SetProgress(0, "Installation cancelled.", 0, 0, null, null, null);
                }
                catch (Exception ex)
                {
                    _installFailed = true;
                    var info = BuildInstallErrorInfo(ex, _trackedStep, ReadProgressDetail());
                    _installError = info.Summary;
                    ExitCode = 1;
                    SetProgress(0, info.Summary, 0, 0, null, null, info.Summary);
                    BeginInvoke((Action)delegate { ThemedMessageBox.ShowError(this, info); });
                }
                finally
                {
                    KillActiveProcess();
                    _installing = false;
                    BeginInvoke((Action)delegate { ShowPage(PageProgress); });
                }
            }

            InstallErrorInfo BuildInstallErrorInfo(Exception ex, int step, string progressDetail)
            {
                string raw = (progressDetail ?? ex.Message ?? "Unknown error").Trim();
                string lower = raw.ToLowerInvariant();
                string logHint = File.Exists(_installLogPath)
                    ? "Command log: " + _installLogPath
                    : "See the command log in the installer window for more detail.";

                if (ex is FileNotFoundException && lower.Contains("bob.msi"))
                {
                    return new InstallErrorInfo
                    {
                        Title = "Installer files missing",
                        Summary = "Bob.msi was not found in the installer payload.",
                        Details = raw + "\r\n\r\nExpected location:\r\n" + _msiPath,
                        HowToFix = "The installer file may be incomplete or corrupted.\r\n"
                            + "1. Download BobSetup.exe again from the original source.\r\n"
                            + "2. Delete %LOCALAPPDATA%\\BOB\\setup\\payload-cache and try again.\r\n"
                            + "3. If you built Bob yourself, rerun .\\installer\\scripts\\build.ps1.\r\n\r\n" + logHint,
                    };
                }
                if (lower.Contains("python was not found") || lower.Contains("setup script was not found"))
                {
                    return new InstallErrorInfo
                    {
                        Title = "Incomplete installation",
                        Summary = "BOB files were copied but the Python environment is missing.",
                        Details = raw,
                        HowToFix = "The dependency step may have failed or been interrupted.\r\n"
                            + "1. Close BOB Setup.\r\n"
                            + "2. Delete the partial install folder if you want a clean retry.\r\n"
                            + "3. Run BobSetup.exe again and let step 3 (Python dependencies) finish.\r\n\r\n" + logHint,
                    };
                }
                if (lower.Contains("ollama"))
                {
                    return new InstallErrorInfo
                    {
                        Title = "Ollama setup failed",
                        Summary = "BOB could not install or reach Ollama.",
                        Details = raw,
                        HowToFix = "1. Check your internet connection.\r\n"
                            + "2. Install Ollama manually from https://ollama.com/download\r\n"
                            + "3. Start Ollama from the Start Menu, then run BOB Setup again.\r\n"
                            + "4. If a firewall or proxy blocks downloads, allow Ollama and retry.\r\n\r\n" + logHint,
                    };
                }
                if (lower.Contains("disconnected") || lower.Contains("huggingface") || lower.Contains("parakeet")
                    || lower.Contains("smart turn") || lower.Contains("connection") || lower.Contains("timed out")
                    || lower.Contains("internet"))
                {
                    return new InstallErrorInfo
                    {
                        Title = "Model download failed",
                        Summary = "A speech or AI model could not be downloaded.",
                        Details = raw + (step > 0 ? "\r\n\r\nFailed during setup step " + step + " of " + StepCount + "." : ""),
                        HowToFix = "1. Check your internet connection and try again.\r\n"
                            + "2. If you use a VPN, proxy, or corporate firewall, allow access to huggingface.co and github.com.\r\n"
                            + "3. Run BobSetup.exe again — downloads resume where possible.\r\n"
                            + "4. To retry only model downloads after a successful install:\r\n"
                            + "   " + Quote(Path.Combine(_installRoot ?? "", ".venv", "Scripts", "python.exe"))
                            + " \"" + Path.Combine(_installRoot ?? "", "packaging", "setup_wizard.py")
                            + "\" --root \"" + (_installRoot ?? "") + "\" --quiet\r\n\r\n" + logHint,
                    };
                }
                if (lower.Contains("pip") || lower.Contains("dependenc") || lower.Contains("wheel") || lower.Contains("requirements"))
                {
                    return new InstallErrorInfo
                    {
                        Title = "Python dependency install failed",
                        Summary = "BOB could not install its Python packages.",
                        Details = raw + (step > 0 ? "\r\n\r\nFailed during setup step " + step + " of " + StepCount + "." : ""),
                        HowToFix = "1. Ensure the install drive has enough free space (about 15 GB total).\r\n"
                            + "2. Check your internet connection — CUDA and ML packages are downloaded from PyPI.\r\n"
                            + "3. Disable any custom pip index in your user environment; BOB uses an isolated install.\r\n"
                            + "4. Delete the install folder and run BobSetup.exe again for a clean retry.\r\n\r\n" + logHint,
                    };
                }
                if (lower.Contains("msi") || lower.Contains("file install"))
                {
                    return new InstallErrorInfo
                    {
                        Title = "Could not copy BOB files",
                        Summary = "Windows Installer failed to copy BOB into the chosen folder.",
                        Details = raw,
                        HowToFix = "1. Choose a folder you can write to (for example D:\\BOB or %LOCALAPPDATA%\\Programs\\BOB).\r\n"
                            + "2. Close other programs that may be using the install folder.\r\n"
                            + "3. Temporarily pause antivirus scanning of the target folder and retry.\r\n"
                            + "4. Run BobSetup.exe again.\r\n\r\n" + logHint,
                    };
                }
                if (lower.Contains("disk") || lower.Contains("space") || lower.Contains("no space"))
                {
                    return new InstallErrorInfo
                    {
                        Title = "Not enough disk space",
                        Summary = "The install ran out of space on the target drive.",
                        Details = raw,
                        HowToFix = "Free at least 15 GB on the install drive, or choose a different install location, then run BobSetup.exe again.\r\n\r\n" + logHint,
                    };
                }
                if (lower.Contains("permission denied") || lower.Contains("errno 13") || lower.Contains("access is denied"))
                {
                    return new InstallErrorInfo
                    {
                        Title = "File access blocked",
                        Summary = "BOB Setup could not update its progress file.",
                        Details = raw + "\r\n\r\nBOB does not require Administrator mode for a normal per-user install.",
                        HowToFix = "This is usually caused by another program locking a setup file, not missing admin rights.\r\n"
                            + "1. Close any other BOB Setup windows and retry.\r\n"
                            + "2. Temporarily pause antivirus real-time scanning, then run BobSetup.exe again.\r\n"
                            + "3. Install to a folder you own (for example %LOCALAPPDATA%\\Programs\\BOB or D:\\BOB).\r\n"
                            + "4. Do not run BobSetup.exe as Administrator unless IT requires it — a standard user install is expected.\r\n\r\n"
                            + logHint,
                    };
                }

                string stepLabel = step > 0 ? "Failed during setup step " + step + " of " + StepCount + "." : "";
                return new InstallErrorInfo
                {
                    Title = "Setup failed",
                    Summary = raw.Length > 120 ? raw.Substring(0, 117) + "…" : raw,
                    Details = raw + (string.IsNullOrEmpty(stepLabel) ? "" : "\r\n\r\n" + stepLabel),
                    HowToFix = "1. Read the command log below the progress bars for the exact command that failed.\r\n"
                        + "2. Fix the issue (network, disk space, permissions), then run BobSetup.exe again.\r\n"
                        + "3. If the problem persists, delete the partial install folder and retry.\r\n\r\n" + logHint,
                };
            }

            void ThrowIfCancelled()
            {
                if (_suppressCancelChecks)
                    return;
                if (_cancelRequested || File.Exists(_cancelPath))
                    throw new OperationCanceledException("Installation cancelled.");
            }

            void RollbackInstall()
            {
                if (string.IsNullOrEmpty(_installRoot))
                    return;
                _suppressCancelChecks = true;
                try
                {
                    if (_lastCompletedStep >= 3)
                    {
                        SetProgress(0, "Cleaning up partial install…", 0, null, null, null, null);
                        string post = Path.Combine(_payloadDir, "RunPostInstall.exe");
                        if (File.Exists(post))
                            RunExe(post, "--root " + Quote(_installRoot) + " --desktop-shortcut 0 --uninstall");
                    }
                    if (_lastCompletedStep >= 2 && File.Exists(_msiPath))
                    {
                        SetProgress(0, "Removing BOB files…", 0, null, null, null, null);
                        RunMsiUninstall(_msiPath, _installRoot);
                    }
                }
                catch
                {
                }
                finally
                {
                    _suppressCancelChecks = false;
                }
            }

            string ReadProgressFile()
            {
                if (!File.Exists(_progressPath))
                    return null;
                try
                {
                    using (var fs = new FileStream(
                        _progressPath,
                        FileMode.Open,
                        FileAccess.Read,
                        FileShare.ReadWrite | FileShare.Delete))
                    using (var reader = new StreamReader(fs, Encoding.UTF8))
                        return reader.ReadToEnd();
                }
                catch
                {
                    return null;
                }
            }

            string ReadProgressDetail()
            {
                string json = ReadProgressFile();
                if (string.IsNullOrEmpty(json))
                    return null;
                try
                {
                    string error = JsonString(json, "error");
                    if (!string.IsNullOrEmpty(error))
                        return error;
                    return JsonString(json, "message");
                }
                catch
                {
                    return null;
                }
            }

            void PollProgress()
            {
                TailInstallLog();
                string json = ReadProgressFile();
                if (string.IsNullOrEmpty(json))
                    return;

                string message = JsonString(json, "message");
                string subdetail = JsonString(json, "detail");
                if (!string.IsNullOrEmpty(message))
                    _taskLabel.Text = message;
                double? overall = JsonNumber(json, "overall");
                double? stage = JsonNumber(json, "stage");
                if (overall.HasValue)
                {
                    int mapped = MapOverallToUi(overall.Value);
                    _overall.Value = ClampPct(mapped / 100.0);
                }
                if (stage.HasValue)
                    _stage.Value = ClampPct(stage.Value);
                int? step = JsonInt(json, "step");
                int? stepTotal = JsonInt(json, "step_total");
                if (step.HasValue && step.Value != _trackedStep)
                {
                    _trackedStep = step.Value;
                    _stepStartedAt = DateTime.UtcNow;
                }
                long? completed = JsonLong(json, "completed");
                long? total = JsonLong(json, "total");
                double? rate = JsonNumber(json, "rate_bps");
                double? eta = JsonNumber(json, "eta_seconds");
                double? stepEta = JsonNumber(json, "step_eta_seconds");
                double? stepDuration = JsonNumber(json, "step_duration_seconds");
                double? overallEta = JsonNumber(json, "overall_eta_seconds");
                UpdateTimeEstimates(step, stepTotal, stage, overall, completed, total, rate, eta, stepEta, stepDuration, overallEta);
                string detail = BuildProgressDetail(
                    subdetail,
                    completed,
                    total,
                    rate,
                    EstimateRemainingSeconds(completed, total, rate, eta, stepEta));
                if (!string.IsNullOrEmpty(detail))
                    _detailLabel.Text = detail;
                string error = JsonString(json, "error");
                if (!string.IsNullOrEmpty(error))
                    _taskLabel.Text = error;
                if (JsonBool(json, "cancelled") || _installCancelled)
                {
                    _taskLabel.Text = "Installation cancelled.";
                    _poll.Stop();
                    _next.Enabled = true;
                    _next.Text = "Close";
                    _cancel.Enabled = false;
                }
                if (_installFailed && !string.IsNullOrEmpty(_installError))
                {
                    _taskLabel.Text = _installError;
                    _poll.Stop();
                    _next.Enabled = true;
                    _cancel.Enabled = false;
                }
                if (!_installing && ExitCode == 0)
                {
                    _poll.Stop();
                    _next.Enabled = true;
                    _next.Text = "Close";
                    _cancel.Enabled = false;
                }
            }

            int MapOverallToUi(double overall)
            {
                // Steps 1–3 map to 0–82%; model download steps 4–11 map to 82–100%.
                if (overall <= 0.25)
                    return ClampPctInt(overall / 0.25 * 25);
                if (overall <= 0.82)
                    return 25 + ClampPctInt((overall - 0.25) / 0.57 * 57);
                return 82 + ClampPctInt((overall - 0.82) / 0.18 * 18);
            }

            void SetProgress(int step, string message, double overall, double? stage, long? completed, long? total, string error)
            {
                if (InvokeRequired)
                {
                    BeginInvoke(new Action<int, string, double, double?, long?, long?, string>(SetProgress), step, message, overall, stage, completed, total, error);
                    return;
                }
                if (step != _trackedStep)
                {
                    _trackedStep = step;
                    _stepStartedAt = DateTime.UtcNow;
                }
                _taskLabel.Text = message;
                _overall.Value = ClampPct(overall);
                if (stage.HasValue)
                    _stage.Value = ClampPct(stage.Value);
                UpdateTimeEstimates(step, StepCount, stage, overall, completed, total, null, null, null, null, null);
                if (string.IsNullOrEmpty(error))
                {
                    string detail = BuildProgressDetail(null, completed, total, null, EstimateRemainingSeconds(completed, total, null, null, null));
                    _detailLabel.Text = detail ?? "";
                }
                if (!string.IsNullOrEmpty(error))
                    _taskLabel.Text = error;
            }

            void UpdateTimeEstimates(
                int? step,
                int? stepTotal,
                double? stage,
                double? overall,
                long? completed,
                long? total,
                double? rate,
                double? downloadEta,
                double? jsonStepEta,
                double? jsonStepDuration,
                double? jsonOverallEta)
            {
                if (!step.HasValue || step.Value < 1)
                    return;
                int s = step.Value;
                int totalSteps = stepTotal ?? StepCount;
                _stepLabel.Text = string.Format(
                    CultureInfo.InvariantCulture,
                    "Step {0} of {1}",
                    s,
                    totalSteps);
            }

            double? EstimateRemainingSeconds(
                long? completed,
                long? total,
                double? rate,
                double? downloadEta,
                double? jsonStepEta)
            {
                if (downloadEta.HasValue && downloadEta.Value >= 0 && downloadEta.Value < 86400)
                    return downloadEta;
                if (jsonStepEta.HasValue && jsonStepEta.Value >= 0 && jsonStepEta.Value < 86400)
                    return jsonStepEta;
                if (total.HasValue && total.Value > 0 && completed.HasValue && rate.HasValue && rate.Value > 0)
                    return (total.Value - completed.Value) / rate.Value;
                int pct = _overall.Value;
                if (pct >= 3 && pct < 100 && _installStartedAt != DateTime.MinValue)
                {
                    double elapsed = (DateTime.UtcNow - _installStartedAt).TotalSeconds;
                    return elapsed * (100.0 - pct) / pct;
                }
                return null;
            }

            string BuildProgressDetail(
                string subdetail,
                long? completed,
                long? total,
                double? rate,
                double? remainSeconds)
            {
                var parts = new List<string>();
                if (!string.IsNullOrWhiteSpace(subdetail))
                {
                    string trimmed = subdetail.Trim();
                    if (!trimmed.StartsWith("component ", StringComparison.OrdinalIgnoreCase))
                        parts.Add(trimmed);
                }
                if (completed.HasValue && total.HasValue && total.Value > 0)
                    parts.Add(FormatBytes(completed.Value) + " / " + FormatBytes(total.Value));
                if (rate.HasValue && rate.Value > 0)
                    parts.Add(FormatBytes((long)rate.Value) + "/s");
                if (remainSeconds.HasValue && remainSeconds.Value >= 5 && remainSeconds.Value < 86400)
                    parts.Add("~" + FormatDurationShort(remainSeconds.Value) + " remaining");
                if (parts.Count == 0)
                    return null;
                return string.Join("  ·  ", parts.ToArray());
            }

            int RunExe(string path, string args)
            {
                ThrowIfCancelled();
                LogCommand(path, args);
                var start = new ProcessStartInfo
                {
                    FileName = path,
                    Arguments = args,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8,
                };
                ApplyInstallEnvironment(start);
                using (var proc = Process.Start(start))
                {
                    if (proc == null)
                    {
                        LogLine("  failed to start");
                        return 1;
                    }
                    proc.OutputDataReceived += delegate(object s, DataReceivedEventArgs e)
                    {
                        if (e.Data != null)
                            LogProcessOutput(e.Data);
                    };
                    proc.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e)
                    {
                        if (e.Data != null)
                            LogProcessOutput(e.Data);
                    };
                    proc.BeginOutputReadLine();
                    proc.BeginErrorReadLine();
                    int code = WaitForProcess(proc);
                    LogLine(code == 0 ? "  done" : ("  exited " + code));
                    return code;
                }
            }

            int RunMsi(string msiPath, string installFolder, int desktopShortcut)
            {
                string args = "/i " + Quote(msiPath)
                    + " INSTALLFOLDER=" + Quote(installFolder)
                    + " DESKTOPSHORTCUT=" + desktopShortcut
                    + " /qn /norestart";
                return RunProcess("msiexec.exe", args);
            }

            int RunMsiUninstall(string msiPath, string installFolder)
            {
                string args = "/x " + Quote(msiPath)
                    + " INSTALLFOLDER=" + Quote(installFolder)
                    + " /qn /norestart";
                return RunProcess("msiexec.exe", args);
            }

            void ApplyInstallEnvironment(ProcessStartInfo start)
            {
                start.EnvironmentVariables["BOB_SETUP_UI"] = "1";
                start.EnvironmentVariables["BOB_INSTALL_PROGRESS"] = _progressPath;
                start.EnvironmentVariables["BOB_INSTALL_CANCEL"] = _cancelPath;
                start.EnvironmentVariables["BOB_INSTALL_LOG"] = _installLogPath;
            }

            int RunProcess(string fileName, string args)
            {
                ThrowIfCancelled();
                LogCommand(fileName, args);
                var start = new ProcessStartInfo
                {
                    FileName = fileName,
                    Arguments = args,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                ApplyInstallEnvironment(start);
                using (var proc = Process.Start(start))
                {
                    if (proc == null)
                    {
                        LogLine("  failed to start");
                        return 1;
                    }
                    int code = WaitForProcess(proc);
                    LogLine(code == 0 ? "  done" : ("  exited " + code));
                    return code;
                }
            }

            int WaitForProcess(Process proc)
            {
                lock (_processLock)
                {
                    _activeProcess = proc;
                }
                try
                {
                    while (!proc.WaitForExit(200))
                    {
                        if (!_suppressCancelChecks && (_cancelRequested || File.Exists(_cancelPath)))
                        {
                            KillActiveProcess();
                            throw new OperationCanceledException("Installation cancelled.");
                        }
                    }
                    return proc.ExitCode;
                }
                finally
                {
                    lock (_processLock)
                    {
                        if (_activeProcess == proc)
                            _activeProcess = null;
                    }
                }
            }

            void KillActiveProcess()
            {
                Process proc;
                lock (_processLock)
                {
                    proc = _activeProcess;
                }
                if (proc == null || proc.HasExited)
                    return;
                try
                {
                    proc.CloseMainWindow();
                    if (!proc.WaitForExit(1500))
                        proc.Kill();
                    proc.WaitForExit(5000);
                }
                catch
                {
                    try { proc.Kill(); } catch { }
                }
            }

            sealed class LlmChoice
            {
                public readonly string Name;
                public readonly int MinMb;
                public LlmChoice(string name, int minMb) { Name = name; MinMb = minMb; }
            }

            static readonly LlmChoice[] LlmCatalog = new LlmChoice[]
            {
                new LlmChoice("qwen2.5:1.5b", 0),
                new LlmChoice("qwen2.5:3b", 7168),
                new LlmChoice("qwen3:4b", 9216),
                new LlmChoice("qwen2.5:7b", 11264),
                new LlmChoice("qwen3:8b", 15360),
            };

            static int? DetectVramMb()
            {
                try
                {
                    var start = new ProcessStartInfo
                    {
                        FileName = "nvidia-smi",
                        Arguments = "--query-gpu=memory.total --format=csv,noheader,nounits",
                        RedirectStandardOutput = true,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                    };
                    using (var proc = Process.Start(start))
                    {
                        if (proc == null)
                            return null;
                        string line = proc.StandardOutput.ReadLine();
                        proc.WaitForExit(3000);
                        int mb;
                        if (int.TryParse((line ?? "").Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out mb))
                            return mb;
                    }
                }
                catch
                {
                }
                return null;
            }

            static string RecommendLlmModel(int? vramMb)
            {
                if (!vramMb.HasValue)
                    return "qwen2.5:1.5b";
                int vram = vramMb.Value;
                string pick = LlmCatalog[0].Name;
                foreach (var item in LlmCatalog)
                {
                    if (vram >= item.MinMb)
                        pick = item.Name;
                }
                return pick;
            }

            static bool IsModifierKey(Keys key)
            {
                return key == Keys.ControlKey || key == Keys.LControlKey || key == Keys.RControlKey
                    || key == Keys.ShiftKey || key == Keys.LShiftKey || key == Keys.RShiftKey
                    || key == Keys.Menu || key == Keys.LMenu || key == Keys.RMenu
                    || key == Keys.LWin || key == Keys.RWin;
            }

            static string KeyToName(Keys key)
            {
                if (key >= Keys.A && key <= Keys.Z)
                    return key.ToString().ToLowerInvariant();
                if (key >= Keys.D0 && key <= Keys.D9)
                    return ((char)('0' + (key - Keys.D0))).ToString(CultureInfo.InvariantCulture);
                if (key >= Keys.F1 && key <= Keys.F24)
                    return "f" + (key - Keys.F1 + 1).ToString(CultureInfo.InvariantCulture);
                switch (key)
                {
                    case Keys.Space: return "space";
                    case Keys.Tab: return "tab";
                    case Keys.Enter: return "enter";
                    case Keys.Escape: return "esc";
                    case Keys.Back: return "backspace";
                    case Keys.Delete: return "delete";
                    case Keys.Insert: return "insert";
                    case Keys.Home: return "home";
                    case Keys.End: return "end";
                    case Keys.PageUp: return "pageup";
                    case Keys.PageDown: return "pagedown";
                    case Keys.Left: return "left";
                    case Keys.Right: return "right";
                    case Keys.Up: return "up";
                    case Keys.Down: return "down";
                    default: return null;
                }
            }

            static bool IsOllamaAvailable()
            {
                var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                if (File.Exists(Path.Combine(local, "Programs", "Ollama", "ollama.exe")))
                    return true;
                try
                {
                    var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:11434/api/tags");
                    req.Method = "GET";
                    req.Timeout = 2000;
                    using (var resp = (HttpWebResponse)req.GetResponse())
                    {
                        if (resp.StatusCode == HttpStatusCode.OK)
                            return true;
                    }
                }
                catch { }
                return false;
            }

            static string Quote(string value)
            {
                return "\"" + value.Replace("\"", "\\\"") + "\"";
            }

            static void TryDelete(string path)
            {
                try { if (File.Exists(path)) File.Delete(path); }
                catch { }
            }

            static int ClampPctInt(double n)
            {
                int pct = (int)Math.Round(n);
                if (pct < 0) return 0;
                if (pct > 100) return 100;
                return pct;
            }

            static int ClampPct(double n)
            {
                return ClampPctInt(n * 100.0);
            }

            static string FormatBytes(long n)
            {
                double value = n;
                string[] units = { "B", "KB", "MB", "GB", "TB" };
                int u = 0;
                while (value >= 1024 && u < units.Length - 1)
                {
                    value /= 1024;
                    u++;
                }
                return u == 0 ? ((long)value) + " " + units[u] : value.ToString("0.0", CultureInfo.InvariantCulture) + " " + units[u];
            }

            static string FormatDurationShort(double seconds)
            {
                if (seconds < 0 || seconds > 86400)
                    return "a moment";
                int s = (int)seconds;
                if (s < 60)
                    return s + "s";
                int m = (int)Math.Ceiling(s / 60.0);
                if (m < 60)
                    return m + " min";
                int h = (int)Math.Ceiling(m / 60.0);
                return h + " hr";
            }

            static string JsonString(string json, string key)
            {
                string token = "\"" + key + "\":";
                int i = json.IndexOf(token, StringComparison.Ordinal);
                if (i < 0) return null;
                i += token.Length;
                while (i < json.Length && char.IsWhiteSpace(json[i]))
                    i++;
                if (i >= json.Length || json[i] != '"')
                    return null;
                int start = i + 1;
                int j = json.IndexOf('"', start);
                if (j < 0) return null;
                return json.Substring(start, j - start);
            }

            static double? JsonNumber(string json, string key)
            {
                string token = "\"" + key + "\":";
                int i = json.IndexOf(token, StringComparison.Ordinal);
                if (i < 0) return null;
                i += token.Length;
                while (i < json.Length && json[i] == ' ') i++;
                if (i < json.Length && json.Substring(i).StartsWith("null", StringComparison.Ordinal))
                    return null;
                int j = i;
                while (j < json.Length && "0123456789.+-eE".IndexOf(json[j]) >= 0) j++;
                double n;
                if (double.TryParse(json.Substring(i, j - i), NumberStyles.Float, CultureInfo.InvariantCulture, out n))
                    return n;
                return null;
            }

            static long? JsonLong(string json, string key)
            {
                double? n = JsonNumber(json, key);
                return n.HasValue ? (long)n.Value : (long?)null;
            }

            static int? JsonInt(string json, string key)
            {
                double? n = JsonNumber(json, key);
                return n.HasValue ? (int)n.Value : (int?)null;
            }

            static bool JsonBool(string json, string key)
            {
                string token = "\"" + key + "\":";
                int i = json.IndexOf(token, StringComparison.Ordinal);
                if (i < 0)
                    return false;
                return json.IndexOf("true", i, StringComparison.Ordinal) == i + token.Length
                    || json.IndexOf(" true", i, StringComparison.Ordinal) == i + token.Length;
            }
        }
    }
}
