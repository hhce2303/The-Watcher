"""EditorBridge — Python↔QML bridge for the evidence-reel editor (R-1, R-5).

Wraps a :class:`EditTimeline` and an :class:`EditorExportPort`, exposing the reel
to QML as a list model plus slots for add/remove/move/trim/clear/export.

Per AGENTS.md, a QObject must NOT also inherit from an ABC (Qt/ABCMeta clash):
this bridge *uses* the port by composition; it does not implement one.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from PySide6.QtCore import Property, QObject, Signal, Slot

from app.core.analytics.sidecar import read_sidecar
from app.core.editor.models import ClipEntry, EditTimeline
from app.core.editor.sequencer import TimelineSequencer
from app.core.ports.clip_inspector_port import ClipInspectorPort
from app.core.ports.editor_export_port import EditorExportPort


class EditorBridge(QObject):
    """Owns the editing-tab timeline and drives lossless reel export."""

    timelineChanged = Signal()
    exportStarted   = Signal()
    exportProgress  = Signal(float)   # 0.0 – 1.0
    exportFinished  = Signal(str)     # output path
    exportFailed    = Signal(str)     # human-readable error

    def __init__(
        self,
        export_port: Optional[EditorExportPort] = None,
        clips_dir: Optional[Path] = None,
        inspector: Optional[ClipInspectorPort] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._timeline = EditTimeline()
        self._export_port = export_port
        self._clips_dir = Path(clips_dir) if clips_dir else None
        # ffprobe inspector — used by addFilesFromUrls to learn each picked
        # file's duration (the reel needs source_duration_s for fractions).
        self._inspector = inspector
        self._exporting = False

    # ── Exposed state ─────────────────────────────────────────────────
    @Property("QVariantList", notify=timelineChanged)
    def clips(self) -> list:
        """Reel contents for the QML Repeater/ListView."""
        out = []
        for i, c in enumerate(self._timeline.clips):
            out.append(
                {
                    "index": i,
                    "sourcePath": str(c.source_path),
                    "fileName": c.source_path.name,
                    "sourceDuration": c.source_duration_s,
                    "inPoint": c.in_point_s,
                    "outPoint": c.out_point_s,
                    "trimmedDuration": c.trimmed_duration_s,
                }
            )
        return out

    @Property(float, notify=timelineChanged)
    def totalDuration(self) -> float:
        return self._timeline.total_duration_s

    @Property(int, notify=timelineChanged)
    def count(self) -> int:
        return len(self._timeline)

    @Property(bool, notify=exportStarted)
    def exporting(self) -> bool:
        return self._exporting

    # ── Mutations (called from QML) ───────────────────────────────────
    @Slot(str, float)
    def addClip(self, path: str, duration_s: float) -> None:
        """Append a clip at full length. *duration_s* comes from ffprobe."""
        self._timeline.add(ClipEntry(Path(path), float(duration_s)))
        logger.debug("[editor] +clip {} ({:.1f}s) → {} total", Path(path).name, duration_s, len(self._timeline))
        self.timelineChanged.emit()

    @Slot(str, float, float, float)
    def addClipTrimmed(self, path: str, duration_s: float, in_frac: float, out_frac: float) -> None:
        """Append a clip already trimmed to the editor's IN/OUT marks (0..1 fractions).

        Lets the ＋ button capture the marks the user just set in the preview,
        instead of always adding the whole source and trimming as a second step.
        """
        dur = float(duration_s)
        self._timeline.add(ClipEntry(Path(path), dur, in_frac * dur, out_frac * dur))
        logger.debug(
            "[editor] +clip {} [{:.0%}–{:.0%} of {:.1f}s] → {} total",
            Path(path).name, in_frac, out_frac, dur, len(self._timeline),
        )
        self.timelineChanged.emit()

    @Slot("QVariantList", result=int)
    def addFilesFromUrls(self, urls: list) -> int:
        """Add one or more picked files (file:// URLs or paths) to the reel.

        Probes each file's duration with the inspector and appends it at full
        length. Files that cannot be probed (corrupt / unreadable / zero length)
        are skipped with a warning rather than poisoning the reel with a clip
        that would fail export. Returns the index of the first clip added, or
        ``-1`` if nothing was added.
        """
        first = -1
        for raw in urls or []:
            path = self._to_local_path(raw)
            if not path:
                continue
            dur = self._probe_duration(path)
            if dur <= 0:
                logger.warning("[editor] skipping un-probeable / zero-length file: {}", path)
                continue
            idx = self._timeline.add(ClipEntry(path, dur))
            if first < 0:
                first = idx
            logger.debug("[editor] +file {} ({:.1f}s)", path.name, dur)
        if first >= 0:
            self.timelineChanged.emit()
        return first

    @staticmethod
    def _to_local_path(raw: object) -> Optional[Path]:
        """Normalise a QML-supplied url/string into a local filesystem Path."""
        from PySide6.QtCore import QUrl  # noqa: PLC0415
        if isinstance(raw, QUrl):
            return Path(raw.toLocalFile())
        s = str(raw)
        if s.startswith("file:"):
            return Path(QUrl(s).toLocalFile())
        return Path(s) if s else None

    def _probe_duration(self, path: Path) -> float:
        """Return the file's duration in seconds (0.0 if it cannot be probed)."""
        if self._inspector is None:
            logger.error("[editor] no inspector configured — cannot probe {}", path)
            return 0.0
        try:
            return float(self._inspector.inspect(path).duration_seconds)
        except Exception as exc:  # noqa: BLE001
            # Expected for non-media / unreadable picks — warn, don't dump a
            # full traceback (the caller skips the file and warns too).
            logger.warning("[editor] failed to probe {}: {}", path, exc)
            return 0.0

    @Slot(int)
    def removeClip(self, index: int) -> None:
        try:
            self._timeline.remove(index)
        except IndexError:
            logger.warning("[editor] removeClip: bad index {}", index)
            return
        self.timelineChanged.emit()

    @Slot(int, int)
    def moveClip(self, src: int, dst: int) -> None:
        try:
            self._timeline.move(src, dst)
        except IndexError:
            logger.warning("[editor] moveClip: bad src {}", src)
            return
        self.timelineChanged.emit()

    @Slot(int, float, float)
    def setTrim(self, index: int, in_point_s: float, out_point_s: float) -> None:
        """Set a clip's IN/OUT in seconds."""
        if 0 <= index < len(self._timeline):
            self._timeline.set_trim(index, in_point_s, out_point_s)
            self.timelineChanged.emit()

    @Slot(int, float, float)
    def setTrimFraction(self, index: int, in_frac: float, out_frac: float) -> None:
        """Set a clip's IN/OUT as 0..1 fractions (matches VideoEditor's marks)."""
        if 0 <= index < len(self._timeline):
            dur = self._timeline[index].source_duration_s
            self._timeline.set_trim(index, in_frac * dur, out_frac * dur)
            self.timelineChanged.emit()

    @Slot()
    def clear(self) -> None:
        self._timeline.clear()
        self.timelineChanged.emit()

    # ── Sequencer helpers (for the QML playhead) ──────────────────────
    @Slot(float, result="QVariantMap")
    def locate(self, global_pos_s: float) -> dict:
        """Map a reel-global position to ``{index, localPos, sourcePath}`` (empty if none)."""
        hit = TimelineSequencer(self._timeline).locate(global_pos_s)
        if hit is None:
            return {}
        index, local = hit
        return {
            "index": index,
            "localPos": local,
            "sourcePath": str(self._timeline[index].source_path),
        }

    # ── Event markers (Fase 1) ────────────────────────────────────────
    @Slot(str, result="QVariantList")
    def eventsForClip(self, clip_path: str) -> list:
        """Return the analytic events recorded in *clip_path*'s sidecar.

        The editor uses this to paint timeline markers. Empty if no sidecar.
        """
        out = []
        for ev in read_sidecar(Path(clip_path)):
            out.append(
                {
                    "eventId": ev.event_id,
                    "type": ev.type,
                    "source": ev.source,
                    "start": ev.start.isoformat(),
                    "end": ev.end.isoformat(),
                    "confidence": ev.confidence if ev.confidence is not None else -1.0,
                }
            )
        return out

    # ── Export ────────────────────────────────────────────────────────
    def _default_output_path(self) -> Optional[Path]:
        """Build a timestamped reel path under ``clips_dir`` (None if unset)."""
        if self._clips_dir is None:
            return None
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return self._clips_dir / f"reel_{stamp}.mp4"

    @Slot()
    def exportReel(self) -> None:
        """Export to an auto-named file under ``clips_dir`` (UI convenience)."""
        out = self._default_output_path()
        if out is None:
            self.exportFailed.emit("No hay carpeta de salida configurada.")
            return
        self.exportTimeline(str(out))

    @Slot(str)
    def exportTimeline(self, output_path: str) -> None:
        """Validate then export the reel on a background thread (signals report progress)."""
        if self._exporting:
            logger.warning("[editor] export already in progress")
            return
        if self._export_port is None:
            self.exportFailed.emit("No hay motor de exportación configurado.")
            return
        errors = self._timeline.validate()
        if errors:
            self.exportFailed.emit(" ".join(errors))
            return
        self._exporting = True
        self.exportStarted.emit()
        threading.Thread(
            target=self._do_export, args=(output_path,), daemon=True,
            name="editor-export",
        ).start()

    def _do_export(self, output_path: str) -> None:
        try:
            self._export_port.export(
                self._timeline, Path(output_path), on_progress=self.exportProgress.emit
            )
            self.exportFinished.emit(output_path)
            logger.info("[editor] export finished: {}", output_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[editor] export failed")
            self.exportFailed.emit(str(exc))
        finally:
            self._exporting = False
