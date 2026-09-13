from __future__ import annotations

from pathlib import Path

from app.tools.browser_local_enroll import _upsert_env_var, _find_mkcert


def test_upsert_env_var_appends_when_missing(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=1\n", encoding="utf-8")

    _upsert_env_var(env_path, "BROWSER_LOCAL_CERT_FILE", r"C:\certs\localhost.pem")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert "FOO=1" in lines
    assert r"BROWSER_LOCAL_CERT_FILE=C:\certs\localhost.pem" in lines


def test_upsert_env_var_replaces_commented_line(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("#BROWSER_LOCAL_CERT_FILE=placeholder\nOTHER=2\n", encoding="utf-8")

    _upsert_env_var(env_path, "BROWSER_LOCAL_CERT_FILE", r"C:\certs\localhost.pem")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert r"BROWSER_LOCAL_CERT_FILE=C:\certs\localhost.pem" in lines
    assert not any(line.startswith("#BROWSER_LOCAL_CERT_FILE=") for line in lines)
    assert "OTHER=2" in lines


def test_upsert_env_var_replaces_existing_uncommented_line(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("BROWSER_LOCAL_CERT_FILE=old.pem\n", encoding="utf-8")

    _upsert_env_var(env_path, "BROWSER_LOCAL_CERT_FILE", "new.pem")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert lines.count("BROWSER_LOCAL_CERT_FILE=new.pem") == 1


def test_upsert_env_var_creates_file_when_absent(tmp_path):
    env_path = tmp_path / ".env"

    _upsert_env_var(env_path, "BROWSER_LOCAL_DATA_DIR", r"C:\data")

    assert env_path.read_text(encoding="utf-8").strip() == r"BROWSER_LOCAL_DATA_DIR=C:\data"


def test_find_mkcert_prefers_bundled_binary(tmp_path, monkeypatch):
    import sys

    # PyInstaller's onedir contents-directory layout bundles binaries/ under
    # _MEIPASS (dist/The Watcher/_internal/), not next to the .exe itself --
    # see app/adapters/ffmpeg/ffmpeg_path.py, which resolves ffmpeg.exe the
    # same way.
    meipass_dir = tmp_path / "dist" / "The Watcher" / "_internal"
    (meipass_dir / "bin").mkdir(parents=True)
    bundled = meipass_dir / "bin" / "mkcert.exe"
    bundled.write_text("", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)

    assert _find_mkcert() == bundled


def test_find_mkcert_returns_none_when_not_found(monkeypatch):
    import sys
    import shutil

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    assert _find_mkcert() is None
