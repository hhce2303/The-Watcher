"""Offscreen QML *runtime* smoke test for the editor tab.

Goes beyond qml_smoke.py (which only checks type resolution): it actually
*instantiates* VideoEditor.qml + FullscreenPlayer.qml with a real EditorBridge
and a stub AppBridge as context properties, so binding/JS errors in the new
reel/zoom/fullscreen wiring surface as QML warnings.

Run:  python project/tests/qml_runtime_smoke.py
Exit: 0 = instantiated with no QML warnings, 1 = warnings found.

NOTE: not test_*.py on purpose — needs a QGuiApplication (collides with the
QCoreApplication session fixture used by pytest).
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import PySide6  # noqa: E402

_PYSIDE6_DIR = pathlib.Path(PySide6.__file__).parent
_PLATFORMS = _PYSIDE6_DIR / "plugins" / "platforms"
if hasattr(os, "add_dll_directory") and _PYSIDE6_DIR.exists():
    os.add_dll_directory(str(_PYSIDE6_DIR))
if _PLATFORMS.exists():
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_PLATFORMS))
    os.environ.setdefault("QT_PLUGIN_PATH", str(_PYSIDE6_DIR / "plugins"))

# Make the app package importable (project/ root).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Property, QMetaObject, Q_ARG, Qt, QObject, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402

from app.adapters.ui.editor_bridge import EditorBridge  # noqa: E402

_UI_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "adapters" / "ui"


class _StubAppBridge(QObject):
    """Minimal stand-in for AppBridge — only what VideoEditor reads.

    Mirrors the real AppBridge's change-signal contract so VideoEditor's
    ``Connections { target: AppBridge; onCurrentClipPathChanged }`` resolves.
    """

    currentClipPathChanged = Signal()
    currentClipInfoChanged = Signal()

    @Property(str, notify=currentClipPathChanged)
    def currentClipPath(self) -> str:
        return ""

    @Property("QVariantMap", notify=currentClipInfoChanged)
    def currentClipInfo(self) -> dict:
        return {"durationSeconds": 12.0, "fps": "30", "codec": "h264"}

    @Slot(str, result=str)
    def mediaUrl(self, p: str) -> str:
        return ""

    @Slot(str)
    def loadClip(self, p: str) -> None:
        # VideoEditor.loadReelClip() calls this when opening a reel clip.
        pass


_ERR_MARKERS = ("ReferenceError", "TypeError", "is not a function",
                "Unable to assign", "Cannot read property", "undefined")


def main() -> int:
    app = QGuiApplication([])  # noqa: F841
    engine = QQmlEngine()
    engine.addImportPath(str(_PYSIDE6_DIR / "qml"))
    engine.addImportPath(str(_UI_DIR))

    warnings: list[str] = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))

    editor_bridge = EditorBridge()
    # Exercise the reel bindings with real data.
    editor_bridge.addClip("C:/clips/a.mp4", 10.0)
    editor_bridge.addClip("C:/clips/b.mp4", 20.0)

    stub_app = _StubAppBridge()
    engine.rootContext().setContextProperty("EditorBridge", editor_bridge)
    engine.rootContext().setContextProperty("AppBridge", stub_app)

    objects = []
    for rel in ("qml/FullscreenPlayer.qml", "qml/VideoEditor.qml"):
        path = _UI_DIR / rel
        comp = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
        obj = comp.create()
        compile_errors = [e.toString() for e in comp.errors()]
        if compile_errors:
            print(f"[COMPILE-ERROR] {rel}")
            for e in compile_errors:
                print(f"    {e}")
            warnings.extend(compile_errors)
        else:
            print(f"[INSTANTIATED] {rel} (obj={'ok' if obj else 'None'})")
        objects.append(obj)

    app.processEvents()

    # Exercise the multi-clip reel↔editor path (the closest thing to a click in
    # a headless harness): open each reel clip and confirm no JS/binding error.
    editor = objects[-1]
    if editor is not None:
        for i in (0, 1):
            QMetaObject.invokeMethod(editor, "openReelClip",
                                     Qt.DirectConnection, Q_ARG("QVariant", i))
            app.processEvents()

    relevant = [w for w in warnings if any(m in w for m in _ERR_MARKERS)]
    print(f"\nRELEVANT_WARNINGS={len(relevant)}")
    for w in relevant:
        print(f"    {w}")
    return 1 if relevant else 0


if __name__ == "__main__":
    sys.exit(main())
