using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using Microsoft.Win32;

namespace Bob
{
    sealed class ExistingBobInstall
    {
        public string FolderPath;
        public string MsiProductCode;
        public bool RequiresElevation;

        public string DisplayLabel
        {
            get
            {
                if (!string.IsNullOrEmpty(FolderPath) && Directory.Exists(FolderPath))
                    return FolderPath;
                if (!string.IsNullOrEmpty(MsiProductCode))
                    return "BOB in Apps & Features (" + MsiProductCode + ")";
                return "BOB installation";
            }
        }
    }

    sealed class ExistingInstallRemovalResult
    {
        public bool Success;
        public bool NeedsElevation;
        public string Message;
    }

    static class ExistingInstallScanner
    {
        const string BobUpgradeCode = "8F3C1A7E-6B2D-4E91-9C4A-2D8F7B1E5A30";

        public static List<ExistingBobInstall> FindAll()
        {
            var byFolder = new Dictionary<string, ExistingBobInstall>(StringComparer.OrdinalIgnoreCase);
            var registryOnly = new List<ExistingBobInstall>();

            foreach (var entry in ReadRegistryEntries())
            {
                if (!string.IsNullOrEmpty(entry.FolderPath) && IsBobInstallRoot(entry.FolderPath))
                {
                    Merge(byFolder, entry);
                    continue;
                }
                if (!string.IsNullOrEmpty(entry.MsiProductCode))
                    registryOnly.Add(entry);
            }

            try
            {
                using (var bobKey = Registry.CurrentUser.OpenSubKey(@"Software\Bob"))
                {
                    var folder = bobKey != null ? bobKey.GetValue("InstallFolder") as string : null;
                    if (!string.IsNullOrEmpty(folder) && IsBobInstallRoot(folder))
                        Merge(byFolder, new ExistingBobInstall { FolderPath = folder.TrimEnd('\\', '/') });
                }
            }
            catch { }

            foreach (var drive in DriveInfo.GetDrives())
            {
                if (drive.DriveType != DriveType.Fixed || !drive.IsReady)
                    continue;
                try
                {
                    foreach (var dir in Directory.EnumerateDirectories(drive.RootDirectory.FullName))
                    {
                        if (!IsBobInstallRoot(dir))
                            continue;
                        Merge(byFolder, new ExistingBobInstall { FolderPath = dir });
                    }
                }
                catch { }
            }

            var localPrograms = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs");
            if (Directory.Exists(localPrograms))
            {
                try
                {
                    foreach (var dir in Directory.EnumerateDirectories(localPrograms))
                    {
                        if (!IsBobInstallRoot(dir))
                            continue;
                        Merge(byFolder, new ExistingBobInstall { FolderPath = dir });
                    }
                }
                catch { }
            }

            var results = byFolder.Values.ToList();
            foreach (var orphan in registryOnly)
            {
                if (results.Any(r => string.Equals(r.MsiProductCode, orphan.MsiProductCode, StringComparison.OrdinalIgnoreCase)))
                    continue;
                results.Add(orphan);
            }
            return results.OrderBy(r => r.DisplayLabel, StringComparer.OrdinalIgnoreCase).ToList();
        }

        static void Merge(IDictionary<string, ExistingBobInstall> map, ExistingBobInstall entry)
        {
            string folder = (entry.FolderPath ?? "").TrimEnd('\\', '/');
            if (string.IsNullOrEmpty(folder))
                return;
            ExistingBobInstall existing;
            if (!map.TryGetValue(folder, out existing))
            {
                entry.FolderPath = folder;
                map[folder] = entry;
                return;
            }
            if (string.IsNullOrEmpty(existing.MsiProductCode) && !string.IsNullOrEmpty(entry.MsiProductCode))
                existing.MsiProductCode = entry.MsiProductCode;
            existing.RequiresElevation |= entry.RequiresElevation;
        }

        static bool IsBobInstallRoot(string path)
        {
            if (string.IsNullOrEmpty(path))
                return false;
            return File.Exists(Path.Combine(path, "bob", "__main__.py"))
                && File.Exists(Path.Combine(path, "packaging", "setup_wizard.py"));
        }

        static IEnumerable<ExistingBobInstall> ReadRegistryEntries()
        {
            foreach (var item in ReadUninstallHive(Registry.CurrentUser, @"Software\Microsoft\Windows\CurrentVersion\Uninstall", false))
                yield return item;
            foreach (var item in ReadUninstallHive(Registry.LocalMachine, @"Software\Microsoft\Windows\CurrentVersion\Uninstall", true))
                yield return item;
            foreach (var item in ReadUninstallHive(Registry.LocalMachine, @"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", true))
                yield return item;
        }

        static IEnumerable<ExistingBobInstall> ReadUninstallHive(RegistryKey root, string subKey, bool machineWide)
        {
            var results = new List<ExistingBobInstall>();
            try
            {
                using (var uninstall = root.OpenSubKey(subKey))
                {
                    if (uninstall == null)
                        return results;
                    foreach (var id in uninstall.GetSubKeyNames())
                    {
                        if (!IsProductCode(id))
                            continue;
                        using (var key = uninstall.OpenSubKey(id))
                        {
                            if (!IsBobUninstallEntry(key))
                                continue;
                            var install = new ExistingBobInstall
                            {
                                MsiProductCode = id,
                                RequiresElevation = machineWide,
                            };
                            var location = key.GetValue("InstallLocation") as string;
                            if (!string.IsNullOrWhiteSpace(location))
                                install.FolderPath = location.TrimEnd('\\', '/');
                            results.Add(install);
                        }
                    }
                }
            }
            catch { }
            return results;
        }

        static bool IsProductCode(string id)
        {
            if (string.IsNullOrEmpty(id) || id.Length != 38)
                return false;
            return id[0] == '{' && id[37] == '}';
        }

        static bool IsBobUninstallEntry(RegistryKey key)
        {
            if (key == null)
                return false;
            var name = (key.GetValue("DisplayName") as string ?? "").Trim();
            var publisher = (key.GetValue("Publisher") as string ?? "").Trim();
            if (string.Equals(name, "BOB", StringComparison.OrdinalIgnoreCase))
                return true;
            return string.Equals(publisher, "BOB", StringComparison.OrdinalIgnoreCase)
                && name.IndexOf("BOB", StringComparison.OrdinalIgnoreCase) >= 0;
        }
    }

    static class ExistingInstallRemover
    {
        const string BobUpgradeCode = "8F3C1A7E-6B2D-4E91-9C4A-2D8F7B1E5A30";

        public static ExistingInstallRemovalResult Remove(ExistingBobInstall install, Action<string> log)
        {
            var result = new ExistingInstallRemovalResult { Success = true };
            try
            {
                if (!string.IsNullOrEmpty(install.FolderPath) && Directory.Exists(install.FolderPath))
                    RemoveFolderInstall(install.FolderPath, log);

                if (!string.IsNullOrEmpty(install.MsiProductCode))
                {
                    int code = RunMsiProductUninstall(install.MsiProductCode, log);
                    if (code != 0 && code != 1605 && code != 1614)
                    {
                        log("msiexec uninstall exited " + code + " (continuing with registry cleanup)");
                    }
                    bool registryOk = RemoveMsiRegistry(install.MsiProductCode, install.RequiresElevation, log);
                    if (!registryOk)
                    {
                        result.NeedsElevation = install.RequiresElevation;
                        result.Success = false;
                        result.Message = "Could not remove Apps & Features entry. Run BOB Setup as Administrator or use cleanup-bob-installs.ps1 -RegistryOnly.";
                    }
                }

                if (!string.IsNullOrEmpty(install.FolderPath) && Directory.Exists(install.FolderPath))
                {
                    try
                    {
                        log("Deleting " + install.FolderPath);
                        Directory.Delete(install.FolderPath, true);
                    }
                    catch (Exception ex)
                    {
                        result.Success = false;
                        result.Message = "Could not delete install folder: " + ex.Message;
                    }
                }
            }
            catch (Exception ex)
            {
                result.Success = false;
                result.Message = ex.Message;
            }
            return result;
        }

        static void RemoveFolderInstall(string root, Action<string> log)
        {
            string uninstallPs1 = Path.Combine(root, "uninstall.ps1");
            string venvPython = Path.Combine(root, ".venv", "Scripts", "python.exe");
            string msiPost = Path.Combine(root, "packaging", "msi_postinstall.py");
            string installPy = Path.Combine(root, "packaging", "install.py");

            if (File.Exists(uninstallPs1))
            {
                log("Running uninstall.ps1");
                RunProcess("powershell.exe", "-NoProfile -ExecutionPolicy Bypass -File " + Quote(uninstallPs1), log);
                return;
            }
            if (File.Exists(venvPython) && File.Exists(msiPost))
            {
                log("Running msi_postinstall.py --uninstall");
                RunProcess(venvPython, Quote(msiPost) + " --root " + Quote(root) + " --uninstall", log);
                return;
            }
            if (File.Exists(venvPython) && File.Exists(installPy))
            {
                log("Running install.py --uninstall");
                RunProcess(venvPython, Quote(installPy) + " --uninstall", log);
            }
        }

        static int RunMsiProductUninstall(string productCode, Action<string> log)
        {
            string args = "/x " + productCode + " /qn /norestart";
            log("> msiexec.exe " + args);
            var start = new ProcessStartInfo
            {
                FileName = "msiexec.exe",
                Arguments = args,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            using (var proc = Process.Start(start))
            {
                if (proc == null)
                    return 1;
                proc.WaitForExit();
                log(proc.ExitCode == 0 ? "  done" : ("  exited " + proc.ExitCode));
                return proc.ExitCode;
            }
        }

        static bool RemoveMsiRegistry(string productCode, bool machineWide, Action<string> log)
        {
            bool ok = true;
            ok &= TryDeleteRegistry(Registry.CurrentUser, @"Software\Microsoft\Windows\CurrentVersion\Uninstall\" + productCode, log);
            ok &= TryDeleteInstallerProduct(Registry.CurrentUser, productCode, log);
            if (machineWide)
            {
                ok &= TryDeleteRegistry(Registry.LocalMachine, @"Software\Microsoft\Windows\CurrentVersion\Uninstall\" + productCode, log);
                ok &= TryDeleteInstallerProduct(Registry.LocalMachine, productCode, log);
            }
            return ok || !machineWide;
        }

        static bool TryDeleteInstallerProduct(RegistryKey hive, string productCode, Action<string> log)
        {
            string compressed = CompressMsiGuid(productCode);
            if (string.IsNullOrEmpty(compressed))
                return true;
            bool ok = true;
            ok &= TryDeleteRegistry(hive, @"Software\Microsoft\Installer\Products\" + compressed, log);
            ok &= TryDeleteRegistry(hive, @"Software\Classes\Installer\Products\" + compressed, log);
            ok &= TryDeleteRegistry(hive, @"Software\Microsoft\Installer\Features\" + compressed, log);
            return ok;
        }

        static bool TryDeleteRegistry(RegistryKey hive, string subKey, Action<string> log)
        {
            try
            {
                hive.DeleteSubKeyTree(subKey, false);
                log("Removed registry: " + subKey);
                return true;
            }
            catch (UnauthorizedAccessException)
            {
                log("Access denied removing registry: " + subKey);
                return false;
            }
            catch (IOException)
            {
                return true;
            }
            catch (ArgumentException)
            {
                return true;
            }
        }

        static string CompressMsiGuid(string guid)
        {
            string g = (guid ?? "").Trim('{', '}').Replace("-", "");
            if (g.Length != 32)
                return null;
            return g.Substring(6, 2) + g.Substring(4, 2) + g.Substring(2, 2) + g.Substring(0, 2)
                + g.Substring(10, 2) + g.Substring(8, 2)
                + g.Substring(14, 2) + g.Substring(12, 2)
                + g.Substring(16);
        }

        static void RunProcess(string fileName, string args, Action<string> log)
        {
            log("> " + fileName + " " + args);
            var start = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = args,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            using (var proc = Process.Start(start))
            {
                if (proc == null)
                    return;
                proc.WaitForExit();
                log(proc.ExitCode == 0 ? "  done" : ("  exited " + proc.ExitCode));
            }
        }

        static string Quote(string value)
        {
            if (string.IsNullOrEmpty(value))
                return "\"\"";
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }
    }
}
