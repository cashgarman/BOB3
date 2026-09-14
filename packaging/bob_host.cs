using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Bob")]
[assembly: AssemblyProduct("Bob")]
[assembly: AssemblyDescription("Bob")]
[assembly: AssemblyCompany("Bob")]
[assembly: AssemblyCopyright("Bob")]
[assembly: AssemblyFileVersion("0.1.0.0")]
[assembly: AssemblyInformationalVersion("0.1.0")]

namespace Bob
{
    static class Host
    {
        const string AppId = "Cash.Bob";
        const uint LOAD_WITH_ALTERED_SEARCH_PATH = 8;

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        static extern int SetCurrentProcessExplicitAppUserModelID(string appID);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr LoadLibraryEx(string lpFileName, IntPtr hFile, uint dwFlags);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool SetDllDirectory(string lpPathName);

        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true, SetLastError = true)]
        static extern IntPtr GetProcAddress(IntPtr hModule, string procName);

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        delegate int PyMain(int argc, IntPtr argv);

        [STAThread]
        static int Main(string[] args)
        {
            try
            {
                SetCurrentProcessExplicitAppUserModelID(AppId);
                string exe = Process.GetCurrentProcess().MainModule.FileName;
                string cfgPath = FindVenvCfg(Path.GetDirectoryName(exe));
                if (cfgPath == null)
                {
                    Fail("Could not find pyvenv.cfg.\nRun setup.ps1, then install.ps1.");
                    return 1;
                }
                string venv = Path.GetDirectoryName(cfgPath);
                string home = ReadHome(cfgPath);
                if (string.IsNullOrEmpty(home) || !Directory.Exists(home))
                {
                    Fail("pyvenv.cfg home is missing:\n" + home);
                    return 1;
                }
                string root = string.Equals(Path.GetFileName(venv), ".venv", StringComparison.OrdinalIgnoreCase)
                    ? Directory.GetParent(venv).FullName
                    : venv;
                string scripts = Path.Combine(venv, "Scripts");
                Directory.SetCurrentDirectory(root);
                Environment.SetEnvironmentVariable("VIRTUAL_ENV", venv);
                string path = Environment.GetEnvironmentVariable("PATH") ?? "";
                Environment.SetEnvironmentVariable("PATH", home + ";" + Path.Combine(home, "DLLs") + ";" + scripts + ";" + path);

                SetDllDirectory(home);
                string dllPath = Path.Combine(home, "python312.dll");
                IntPtr dll = LoadLibraryEx(dllPath, IntPtr.Zero, LOAD_WITH_ALTERED_SEARCH_PATH);
                if (dll == IntPtr.Zero)
                {
                    Fail("Failed to load python312.dll from:\n" + dllPath + "\n" + new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()).Message);
                    return 1;
                }
                IntPtr fn = GetProcAddress(dll, "Py_Main");
                if (fn == IntPtr.Zero)
                {
                    Fail("python312.dll is missing Py_Main.");
                    return 1;
                }
                var pyMain = (PyMain)Marshal.GetDelegateForFunctionPointer(fn, typeof(PyMain));

                string[] argv;
                if (args == null || args.Length == 0)
                    argv = new[] { exe, "-m", "bob" };
                else
                {
                    argv = new string[args.Length + 1];
                    argv[0] = exe;
                    Array.Copy(args, 0, argv, 1, args.Length);
                }
                return pyMain(argv.Length, AllocArgv(argv));
            }
            catch (Exception ex)
            {
                Fail(ex.ToString());
                return 1;
            }
        }

        static string FindVenvCfg(string start)
        {
            DirectoryInfo dir = new DirectoryInfo(start);
            while (dir != null)
            {
                string here = Path.Combine(dir.FullName, "pyvenv.cfg");
                if (File.Exists(here))
                    return here;
                string nested = Path.Combine(dir.FullName, ".venv", "pyvenv.cfg");
                if (File.Exists(nested))
                    return nested;
                dir = dir.Parent;
            }
            return null;
        }

        static string ReadHome(string cfgPath)
        {
            foreach (string line in File.ReadAllLines(cfgPath, Encoding.UTF8))
            {
                int eq = line.IndexOf('=');
                if (eq <= 0)
                    continue;
                if (line.Substring(0, eq).Trim().Equals("home", StringComparison.OrdinalIgnoreCase))
                    return line.Substring(eq + 1).Trim();
            }
            return null;
        }

        static IntPtr AllocArgv(string[] argv)
        {
            IntPtr block = Marshal.AllocHGlobal(IntPtr.Size * argv.Length);
            for (int i = 0; i < argv.Length; i++)
                Marshal.WriteIntPtr(block, i * IntPtr.Size, Marshal.StringToHGlobalUni(argv[i]));
            return block;
        }

        static void Fail(string message)
        {
            MessageBox.Show(message, "Bob", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
