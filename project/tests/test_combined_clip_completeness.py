from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.adapters.ffmpeg.combined_clip_builder import CombinedClipBuilder


def _clip(raw: Path, window: str, index: int) -> Path:
    path = raw / f"{window}_m{index}.mp4"
    path.write_bytes(b"raw")
    return path


def test_combined_builder_waits_for_all_four_monitors(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    builder = CombinedClipBuilder(
        raw_dir=raw, output_dir=tmp_path / "combined", monitor_count=4,
        monitor_indices=[0, 1, 2, 3],
    )
    queued: list[tuple[list[Path], Path]] = []
    builder._submit = lambda clips, output, _window, _start: queued.append((clips, output))
    window = "2026-09-15_02-00-00"
    start = datetime(2026, 9, 15, 2, tzinfo=timezone.utc)

    for index in range(3):
        builder.on_clip_ready(_clip(raw, window, index), window, start)
    builder.on_clip_ready(_clip(raw, "2026-09-15_03-00-00", 0), "2026-09-15_03-00-00", start)

    assert queued == []
    # Once the late fourth raw clip is present, its callback re-checks the
    # finished older window and exactly its four ordered inputs are submitted.
    builder.on_clip_ready(_clip(raw, window, 3), window, start)

    assert len(queued) == 1
    assert [clip.name for clip in queued[0][0]] == [f"{window}_m{i}.mp4" for i in range(4)]


def test_raw_clip_names_use_window_boundary_not_first_segment_second(tmp_path: Path) -> None:
    from app.adapters.ffmpeg.hourly_recording_builder import RecordingClipBuilder

    builder = RecordingClipBuilder(output_dir=tmp_path, monitor_index=2)
    assert builder._window_output(datetime(2026, 9, 15, 2, 0, tzinfo=timezone.utc)).name == (
        "2026-09-15_02-00-00_m2.mp4"
    )
