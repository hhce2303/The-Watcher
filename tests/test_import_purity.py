"""Import-purity gate (spec section 6).

The daemon must never import editor, player, analytics, cloud-share, role/IPC,
Qt or Tauri code. Two complementary checks:

* static: every import statement in app/ at any depth, including lazy
  ``# noqa: PLC0415`` imports inside functions and ``importlib.import_module``
  string literals;
* dynamic: run the real headless startup (``run_daemon``) in a clean
  interpreter and inspect ``sys.modules`` afterwards.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"

FORBIDDEN_PREFIXES = (
    # UI toolkits
    "PySide6", "PySide2", "PyQt5", "PyQt6", "shiboken6", "tauri", "tkinter",
    # monorepo areas that are not part of the daemon
    "app.core.api", "app.core.editor", "app.core.player", "app.core.analytics",
    "app.core.cloud_share_service", "app.core.event_service", "app.core.auto_event_service",
    "app.core.role", "app.core.policy",
    "app.adapters.ipc", "app.adapters.ws", "app.adapters.cloud", "app.adapters.ml",
    "app.adapters.storage", "app.adapters.preview_server",
    "app.adapters.browser_local.server",
    "app.main", "app.runtime.backend", "app.runtime.mode",
    # heavy ML / unused third-party stacks
    "onnxruntime", "numpy", "PIL", "websockets",
)


def _is_forbidden(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES)


def _imports_in(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    package = ".".join(path.relative_to(REPO).with_suffix("").parts[:-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
            mod = ".".join(base + ([node.module] if node.module else []))
            found.append((node.lineno, mod))
            found += [(node.lineno, f"{mod}.{a.name}") for a in node.names]
            continue
        if isinstance(node, ast.Import):
            found += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
            found += [(node.lineno, f"{node.module}.{a.name}") for a in node.names]
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append((node.lineno, arg.value))
    return found


def test_no_forbidden_import_statement_anywhere_in_app() -> None:
    offenders = [
        f"{path.relative_to(REPO)}:{line} imports {module}"
        for path in sorted(APP.rglob("*.py"))
        for line, module in _imports_in(path)
        if _is_forbidden(module)
    ]
    assert not offenders, "forbidden imports (incl. lazy ones):\n" + "\n".join(offenders)


def test_static_scan_actually_sees_lazy_imports() -> None:
    # Guard the guard: the scanner must find function-level imports.
    feed = APP / "adapters" / "live_view_lan" / "h264_feed.py"  # both imports are function-level
    modules = {m for _, m in _imports_in(feed)}
    assert "app.adapters.ffmpeg.process_guard" in modules
    assert "app.adapters.ffmpeg.encoder_selector" in modules
    # relative imports are resolved against the package, not skipped
    assert any(m.startswith("app.") for m in {m for _, m in _imports_in(APP / "daemon_root.py")})


def test_relative_imports_are_resolved(tmp_path) -> None:
    f = APP / "_probe_tmp.py"
    f.write_text("from .core.api import dto\n", encoding="utf-8")
    try:
        assert any(_is_forbidden(m) for _, m in _imports_in(f))
    finally:
        f.unlink()


_BOOT_SCRIPT = textwrap.dedent(
    """
    import json, sys, threading, time
    from pathlib import Path

    sys.path.insert(0, {repo!r})
    from app import daemon_root
    from app.core.ports.monitor_port import MonitorPort
    from app.core.recording_service.models import MonitorInfo
    from app.infrastructure.config import Settings
    from app.runtime import instance

    class Port(MonitorPort):
        def list_monitors(self):
            return [MonitorInfo(name="D1", width=1280, height=720, x=0, y=0, is_primary=True, index=0)]

    root = Path({root!r})
    s = Settings()
    s.segment_dir = root / "segments"
    s.clips_dir = root / "clips"
    s.raw_clips_dir = root / "clips_raw"
    s.event_clips_dir = root / "clips_events"
    s.live_view_enabled = True          # exercises LiveViewLanAdapter + TLS bundle path
    s.tls_provisioning_mode = "file"    # no cert configured: must fail soft, never block

    state = root
    result = {{}}
    th = threading.Thread(
        target=lambda: result.setdefault("code", daemon_root.run_daemon(
            s, monitor_port=Port(), start_recording=False, install_signals=False,
            poll_seconds=0.05, register_launcher=False)),
        daemon=True,
    )
    th.start()
    deadline = time.time() + 20
    while time.time() < deadline and instance.read_status(state) is None:
        time.sleep(0.05)
    booted = instance.read_status(state) is not None
    instance.request_stop(state)
    th.join(20)
    print(json.dumps({{"booted": booted, "code": result.get("code"), "modules": sorted(sys.modules)}}))
    """
)


def test_headless_startup_imports_nothing_forbidden(tmp_path) -> None:
    # Keep the real environment: on Windows Python needs SYSTEMROOT etc. to start.
    env = {**os.environ, "LOG_LEVEL": "WARNING", "WATCHER_LOG_DIR": str(tmp_path / "logs"),
           "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "LOCALAPPDATA": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, "-c", _BOOT_SCRIPT.format(repo=str(REPO), root=str(tmp_path))],
        capture_output=True, text=True, timeout=90, env=env, cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["booted"] is True and payload["code"] == 0
    modules = payload["modules"]
    # The boot really went through the daemon surface...
    for expected in ("app.daemon_root", "app.daemon_api", "app.adapters.live_view_lan.server",
                     "app.core.recording_service.service", "app.adapters.browser_local.auth"):
        assert expected in modules, f"{expected} not imported - boot did not exercise it"
    # ...and pulled in nothing from the forbidden set.
    offenders = sorted(m for m in modules if _is_forbidden(m))
    assert not offenders, f"forbidden modules imported at runtime: {offenders}"
