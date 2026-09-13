"""Print the public enrolment material for Daily SIG Systems administrators.

Also (re)issues the browser-local loopback TLS certificate via mkcert and
patches the deployed .env with the resulting local facts, so a fresh deploy's
first run needs no manual TLS/identity setup — only the Daily-assigned
station_id/issuer key remain a manual follow-up (see ADR-0020).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.adapters.browser_local.identity import DeviceIdentityStore
from app.infrastructure.config import get_settings


def _find_mkcert() -> Path | None:
    """Resolve mkcert.exe: bundled bin/ (frozen build) > PATH."""
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).parent / "bin" / "mkcert.exe"
        if bundled.is_file():
            return bundled
    found = shutil.which("mkcert")
    return Path(found) if found else None


def _restrict_key_to_current_user(key: Path) -> None:
    username = os.environ.get("USERNAME")
    if not username or os.name != "nt":
        return
    try:
        subprocess.run(
            ["icacls", str(key), "/inheritance:r", "/grant:r", f"{username}:(R,W)"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:  # noqa: BLE001 -- best-effort, never block enrollment
        pass


def _ensure_certificate(data_dir: Path) -> tuple[Path, Path] | None:
    """Create the loopback TLS cert via mkcert if missing. Returns (cert, key) or None."""
    cert = data_dir / "localhost.pem"
    key = data_dir / "localhost-key.pem"
    if cert.is_file() and key.is_file():
        return cert, key
    mkcert = _find_mkcert()
    if mkcert is None:
        print(
            "WARNING: mkcert.exe not found -- skipping TLS certificate generation.",
            file=sys.stderr,
        )
        print("  Install it with: winget install FiloSottile.mkcert", file=sys.stderr)
        return None
    data_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(mkcert), "-install"], check=True, capture_output=True, text=True)
    subprocess.run(
        [
            str(mkcert),
            "-cert-file", str(cert),
            "-key-file", str(key),
            "localhost", "127.0.0.1", "::1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    _restrict_key_to_current_user(key)
    return cert, key


def _cert_fingerprint(cert_path: Path) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    digest = cert.fingerprint(hashes.SHA256())
    return ":".join(f"{byte:02X}" for byte in digest)


def _upsert_env_var(env_path: Path, key: str, value: str) -> None:
    """Set KEY=value in a .env file, replacing an existing (commented or not) line."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []
    prefix_plain = f"{key}="
    prefix_commented = f"#{key}="
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(prefix_plain) or stripped.startswith(prefix_commented):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _env_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / ".env"
    return Path(".env")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--station-id",
        type=int,
        default=None,
        help="Daily-assigned station id; when given, also enables the browser-local channel.",
    )
    parser.add_argument("--issuer-kid", default=None, help="Daily's signing-key id.")
    parser.add_argument(
        "--issuer-public-key-file",
        default=None,
        help="Path to Daily's Ed25519 issuer public key PEM.",
    )
    args = parser.parse_args()

    settings = get_settings()
    data_dir = settings.browser_local_data_dir
    identity = DeviceIdentityStore(data_dir).load_or_create()
    cert_files = _ensure_certificate(data_dir)

    env_path = _env_path()
    if cert_files is not None:
        cert, key = cert_files
        _upsert_env_var(env_path, "BROWSER_LOCAL_CERT_FILE", str(cert))
        _upsert_env_var(env_path, "BROWSER_LOCAL_KEY_FILE", str(key))
    _upsert_env_var(env_path, "BROWSER_LOCAL_DATA_DIR", str(data_dir))

    if args.station_id is not None:
        _upsert_env_var(env_path, "BROWSER_LOCAL_STATION_ID", str(args.station_id))
        if args.issuer_kid:
            _upsert_env_var(env_path, "BROWSER_LOCAL_ISSUER_KID", args.issuer_kid)
        if args.issuer_public_key_file:
            _upsert_env_var(
                env_path, "BROWSER_LOCAL_ISSUER_PUBLIC_KEY_FILE", args.issuer_public_key_file
            )
        _upsert_env_var(env_path, "BROWSER_LOCAL_ENABLED", "true")

    report: dict[str, str] = dict(identity.enrollment_payload())
    if cert_files is not None:
        report["certificate_fingerprint_sha256"] = _cert_fingerprint(cert_files[0])
        report["certificate_file"] = str(cert_files[0])

    print("=" * 70)
    print("The Watcher -- Daily SIG Systems enrollment material")
    print("=" * 70)
    print(json.dumps(report, indent=2))
    print()
    if args.station_id is None:
        print("NEXT STEP: paste device_id + public_key_pem into SIGDailyReport's admin")
        print("panel. Once Daily assigns a station id and issuer key, re-run:")
        print('  "The Watcher Enroll.exe" --station-id <N> --issuer-kid <KID> \\')
        print("      --issuer-public-key-file <path-to-daily-issuer-public.pem>")
    else:
        print(f"BROWSER_LOCAL_ENABLED=true written to {env_path} (station_id={args.station_id}).")
    print("=" * 70)


if __name__ == "__main__":
    main()
