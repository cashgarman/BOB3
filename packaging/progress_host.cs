using System;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Windows.Forms;

namespace Bob
{
    static class ProgressHost
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new ProgressForm());
        }
    }

    sealed class ProgressForm : Form
    {
        readonly ProgressBar _overall = new ProgressBar { Style = ProgressBarStyle.Continuous, Height = 22 };
        readonly ProgressBar _stage = new ProgressBar { Style = ProgressBarStyle.Continuous, Height = 22 };
        readonly Label _title = new Label { AutoSize = false, Height = 28, Font = new Font("Segoe UI", 12, FontStyle.Bold), Text = "Installing BOB" };
        readonly Label _overallLabel = new Label { AutoSize = false, Height = 20, Text = "Overall" };
        readonly Label _stageLabel = new Label { AutoSize = false, Height = 20, Text = "Starting…" };
        readonly Label _size = new Label { AutoSize = false, Height = 20 };
        readonly Timer _timer = new Timer { Interval = 250 };
        readonly string _path;

        public ProgressForm()
        {
            Text = "Installing BOB";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(480, 180);
            BackColor = Color.FromArgb(17, 19, 24);
            ForeColor = Color.FromArgb(229, 231, 235);
            _title.ForeColor = ForeColor;
            _overallLabel.ForeColor = Color.FromArgb(107, 114, 128);
            _stageLabel.ForeColor = ForeColor;
            _size.ForeColor = Color.FromArgb(107, 114, 128);

            var temp = Environment.GetEnvironmentVariable("BOB_INSTALL_PROGRESS");
            _path = string.IsNullOrEmpty(temp)
                ? Path.Combine(Path.GetTempPath(), "bob-install.json")
                : temp;

            int y = 16;
            foreach (Control c in new Control[] { _title, _overallLabel, _overall, _stageLabel, _stage, _size })
            {
                c.Left = 20;
                c.Width = ClientSize.Width - 40;
                c.Top = y;
                y += c.Height + 6;
                Controls.Add(c);
            }

            _timer.Tick += delegate { Poll(); };
            _timer.Start();

            try
            {
                string ico = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "bob.ico");
                if (File.Exists(ico))
                    Icon = new Icon(ico);
            }
            catch
            {
            }
        }

        void Poll()
        {
            if (!File.Exists(_path))
                return;
            string json;
            try { json = File.ReadAllText(_path); }
            catch { return; }

            string message = JsonString(json, "message");
            if (!string.IsNullOrEmpty(message))
                _stageLabel.Text = message;
            double? overall = JsonNumber(json, "overall");
            double? stage = JsonNumber(json, "stage");
            if (overall.HasValue)
            {
                _overall.Value = ClampPct(overall.Value);
                _overallLabel.Text = "Overall  " + _overall.Value + "%";
            }
            if (stage.HasValue)
                _stage.Value = ClampPct(stage.Value);
            long? completed = JsonLong(json, "completed");
            long? total = JsonLong(json, "total");
            if (completed.HasValue && total.HasValue && total.Value > 0)
            {
                string detail = FormatBytes(completed.Value) + " / " + FormatBytes(total.Value);
                double? rate = JsonNumber(json, "rate_bps");
                double? eta = JsonNumber(json, "eta_seconds");
                if (rate.HasValue && rate.Value > 0)
                    detail += "   " + FormatBytes((long)rate.Value) + "/s";
                if (eta.HasValue && eta.Value >= 0)
                    detail += "   " + FormatEta(eta.Value);
                _size.Text = detail;
            }
            string error = JsonString(json, "error");
            if (!string.IsNullOrEmpty(error))
                _stageLabel.Text = error;
            if (JsonBool(json, "done"))
                Close();
        }

        static int ClampPct(double n)
        {
            int pct = (int)Math.Round(n * 100.0);
            if (pct < 0) return 0;
            if (pct > 100) return 100;
            return pct;
        }

        static string JsonString(string json, string key)
        {
            string token = "\"" + key + "\":";
            int i = json.IndexOf(token, StringComparison.Ordinal);
            if (i < 0)
                return null;
            i = json.IndexOf('"', i + token.Length);
            if (i < 0)
                return null;
            int j = json.IndexOf('"', i + 1);
            if (j < 0)
                return null;
            return json.Substring(i + 1, j - i - 1);
        }

        static double? JsonNumber(string json, string key)
        {
            string token = "\"" + key + "\":";
            int i = json.IndexOf(token, StringComparison.Ordinal);
            if (i < 0)
                return null;
            i += token.Length;
            while (i < json.Length && json[i] == ' ')
                i++;
            if (i < json.Length && json.Substring(i).StartsWith("null", StringComparison.Ordinal))
                return null;
            int j = i;
            while (j < json.Length && "0123456789.+-eE".IndexOf(json[j]) >= 0)
                j++;
            double n;
            if (double.TryParse(json.Substring(i, j - i), NumberStyles.Float, CultureInfo.InvariantCulture, out n))
                return n;
            return null;
        }

        static long? JsonLong(string json, string key)
        {
            double? n = JsonNumber(json, key);
            if (!n.HasValue)
                return null;
            return (long)n.Value;
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

        static string FormatEta(double seconds)
        {
            if (seconds < 0 || seconds > 86400)
                return "";
            int s = (int)seconds;
            if (s < 60)
                return s + "s remaining";
            int m = s / 60;
            s = s % 60;
            if (m < 60)
                return m + "m " + s + "s remaining";
            int h = m / 60;
            m = m % 60;
            return h + "h " + m + "m remaining";
        }
    }
}
