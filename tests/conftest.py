"""Shared pytest fixtures for the full test suite."""
from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers (avoids PytestUnknownMarkWarning)."""
    config.addinivalue_line(
        "markers",
        "parity: Rust↔FFmpeg segment-compiler parity harness (F0 gate, "
        "auto-skips until the native engine is built).",
    )


# Tests that drive Windows-only code paths (``subprocess.CREATE_NO_WINDOW`` and
# friends are real attributes only on win32). They run in the Windows CI job and
# on watcher-win; on Linux they are skipped explicitly - never silently dropped -
# so a Linux pytest run reports them as SKIPPED with this reason.
_WINDOWS_ONLY = {
    "tests/test_proc_telemetry.py::TestProcTelemetry::test_track_and_snapshot",
    "tests/test_proc_telemetry.py::TestProcTelemetry::test_untrack_removes_entry",
    "tests/test_proc_telemetry.py::TestProcTelemetry::test_sample_reports_alive_then_evicts_dead_process",
    "tests/test_proc_telemetry.py::TestProcTelemetry::test_csv_export_writes_header_once_and_appends_rows",
    "tests/test_proc_telemetry.py::TestProcTelemetry::test_csv_export_resumes_without_rewriting_header",
    "tests/test_proc_telemetry.py::TestProcTelemetry::test_csv_export_disabled_by_default",
    "tests/test_process_guard.py::TestRunBatchedFfmpeg::test_caps_peak_concurrency",
    "tests/test_process_guard.py::TestRunBatchedFfmpeg::test_returns_completed_process_with_returncode_and_stderr",
    "tests/test_process_guard.py::TestRunBatchedFfmpeg::test_on_started_and_on_finished_are_called",
    "tests/test_process_guard.py::TestRunBatchedFfmpeg::test_timeout_kills_process_and_reraises",
    "tests/test_process_guard.py::TestRunBatchedFfmpeg::test_on_finished_still_fires_when_timeout_kills_process",
    "tests/test_recorder_pipeline.py::TestZeroCopyProbeCaching::test_probe_result_is_cached_per_monitor_and_family",
    "tests/test_segment_compiler.py::TestCompile::test_success_returns_output",
    "tests/test_segment_compiler.py::TestCompile::test_failure_raises_runtimeerror",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    import sys

    if sys.platform == "win32":
        return
    skip = pytest.mark.skip(reason="Windows-only code path (subprocess.CREATE_NO_WINDOW); runs in Windows CI / watcher-win")
    for item in items:
        if item.nodeid in _WINDOWS_ONLY:
            item.add_marker(skip)
