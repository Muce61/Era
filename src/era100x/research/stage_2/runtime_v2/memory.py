"""Production memory evidence with audit-only resource thresholds."""

from __future__ import annotations

import ctypes
import ctypes.util
import resource
import sys
import threading
from contextlib import AbstractContextManager
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from .models import (
    MAX_PROCESS_CURRENT_RSS_BYTES,
    MAX_PROCESS_RSS_DELTA_BYTES,
)
from .resource_anomalies import ResourceCategory, ResourceThresholdObservation


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
    """Observe resource thresholds without turning them into research failures.

    ``ru_maxrss`` is process-lifetime state and cannot be reset at a phase
    boundary.  CR-2026-012 therefore never treats its delta as a phase-local
    hard limit. CR-2026-013 also classifies current-RSS and Arrow limits as
    execution anomalies. Actual inability to continue is represented by an
    explicit recoverable pause at the orchestrator boundary.
    """

    def __init__(
        self,
        *,
        current_limit_bytes: int = MAX_PROCESS_CURRENT_RSS_BYTES,
        delta_limit_bytes: int = MAX_PROCESS_RSS_DELTA_BYTES,
        arrow_limit_bytes: int = 1_073_741_824,
        current_reader: Callable[[], int] = process_current_rss_bytes,
        peak_reader: Callable[[], int] = process_peak_rss_bytes,
    ) -> None:
        self.current_limit_bytes = current_limit_bytes
        self.delta_limit_bytes = delta_limit_bytes
        self.arrow_limit_bytes = arrow_limit_bytes
        self._current_reader = current_reader
        self._peak_reader = peak_reader
        self._lock = threading.Lock()
        self.baseline_current_rss_bytes = current_reader()
        self.baseline_peak_rss_bytes = peak_reader()
        self.max_current_rss_bytes_observed = self.baseline_current_rss_bytes
        self.max_peak_rss_bytes_observed = self.baseline_peak_rss_bytes
        self.max_current_rss_delta_bytes_observed = 0
        self.max_peak_rss_delta_bytes_observed = 0
        self.samples: list[ProcessMemorySample] = []
        self.anomalies: list[ResourceThresholdObservation] = []

    def begin_phase(self, phase: str) -> ProcessMemorySample:
        """Reset only the phase-current baseline; retain lifetime peak audit."""

        with self._lock:
            self.baseline_current_rss_bytes = self._current_reader()
            self.baseline_peak_rss_bytes = self._peak_reader()
        return self.check(f"{phase}:baseline")

    def monitor_phase(
        self,
        phase: str,
        *,
        interval_seconds: float = 0.05,
    ) -> AbstractContextManager[ProcessMemoryBudget]:
        """Continuously sample current RSS while a production phase runs."""

        return _ProcessMemoryPhaseMonitor(self, phase, interval_seconds)

    def check(self, phase: str, *, arrow_inflight_bytes: int = 0) -> ProcessMemorySample:
        with self._lock:
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
            self._record_anomaly(
                category="MEMORY_RSS",
                phase=phase,
                metric_name="CURRENT_RSS_BYTES",
                threshold=self.current_limit_bytes,
                observed=current,
            )
        if current_delta > self.delta_limit_bytes:
            self._record_anomaly(
                category="MEMORY_RSS",
                phase=phase,
                metric_name="CURRENT_RSS_DELTA_BYTES",
                threshold=self.delta_limit_bytes,
                observed=current_delta,
            )
        if arrow_inflight_bytes > self.arrow_limit_bytes:
            self._record_anomaly(
                category="ARROW_INFLIGHT",
                phase=phase,
                metric_name="ARROW_INFLIGHT_BYTES",
                threshold=self.arrow_limit_bytes,
                observed=arrow_inflight_bytes,
            )
        return sample

    def observe_threshold(
        self,
        *,
        category: ResourceCategory,
        phase: str,
        metric_name: str,
        threshold: int,
        observed: int,
        unit: str = "bytes",
    ) -> None:
        if observed > threshold:
            self._record_anomaly(
                category=category,
                phase=phase,
                metric_name=metric_name,
                threshold=threshold,
                observed=observed,
                unit=unit,
            )

    def drain_anomalies(self) -> tuple[ResourceThresholdObservation, ...]:
        with self._lock:
            values = tuple(self.anomalies)
            self.anomalies.clear()
        return values

    def _record_anomaly(
        self,
        *,
        category: ResourceCategory,
        phase: str,
        metric_name: str,
        threshold: int,
        observed: int,
        unit: str = "bytes",
    ) -> None:
        observation = ResourceThresholdObservation(
            category=category,
            phase=phase,
            metric_name=metric_name,
            unit=unit,
            threshold=threshold,
            observed=observed,
        ).with_clock()
        with self._lock:
            self.anomalies.append(observation)


class _ProcessMemoryPhaseMonitor(AbstractContextManager[ProcessMemoryBudget]):
    """Daemon sampler that records threshold anomalies through phase exit."""

    def __init__(
        self,
        budget: ProcessMemoryBudget,
        phase: str,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("memory sample interval must be positive")
        self.budget = budget
        self.phase = phase
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> ProcessMemoryBudget:
        self.budget.begin_phase(self.phase)
        self._thread = threading.Thread(
            target=self._sample,
            name=f"rss-monitor-{self.phase}",
            daemon=True,
        )
        self._thread.start()
        return self.budget

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> Literal[False]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 4))
            if self._thread.is_alive():
                raise RuntimeError("memory sampler did not stop")
        if exc is None:
            self.budget.check(f"{self.phase}:complete")
        return False

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.budget.check(f"{self.phase}:sample")


MIB: Final = 1024 * 1024
