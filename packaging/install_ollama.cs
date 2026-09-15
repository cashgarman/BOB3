using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Threading;
using System.Windows.Forms;

namespace Bob
{
    static class InstallOllama
    {
        const string OllamaUrl = "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe";
        const string SilentArgs = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-";

        [STAThread]
        static int Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            try
            {
                if (IsOllamaAvailable())
                    return 0;
                using (var form = new DownloadForm())
                {
                    form.ShowDialog();
                    return form.ExitCode;
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "BOB — Ollama", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }

        static bool IsOllamaAvailable()
        {
            foreach (var path in CandidatePaths())
            {
                if (File.Exists(path))
                    return true;
            }
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
            catch
            {
            }
            return false;
        }

        static string[] CandidatePaths()
        {
            var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            var pf = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            return new[]
            {
                Path.Combine(local, "Programs", "Ollama", "ollama.exe"),
                Path.Combine(pf, "Ollama", "ollama.exe"),
            };
        }

        sealed class DownloadForm : Form
        {
            readonly ProgressBar _bar = new ProgressBar { Style = ProgressBarStyle.Continuous, Height = 22 };
            readonly Label _status = new Label { AutoSize = false, Height = 40, Text = "Checking for Ollama…" };
            public int ExitCode { get; private set; }

            public DownloadForm()
            {
                ExitCode = 1;
                Text = "Installing Ollama";
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false;
                MinimizeBox = false;
                StartPosition = FormStartPosition.CenterScreen;
                ClientSize = new Size(460, 120);
                BackColor = Color.FromArgb(17, 19, 24);
                ForeColor = Color.FromArgb(229, 231, 235);
                _status.ForeColor = ForeColor;
                _status.Left = 20;
                _status.Top = 16;
                _status.Width = ClientSize.Width - 40;
                _bar.Left = 20;
                _bar.Top = 64;
                _bar.Width = ClientSize.Width - 40;
                Controls.Add(_status);
                Controls.Add(_bar);
                Shown += delegate { BeginInvoke(new Action(Run)); };
            }

            static string CancelPath()
            {
                var overridePath = Environment.GetEnvironmentVariable("BOB_INSTALL_CANCEL");
                if (!string.IsNullOrEmpty(overridePath))
                    return overridePath;
                return Path.Combine(Path.GetTempPath(), "bob-install.cancel");
            }

            static void ThrowIfCancelled()
            {
                if (File.Exists(CancelPath()))
                    throw new OperationCanceledException("Installation cancelled.");
            }

            void Run()
            {
                try
                {
                    ThrowIfCancelled();
                    var temp = Path.Combine(Path.GetTempPath(), "Bob-OllamaSetup.exe");
                    _status.Text = "Downloading Ollama…";
                    Download(OllamaUrl, temp);
                    ThrowIfCancelled();
                    _status.Text = "Installing Ollama…";
                    _bar.Style = ProgressBarStyle.Marquee;
                    var proc = Process.Start(new ProcessStartInfo
                    {
                        FileName = temp,
                        Arguments = SilentArgs,
                        UseShellExecute = true,
                    });
                    if (proc == null)
                        throw new InvalidOperationException("Could not start OllamaSetup.exe");
                    proc.WaitForExit();
                    try { File.Delete(temp); } catch { }
                    if (proc.ExitCode != 0)
                        throw new InvalidOperationException("Ollama installer exited with code " + proc.ExitCode);
                    if (!IsOllamaAvailable())
                        throw new InvalidOperationException("Ollama was installed but is not responding yet. Start Ollama from the Start Menu and retry.");
                    ExitCode = 0;
                }
                catch (OperationCanceledException)
                {
                    _status.Text = "Installation cancelled.";
                    ExitCode = 2;
                }
                catch (Exception ex)
                {
                    _status.Text = ex.Message;
                    ExitCode = 1;
                }
                Close();
            }

            void Download(string url, string dest)
            {
                var req = (HttpWebRequest)WebRequest.Create(url);
                req.Method = "GET";
                using (var resp = (HttpWebResponse)req.GetResponse())
                using (var input = resp.GetResponseStream())
                using (var output = File.Create(dest))
                {
                    long total = resp.ContentLength;
                    var buffer = new byte[81920];
                    long done = 0;
                    int read;
                    while (input != null && (read = input.Read(buffer, 0, buffer.Length)) > 0)
                    {
                        ThrowIfCancelled();
                        output.Write(buffer, 0, read);
                        done += read;
                        if (total > 0)
                        {
                            int pct = (int)Math.Min(100, done * 100 / total);
                            _bar.Value = pct;
                        }
                        Application.DoEvents();
                    }
                }
                _bar.Value = 100;
            }
        }
    }
}
