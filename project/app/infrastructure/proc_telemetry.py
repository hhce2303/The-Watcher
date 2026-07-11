"""
psutil-based CPU/RSS telemetry for tracked FFmpeg subprocesses (PoC-2 —
ffmpeg-pipeline-optimization-research.md §4.2-4).

A single background thread samples every tracked PID roughly once per
``interval_seconds`` and logs ``cpu_pct``/``rss_mb`` per category/label. This
is the data source for the ADR-0007 gate: whether captured CPU stays above the
SLA on a relevant slice of the fleet after the zero-copy pipeline (ADR-0014),
which would justify escalating the Rust capture port instead of tuning FFmpeg
further. It is also the data source for the Track R2 M0 bench harness
(``project/tools/bench_recording.ps1``) via the ``TELEMETRY_CSV`` env var.

Usage::

    from app.infrastructure.proc_telemetry import get_telemetry, track_process, untrack_process

    get_telemetry().start()
    ...
    track_process(proc.pid, category="recorder", label="m0")
    ...
    untrack_process(proc.pid)
    ...
    get_telemetry().stop()

Tracking a PID that has already exited is harmless — the next sample simply
evicts it. Untracking is best-effort cleanup, not a correctness requirement.
"""
from __future__ import annotations

import csv
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psutil
from loguru import logger

_CSV_HEADER = ["ts", "category", "label", "pid", "cpu_pct", "rss_mb"]


@dataclass
class _Tracked:
    pid: int
    category: str  # "recorder" | "batch"
    label: str      # e.g. "m0", "combined", "mp4_converter", "batch_analyzer"
    proc: psutil.Process


class ProcTelemetry:
    """Background psutil sampler for a dynamic set of tracked PIDs."""

    def __init__(
        self, interval_seconds: float = 10.0, csv_path: Optional[str] = None
    ) -> None:
        self._interval = max(1.0, interval_seconds)
        self._lock = threading.Lock()
        self._tracked: dict[int, _Tracked] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # TELEMETRY_CSV: opt-in bench-harness sink (Track R2 M0). Diagnostic-only —
        # a write failure must never affect sampling, so errors are swallowed.
        self._csv_path = csv_path if csv_path is not None else os.getenv("TELEMETRY_CSV")
        self._csv_header_written = False
        if self._csv_path:
            self._csv_header_written = Path(self._csv_path).exists()

    def set_interval(self, interval_seconds: float) -> None:
        self._interval = max(1.0, interval_seconds)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="proc-telemetry", daemon=True)
        self._thread.start()
        logger.info("[telemetry] started (interval={}s)", self._interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def track(self, pid: int, category: str, label: str) -> None:
        """Start sampling *pid* under (category, label). Silently ignored on any failure.

        Telemetry is diagnostic-only and must never be able to break the
        recording/batch pipeline it's observing — e.g. a test double or a
        caller bug passing a non-int ``pid`` must not propagate here.
        """
        try:
            proc = psutil.Process(pid)
            proc.cpu_percent(None)  # prime — the first *reported* sample is meaningful
        except (psutil.Error, TypeError, ValueError):
            return
        with self._lock:
            self._tracked[pid] = _Tracked(pid=pid, category=category, label=label, proc=proc)

    def untrack(self, pid: int) -> None:
        with self._lock:
            self._tracked.pop(pid, None)

    def snapshot(self) -> list[dict]:
        """Return the last-known tracked set (for tests / diagnostics), no sampling."""
        with self._lock:
            return [
                {"pid": t.pid, "category": t.category, "label": t.label}
                for t in self._tracked.values()
            ]

    # ── Internal ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            self._sample()

    def _sample(self) -> None:
        with self._lock:
            items = list(self._tracked.values())
        dead: list[int] = []
        rows: list[list] = []
        now = time.time()
        for t in items:
            try:
                cpu_pct = t.proc.cpu_percent(None)
                rss_mb = t.proc.memory_info().rss / 1_048_576
            except psutil.Error:
                dead.append(t.pid)
                continue
            # DEBUG: periodic per-process sampling — diagnostic data for the log file, not
            # something a user should see as a UI notification (C3 bus sink is INFO+).
            logger.debug(
                "[telemetry] category={} label={} pid={} cpu_pct={:.1f} rss_mb={:.1f}",
                t.category, t.label, t.pid, cpu_pct, rss_mb,
            )
            rows.append([now, t.category, t.label, t.pid, cpu_pct, rss_mb])
        if dead:
            with self._lock:
                for pid in dead:
                    self._tracked.pop(pid, None)
        if rows and self._csv_path:
            self._append_csv(rows)

    def _append_csv(self, rows: list[list]) -> None:
        try:
            write_header = not self._csv_header_written
            with open(self._csv_path, "a", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                if write_header:
                    writer.writerow(_CSV_HEADER)
                    self._csv_header_written = True
                writer.writerows(rows)
        except OSError:
            logger.debug("[telemetry] TELEMETRY_CSV write failed — dropping this batch.")


_telemetry: Optional[ProcTelemetry] = None


def get_telemetry() -> ProcTelemetry:
    global _telemetry
    if _telemetry is None:
        _telemetry = ProcTelemetry()
    return _telemetry


def configure_telemetry(interval_seconds: float) -> None:
    get_telemetry().set_interval(interval_seconds)


def track_process(pid: int, category: str, label: str) -> None:
    get_telemetry().track(pid, category, label)


def untrack_process(pid: int) -> None:
    get_telemetry().untrack(pid)
