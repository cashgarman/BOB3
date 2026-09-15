using System;
using System.Diagnostics;
using System.IO;

namespace Bob
{
    static class RunPostInstall
    {
        static int Main(string[] args)
        {
            string root = null;
            int desktopShortcut = 0;
            bool uninstall = false;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--root" && i + 1 < args.Length)
                    root = args[i + 1];
                else if (args[i] == "--desktop-shortcut" && i + 1 < args.Length)
                    int.TryParse(args[i + 1], out desktopShortcut);
                else if (args[i] == "--uninstall")
                    uninstall = true;
            }
            if (string.IsNullOrEmpty(root))
            {
                root = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Programs",
                    "BOB");
            }

            root = root.Trim().TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            string script = Path.Combine(root, "packaging", "msi_postinstall.ps1");
            if (!File.Exists(script))
            {
                Console.Error.WriteLine("Post-install script not found: " + script);
                return 1;
            }

            string installArg = QuotePath(root);
            string psArgs = "-NoProfile -ExecutionPolicy Bypass -File " + QuotePath(script)
                + " -InstallFolder " + installArg
                + " -DesktopShortcut " + desktopShortcut;
            if (uninstall)
                psArgs += " -Uninstall";

            var start = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = psArgs,
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("BOB_SETUP_UI")))
                start.EnvironmentVariables["BOB_SETUP_UI"] = "1";
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("BOB_INSTALL_PROGRESS")))
                start.EnvironmentVariables["BOB_INSTALL_PROGRESS"] = Environment.GetEnvironmentVariable("BOB_INSTALL_PROGRESS");
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("BOB_INSTALL_CANCEL")))
                start.EnvironmentVariables["BOB_INSTALL_CANCEL"] = Environment.GetEnvironmentVariable("BOB_INSTALL_CANCEL");
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("BOB_INSTALL_LOG")))
                start.EnvironmentVariables["BOB_INSTALL_LOG"] = Environment.GetEnvironmentVariable("BOB_INSTALL_LOG");
            using (var proc = Process.Start(start))
            {
                if (proc == null)
                    return 1;
                proc.WaitForExit();
                return proc.ExitCode;
            }
        }

        static string QuotePath(string path)
        {
            return "\"" + path.Replace("\"", "\\\"") + "\"";
        }
    }
}
