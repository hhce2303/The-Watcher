"""
Windows Job Object guard for FFmpeg subprocesses, plus batch concurrency control.

Two governance tiers (ffmpeg-pipeline-optimization-research.md §4):

* ``assign_to_job`` — the live recorder.  Kill-on-close only, no throttling:
  the recorder must never be frozen or de-prioritized.
* ``assign_to_batch_job`` — offline/background work (hourly/combined clip
  builders, mp4 converter, batch analyzer).  All batch processes share ONE
  Job Object with a relative CPU weight, BELOW_NORMAL priority, and an
  optional hard memory ceiling, so a runaway 4K re-encode yields to the
  recorder instead of starving it.
* ``batch_slot()`` — a process-wide semaphore (``MAX_BATCH_FFMPEG``) that
  serializes how many batch FFmpeg processes run at once, independent of the
  Job Object limits above. Platform-independent (plain ``threading``).

Usage::

    proc = subprocess.Popen(cmd, ...)
    assign_to_job(proc)                 # recorder — never throttled

    result = run_batched_ffmpeg(cmd, label="clip-m0")   # batch — preferred path

    # Equivalent manual form, for callers that can't use run_batched_ffmpeg
    # directly (e.g. batch_clip_analyzer.py, mp4_converter_adapter.py):
    with batch_slot():
        proc = subprocess.Popen(cmd, ...)
        assign_to_batch_job(proc)       # batch — shared weight/priority/mem cap
        proc.communicate()
"""
from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from typing import Optional

from loguru import logger

from app.infrastructure.proc_telemetry import track_process, untrack_process

# ── Batch concurrency semaphore (platform-independent) ─────────────────────
# Bounds how many batch FFmpeg processes may run at once system-wide — flattens
# CPU/RAM spikes and keeps concurrent HW-encode sessions under vendor limits
# (NVENC consumer: 8 sessions/system). Default 1 = fully serialized.
_batch_sem_lock = threading.Lock()
_batch_semaphore: threading.BoundedSemaphore | None = None
_batch_semaphore_size = 1


def configure_batch_concurrency(max_concurrent: int) -> None:
    """Set how many batch FFmpeg processes may run concurrently (``MAX_BATCH_FFMPEG``).

    Call once at startup, before any batch process spawns.
    """
    global _batch_semaphore, _batch_semaphore_size
    with _batch_sem_lock:
        _batch_semaphore_size = max(1, max_concurrent)
        _batch_semaphore = threading.BoundedSemaphore(_batch_semaphore_size)
    logger.info("process_guard: batch concurrency set to {}.", _batch_semaphore_size)


def _get_batch_semaphore() -> threading.BoundedSemaphore:
    global _batch_semaphore
    with _batch_sem_lock:
        if _batch_semaphore is None:
            _batch_semaphore = threading.BoundedSemaphore(_batch_semaphore_size)
        return _batch_semaphore


@contextlib.contextmanager
def batch_slot() -> Iterator[None]:
    """Block until a batch-FFmpeg concurrency slot is free.

    Wrap the spawn+wait of any offline/background FFmpeg encode in this —
    never the live recorder, which must always be able to start immediately.
    """
    sem = _get_batch_semaphore()
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


def run_batched_ffmpeg(
    cmd: list[str],
    *,
    label: str,
    timeout: float = 3600,
    on_started: Optional[Callable[[subprocess.Popen], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
) -> subprocess.CompletedProcess:
    """Run *cmd* inside the batch concurrency slot + job object.

    Wraps the batch_slot()/assign_to_batch_job()/track_process() boilerplate
    for offline FFmpeg spawns. Currently used by the clip builders
    (hourly_recording_builder.py, combined_clip_builder.py) and the event-clip
    adapters (timestamp_adapter.py, trim_adapter.py); batch_clip_analyzer.py
    and mp4_converter_adapter.py still call the pieces directly and have not
    been migrated. Blocks until the process exits.

    ``on_started``/``on_finished`` let a caller track the live Popen for
    cancellation (e.g. a builder's shutdown path) without duplicating the
    batch_slot/job/telemetry wiring itself.
    """
    with batch_slot():
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assign_to_batch_job(proc)
        track_process(proc.pid, category="batch", label=label)
        try:
            if on_started is not None:
                on_started(proc)
            _, stderr_bytes = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        finally:
            untrack_process(proc.pid)
            if on_finished is not None:
                on_finished()
    return subprocess.CompletedProcess(cmd, proc.returncode, None, stderr_bytes)


if sys.platform != "win32":

    def assign_to_job(proc: subprocess.Popen) -> None:  # type: ignore[arg-type]
        pass

    def assign_to_batch_job(proc: subprocess.Popen) -> None:  # type: ignore[arg-type]
        pass

    def configure_batch_governance(
        weight: int = 2,
        memory_limit_mb: int = 0,
        cpu_hard_cap_percent: int = 0,
    ) -> None:
        pass

else:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # SetInformationJobObject classes
    _JOBOBJECTINFOCLASS_ExtendedLimitInformation = 9
    _JOBOBJECTINFOCLASS_CpuRateControlInformation = 15

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x00000020
    _JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    _BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

    _JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x00000001
    _JOB_OBJECT_CPU_RATE_CONTROL_WEIGHT_BASED = 0x00000002
    _JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x00000004

    class _BasicLimitInfo(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit",     ctypes.c_int64),
            ("LimitFlags",             ctypes.wintypes.DWORD),
            ("MinimumWorkingSetSize",  ctypes.c_size_t),
            ("MaximumWorkingSetSize",  ctypes.c_size_t),
            ("ActiveProcessLimit",     ctypes.wintypes.DWORD),
            ("Affinity",               ctypes.c_size_t),
            ("PriorityClass",          ctypes.wintypes.DWORD),
            ("SchedulingClass",        ctypes.wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount",  ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount",   ctypes.c_uint64),
            ("WriteTransferCount",  ctypes.c_uint64),
            ("OtherTransferCount",  ctypes.c_uint64),
        ]

    class _ExtendedLimitInfo(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInfo),
            ("IoInfo",                _IoCounters),
            ("ProcessMemoryLimit",    ctypes.c_size_t),
            ("JobMemoryLimit",        ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed",     ctypes.c_size_t),
        ]

    class _CpuRateControlUnion(ctypes.Union):
        _fields_ = [
            ("CpuRate", ctypes.wintypes.DWORD),
            ("Weight",  ctypes.wintypes.DWORD),
        ]

    class _CpuRateControlInfo(ctypes.Structure):
        _fields_ = [
            ("ControlFlags", ctypes.wintypes.DWORD),
            ("u",             _CpuRateControlUnion),
        ]

    def assign_to_job(proc: subprocess.Popen) -> None:  # type: ignore[arg-type]
        """Assign *proc* to a new Job Object with KillOnJobClose.

        The job handle is intentionally kept open for the lifetime of the
        Python process (stored in a module-level list).  When Python exits,
        the handle is closed and Windows kills the job's processes.
        """
        try:
            job = _kernel32.CreateJobObjectW(None, None)
            if not job:
                raise ctypes.WinError(ctypes.get_last_error())

            info = _ExtendedLimitInfo()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = _kernel32.SetInformationJobObject(
                job,
                _JOBOBJECTINFOCLASS_ExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not ok:
                _kernel32.CloseHandle(job)
                raise ctypes.WinError(ctypes.get_last_error())

            _assign_process_to_job(job, proc.pid)
            # Keep the job handle alive until Python exits.
            _open_jobs.append(job)
            logger.debug("process_guard: PID {} assigned to job object.", proc.pid)

        except Exception as exc:
            logger.debug("process_guard: job object setup failed for PID {}: {}", proc.pid, exc)

    # ── Batch governance: one shared Job Object for offline/background work ──
    _batch_job_lock = threading.Lock()
    _batch_job_handle: int | None = None
    _batch_weight = 2
    _batch_memory_limit_mb = 0
    _batch_cpu_hard_cap_percent = 0

    def configure_batch_governance(
        weight: int = 2,
        memory_limit_mb: int = 0,
        cpu_hard_cap_percent: int = 0,
    ) -> None:
        """Configure the shared batch Job Object (``BATCH_JOB_*`` settings).

        Call once at startup, before any batch process spawns — the shared job
        is created lazily on first :func:`assign_to_batch_job` call using
        whatever was last configured here.
        """
        global _batch_weight, _batch_memory_limit_mb, _batch_cpu_hard_cap_percent
        _batch_weight = max(1, min(9, weight))
        _batch_memory_limit_mb = max(0, memory_limit_mb)
        _batch_cpu_hard_cap_percent = max(0, min(100, cpu_hard_cap_percent))

    def _get_or_create_batch_job() -> int:
        global _batch_job_handle
        with _batch_job_lock:
            if _batch_job_handle is not None:
                return _batch_job_handle

            job = _kernel32.CreateJobObjectW(None, None)
            if not job:
                raise ctypes.WinError(ctypes.get_last_error())

            limit_flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | _JOB_OBJECT_LIMIT_PRIORITY_CLASS
            info = _ExtendedLimitInfo()
            if _batch_memory_limit_mb > 0:
                limit_flags |= _JOB_OBJECT_LIMIT_JOB_MEMORY
                info.JobMemoryLimit = _batch_memory_limit_mb * 1024 * 1024
            info.BasicLimitInformation.LimitFlags = limit_flags
            info.BasicLimitInformation.PriorityClass = _BELOW_NORMAL_PRIORITY_CLASS
            ok = _kernel32.SetInformationJobObject(
                job,
                _JOBOBJECTINFOCLASS_ExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not ok:
                err = ctypes.get_last_error()
                _kernel32.CloseHandle(job)
                raise ctypes.WinError(err)

            cpu_info = _CpuRateControlInfo()
            if _batch_cpu_hard_cap_percent > 0:
                cpu_info.ControlFlags = (
                    _JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | _JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
                )
                cpu_info.u.CpuRate = _batch_cpu_hard_cap_percent * 100
            else:
                cpu_info.ControlFlags = (
                    _JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | _JOB_OBJECT_CPU_RATE_CONTROL_WEIGHT_BASED
                )
                cpu_info.u.Weight = _batch_weight
            if not _kernel32.SetInformationJobObject(
                job,
                _JOBOBJECTINFOCLASS_CpuRateControlInformation,
                ctypes.byref(cpu_info),
                ctypes.sizeof(cpu_info),
            ):
                # Documented to fail under Remote Desktop Services with DFSS
                # active — degrade to priority/memory limits only rather than
                # losing the whole job.
                logger.debug(
                    "process_guard: CPU rate control unavailable (err={}) — "
                    "batch job keeps priority/memory limits only.",
                    ctypes.get_last_error(),
                )

            _batch_job_handle = job
            logger.info(
                "process_guard: batch job created (weight={}, mem_limit_mb={}, cpu_hard_cap_pct={}).",
                _batch_weight,
                _batch_memory_limit_mb or "none",
                _batch_cpu_hard_cap_percent or "off",
            )
            return job

    def assign_to_batch_job(proc: subprocess.Popen) -> None:  # type: ignore[arg-type]
        """Assign *proc* to the shared batch Job Object (weight/priority/memory-capped).

        Use for offline/background FFmpeg work only (clip builders, combined
        grid, mp4 converter, batch analyzer) — never the live recorder.
        """
        try:
            job = _get_or_create_batch_job()
            _assign_process_to_job(job, proc.pid)
            logger.debug("process_guard: PID {} assigned to batch job.", proc.pid)
        except Exception as exc:
            logger.debug("process_guard: batch job assign failed for PID {}: {}", proc.pid, exc)

    def _assign_process_to_job(job: int, pid: int) -> None:
        # Coerce to a plain int before it reaches ctypes: passing an arbitrary
        # object (e.g. a MagicMock in tests that stub subprocess.Popen) into a
        # WinDLL call with no declared argtypes makes ctypes probe it for
        # marshaling hooks like _as_parameter_ — on a Mock that recurses into
        # infinitely-generated child mocks and crashes the interpreter with a
        # stack overflow (a fatal fault, not a catchable Python exception).
        # int() surfaces a normal, catchable TypeError instead.
        pid = int(pid)
        PROCESS_ALL_ACCESS = 0x1F0FFF
        h_proc = _kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not h_proc:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ok = _kernel32.AssignProcessToJobObject(job, h_proc)
            if not ok:
                err = ctypes.get_last_error()
                # ERROR_ACCESS_DENIED (5) is expected when the process is already
                # in an incompatible job (rare on Windows 8+, which supports
                # nested jobs, but handled gracefully).
                if err != 5:
                    raise ctypes.WinError(err)
                logger.debug("process_guard: process {} already in a job object.", pid)
        finally:
            _kernel32.CloseHandle(h_proc)

    # Module-level list keeps per-recorder job handles open for the process lifetime.
    _open_jobs: list[int] = []
