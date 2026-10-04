"""Daily enrollment data comes from one versioned script, never ad hoc.

The script must only ever expose public identity fields. Static checks: the
behaviour itself is Windows-only.
"""
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "installer"
SCRIPT = INSTALLER / "watcher-enrollment.ps1"
LAUNCHER = INSTALLER / "Datos de enrolamiento.cmd"


def test_enrollment_script_and_double_click_launcher_exist():
    assert SCRIPT.is_file()
    assert LAUNCHER.is_file()
    assert "watcher-enrollment.ps1" in LAUNCHER.read_text(encoding="utf-8")


def test_enrollment_script_never_reads_out_the_private_key():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "private_key_pem" not in text
    assert "public_key_pem" in text
    assert "device_id" in text


def test_enrollment_script_reads_station_from_installed_profile():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "$PSScriptRoot" in text
    assert "LIVE_VIEW_STATION_ID" in text
    assert "BROWSER_LOCAL_DATA_DIR" in text


def test_enrollment_script_has_utf8_bom_for_windows_powershell():
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_installer_ships_enrollment_script_with_start_menu_shortcut():
    iss = (INSTALLER / "The Watcher.iss").read_text(encoding="utf-8")
    assert "Datos de enrolamiento.cmd" in iss
    build = (INSTALLER / "build.ps1").read_text(encoding="utf-8")
    assert "watcher-enrollment.ps1" in build
    assert "Datos de enrolamiento.cmd" in build
