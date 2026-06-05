"""
Windows Job Object guard for FFmpeg subprocesses.

Assigns each spawned FFmpeg process to a Job Object that has
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE set.  When the Python parent exits
(even if killed forcefully), the OS closes all job handles and terminates
every process assigned to them — no more orphaned FFmpeg instances.

Usage:
    proc = subprocess.Popen(cmd, ...)
    assign_to_job(proc)
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import subprocess
import sys

from loguru import logger

if sys.platform != "win32":
    def assign_to_job(proc: subprocess.Popen) -> None:  # type: ignore[arg-type]
        pass
else:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # SetInformationJobObject class for extended limits
    _JOBOBJECTINFOCLASS_ExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

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

            # Open a fresh handle to the target process (proc._handle is private).
            PROCESS_ALL_ACCESS = 0x1F0FFF
            h_proc = _kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, proc.pid)
            if not h_proc:
                _kernel32.CloseHandle(job)
                raise ctypes.WinError(ctypes.get_last_error())

            ok = _kernel32.AssignProcessToJobObject(job, h_proc)
            _kernel32.CloseHandle(h_proc)
            if not ok:
                err = ctypes.get_last_error()
                _kernel32.CloseHandle(job)
                # ERROR_ACCESS_DENIED (5) is expected when the process is already
                # in an incompatible job (rare on Windows 8+ which supports nested
                # jobs, but handled gracefully).
                if err != 5:
                    raise ctypes.WinError(err)
                logger.debug("process_guard: process {} already in a job object.", proc.pid)
                return

            # Keep the job handle alive until Python exits.
            _open_jobs.append(job)
            logger.debug("process_guard: PID {} assigned to job object.", proc.pid)

        except Exception as exc:
            logger.debug("process_guard: job object setup failed for PID {}: {}", proc.pid, exc)


    # Module-level list keeps job handles open for the lifetime of the process.
    _open_jobs: list[int] = []
