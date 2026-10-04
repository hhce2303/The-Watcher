"""The LAN firewall rule is created by one versioned script, never ad hoc.

Pilot stations are domain-joined, so a Private-only rule silently does not
apply. Static checks: the behaviour itself is Windows-only.
"""
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "installer"
SCRIPT = INSTALLER / "watcher-firewall.ps1"
LAUNCHER = INSTALLER / "Configurar firewall.cmd"


def test_firewall_script_and_double_click_launcher_exist():
    assert SCRIPT.is_file()
    assert LAUNCHER.is_file()
    assert "watcher-firewall.ps1" in LAUNCHER.read_text(encoding="utf-8")


def test_firewall_script_covers_domain_and_private_but_never_public():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "'Domain', 'Private'" in text
    assert "Profile     = 'Public'" not in text
    assert "8767" in text


def test_firewall_script_locates_exe_next_to_itself_not_via_localappdata():
    # Elevating with an IT account would resolve LOCALAPPDATA to that profile.
    text = SCRIPT.read_text(encoding="utf-8")
    assert "$PSScriptRoot" in text
    assert "$env:LOCALAPPDATA" not in text


def test_firewall_script_has_utf8_bom_for_windows_powershell():
    # PowerShell 5.1 reads BOM-less UTF-8 as ANSI and mangles the accents.
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_installer_ships_and_runs_the_script_instead_of_inline_netsh():
    iss = (INSTALLER / "The Watcher.iss").read_text(encoding="utf-8")
    assert "profile=private" not in iss
    assert "watcher-firewall.ps1" in iss
    build = (INSTALLER / "build.ps1").read_text(encoding="utf-8")
    assert "watcher-firewall.ps1" in build
    assert "Configurar firewall.cmd" in build
