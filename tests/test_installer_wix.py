from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIX = ROOT / "installer" / "wix"


def test_wix_sources_are_well_formed():
    for name in ("Product.wxs", "Bundle.wxs", "Variables.wxi"):
        path = WIX / name
        assert path.is_file(), path
        ET.parse(path)


def test_product_uses_custom_installfolder_root():
    text = (WIX / "Product.wxs").read_text(encoding="utf-8")
    assert 'InstallScope="perUser"' in text
    assert '<Directory Id="INSTALLFOLDER" Name="BOB" />' in text
    assert "LocalAppDataFolder" not in text
    assert "SetRunPostInstall" not in text


def test_cleanup_script_exists():
    text = (ROOT / "cleanup-bob-installs.ps1").read_text(encoding="utf-8")
    assert "Find-BobInstallRoots" in text
    assert "Clear-DriveConfigMsi" in text
    assert "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall" in text
    assert "RegistryOnly" in text
    assert (ROOT / "installer" / "scripts" / "build.ps1").read_text(encoding="utf-8").count(
        "cleanup-bob-installs.ps1"
    ) >= 1


def test_installer_assets_and_scripts_exist():
    assert (ROOT / "installer" / "assets" / "license.rtf").is_file()
    assert (ROOT / "installer" / "scripts" / "build.ps1").is_file()
    assert (ROOT / "installer" / "scripts" / "prefetch-deps.ps1").is_file()
    assert (ROOT / "installer" / "runtime-deps.json").is_file()
    assert (ROOT / "installer" / "config.defaults.yaml").is_file()
    assert (ROOT / "packaging" / "setup_wizard.py").is_file()
    assert (ROOT / "packaging" / "bootstrap_models.py").is_file()
    assert (ROOT / "packaging" / "windows_install.py").is_file()
    assert (ROOT / "packaging" / "msi_postinstall.ps1").is_file()
    assert (ROOT / "packaging" / "download_runtime.ps1").is_file()
    assert (ROOT / "packaging" / "install_ollama.cs").is_file()
    assert (ROOT / "packaging" / "run_postinstall.cs").is_file()
    assert (ROOT / "packaging" / "bob_setup_ui.cs").is_file()
    assert (ROOT / "bob" / "ollama_pull.py").is_file()
    assert (ROOT / "bob" / "llm_recommend.py").is_file()


def test_build_script_builds_custom_setup_ui():
    text = (ROOT / "installer" / "scripts" / "build.ps1").read_text(encoding="utf-8")
    assert "bob_setup_ui.cs" in text
    assert "embedded_payload.cs" in text
    assert "pack_bob_setup.py" in text
    assert "BobSetup.exe" in text
    assert "WixBalExtension" not in text


def test_pack_bob_setup_script_exists():
    assert (ROOT / "packaging" / "pack_bob_setup.py").is_file()
    assert (ROOT / "packaging" / "embedded_payload.cs").is_file()
    assert (ROOT / "packaging" / "existing_installs.cs").is_file()


def test_runtime_manifest_lists_urls():
    import json

    data = json.loads((ROOT / "installer" / "runtime-deps.json").read_text(encoding="utf-8"))
    assert "python.org" in data["python"]["url"]
    assert "ollama" in data["ollama"]["url"].lower()
