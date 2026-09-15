using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

namespace Bob
{
    /// <summary>
    /// Self-contained installer payload appended to BobSetup.exe at build time.
    /// Trailer (24 bytes at EOF): manifest offset (8) + manifest length (8) + magic (8).
    /// </summary>
    static class EmbeddedPayload
    {
        const string Magic = "BOBPAY01";
        const int TrailerSize = 24;

        sealed class ManifestFile
        {
            public string name;
            public long offset;
            public long length;
        }

        sealed class Manifest
        {
            public int version;
            public string hash;
            public List<ManifestFile> files = new List<ManifestFile>();
        }

        public static string ResolvePayloadDir(string exePath)
        {
            if (string.IsNullOrEmpty(exePath) || !File.Exists(exePath))
                return Path.GetDirectoryName(exePath) ?? AppDomain.CurrentDomain.BaseDirectory;

            Manifest manifest;
            if (!TryReadManifest(exePath, out manifest))
                return Path.GetDirectoryName(exePath) ?? AppDomain.CurrentDomain.BaseDirectory;

            string cacheRoot = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "BOB",
                "setup",
                "payload-cache");
            string cacheDir = Path.Combine(cacheRoot, manifest.hash ?? "unknown");
            if (IsCacheComplete(cacheDir, manifest))
                return cacheDir;

            Directory.CreateDirectory(cacheDir);
            ExtractFiles(exePath, manifest, cacheDir);
            return cacheDir;
        }

        static bool TryReadManifest(string exePath, out Manifest manifest)
        {
            manifest = null;
            try
            {
                using (var stream = new FileStream(exePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    if (stream.Length < TrailerSize)
                        return false;
                    stream.Seek(-TrailerSize, SeekOrigin.End);
                    var trailer = new byte[TrailerSize];
                    if (stream.Read(trailer, 0, TrailerSize) != TrailerSize)
                        return false;
                    long manifestOffset = BitConverter.ToInt64(trailer, 0);
                    long manifestLength = BitConverter.ToInt64(trailer, 8);
                    string magic = Encoding.ASCII.GetString(trailer, 16, 8);
                    if (!string.Equals(magic, Magic, StringComparison.Ordinal))
                        return false;
                    if (manifestOffset < 0 || manifestLength <= 0
                        || manifestOffset + manifestLength > stream.Length - TrailerSize)
                        return false;
                    stream.Seek(manifestOffset, SeekOrigin.Begin);
                    var jsonBytes = new byte[manifestLength];
                    if (stream.Read(jsonBytes, 0, (int)manifestLength) != manifestLength)
                        return false;
                    string json = Encoding.UTF8.GetString(jsonBytes);
                    var serializer = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
                    manifest = serializer.Deserialize<Manifest>(json);
                    return manifest != null && manifest.files != null && manifest.files.Count > 0;
                }
            }
            catch
            {
                manifest = null;
                return false;
            }
        }

        static bool IsCacheComplete(string cacheDir, Manifest manifest)
        {
            if (!Directory.Exists(cacheDir))
                return false;
            foreach (var entry in manifest.files)
            {
                if (string.IsNullOrEmpty(entry.name))
                    return false;
                var path = Path.Combine(cacheDir, entry.name);
                if (!File.Exists(path))
                    return false;
                var info = new FileInfo(path);
                if (info.Length != entry.length)
                    return false;
            }
            return true;
        }

        static void ExtractFiles(string exePath, Manifest manifest, string cacheDir)
        {
            using (var stream = new FileStream(exePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                foreach (var entry in manifest.files)
                {
                    if (string.IsNullOrEmpty(entry.name) || entry.length <= 0)
                        throw new InvalidDataException("Invalid embedded payload entry.");
                    string dest = Path.Combine(cacheDir, entry.name);
                    string parent = Path.GetDirectoryName(dest);
                    if (!string.IsNullOrEmpty(parent))
                        Directory.CreateDirectory(parent);
                    stream.Seek(entry.offset, SeekOrigin.Begin);
                    using (var output = new FileStream(dest, FileMode.Create, FileAccess.Write, FileShare.None))
                    {
                        CopyBytes(stream, output, entry.length);
                    }
                }
            }
        }

        static void CopyBytes(Stream input, Stream output, long length)
        {
            var buffer = new byte[65536];
            long remaining = length;
            while (remaining > 0)
            {
                int read = input.Read(buffer, 0, (int)Math.Min(buffer.Length, remaining));
                if (read <= 0)
                    throw new EndOfStreamException("Embedded payload is truncated.");
                output.Write(buffer, 0, read);
                remaining -= read;
            }
        }

        public static string ComputePayloadHash(IEnumerable<string> filePaths)
        {
            using (var sha = SHA256.Create())
            {
                foreach (var path in filePaths)
                {
                    var nameBytes = Encoding.UTF8.GetBytes(Path.GetFileName(path) ?? "");
                    sha.TransformBlock(nameBytes, 0, nameBytes.Length, null, 0);
                    using (var stream = File.OpenRead(path))
                    {
                        var buffer = new byte[65536];
                        int read;
                        while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
                            sha.TransformBlock(buffer, 0, read, null, 0);
                    }
                }
                sha.TransformFinalBlock(new byte[0], 0, 0);
                var hash = sha.Hash ?? new byte[0];
                var text = new StringBuilder(hash.Length * 2);
                foreach (byte b in hash)
                    text.Append(b.ToString("x2"));
                return text.ToString();
            }
        }
    }
}
