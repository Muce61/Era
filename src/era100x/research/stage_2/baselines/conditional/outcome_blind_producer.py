"""Outcome-blind candidate indexing and five-control selection for T15."""

from __future__ import annotations

import hashlib
import heapq
import json
from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .binning_run import read_binning_set
from .features import NS, ROLLING_FOLDS
from .t10_access import read_json_file
from .v14_contracts import (
    BACKWARD_PURGE_SECONDS,
    COMBINATION_ORDER,
    CONTROLS_PER_EPISODE,
    FORWARD_EMBARGO_SECONDS,
    MATCHING_SEED,
    ControlAnchor,
    FrozenQuintileBoundaries,
    MatchLevel,
    OutcomeCell,
    S2P13T16ContractAuthority,
    S2T15ContractAuthority,
    V14ControlCandidate,
    V14PrimaryEpisode,
    canonical_hash,
)

STAGE1_DATA_RUN_ID = "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"

SELECTION_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("pre_registered_period", pa.string(), nullable=False),
        pa.field("evaluation_fold", pa.string(), nullable=False),
        pa.field("parameter_set_id", pa.string(), nullable=False),
        pa.field("time_combination_id", pa.string(), nullable=False),
        pa.field("market_episode_id", pa.string(), nullable=False),
        pa.field("classification_row_hash", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("match_level", pa.string(), nullable=False),
        pa.field("control_candidate_ids", pa.list_(pa.string()), nullable=False),
        pa.field("selected_candidates_json", pa.string(), nullable=False),
        pa.field("event_outcomes_json", pa.string(), nullable=False),
        pa.field("selection_hash", pa.string(), nullable=False),
    ]
)


@dataclass(frozen=True, slots=True)
class CandidateLite:
    anchor_ns: int
    reference_price: Decimal
    high_timeframe_trend_state: str
    volatility_quintile: int
    activity_quintile: int
    distance_quintile: int
    four_hour_bucket: int
    quarter: int
    year: int


class BinningIndex:
    def __init__(self, path: Path, *, authority_hash: str) -> None:
        self.manifest = read_binning_set(path, authority_hash=authority_hash)
        self.root = path.parent
        self._cache: dict[tuple[str, str, str, str, str | None], FrozenQuintileBoundaries] = {}

    def boundary(
        self,
        *,
        instrument: str,
        period: str,
        fold: str,
        feature_kind: str,
        parameter_set_id: str | None = None,
    ) -> FrozenQuintileBoundaries:
        key = (instrument, period, fold, feature_kind, parameter_set_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        name = (
            feature_kind if parameter_set_id is None else f"KEY_LEVEL_DISTANCE__{parameter_set_id}"
        )
        path = self.root / "boundaries" / instrument / period / fold / f"{name}.json"
        boundary = FrozenQuintileBoundaries.model_validate_json(
            json.dumps(read_json_file(path), ensure_ascii=False, sort_keys=True)
        )
        if boundary.boundary_hash != boundary.computed_hash():
            raise ValueError("binning boundary changed before matching")
        self._cache[key] = boundary
        return boundary

    def combined_hash(self, instrument: str, period: str, fold: str, parameter: str) -> str:
        key = f"{instrument}|{period}|{fold}|{parameter}"
        try:
            return str(self.manifest["combined_binning_snapshot_hashes"][key])
        except KeyError as exc:
            raise ValueError("missing combined binning snapshot") from exc


class SameFamilyIntervals:
    def __init__(self, episode_table: pa.Table) -> None:
        self._values: dict[str, tuple[list[int], list[int]]] = {}
        for instrument in ("BTCUSDT", "ETHUSDT"):
            selected = episode_table.filter(pc.equal(episode_table["instrument"], instrument))
            intervals = sorted(
                {
                    (int(start), int(end))
                    for start, end in zip(
                        selected["anchor_ns"].to_pylist(),
                        selected["requested_window_end_ns"].to_pylist(),
                        strict=True,
                    )
                }
            )
            starts: list[int] = []
            prefix_max_end: list[int] = []
            maximum = 0
            for start, end in intervals:
                starts.append(start)
                maximum = max(maximum, end)
                prefix_max_end.append(maximum)
            self._values[instrument] = starts, prefix_max_end

    def overlaps(self, *, instrument: str, start_ns: int, end_ns: int) -> bool:
        starts, prefix = self._values[instrument]
        index = bisect_left(starts, end_ns) - 1
        return index >= 0 and prefix[index] > start_ns


def _overlaps(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start < right_end and right_start < left_end


def _cell_values(center: int, tolerance: int) -> tuple[int, ...]:
    return tuple(
        value for value in range(center - tolerance, center + tolerance + 1) if 1 <= value <= 5
    )


class CandidateIndex:
    def __init__(self, candidates: Iterable[CandidateLite]) -> None:
        self.quarter: dict[tuple[str, int, int, int, int, int], list[CandidateLite]] = {}
        self.year: dict[tuple[str, int, int, int, int, int], list[CandidateLite]] = {}
        for candidate in candidates:
            qkey = (
                candidate.high_timeframe_trend_state,
                candidate.distance_quintile,
                candidate.activity_quintile,
                candidate.volatility_quintile,
                candidate.four_hour_bucket,
                candidate.quarter,
            )
            ykey = (*qkey[:-1], candidate.year)
            self.quarter.setdefault(qkey, []).append(candidate)
            self.year.setdefault(ykey, []).append(candidate)

    def _matches(self, episode: V14PrimaryEpisode, level: MatchLevel) -> Iterable[CandidateLite]:
        activity_tolerance = 0 if level == "L0" else 1
        volatility_tolerance = 0 if level in {"L0", "L1"} else 1
        buckets = (
            (episode.utc_four_hour_bucket,)
            if level in {"L0", "L1", "L2"}
            else (
                (episode.utc_four_hour_bucket - 1) % 6,
                episode.utc_four_hour_bucket,
                (episode.utc_four_hour_bucket + 1) % 6,
            )
        )
        source = self.year if level == "L4" else self.quarter
        terminal = episode.utc_calendar_year if level == "L4" else episode.utc_calendar_quarter
        for activity in _cell_values(episode.activity_quintile, activity_tolerance):
            for volatility in _cell_values(episode.volatility_quintile, volatility_tolerance):
                for bucket in buckets:
                    key = (
                        episode.high_timeframe_trend_state,
                        episode.key_level_distance_quintile,
                        activity,
                        volatility,
                        bucket,
                        terminal,
                    )
                    yield from source.get(key, ())

    def select(self, episode: V14PrimaryEpisode) -> tuple[MatchLevel, tuple[CandidateLite, ...]]:
        for level in cast(tuple[MatchLevel, ...], ("L0", "L1", "L2", "L3", "L4")):
            eligible = (
                candidate
                for candidate in self._matches(episode, level)
                if not _overlaps(
                    candidate.anchor_ns - BACKWARD_PURGE_SECONDS * NS,
                    candidate.anchor_ns + FORWARD_EMBARGO_SECONDS * NS,
                    episode.information_span_start_ns,
                    episode.information_span_end_ns,
                )
            )
            selected = tuple(
                heapq.nsmallest(
                    CONTROLS_PER_EPISODE,
                    eligible,
                    key=lambda candidate: (
                        hashlib.sha256(
                            (
                                f"{episode.market_episode_id}|{candidate.anchor_ns}|{MATCHING_SEED}"
                            ).encode()
                        ).hexdigest(),
                        candidate.anchor_ns,
                    ),
                )
            )
            if len(selected) == CONTROLS_PER_EPISODE:
                return level, selected
        return "L5", ()


def _utc_parts(timestamp_ns: int) -> tuple[int, int, int, int]:
    instant = datetime.fromtimestamp(timestamp_ns / NS, UTC)
    return instant.year, (instant.month - 1) // 3 + 1, instant.hour // 4, instant.month


def _event_outcomes(row: dict[str, Any]) -> tuple[OutcomeCell, ...]:
    cells = tuple(
        OutcomeCell(
            combination_id=combination,
            label=cast(Any, label),
            label_reason=str(reason),
            strict_target_first=cast(Any, int(bool(strict))),
        )
        for combination, label, reason, strict in zip(
            COMBINATION_ORDER,
            row["labels"],
            row["label_reasons"],
            row["strict_target_first"],
            strict=True,
        )
    )
    if len(cells) != 30:
        raise ValueError("event outcome matrix no longer has 30 cells")
    return cells


def match_group(
    *,
    authority: S2T15ContractAuthority | S2P13T16ContractAuthority,
    bins: BinningIndex,
    same_family: SameFamilyIntervals,
    episode_rows: list[dict[str, Any]],
    feature_block_path: Path,
    instrument: str,
    period: str,
    fold: str,
    parameter_set_id: str,
    time_combination_id: str,
    output_path: Path,
    t10_snapshot_hash: str,
) -> dict[str, Any]:
    contract = next(item for item in ROLLING_FOLDS if item.period == period and item.fold == fold)
    volatility = bins.boundary(
        instrument=instrument, period=period, fold=fold, feature_kind="VOLATILITY"
    )
    activity = bins.boundary(
        instrument=instrument, period=period, fold=fold, feature_kind="TRADES_ACTIVITY"
    )
    distance = bins.boundary(
        instrument=instrument,
        period=period,
        fold=fold,
        feature_kind="KEY_LEVEL_DISTANCE",
        parameter_set_id=parameter_set_id,
    )
    combined_hash = bins.combined_hash(instrument, period, fold, parameter_set_id)
    table = pq.read_table(feature_block_path)
    distance_column = f"distance_bps__{parameter_set_id}"
    counts: Counter[str] = Counter()
    candidates: list[CandidateLite] = []
    for row in table.select(
        [
            "anchor_ns",
            "reference_price",
            "volatility_rms_bps",
            "activity_count_60s",
            "high_timeframe_trend_state",
            "market_exclusion_reason",
            distance_column,
        ]
    ).to_pylist():
        counts["grid_anchor_count"] += 1
        anchor = int(row["anchor_ns"])
        if not (
            contract.evaluation_start_ns <= anchor - BACKWARD_PURGE_SECONDS * NS
            and anchor + FORWARD_EMBARGO_SECONDS * NS <= contract.evaluation_end_ns
        ):
            counts["incomplete_information_span"] += 1
            continue
        reason = row["market_exclusion_reason"]
        if reason is not None:
            counts[str(reason).lower()] += 1
            continue
        counts["market_state_eligible_anchor_count"] += 1
        counts["candidate_opportunity_count"] += 1
        if row[distance_column] is None:
            counts["key_level_unavailable"] += 1
            continue
        if same_family.overlaps(
            instrument=instrument,
            start_ns=anchor,
            end_ns=anchor + FORWARD_EMBARGO_SECONDS * NS,
        ):
            counts["registered_same_family_event"] += 1
            continue
        year, quarter, bucket, _ = _utc_parts(anchor)
        candidates.append(
            CandidateLite(
                anchor_ns=anchor,
                reference_price=Decimal(row["reference_price"]),
                high_timeframe_trend_state=str(row["high_timeframe_trend_state"]),
                volatility_quintile=volatility.assign(Decimal(row["volatility_rms_bps"])),
                activity_quintile=activity.assign(Decimal(row["activity_count_60s"])),
                distance_quintile=distance.assign(Decimal(row[distance_column])),
                four_hour_bucket=bucket,
                quarter=quarter,
                year=year,
            )
        )
    counts["eligible_control_count"] = len(candidates)
    counts["unique_control_candidate_count"] = len(candidates)
    index = CandidateIndex(candidates)
    rows: list[dict[str, Any]] = []
    match_levels: Counter[str] = Counter()
    assignment_ids: list[str] = []
    for source in episode_rows:
        anchor = int(source["anchor_ns"])
        year, quarter, bucket, _ = _utc_parts(anchor)
        episode = V14PrimaryEpisode(
            market_episode_id=source["market_episode_id"],
            source_h2_path_hash=source["classification_row_hash"],
            instrument=cast(Any, instrument),
            anchor_ns=anchor,
            high_timeframe_trend_state=source["high_timeframe_trend_state"],
            pre_registered_period=cast(Any, period),
            evaluation_fold=cast(Any, fold),
            parameter_set_id=parameter_set_id,
            time_combination_id=cast(Any, time_combination_id),
            label_contract_hash=authority.label_contract_hash,
            volatility_quintile=volatility.assign(Decimal(source["volatility_rms_bps"])),
            activity_quintile=activity.assign(Decimal(source["activity_count_60s"])),
            key_level_distance_quintile=distance.assign(Decimal(source["key_level_distance_bps"])),
            utc_four_hour_bucket=bucket,
            utc_calendar_quarter=quarter,
            utc_calendar_year=year,
            binning_snapshot_hash=combined_hash,
            information_span_start_ns=anchor - BACKWARD_PURGE_SECONDS * NS,
            information_span_end_ns=anchor + FORWARD_EMBARGO_SECONDS * NS,
        )
        level, selected = index.select(episode)
        sealed: list[V14ControlCandidate] = []
        for candidate in selected:
            control_anchor = ControlAnchor.seal(
                {
                    "instrument": instrument,
                    "candidate_timestamp_ns": candidate.anchor_ns,
                    "stage1_data_run_id": STAGE1_DATA_RUN_ID,
                    "t10_snapshot_hash": t10_snapshot_hash,
                }
            )
            sealed.append(
                V14ControlCandidate.seal(
                    {
                        "control_anchor_id": control_anchor.control_anchor_id,
                        "instrument": instrument,
                        "candidate_timestamp_ns": candidate.anchor_ns,
                        "high_timeframe_trend_state": candidate.high_timeframe_trend_state,
                        "pre_registered_period": period,
                        "evaluation_fold": fold,
                        "parameter_set_id": parameter_set_id,
                        "time_combination_id": time_combination_id,
                        "label_contract_hash": authority.label_contract_hash,
                        "control_entry_price": candidate.reference_price,
                        "entry_price_source_hash": t10_snapshot_hash,
                        "outcome_contract_hash": authority.label_contract_hash,
                        "volatility_quintile": candidate.volatility_quintile,
                        "activity_quintile": candidate.activity_quintile,
                        "key_level_distance_quintile": candidate.distance_quintile,
                        "utc_four_hour_bucket": candidate.four_hour_bucket,
                        "utc_calendar_quarter": candidate.quarter,
                        "utc_calendar_year": candidate.year,
                        "binning_snapshot_hash": combined_hash,
                        "information_span_start_ns": (
                            candidate.anchor_ns - BACKWARD_PURGE_SECONDS * NS
                        ),
                        "information_span_end_ns": (
                            candidate.anchor_ns + FORWARD_EMBARGO_SECONDS * NS
                        ),
                        "is_registered_same_family_event": False,
                    }
                )
            )
        status = "MATCHED" if sealed else "UNMATCHED"
        match_levels[level] += 1
        assignment_ids.extend(candidate.control_candidate_id for candidate in sealed)
        outcomes = _event_outcomes(source)
        selected_json = json.dumps(
            [candidate.model_dump(mode="json") for candidate in sealed],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        event_json = json.dumps(
            [cell.model_dump(mode="json") for cell in outcomes],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        row = {
            "instrument": instrument,
            "pre_registered_period": period,
            "evaluation_fold": fold,
            "parameter_set_id": parameter_set_id,
            "time_combination_id": time_combination_id,
            "market_episode_id": episode.market_episode_id,
            "classification_row_hash": episode.source_h2_path_hash,
            "status": status,
            "match_level": level,
            "control_candidate_ids": [candidate.control_candidate_id for candidate in sealed],
            "selected_candidates_json": selected_json,
            "event_outcomes_json": event_json,
        }
        row["selection_hash"] = canonical_hash(row)
        rows.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=SELECTION_SCHEMA),
        output_path,
        compression="zstd",
    )
    matched = sum(row["status"] == "MATCHED" for row in rows)
    report: dict[str, Any] = {
        "schema_name": "stage2-s2t15-outcome-blind-group-report",
        "schema_version": "1.0",
        "status": "PASS",
        "instrument": instrument,
        "period": period,
        "fold": fold,
        "parameter_set_id": parameter_set_id,
        "time_combination_id": time_combination_id,
        "eligible_episode_count": len(rows),
        "matched_episode_count": matched,
        "unmatched_episode_count": len(rows) - matched,
        "match_level_counts": dict(sorted(match_levels.items())),
        "control_assignment_count": len(assignment_ids),
        "unique_assigned_control_count": len(set(assignment_ids)),
        "control_reuse_rate": (
            format(
                Decimal(len(assignment_ids) - len(set(assignment_ids)))
                / Decimal(len(assignment_ids)),
                "f",
            )
            if assignment_ids
            else None
        ),
        "control_accounting": dict(sorted(counts.items())),
        "selection_parquet_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "outcome_fields_read_before_matching": [],
        "historical_evidence_only": True,
    }
    report["report_hash"] = canonical_hash(report)
    return report
