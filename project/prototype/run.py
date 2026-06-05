"""
QML UI Prototype — The Watcher
Run: python prototype/run.py
"""
from __future__ import annotations
import sys, os, pathlib

try:
    import PySide6
    _dir = pathlib.Path(PySide6.__file__).parent
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(_dir))
    _plugins = _dir / "plugins"
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_plugins / "platforms"))
    _cur = os.environ.get("QT_PLUGIN_PATH", "")
    _pp  = str(_plugins)
    if _pp not in _cur:
        os.environ["QT_PLUGIN_PATH"] = _pp + (os.pathsep + _cur if _cur else "")
except ImportError:
    pass

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl

app = QGuiApplication(sys.argv)
engine = QQmlApplicationEngine()
qml_path = pathlib.Path(__file__).parent / "Main.qml"
engine.addImportPath(str(pathlib.Path(__file__).parent))
engine.load(QUrl.fromLocalFile(str(qml_path.resolve())))
if not engine.rootObjects():
    sys.exit(-1)
sys.exit(app.exec())
