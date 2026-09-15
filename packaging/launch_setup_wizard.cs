using System;
using System.Diagnostics;
using System.IO;
using System.Management;
using System.Windows.Forms;

namespace Bob
{
    static class LaunchSetupWizard
    {
        [STAThread]
        static int Main(string[] args)
        {
            string root = null;
            bool quiet = ParentIsQuiet() || HasFlag(args, "--quiet");
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--root" && i + 1 < args.Length)
                    root = args[i + 1];
            }
            if (string.IsNullOrEmpty(root))
                root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "BOB");

            string pythonw = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
            string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
            string exe = quiet ? (File.Exists(python) ? python : pythonw) : (File.Exists(pythonw) ? pythonw : python);
            if (!File.Exists(exe))
            {
                MessageBox.Show("BOB is installed but Python was not found:\n" + exe, "BOB", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            string wizard = Path.Combine(root, "packaging", "setup_wizard.py");
            var start = new ProcessStartInfo
            {
                FileName = exe,
                WorkingDirectory = root,
                UseShellExecute = false,
            };
            start.Arguments = Quote(wizard) + " --root " + Quote(root);
            for (int i = 0; i < args.Length; i++)
            {
                if (string.Equals(args[i], "--root", StringComparison.OrdinalIgnoreCase))
                {
                    i++;
                    continue;
                }
                if (string.Equals(args[i], "--quiet", StringComparison.OrdinalIgnoreCase))
                    continue;
                start.Arguments += " " + Quote(args[i]);
            }
            if (quiet && start.Arguments.IndexOf("--quiet", StringComparison.OrdinalIgnoreCase) < 0)
                start.Arguments += " --quiet";
            start.EnvironmentVariables["BOB_ROOT"] = root;
            var proc = Process.Start(start);
            if (proc == null)
                return 1;
            proc.WaitForExit();
            return proc.ExitCode;
        }

        static bool HasFlag(string[] args, string flag)
        {
            foreach (string arg in args)
            {
                if (string.Equals(arg, flag, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            return false;
        }

        static bool ParentIsQuiet()
        {
            try
            {
                var current = Process.GetCurrentProcess();
                int pid = current.Id;
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT ParentProcessId FROM Win32_Process WHERE ProcessId=" + pid))
                {
                    foreach (ManagementObject obj in searcher.Get())
                    {
                        int parent = Convert.ToInt32(obj["ParentProcessId"]);
                        using (var cmd = new ManagementObjectSearcher(
                            "SELECT CommandLine FROM Win32_Process WHERE ProcessId=" + parent))
                        {
                            foreach (ManagementObject row in cmd.Get())
                            {
                                string line = Convert.ToString(row["CommandLine"]) ?? "";
                                if (line.IndexOf("/quiet", StringComparison.OrdinalIgnoreCase) >= 0
                                    || line.IndexOf("/qn", StringComparison.OrdinalIgnoreCase) >= 0
                                    || line.IndexOf("/q ", StringComparison.OrdinalIgnoreCase) >= 0)
                                    return true;
                            }
                        }
                    }
                }
            }
            catch
            {
            }
            return false;
        }

        static string Quote(string value)
        {
            if (string.IsNullOrEmpty(value))
                return "\"\"";
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }
    }
}
