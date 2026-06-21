"""Offscreen QML component-compile smoke test.

Loads each QML component through QQmlComponent under the offscreen platform and
fails on type-resolution errors (unavailable type / non-existent attached
object / not-a-type / bad assignment). This catches the class of error that
`pyside6-qmllint` silently passes — e.g. a missing `import QtQuick.Controls`
for an attached `ToolTip`.

Runtime ReferenceErrors for context properties (AppBridge / SettingsBridge) are
EXPECTED here (those are injected at app start, not at component-compile) and are
filtered out — we only care about type resolution.

Run:  python project/tests/qml_smoke.py
Exit: 0 = all components resolve, 1 = type errors found.

NOTE: not named test_*.py on purpose — it needs a QGuiApplication, which would
collide with the QCoreApplication session fixture used by the pytest suite.
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import PySide6  # noqa: E402

# Windows (Python 3.8+) uses a restricted DLL search path. Register the PySide6
# root and platform-plugin dir so the offscreen plugin DLL resolves its Qt6
# dependencies — same setup main.py does at startup. Without this, constructing
# QGuiApplication under offscreen hard-crashes (0xC0000409) instead of loading.
_PYSIDE6_DIR = pathlib.Path(PySide6.__file__).parent
_PLATFORMS = _PYSIDE6_DIR / "plugins" / "platforms"
if hasattr(os, "add_dll_directory") and _PYSIDE6_DIR.exists():
    os.add_dll_directory(str(_PYSIDE6_DIR))
if _PLATFORMS.exists():
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_PLATFORMS))
    os.environ.setdefault("QT_PLUGIN_PATH", str(_PYSIDE6_DIR / "plugins"))

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402

# project/tests/qml_smoke.py -> project/app/adapters/ui
_UI_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "adapters" / "ui"
_QML_DIR = _UI_DIR / "qml"

# Components touched by the editor enhancement + their key dependencies.
_FILES = [
    "qml/Tokens.qml",
    "qml/MonitorSelector.qml",
    "qml/ClipBrowser.qml",
    "qml/VideoEditor.qml",
    "qml/OutputPanel.qml",
    "qml/ITEditorView.qml",
    "qml/SettingsView.qml",
    "Main.qml",
]

_TYPE_ERR_MARKERS = (
    "unavailable",
    "Non-existent attached",
    "is not a type",
    "Cannot assign",
    "Expected type name",
)


def main() -> int:
    print("smoke: creating QGuiApplication...", flush=True)
    app = QGuiApplication([])  # noqa: F841 — must exist for QML engine
    print("smoke: creating QQmlEngine...", flush=True)
    engine = QQmlEngine()
    engine.addImportPath(str(pathlib.Path(PySide6.__file__).parent / "qml"))
    engine.addImportPath(str(_UI_DIR))  # makes the "Watcher" module + "." resolve
    print(f"smoke: import path = {_UI_DIR}", flush=True)

    total_type_errors = 0
    for rel in _FILES:
        print(f"smoke: loading {rel} ...", flush=True)
        path = _UI_DIR / rel
        comp = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
        errors = [e.toString() for e in comp.errors()]
        type_errors = [e for e in errors if any(m in e for m in _TYPE_ERR_MARKERS)]
        status = comp.status()
        flag = "OK" if not type_errors else "TYPE-ERRORS"
        print(f"[{flag}] {rel}  (status={status.name})", flush=True)
        for e in type_errors:
            print(f"    {e}", flush=True)
        total_type_errors += len(type_errors)

    print(f"\nTYPE_ERRORS_TOTAL={total_type_errors}", flush=True)
    return 1 if total_type_errors else 0


if __name__ == "__main__":
    sys.exit(main())
