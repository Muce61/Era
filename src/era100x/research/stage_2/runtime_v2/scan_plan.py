"""Deterministic scan planning for reuse across approved research events."""

from __future__ import annotations

from dataclasses import dataclass

from era100x.research.stage_2.runtime_v2.contracts import (
    EvidenceCapability,
    FeatureSource,
    HalfOpenTimeWindow,
    Instrument,
    require_sha256,
)
from era100x.research.stage_2.runtime_v2.models import metadata_sha256
from era100x.research.stage_2.runtime_v2.plugins import FeatureRequirement

_INSTRUMENTS = {"BTCUSDT", "ETHUSDT"}
_SOURCES = {"PRICE_FEATURE", "TRADE_PRIMITIVE", "EXACT_TRADE_ROWS", "EVENT_FACT"}
_CAPABILITIES = {"H1", "H2"}


@dataclass(frozen=True, slots=True)
class ScanPlanSegment:
    """One coalesced logical source scan over ``[start_ns, end_ns)``."""

    source: FeatureSource
    required_capability: EvidenceCapability
    instrument: Instrument
    window: HalfOpenTimeWindow
    as_of_ns: int
    required_definition_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.instrument not in _INSTRUMENTS:
            raise ValueError("scan segment instrument is not approved")
        if self.source not in _SOURCES:
            raise ValueError("scan segment source is not approved")
        if self.required_capability not in _CAPABILITIES:
            raise ValueError("scan segment capability is not approved")
        if self.source in {"TRADE_PRIMITIVE", "EXACT_TRADE_ROWS"}:
            if self.required_capability != "H2":
                raise ValueError("Trades-derived scan segments require H2 capability")
        if self.as_of_ns < self.window.end_ns:
            raise ValueError("scan segment cannot read beyond its causal as-of boundary")
        if not self.required_definition_hashes:
            raise ValueError("scan segment requires at least one Feature Definition")
        for digest in self.required_definition_hashes:
            require_sha256(digest, "required_definition_hash")
        object.__setattr__(
            self,
            "required_definition_hashes",
            tuple(sorted(set(self.required_definition_hashes))),
        )


@dataclass(frozen=True, slots=True)
class ScanPlan:
    """Immutable physical-layout-independent scan intent."""

    instrument: Instrument
    owner_windows: tuple[HalfOpenTimeWindow, ...]
    segments: tuple[ScanPlanSegment, ...]
    as_of_ns: int

    def __post_init__(self) -> None:
        if not self.owner_windows or not self.segments:
            raise ValueError("scan plan requires owner windows and source segments")
        if self.instrument not in _INSTRUMENTS:
            raise ValueError("scan plan instrument is not approved")
        if self.as_of_ns < max(item.end_ns for item in self.owner_windows):
            raise ValueError("scan plan as-of boundary predates an owner window")
        if any(segment.instrument != self.instrument for segment in self.segments):
            raise ValueError("scan plan cannot mix instruments")
        if any(segment.as_of_ns != self.as_of_ns for segment in self.segments):
            raise ValueError("scan plan segments must share one locked as-of boundary")

    @property
    def plan_key(self) -> str:
        return str(
            metadata_sha256(
                {
                    "instrument": self.instrument,
                    "as_of_ns": self.as_of_ns,
                    "owner_windows": [
                        {"start_ns": item.start_ns, "end_ns": item.end_ns}
                        for item in self.owner_windows
                    ],
                    "segments": [
                        {
                            "source": item.source,
                            "required_capability": item.required_capability,
                            "instrument": item.instrument,
                            "start_ns": item.window.start_ns,
                            "end_ns": item.window.end_ns,
                            "as_of_ns": item.as_of_ns,
                            "required_definition_hashes": item.required_definition_hashes,
                        }
                        for item in self.segments
                    ],
                }
            )
        )


class ScanPlanBuilder:
    """Coalesce reusable scans without weakening feature-specific authority."""

    def build(
        self,
        *,
        instrument: Instrument,
        owner_windows: tuple[HalfOpenTimeWindow, ...],
        requirements: tuple[FeatureRequirement, ...],
        as_of_ns: int,
    ) -> ScanPlan:
        windows = self._canonical_owner_windows(owner_windows, as_of_ns)
        features = self._canonical_requirements(requirements)

        grouped: dict[tuple[FeatureSource, EvidenceCapability], list[FeatureRequirement]] = {}
        for requirement in features:
            grouped.setdefault((requirement.source, requirement.required_capability), []).append(
                requirement
            )

        segments: list[ScanPlanSegment] = []
        for (source, capability), selected in sorted(grouped.items()):
            lookback_ns = max(item.lookback_ns for item in selected)
            definition_hashes = tuple(item.definition_hash for item in selected)
            expanded = tuple(item.expand_lookback(lookback_ns) for item in windows)
            for window in self._merge_windows(expanded):
                segments.append(
                    ScanPlanSegment(
                        source=source,
                        required_capability=capability,
                        instrument=instrument,
                        window=window,
                        as_of_ns=as_of_ns,
                        required_definition_hashes=definition_hashes,
                    )
                )

        return ScanPlan(
            instrument=instrument,
            owner_windows=windows,
            segments=tuple(
                sorted(
                    segments,
                    key=lambda item: (
                        item.source,
                        item.required_capability,
                        item.window.start_ns,
                        item.window.end_ns,
                    ),
                )
            ),
            as_of_ns=as_of_ns,
        )

    @staticmethod
    def _canonical_owner_windows(
        owner_windows: tuple[HalfOpenTimeWindow, ...], as_of_ns: int
    ) -> tuple[HalfOpenTimeWindow, ...]:
        if not owner_windows:
            raise ValueError("scan planning requires at least one owner window")
        windows = tuple(sorted(set(owner_windows), key=lambda item: (item.start_ns, item.end_ns)))
        if as_of_ns < windows[-1].end_ns:
            raise ValueError("scan plan as_of_ns predates an owner window")
        for left, right in zip(windows, windows[1:], strict=False):
            if left.overlaps(right):
                raise ValueError("logical owner windows must not overlap")
        return windows

    @staticmethod
    def _canonical_requirements(
        requirements: tuple[FeatureRequirement, ...],
    ) -> tuple[FeatureRequirement, ...]:
        if not requirements:
            raise ValueError("scan planning requires approved Feature Definitions")
        by_hash: dict[str, FeatureRequirement] = {}
        for requirement in requirements:
            existing = by_hash.get(requirement.definition_hash)
            if existing is not None and existing != requirement:
                raise ValueError("one Feature Definition hash has conflicting scan requirements")
            by_hash[requirement.definition_hash] = requirement
        return tuple(
            sorted(
                by_hash.values(),
                key=lambda item: (
                    item.source,
                    item.required_capability,
                    item.definition_id,
                    item.definition_version,
                    item.definition_hash,
                ),
            )
        )

    @staticmethod
    def _merge_windows(
        windows: tuple[HalfOpenTimeWindow, ...],
    ) -> tuple[HalfOpenTimeWindow, ...]:
        ordered = sorted(windows, key=lambda item: (item.start_ns, item.end_ns))
        merged: list[HalfOpenTimeWindow] = []
        for window in ordered:
            if not merged or not merged[-1].touches_or_overlaps(window):
                merged.append(window)
                continue
            previous = merged[-1]
            merged[-1] = HalfOpenTimeWindow(
                previous.start_ns,
                max(previous.end_ns, window.end_ns),
            )
        return tuple(merged)
