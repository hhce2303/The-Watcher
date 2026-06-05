from __future__ import annotations

import threading

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


class MonitorScreenshotProvider(QQuickImageProvider):
    """
    GDI-based live monitor preview for QML Image elements.

    QScreen.grabWindow() uses BitBlt (CPU path) and works on every monitor
    regardless of which GPU it is attached to — unlike ScreenCapture/WGC which
    fails for monitors on a secondary adapter.

    URL pattern used from QML:
        "image://monitor_preview/{monitor_idx}?{revision}"
    The revision query-string is a cache-busting counter so QML re-fetches
    the image every time AppBridge.previewRevision increments.
    """

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._lock = threading.Lock()
        self._images: dict[str, QImage] = {}

    def update(self, monitor_idx: int, image: QImage) -> None:
        """Called from the Qt main thread on each screenshot tick."""
        with self._lock:
            self._images[str(monitor_idx)] = image.copy()

    def requestImage(self, id: str, size: QSize, requestedSize: QSize) -> QImage:
        """Called by QML's Image engine (may be on a worker thread).

        PySide6 expects a plain QImage return — NOT a tuple.
        Qt infers the image size from the returned QImage automatically.
        """
        key = id.split("?")[0]
        with self._lock:
            img = self._images.get(key, QImage())
        if img.isNull():
            placeholder = QImage(4, 4, QImage.Format.Format_RGB32)
            placeholder.fill(0x050A18)
            return placeholder
        return img
