"""
Unit tests — Fase 0 (R-1, R-5): EditorBridge QML bridge.

Uses the session ``qt_app`` fixture (QCoreApplication) so QObject signals work.
Export is verified via the synchronous ``_do_export`` with a mocked port.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.adapters.ui.editor_bridge import EditorBridge
from app.core.ports.editor_export_port import EditorExportPort


@pytest.fixture
def bridge(qt_app) -> EditorBridge:
    return EditorBridge()


class TestTimelineSlots:
    def test_add_and_count(self, bridge: EditorBridge) -> None:
        bridge.addClip("a.mp4", 10.0)
        bridge.addClip("b.mp4", 20.0)
        assert bridge.count == 2
        assert bridge.totalDuration == 30.0

    def test_clips_property_shape(self, bridge: EditorBridge) -> None:
        bridge.addClip("dir/a.mp4", 12.0)
        clip = bridge.clips[0]
        assert clip["fileName"] == "a.mp4"
        assert clip["sourceDuration"] == 12.0
        assert clip["inPoint"] == 0.0
        assert clip["outPoint"] == 12.0
        assert clip["trimmedDuration"] == 12.0

    def test_remove(self, bridge: EditorBridge) -> None:
        bridge.addClip("a.mp4", 10.0)
        bridge.removeClip(0)
        assert bridge.count == 0

    def test_remove_bad_index_noop(self, bridge: EditorBridge) -> None:
        bridge.removeClip(5)  # no raise
        assert bridge.count == 0

    def test_move(self, bridge: EditorBridge) -> None:
        for n in ("a", "b", "c"):
            bridge.addClip(f"{n}.mp4", 10.0)
        bridge.moveClip(0, 2)
        assert [c["fileName"] for c in bridge.clips] == ["b.mp4", "c.mp4", "a.mp4"]

    def test_set_trim_seconds(self, bridge: EditorBridge) -> None:
        bridge.addClip("a.mp4", 10.0)
        bridge.setTrim(0, 2.0, 7.0)
        assert bridge.clips[0]["trimmedDuration"] == 5.0

    def test_set_trim_fraction(self, bridge: EditorBridge) -> None:
        bridge.addClip("a.mp4", 10.0)
        bridge.setTrimFraction(0, 0.2, 0.8)
        assert bridge.clips[0]["inPoint"] == pytest.approx(2.0)
        assert bridge.clips[0]["outPoint"] == pytest.approx(8.0)

    def test_clear(self, bridge: EditorBridge) -> None:
        bridge.addClip("a.mp4", 10.0)
        bridge.clear()
        assert bridge.count == 0

    def test_timeline_changed_signal(self, bridge: EditorBridge) -> None:
        fired = []
        bridge.timelineChanged.connect(lambda: fired.append(True))
        bridge.addClip("a.mp4", 10.0)
        assert fired

    def test_add_clip_trimmed_applies_marks(self, bridge: EditorBridge) -> None:
        bridge.addClipTrimmed("a.mp4", 100.0, 0.25, 0.75)
        c = bridge.clips[0]
        assert c["inPoint"] == pytest.approx(25.0)
        assert c["outPoint"] == pytest.approx(75.0)
        assert c["trimmedDuration"] == pytest.approx(50.0)
        # Full source duration is preserved (so the clip can be re-trimmed).
        assert c["sourceDuration"] == pytest.approx(100.0)


class TestAddFilesFromUrls:
    """addFilesFromUrls probes each picked file and appends valid ones (R-1)."""

    class _Inspector:
        def __init__(self, durations: dict) -> None:
            self._d = durations  # path-name → seconds (raise if missing)

        def inspect(self, path: Path):
            from types import SimpleNamespace
            if path.name not in self._d:
                raise RuntimeError(f"unprobeable: {path}")
            return SimpleNamespace(duration_seconds=self._d[path.name])

    def test_adds_probed_files_and_returns_first_index(self, qt_app) -> None:
        insp = self._Inspector({"a.mp4": 12.0, "b.mp4": 8.0})
        b = EditorBridge(inspector=insp)
        first = b.addFilesFromUrls(["file:///C:/clips/a.mp4", "file:///C:/clips/b.mp4"])
        assert first == 0
        assert b.count == 2
        assert b.clips[0]["sourceDuration"] == pytest.approx(12.0)
        assert b.clips[1]["fileName"] == "b.mp4"

    def test_skips_unprobeable_files(self, qt_app) -> None:
        insp = self._Inspector({"good.mp4": 5.0})  # bad.mp4 missing → skipped
        b = EditorBridge(inspector=insp)
        first = b.addFilesFromUrls(["file:///C:/x/bad.mp4", "file:///C:/x/good.mp4"])
        assert b.count == 1
        assert b.clips[0]["fileName"] == "good.mp4"
        assert first == 0  # index within the (single-element) reel

    def test_empty_or_all_invalid_returns_minus_one(self, qt_app) -> None:
        b = EditorBridge(inspector=self._Inspector({}))
        assert b.addFilesFromUrls([]) == -1
        assert b.addFilesFromUrls(["file:///C:/x/nope.mp4"]) == -1
        assert b.count == 0

    def test_no_inspector_adds_nothing(self, qt_app) -> None:
        b = EditorBridge()  # inspector defaults to None
        assert b.addFilesFromUrls(["file:///C:/x/a.mp4"]) == -1
        assert b.count == 0

    def test_plain_path_without_url_scheme(self, qt_app) -> None:
        insp = self._Inspector({"a.mp4": 3.0})
        b = EditorBridge(inspector=insp)
        first = b.addFilesFromUrls([r"C:\clips\a.mp4"])
        assert first == 0 and b.count == 1


class TestLocate:
    def test_locate_returns_mapping(self, bridge: EditorBridge) -> None:
        bridge.addClip("a.mp4", 10.0)   # 0..10
        bridge.addClip("b.mp4", 10.0)   # 10..20
        hit = bridge.locate(12.0)
        assert hit["index"] == 1
        assert hit["localPos"] == pytest.approx(2.0)
        assert hit["sourcePath"].endswith("b.mp4")

    def test_locate_empty(self, bridge: EditorBridge) -> None:
        assert bridge.locate(0.0) == {}


class TestEventMarkers:
    def test_events_for_clip_reads_sidecar(self, qt_app, tmp_path) -> None:
        from datetime import datetime, timedelta, timezone
        from app.core.analytics.models import AnalyticEvent
        from app.core.analytics.sidecar import write_sidecar

        t0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
        clip = tmp_path / "clip.mp4"
        ev = AnalyticEvent(event_id="120000", source="manual", start=t0,
                           end=t0 + timedelta(seconds=30), monitor_index=0)
        write_sidecar(clip, [ev])

        b = EditorBridge()
        markers = b.eventsForClip(str(clip))
        assert len(markers) == 1
        assert markers[0]["eventId"] == "120000"
        assert markers[0]["source"] == "manual"

    def test_events_for_clip_missing_sidecar(self, qt_app, tmp_path) -> None:
        assert EditorBridge().eventsForClip(str(tmp_path / "ghost.mp4")) == []


class TestExport:
    def _port(self) -> MagicMock:
        p = MagicMock(spec=EditorExportPort)
        p.export.side_effect = lambda timeline, output_path, on_progress=None: (
            on_progress(1.0) if on_progress else None
        ) or Path(output_path)
        return p

    def test_export_success_emits_finished(self, qt_app) -> None:
        port = self._port()
        b = EditorBridge(export_port=port)
        b.addClip("a.mp4", 10.0)
        finished, progress = [], []
        b.exportFinished.connect(finished.append)
        b.exportProgress.connect(progress.append)
        b._do_export("out.mp4")  # synchronous path
        assert finished == ["out.mp4"]
        assert progress and progress[-1] == 1.0
        port.export.assert_called_once()

    def test_export_no_port_emits_failed(self, qt_app) -> None:
        b = EditorBridge(export_port=None)
        b.addClip("a.mp4", 10.0)
        failed = []
        b.exportFailed.connect(failed.append)
        b.exportTimeline("out.mp4")
        assert failed

    def test_export_invalid_timeline_emits_failed(self, qt_app) -> None:
        b = EditorBridge(export_port=self._port())
        failed = []
        b.exportFailed.connect(failed.append)
        b.exportTimeline("out.mp4")  # empty timeline
        assert failed

    def test_default_output_path_under_clips_dir(self, qt_app, tmp_path) -> None:
        b = EditorBridge(export_port=self._port(), clips_dir=tmp_path)
        out = b._default_output_path()
        assert out is not None
        assert out.parent == tmp_path
        assert out.name.startswith("reel_") and out.suffix == ".mp4"

    def test_export_reel_no_clips_dir_fails(self, qt_app) -> None:
        b = EditorBridge(export_port=self._port())  # no clips_dir
        b.addClip("a.mp4", 10.0)
        failed = []
        b.exportFailed.connect(failed.append)
        b.exportReel()
        assert failed

    def test_export_exception_emits_failed(self, qt_app) -> None:
        port = MagicMock(spec=EditorExportPort)
        port.export.side_effect = RuntimeError("ffmpeg boom")
        b = EditorBridge(export_port=port)
        b.addClip("a.mp4", 10.0)
        failed = []
        b.exportFailed.connect(failed.append)
        b._do_export("out.mp4")
        assert failed and "boom" in failed[0]
