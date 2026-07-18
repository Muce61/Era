"""Production memory evidence and fail-closed Runtime V2 resource gates."""

from __future__ import annotations

import ctypes
import ctypes.util
import resource
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from .models import (
    MAX_PROCESS_CURRENT_RSS_BYTES,
    MAX_PROCESS_RSS_DELTA_BYTES,
)


def process_peak_rss_bytes() -> int:
    """Return the process high-water RSS in bytes on supported POSIX hosts."""

    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def process_current_rss_bytes() -> int:
    """Return current resident bytes without spawning a monitoring process."""

    if sys.platform == "darwin":
        return _darwin_current_rss_bytes()
    statm = "/proc/self/statm"
    try:
        with open(statm, encoding="ascii") as stream:
            resident_pages = int(stream.read().split()[1])
    except (FileNotFoundError, IndexError, ValueError):
        # The portable fallback is conservative: a high-water value can only
        # fail earlier than current RSS, never hide an over-budget process.
        return process_peak_rss_bytes()
    import os

    return resident_pages * os.sysconf("SC_PAGE_SIZE")


class _TimeValue(ctypes.Structure):
    _fields_ = (("seconds", ctypes.c_int), ("microseconds", ctypes.c_int))


class _MachTaskBasicInfo(ctypes.Structure):
    _fields_ = (
        ("virtual_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("resident_size_max", ctypes.c_uint64),
        ("user_time", _TimeValue),
        ("system_time", _TimeValue),
        ("policy", ctypes.c_int),
        ("suspend_count", ctypes.c_int),
    )


def _darwin_current_rss_bytes() -> int:
    library_name = ctypes.util.find_library("System")
    if library_name is None:
        return process_peak_rss_bytes()
    library = ctypes.CDLL(library_name)
    task = ctypes.c_uint.in_dll(library, "mach_task_self_").value
    info = _MachTaskBasicInfo()
    count = ctypes.c_uint(ctypes.sizeof(info) // ctypes.sizeof(ctypes.c_int))
    # MACH_TASK_BASIC_INFO = 20.  A non-zero kern_return_t fails closed to
    # the portable high-water value.
    result = library.task_info(task, 20, ctypes.byref(info), ctypes.byref(count))
    return int(info.resident_size) if result == 0 else process_peak_rss_bytes()


@dataclass(frozen=True, slots=True)
class ProcessMemorySample:
    phase: str
    baseline_current_rss_bytes: int
    baseline_peak_rss_bytes: int
    current_rss_bytes: int
    peak_rss_bytes: int
    current_rss_delta_bytes: int
    peak_rss_delta_bytes: int
    arrow_inflight_bytes: int


class ProcessMemoryBudget:
    """Separate absolute-current and baseline-relative peak RSS gates."""

    def __init__(
        self,
        *,
        current_limit_bytes: int = MAX_PROCESS_CURRENT_RSS_BYTES,
        delta_limit_bytes: int = MAX_PROCESS_RSS_DELTA_BYTES,
        current_reader: Callable[[], int] = process_current_rss_bytes,
        peak_reader: Callable[[], int] = process_peak_rss_bytes,
    ) -> None:
        self.current_limit_bytes = current_limit_bytes
        self.delta_limit_bytes = delta_limit_bytes
        self._current_reader = current_reader
        self._peak_reader = peak_reader
        self.baseline_current_rss_bytes = current_reader()
        self.baseline_peak_rss_bytes = peak_reader()
        self.max_current_rss_bytes_observed = self.baseline_current_rss_bytes
        self.max_peak_rss_bytes_observed = self.baseline_peak_rss_bytes
        self.max_current_rss_delta_bytes_observed = 0
        self.max_peak_rss_delta_bytes_observed = 0
        self.samples: list[ProcessMemorySample] = []

    def check(self, phase: str, *, arrow_inflight_bytes: int = 0) -> ProcessMemorySample:
        current = self._current_reader()
        peak = self._peak_reader()
        current_delta = max(0, current - self.baseline_current_rss_bytes)
        peak_delta = max(0, peak - self.baseline_peak_rss_bytes)
        sample = ProcessMemorySample(
            phase=phase,
            baseline_current_rss_bytes=self.baseline_current_rss_bytes,
            baseline_peak_rss_bytes=self.baseline_peak_rss_bytes,
            current_rss_bytes=current,
            peak_rss_bytes=peak,
            current_rss_delta_bytes=current_delta,
            peak_rss_delta_bytes=peak_delta,
            arrow_inflight_bytes=arrow_inflight_bytes,
        )
        self.samples.append(sample)
        self.max_current_rss_bytes_observed = max(self.max_current_rss_bytes_observed, current)
        self.max_peak_rss_bytes_observed = max(self.max_peak_rss_bytes_observed, peak)
        self.max_current_rss_delta_bytes_observed = max(
            self.max_current_rss_delta_bytes_observed, current_delta
        )
        self.max_peak_rss_delta_bytes_observed = max(
            self.max_peak_rss_delta_bytes_observed, peak_delta
        )
        if current > self.current_limit_bytes:
            raise MemoryError(
                f"{phase} current RSS {current} exceeds fixed limit {self.current_limit_bytes}"
            )
        if peak_delta > self.delta_limit_bytes:
            raise MemoryError(
                f"{phase} peak RSS delta {peak_delta} exceeds fixed limit "
                f"{self.delta_limit_bytes}; "
                f"baseline={self.baseline_peak_rss_bytes} peak={peak}"
            )
        return sample


MIB: Final = 1024 * 1024
