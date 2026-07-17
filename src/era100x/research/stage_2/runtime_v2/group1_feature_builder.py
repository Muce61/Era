"""Pure Group-1 reconstruction from the immutable Feature Foundation.

This module is the only bridge from the approved V2 feature snapshots to the
existing Group-1 event algorithms.  It accepts explicit Arrow objects and has
no source-discovery, filesystem, network, or dynamic-plugin capability.  The
event formulas, identities, CR-2026-005 Sweep-minute ownership, and the
thirteen formal V1 datasets are deliberately reused unchanged.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

import pyarrow as pa  # type: ignore[import-untyped]

from era100x.data.schema.models import ContractBar, ContractPrice1s
from era100x.research.stage_2.contracts.identity import (
    canonical_candidate_identity,
    canonical_candidate_payload_hash,
)
from era100x.research.stage_2.contracts.models import RawKeyLevel
from era100x.research.stage_2.episodes.hold import detect_hold
from era100x.research.stage_2.episodes.identity import build_market_episode
from era100x.research.stage_2.episodes.reclaim import detect_reclaim
from era100x.research.stage_2.episodes.sweep import detect_sweep
from era100x.research.stage_2.gates.price import evaluate_price_trigger
from era100x.research.stage_2.key_levels.arbitration import arbitrate_key_levels
from era100x.research.stage_2.key_levels.sources.common import SourceLineage
from era100x.research.stage_2.key_levels.sources.range_low import generate_range_lows
from era100x.research.stage_2.key_levels.sources.rolling_low_1m import (
    generate_rolling_lows_1m,
)
from era100x.research.stage_2.key_levels.sources.rolling_low_5m import (
    generate_rolling_lows_5m,
)
from era100x.research.stage_2.manifests.configuration import (
    parameter_sets,
    research_classification,
    timing_configurations,
)
from era100x.research.stage_2.pipelines.candidates.candidate_finalizer import (
    finalize_candidate_attempts,
    owner_partition,
)
from era100x.research.stage_2.pipelines.candidates.flow_phase import UNAVAILABLE_FIELDS
from era100x.research.stage_2.pipelines.candidates.io import records_logical_hash
from era100x.research.stage_2.pipelines.candidates.price_phase import owns_sweep_start

Instrument = Literal["BTCUSDT", "ETHUSDT"]
SourceDayStatus = Literal["COMPLETE", "INCOMPLETE", "UNAVAILABLE"]
type ArrowInput = pa.Table | pa.RecordBatch

SECOND_NS = 1_000_000_000
MINUTE_NS = 60 * SECOND_NS
DAY_NS = 86_400 * SECOND_NS
KEY_LEVEL_PARAMETER_SET_ID = "KEYLEVEL-BASE-V1"

PRICE_DATASETS = (
    "raw_key_levels",
    "canonical_key_levels",
    "arbitration",
    "sweeps",
    "reclaims",
    "holds",
    "price_triggers",
    "market_episodes",
    "candidate_inclusion",
    "flow_windows",
)
FLOW_DATASETS = ("flow_features", "market_episodes", "candidate_inclusion")
PRICE_PRE_FINALIZATION_DATASETS = PRICE_DATASETS[:7]


class FeatureFoundationContractError(ValueError):
    """An explicit V2 feature input cannot satisfy the frozen Group-1 contract."""


@dataclass(frozen=True, slots=True)
class Group1Lineage:
    data_run_id: str
    dataset_logical_hash: str
    config_hash: str
    code_version: str

    def __post_init__(self) -> None:
        if not self.data_run_id:
            raise ValueError("data_run_id is required")
        for field_name, value in (
            ("dataset_logical_hash", self.dataset_logical_hash),
            ("config_hash", self.config_hash),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{field_name} must be a lowercase SHA-256")
        if len(self.code_version) < 7:
            raise ValueError("code_version must identify the approved generator")


@dataclass(frozen=True, slots=True)
class Group1OwnerDayRecords:
    """The exact ten PRICE and three FLOW records for one UTC owner day."""

    instrument: Instrument
    owner_date: date
    price: Mapping[str, tuple[dict[str, Any], ...]]
    flow: Mapping[str, tuple[dict[str, Any], ...]]

    def __post_init__(self) -> None:
        if tuple(self.price) != PRICE_DATASETS:
            raise ValueError("owner day must contain the ten approved PRICE datasets")
        if tuple(self.flow) != FLOW_DATASETS:
            raise ValueError("owner day must contain the three approved FLOW datasets")

    def records(self, variant: str, dataset: str) -> tuple[dict[str, Any], ...]:
        if variant == "V1_PRICE":
            try:
                return self.price[dataset]
            except KeyError as exc:
                raise ValueError(f"unapproved PRICE dataset: {dataset}") from exc
        if variant == "V1_FLOW":
            try:
                return self.flow[dataset]
            except KeyError as exc:
                raise ValueError(f"unapproved FLOW dataset: {dataset}") from exc
        raise ValueError(f"unapproved Group-1 variant: {variant}")

    def legacy_hashes(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for variant, datasets in (("V1_PRICE", self.price), ("V1_FLOW", self.flow)):
            for dataset, records in datasets.items():
                result[f"{variant}/{dataset}"] = records_logical_hash(list(records), dataset)
        return result


@dataclass(frozen=True, slots=True)
class Group1FeatureBuild:
    """Deterministic owner-day projection plus non-published dedup audit facts."""

    instrument: Instrument
    days: tuple[Group1OwnerDayRecords, ...]
    price_audit_records: tuple[dict[str, Any], ...]
    flow_audit_records: tuple[dict[str, Any], ...]
    price_finalization_summary: Mapping[str, Any]
    flow_finalization_summary: Mapping[str, Any]

    def __post_init__(self) -> None:
        dates = tuple(item.owner_date for item in self.days)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("owner days must be unique and deterministically sorted")
        if any(item.instrument != self.instrument for item in self.days):
            raise ValueError("Group-1 build cannot mix BTC and ETH")

    def day(self, owner_date: date) -> Group1OwnerDayRecords:
        for item in self.days:
            if item.owner_date == owner_date:
                return item
        raise KeyError(owner_date)


@dataclass(frozen=True, slots=True)
class LegacyPartitionComparison:
    instrument: Instrument
    owner_date: date
    variant: Literal["V1_PRICE", "V1_FLOW"]
    dataset: str
    actual_row_count: int
    expected_row_count: int
    actual_logical_hash: str
    expected_logical_hash: str
    matches: bool


def build_group1_feature_range(
    *,
    instrument: Instrument,
    owner_dates: Sequence[date],
    contract_price_1s: ArrowInput,
    causal_price_bars: ArrowInput,
    trade_second_primitives: ArrowInput,
    trade_source_day_status: Mapping[date | str, SourceDayStatus],
    lineage: Group1Lineage,
) -> Group1FeatureBuild:
    """Reconstruct approved Group-1 records for one or more UTC owner days.

    ``contract_price_1s`` and ``causal_price_bars`` must include the causal
    lookback needed by the first requested day and the approved forward
    observation halo.  The function additionally evaluates the preceding
    processing day so an event detected immediately before midnight can be
    rehomed by ``available_at_ts`` without reading another artifact.
    """

    targets = tuple(sorted(set(owner_dates)))
    if not targets:
        raise ValueError("at least one owner date is required")
    prices = _contract_prices(contract_price_1s, instrument)
    bars = _contract_bars(causal_price_bars, instrument)
    trade_seconds = _trade_seconds(trade_second_primitives, instrument)
    quality = _normalize_day_quality(trade_source_day_status)

    processing_dates = tuple(sorted(set(targets) | {item - timedelta(days=1) for item in targets}))
    price_processing = [
        build_price_processing_day_from_features(
            instrument=instrument,
            processing_date=processing_date,
            contract_prices=prices,
            causal_bars=bars,
            lineage=lineage,
        )
        for processing_date in processing_dates
    ]

    price_attempts = [
        record for output in price_processing for record in output["candidate_attempts"]
    ]
    price_finalized = finalize_candidate_attempts(price_attempts)
    direct_price = _project_direct_price_records(
        tuple(zip(processing_dates, price_processing, strict=True)), targets
    )

    flow_features: dict[str, list[dict[str, Any]]] = {owner.isoformat(): [] for owner in targets}
    flow_attempts: list[dict[str, Any]] = []
    target_keys = set(flow_features)
    for owner in targets:
        key = owner.isoformat()
        flow_output = build_flow_owner_day_from_primitives(
            instrument=instrument,
            owner_date=owner,
            windows=price_finalized.flow_windows_by_date.get(key, []),
            trade_seconds=trade_seconds,
            trade_source_day_status=quality,
        )
        flow_features[key].extend(flow_output["flow_features"])
        flow_attempts.extend(flow_output["candidate_attempts"])
    flow_finalized = finalize_candidate_attempts(flow_attempts, include_flow_windows=False)

    days: list[Group1OwnerDayRecords] = []
    for owner in targets:
        key = owner.isoformat()
        price_records = {
            dataset: tuple(direct_price[key][dataset])
            for dataset in PRICE_PRE_FINALIZATION_DATASETS
        }
        price_records.update(
            {
                "market_episodes": tuple(price_finalized.market_episodes_by_date.get(key, [])),
                "candidate_inclusion": tuple(price_finalized.inclusion_by_date.get(key, [])),
                "flow_windows": tuple(price_finalized.flow_windows_by_date.get(key, [])),
            }
        )
        flow_records = {
            "flow_features": tuple(flow_features[key]),
            "market_episodes": tuple(flow_finalized.market_episodes_by_date.get(key, [])),
            "candidate_inclusion": tuple(flow_finalized.inclusion_by_date.get(key, [])),
        }
        days.append(
            Group1OwnerDayRecords(
                instrument=instrument,
                owner_date=owner,
                price=price_records,
                flow=flow_records,
            )
        )

    if set(price_finalized.market_episodes_by_date) - target_keys:
        # These are valid halo outputs but cannot silently enter the requested
        # owner range.  They are preserved in the audit records and rebuilt by
        # the adjacent owner-range task.
        pass
    return Group1FeatureBuild(
        instrument=instrument,
        days=tuple(days),
        price_audit_records=tuple(price_finalized.audit_records),
        flow_audit_records=tuple(flow_finalized.audit_records),
        price_finalization_summary=price_finalized.summary,
        flow_finalization_summary=flow_finalized.summary,
    )


def build_price_processing_day_from_features(
    *,
    instrument: Instrument,
    processing_date: date,
    contract_prices: Sequence[ContractPrice1s],
    causal_bars: Sequence[ContractBar],
    lineage: Group1Lineage,
    record_sink: Callable[[str, Mapping[str, Any]], None] | None = None,
    retained_outputs: frozenset[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build one processing day with an optional bounded upstream-record sink.

    The default remains the exact in-memory V1-compatible result.  A production
    caller may retain only ``candidate_attempts`` while receiving each of the
    seven formal upstream PRICE records through ``record_sink`` in the same
    deterministic order.  Candidate attempts are intentionally not sent to the
    sink because they still require cross-processing-day finalization by
    ``available_at_ts``.
    """

    day_start = _day_start_ns(processing_date)
    day_end = day_start + DAY_NS
    previous_start = day_start - DAY_NS
    relevant_bars = [bar for bar in causal_bars if previous_start <= bar.bucket_start_ns < day_end]
    second_rows = [
        row
        for row in contract_prices
        if day_start - 5 * SECOND_NS <= row.ts_event_ns < day_end + 180 * SECOND_NS
    ]
    seconds_by_ts = {row.ts_event_ns: row for row in second_rows}
    if len(seconds_by_ts) != len(second_rows):
        raise FeatureFoundationContractError("duplicate Contract Price second")

    source_lineage = SourceLineage(
        lineage.data_run_id,
        lineage.dataset_logical_hash,
        lineage.config_hash,
        lineage.code_version,
        KEY_LEVEL_PARAMETER_SET_ID,
    )
    raw_all = _raw_levels(relevant_bars, source_lineage)
    raw = [item for item in raw_all if day_start <= item.available_at_ts < day_end]
    by_available: dict[int, list[RawKeyLevel]] = {}
    for item in raw_all:
        by_available.setdefault(item.available_at_ts, []).append(item)

    minute_by_start = {
        bar.bucket_start_ns: bar for bar in relevant_bars if bar.interval_seconds == 60
    }
    hourly = [bar for bar in relevant_bars if bar.interval_seconds == 3600]
    active: dict[tuple[str, str], RawKeyLevel] = {}
    allowed_outputs = (*PRICE_PRE_FINALIZATION_DATASETS, "candidate_attempts")
    retained = frozenset(allowed_outputs) if retained_outputs is None else retained_outputs
    if not retained.issubset(allowed_outputs):
        raise ValueError("retained_outputs contains an unapproved PRICE output")
    if "candidate_attempts" not in retained:
        raise ValueError("candidate_attempts must remain available for deterministic finalization")
    output: dict[str, list[dict[str, Any]]] = {
        name: [] for name in allowed_outputs if name in retained
    }

    def emit(dataset: str, record: dict[str, Any]) -> None:
        if dataset in PRICE_PRE_FINALIZATION_DATASETS and record_sink is not None:
            record_sink(dataset, record)
        if dataset in output:
            output[dataset].append(record)

    for item in raw:
        emit("raw_key_levels", item.model_dump(mode="json"))
    timings = {item.timing_id: item for item in timing_configurations()}
    parameter_family = parameter_sets()
    for minute_start in range(day_start, day_end, MINUTE_NS):
        available = minute_start + MINUTE_NS
        for item in by_available.get(available, []):
            active[(item.source_type, item.source_timeframe)] = item
        current_minute = minute_by_start.get(minute_start)
        previous_minute = minute_by_start.get(minute_start - MINUTE_NS)
        if current_minute is None or previous_minute is None or not active:
            continue
        canonical_by_merge = {
            tolerance: arbitrate_key_levels(
                list(active.values()),
                merge_tolerance_bps=tolerance,
                expires_at_ns=available + MINUTE_NS,
            )
            for tolerance in (Decimal("5"), Decimal("10"), Decimal("15"))
        }
        for parameter in parameter_family:
            canonical_levels = canonical_by_merge[parameter.merge_tolerance_bps]
            for canonical in canonical_levels:
                canonical_record = {
                    **canonical.model_dump(mode="json"),
                    "event_parameter_set_id": parameter.parameter_set_id,
                }
                emit("canonical_key_levels", canonical_record)
                emit(
                    "arbitration",
                    {
                        "key_level_id": canonical_record["key_level_id"],
                        "normalization_group": canonical_record["normalization_group"],
                        "member_key_level_ids": canonical_record["member_key_level_ids"],
                        "reason_code": canonical_record["reason_code"],
                        "event_parameter_set_id": canonical_record["event_parameter_set_id"],
                    },
                )
                if not (
                    current_minute.low < canonical.level_price
                    and previous_minute.close >= canonical.level_price
                ):
                    continue
                window = [
                    seconds_by_ts[ts]
                    for ts in range(minute_start, minute_start + 121 * SECOND_NS, SECOND_NS)
                    if ts in seconds_by_ts
                ]
                sweep = detect_sweep(
                    canonical,
                    window,
                    confirmation_bps=parameter.sweep_confirmation_bps,
                )
                if sweep is None or not owns_sweep_start(minute_start, sweep.sweep_start_ts):
                    continue
                emit(
                    "sweeps",
                    {
                        **sweep.model_dump(mode="json"),
                        "event_parameter_set_id": parameter.parameter_set_id,
                    },
                )
                if sweep.status != "DETECTED":
                    continue
                timing = timings[parameter.timing_id]
                reclaim = detect_reclaim(
                    sweep,
                    canonical,
                    window,
                    reclaim_buffer_bps=parameter.reclaim_buffer_bps,
                    timeout_seconds=timing.reclaim_timeout_seconds,
                )
                emit(
                    "reclaims",
                    {
                        **reclaim.model_dump(mode="json"),
                        "event_parameter_set_id": parameter.parameter_set_id,
                    },
                )
                if reclaim.status != "RECLAIMED":
                    continue
                hold = detect_hold(
                    reclaim,
                    canonical,
                    window,
                    hold_window_seconds=timing.hold_window_seconds,
                    failure_buffer_bps=parameter.hold_failure_buffer_bps,
                )
                emit(
                    "holds",
                    {
                        **hold.model_dump(mode="json"),
                        "event_parameter_set_id": parameter.parameter_set_id,
                    },
                )
                if hold.hold_result != "PASS":
                    continue
                trigger = evaluate_price_trigger(
                    hold,
                    hourly,
                    window,
                    structural_low_price=sweep.sweep_extreme_price,
                )
                emit(
                    "price_triggers",
                    {
                        **trigger.model_dump(mode="json"),
                        "event_parameter_set_id": parameter.parameter_set_id,
                    },
                )
                if trigger.status != "PASS":
                    continue
                episode = build_market_episode(
                    canonical,
                    sweep,
                    reclaim,
                    hold,
                    trigger,
                    None,
                    variant="V1_PRICE",
                    event_parameter_set_id=parameter.parameter_set_id,
                    time_combination_id=parameter.timing_id,
                )
                episode_record = {
                    **episode.model_dump(mode="json"),
                    "event_parameter_set_id": parameter.parameter_set_id,
                }
                ordinal = len(output["candidate_attempts"])
                output["candidate_attempts"].append(
                    {
                        **episode_record,
                        "trigger_available_at_ts": trigger.available_at_ts,
                        "window_start_ts": trigger.available_at_ts - 5 * SECOND_NS,
                        "window_end_ts": trigger.available_at_ts,
                        "source_processing_partition": processing_date.isoformat(),
                        "source_row_ordinal": ordinal,
                        "source_file_logical_path": (
                            f"instrument={instrument}/variant=V1_PRICE/"
                            "candidate_attempts/"
                            f"date={processing_date.isoformat()}/part-000.parquet"
                        ),
                    }
                )
    return output


def build_flow_owner_day_from_primitives(
    *,
    instrument: Instrument,
    owner_date: date,
    windows: Sequence[Mapping[str, Any]],
    trade_seconds: Mapping[int, Mapping[str, Any]],
    trade_source_day_status: Mapping[date, SourceDayStatus],
) -> dict[str, list[dict[str, Any]]]:
    """Build the unchanged G4 facts from sparse causal one-second primitives."""

    features: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for window in windows:
        if window.get("instrument") != instrument:
            raise FeatureFoundationContractError("Flow window mixes instruments")
        start = int(window["window_start_ts"])
        end = int(window["window_end_ts"])
        if end - start != 5 * SECOND_NS or start % SECOND_NS or end % SECOND_NS:
            raise FeatureFoundationContractError("G4 requires an aligned [t-5s,t) window")
        if owner_partition(end) != owner_date.isoformat():
            raise FeatureFoundationContractError("Flow window is outside its UTC owner day")

        buy = Decimal(0)
        sell = Decimal(0)
        latest = 0
        previous_count = 0
        missing_untrusted = False
        for ts in range(start, end, SECOND_NS):
            primitive = trade_seconds.get(ts)
            if primitive is None:
                second_date = _utc_date(ts)
                if trade_source_day_status.get(second_date) != "COMPLETE":
                    missing_untrusted = True
                continue
            buy_quantity = cast(Decimal, primitive["aggressor_buy_qty"])
            sell_quantity = cast(Decimal, primitive["aggressor_sell_qty"])
            # V1 starts each side at Decimal(0).  A missing side therefore
            # serializes as "0", not Decimal128's scale-bearing "0E-18".
            # Non-zero Stage 1 quantities retain their exact approved scale.
            if buy_quantity:
                buy += buy_quantity
            if sell_quantity:
                sell += sell_quantity
            count = int(primitive["trade_count"])
            if ts >= end - SECOND_NS:
                latest += count
            else:
                previous_count += count

        total = buy + sell
        previous_mean = Decimal(previous_count) / Decimal(4)
        imbalance = None if total == 0 or missing_untrusted else (buy - sell) / total
        passed = (
            not missing_untrusted
            and imbalance is not None
            and imbalance > 0
            and Decimal(latest) > previous_mean
        )
        unavailable = missing_untrusted or total == 0
        feature_id = _flow_feature_id(
            instrument,
            str(window["trigger_id"]),
            start,
            end,
            str(window["event_parameter_set_id"]),
        )
        research_role, primary_eligible = research_classification(
            str(window["event_parameter_set_id"]),
            str(window["time_combination_id"]),
        )
        feature = {
            "flow_feature_set_id": feature_id,
            "instrument": instrument,
            "window_start_ts": start,
            "window_end_ts": end,
            "buy_quantity": str(buy),
            "sell_quantity": str(sell),
            "signed_quantity_imbalance": None if imbalance is None else str(imbalance),
            "latest_1s_trade_count": latest,
            "previous_4s_per_second_mean": str(previous_mean),
            "status": "PASS" if passed else ("UNAVAILABLE" if unavailable else "REJECTED"),
            "unavailable_fields": UNAVAILABLE_FIELDS,
            "reason_code": (
                "FLOW_CONFIRMED"
                if passed
                else ("FLOW_TRADES_UNAVAILABLE" if unavailable else "FLOW_THRESHOLD_NOT_MET")
            ),
            "market_episode_id": window["market_episode_id"],
            "event_parameter_set_id": window["event_parameter_set_id"],
            "variant_id": "V1_FLOW",
            "time_combination_id": window["time_combination_id"],
            "research_role": research_role,
            "primary_eligible": primary_eligible,
        }
        features.append(feature)
        if not passed:
            continue

        identity_payload = {
            "variant": "V1_FLOW",
            "instrument": instrument,
            "direction": window["direction"],
            "key_level_id": window["canonical_key_level_id"],
            "sweep_id": window["sweep_id"],
            "reclaim_id": window["reclaim_id"],
            "hold_id": window["hold_id"],
            "price_trigger_id": window["trigger_id"],
            "time_combination_id": window["time_combination_id"],
            "event_parameter_set_id": window["event_parameter_set_id"],
            "available_at_ts": end,
            "stage1_data_run_id": window["data_run_id"],
            "stage1_instrument_logical_hash": window["dataset_logical_hash"],
            "config_hash": window["config_hash"],
            "flow_feature_set_id": feature_id,
        }
        canonical_id = canonical_candidate_identity(identity_payload)
        payload_hash = canonical_candidate_payload_hash(
            {
                "identity": identity_payload,
                "market_episode_id": window["market_episode_id"],
                "venue": window["venue"],
                "sweep_start_ns": window["sweep_start_ns"],
                "episode_status": "CANDIDATE",
                "parent_price_canonical_candidate_id": window["canonical_candidate_id"],
                "parent_price_payload_hash": window["canonical_payload_hash"],
                "flow_feature": feature,
                "variant_id": "V1_FLOW",
                "research_role": research_role,
                "primary_eligible": primary_eligible,
            }
        )
        ordinal = len(attempts)
        partition = owner_date.isoformat()
        attempts.append(
            {
                "market_episode_id": window["market_episode_id"],
                "canonical_candidate_id": canonical_id,
                "candidate_version_id": canonical_id,
                "canonical_payload_hash": payload_hash,
                "instrument": instrument,
                "direction": window["direction"],
                "data_run_id": window["data_run_id"],
                "dataset_logical_hash": window["dataset_logical_hash"],
                "config_hash": window["config_hash"],
                "code_version": window["code_version"],
                "parameter_set_id": window["event_parameter_set_id"],
                "variant": "V1_FLOW",
                "variant_id": "V1_FLOW",
                "available_at_ts": end,
                "venue": window["venue"],
                "canonical_key_level_id": window["canonical_key_level_id"],
                "sweep_id": window["sweep_id"],
                "reclaim_id": window["reclaim_id"],
                "hold_id": window["hold_id"],
                "trigger_id": window["trigger_id"],
                "flow_feature_set_id": feature_id,
                "time_combination_id": window["time_combination_id"],
                "research_role": research_role,
                "primary_eligible": primary_eligible,
                "sweep_start_ns": window["sweep_start_ns"],
                "episode_status": "CANDIDATE",
                "consumed": False,
                "consumed_by_intent_id": None,
                "rearm_eligible_at_ns": None,
                "event_parameter_set_id": window["event_parameter_set_id"],
                "source_processing_partition": partition,
                "source_row_ordinal": ordinal,
                "source_file_logical_path": (
                    f"instrument={instrument}/variant=V1_FLOW/candidate_attempts/"
                    f"date={partition}/part-000.parquet"
                ),
            }
        )
    return {"flow_features": features, "candidate_attempts": attempts}


def compare_group1_legacy_projection(
    actual: Group1FeatureBuild,
    expected: Mapping[date, Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]],
) -> tuple[LegacyPartitionComparison, ...]:
    """Compare a fixture, 30-day window, or full range with V1 daily records."""

    comparisons: list[LegacyPartitionComparison] = []
    for day in actual.days:
        try:
            expected_day = expected[day.owner_date]
        except KeyError as exc:
            raise ValueError(f"missing expected owner day: {day.owner_date}") from exc
        for variant, datasets in (("V1_PRICE", day.price), ("V1_FLOW", day.flow)):
            try:
                expected_variant = expected_day[variant]
            except KeyError as exc:
                raise ValueError(f"missing expected variant: {variant}") from exc
            for dataset, actual_records in datasets.items():
                try:
                    expected_records = expected_variant[dataset]
                except KeyError as exc:
                    raise ValueError(f"missing expected dataset: {variant}/{dataset}") from exc
                actual_hash = records_logical_hash(list(actual_records), dataset)
                expected_list = [dict(record) for record in expected_records]
                expected_hash = records_logical_hash(expected_list, dataset)
                comparisons.append(
                    LegacyPartitionComparison(
                        instrument=actual.instrument,
                        owner_date=day.owner_date,
                        variant=cast(Literal["V1_PRICE", "V1_FLOW"], variant),
                        dataset=dataset,
                        actual_row_count=len(actual_records),
                        expected_row_count=len(expected_list),
                        actual_logical_hash=actual_hash,
                        expected_logical_hash=expected_hash,
                        matches=(
                            len(actual_records) == len(expected_list)
                            and actual_hash == expected_hash
                        ),
                    )
                )
    return tuple(comparisons)


def _project_direct_price_records(
    processing_outputs: Sequence[tuple[date, Mapping[str, list[dict[str, Any]]]]],
    targets: Sequence[date],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Preserve the seven V1 PRICE processing-day partitions exactly.

    CR-2026-004 rehomes only formal candidate, inclusion, and Flow-window
    records by candidate ``available_at_ts``.  The seven upstream fact datasets
    remain byte-for-byte projections of ``build_price_day`` under its explicit
    processing date; silently rehoming them would change Run A's daily legacy
    hashes.
    """

    target_keys = {item.isoformat() for item in targets}
    projected: dict[str, dict[str, list[dict[str, Any]]]] = {
        key: {dataset: [] for dataset in PRICE_PRE_FINALIZATION_DATASETS}
        for key in sorted(target_keys)
    }
    for processing_date, output in processing_outputs:
        key = processing_date.isoformat()
        if key not in target_keys:
            continue
        for dataset in PRICE_PRE_FINALIZATION_DATASETS:
            projected[key][dataset].extend(output[dataset])
    return projected


def _raw_levels(bars: Sequence[ContractBar], lineage: SourceLineage) -> list[RawKeyLevel]:
    by_interval = {
        interval: [bar for bar in bars if bar.interval_seconds == interval]
        for interval in (60, 300, 900, 3600, 14_400, 86_400)
    }
    levels = generate_rolling_lows_1m(by_interval[60], lineage)
    levels += generate_rolling_lows_5m(by_interval[300], lineage)
    for timeframe, seconds in (("15m", 900), ("1H", 3600), ("4H", 14_400), ("1D", 86_400)):
        levels += generate_range_lows(by_interval[seconds], timeframe, lineage)  # type: ignore[arg-type]
    return sorted(levels, key=lambda item: (item.available_at_ts, item.raw_key_level_id))


def _contract_prices(source: ArrowInput, instrument: Instrument) -> tuple[ContractPrice1s, ...]:
    table = _as_table(source)
    required = (
        "instrument",
        "event_ts_ns",
        "available_at_ns",
        "open",
        "high",
        "low",
        "close",
        "volume",
    )
    _require_columns(table, required, "contract_price_1s")
    columns = {name: table[name].combine_chunks().to_pylist() for name in required}
    rows: list[ContractPrice1s] = []
    seen: set[int] = set()
    for index in range(table.num_rows):
        row_instrument = columns["instrument"][index]
        timestamp = columns["event_ts_ns"][index]
        available = columns["available_at_ns"][index]
        if row_instrument != instrument:
            raise FeatureFoundationContractError("Contract Price mixes instruments")
        if not isinstance(timestamp, int) or isinstance(timestamp, bool):
            raise FeatureFoundationContractError("Contract Price timestamp must be UTC ns")
        if available != timestamp + SECOND_NS:
            raise FeatureFoundationContractError("Contract Price availability must follow close")
        if timestamp in seen:
            raise FeatureFoundationContractError("duplicate Contract Price second")
        seen.add(timestamp)
        rows.append(
            ContractPrice1s(
                instrument=instrument,
                ts_event_ns=timestamp,
                open=_price_decimal(columns["open"][index], "open"),
                high=_price_decimal(columns["high"][index], "high"),
                low=_price_decimal(columns["low"][index], "low"),
                close=_price_decimal(columns["close"][index], "close"),
                volume=_price_decimal(columns["volume"][index], "volume"),
                source_encoding="SOURCE_FLOAT64",
            )
        )
    return tuple(sorted(rows, key=lambda item: item.ts_event_ns))


def _contract_bars(source: ArrowInput, instrument: Instrument) -> tuple[ContractBar, ...]:
    table = _as_table(source)
    required = (
        "instrument",
        "interval_seconds",
        "event_ts_ns",
        "available_at_ns",
        "open",
        "high",
        "low",
        "close",
        "volume",
    )
    _require_columns(table, required, "causal_price_bars")
    columns = {name: table[name].combine_chunks().to_pylist() for name in required}
    rows: list[ContractBar] = []
    seen: set[tuple[int, int]] = set()
    approved = {60, 300, 900, 3600, 14_400, 86_400}
    for index in range(table.num_rows):
        row_instrument = columns["instrument"][index]
        interval = columns["interval_seconds"][index]
        timestamp = columns["event_ts_ns"][index]
        available = columns["available_at_ns"][index]
        if row_instrument != instrument:
            raise FeatureFoundationContractError("causal bars mix instruments")
        if interval not in approved:
            raise FeatureFoundationContractError(f"unapproved price-bar interval: {interval}")
        if not isinstance(timestamp, int) or isinstance(timestamp, bool):
            raise FeatureFoundationContractError("price-bar timestamp must be UTC ns")
        if timestamp % (int(interval) * SECOND_NS):
            raise FeatureFoundationContractError("price bar is not UTC aligned")
        if available != timestamp + int(interval) * SECOND_NS:
            raise FeatureFoundationContractError("price bar is available before it closes")
        key = (int(interval), timestamp)
        if key in seen:
            raise FeatureFoundationContractError("duplicate causal price bar")
        seen.add(key)
        rows.append(
            ContractBar(
                instrument=instrument,
                source_type="CONTRACT",
                interval_seconds=int(interval),
                bucket_start_ns=timestamp,
                open=_price_decimal(columns["open"][index], "open"),
                high=_price_decimal(columns["high"][index], "high"),
                low=_price_decimal(columns["low"][index], "low"),
                close=_price_decimal(columns["close"][index], "close"),
                volume=_price_decimal(columns["volume"][index], "volume"),
            )
        )
    return tuple(sorted(rows, key=lambda item: (item.interval_seconds, item.bucket_start_ns)))


def _trade_seconds(source: ArrowInput, instrument: Instrument) -> dict[int, Mapping[str, Any]]:
    table = _as_table(source)
    required = (
        "instrument",
        "event_ts_ns",
        "second_end_ns",
        "available_at_ns",
        "trade_count",
        "aggressor_buy_count",
        "aggressor_sell_count",
        "aggressor_buy_qty",
        "aggressor_sell_qty",
        "signed_qty",
        "source_logical_hash",
    )
    _require_columns(table, required, "trade_second_primitives")
    columns = {name: table[name].combine_chunks().to_pylist() for name in required}
    result: dict[int, Mapping[str, Any]] = {}
    for index in range(table.num_rows):
        row_instrument = columns["instrument"][index]
        timestamp = columns["event_ts_ns"][index]
        if row_instrument != instrument:
            raise FeatureFoundationContractError("Trade primitives mix instruments")
        if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp % SECOND_NS:
            raise FeatureFoundationContractError("Trade primitive start must be aligned UTC ns")
        if timestamp in result:
            raise FeatureFoundationContractError("duplicate Trade primitive second")
        buy_count = int(columns["aggressor_buy_count"][index])
        sell_count = int(columns["aggressor_sell_count"][index])
        trade_count = int(columns["trade_count"][index])
        buy = _trade_decimal(columns["aggressor_buy_qty"][index], "aggressor_buy_qty")
        sell = _trade_decimal(columns["aggressor_sell_qty"][index], "aggressor_sell_qty")
        signed = _trade_decimal(columns["signed_qty"][index], "signed_qty")
        if columns["second_end_ns"][index] != timestamp + SECOND_NS:
            raise FeatureFoundationContractError("Trade primitive is not a one-second interval")
        if columns["available_at_ns"][index] != timestamp + SECOND_NS:
            raise FeatureFoundationContractError("Trade primitive is available before close")
        if trade_count != buy_count + sell_count:
            raise FeatureFoundationContractError("Trade primitive aggressor counts disagree")
        if signed != buy - sell:
            raise FeatureFoundationContractError("Trade primitive signed quantity disagrees")
        source_hash = columns["source_logical_hash"][index]
        if not isinstance(source_hash, str) or len(source_hash) != 64:
            raise FeatureFoundationContractError("Trade primitive source hash is invalid")
        result[timestamp] = {
            "trade_count": trade_count,
            "aggressor_buy_qty": buy,
            "aggressor_sell_qty": sell,
        }
    return result


def _normalize_day_quality(
    source: Mapping[date | str, SourceDayStatus],
) -> dict[date, SourceDayStatus]:
    result: dict[date, SourceDayStatus] = {}
    for raw_day, status in source.items():
        day = date.fromisoformat(raw_day) if isinstance(raw_day, str) else raw_day
        if status not in {"COMPLETE", "INCOMPLETE", "UNAVAILABLE"}:
            raise FeatureFoundationContractError(f"invalid source day status: {status}")
        if day in result and result[day] != status:
            raise FeatureFoundationContractError("conflicting source day quality")
        result[day] = status
    return result


def _as_table(source: ArrowInput) -> pa.Table:
    if isinstance(source, pa.Table):
        return source.combine_chunks()
    if isinstance(source, pa.RecordBatch):
        return pa.Table.from_batches([source]).combine_chunks()
    raise TypeError("Feature Foundation input must be an explicit Arrow table or record batch")


def _require_columns(table: pa.Table, required: Sequence[str], dataset: str) -> None:
    missing = set(required) - set(table.column_names)
    if missing:
        raise FeatureFoundationContractError(f"{dataset} missing columns: {sorted(missing)}")


def _finite_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise FeatureFoundationContractError(f"{field_name} must be a finite Decimal")
    return value


def _price_decimal(value: object, field_name: str) -> Decimal:
    """Reproduce the approved V1 Contract Price Float64 text boundary.

    Stage 1 Contract Price is physically Float64 in both the CSV and Parquet
    source layouts.  V1 converted the Polars Float64 scalar through ``str``
    before constructing Decimal, so integral prices intentionally retain one
    fractional zero (for example ``7171.0``).  The Foundation stores the
    numeric fact as Decimal128; this bounded compatibility conversion restores
    the exact legacy text while all event calculations still consume Decimal.
    """

    decimal_value = _finite_decimal(value, field_name)
    return Decimal(str(float(decimal_value)))


def _trade_decimal(value: object, field_name: str) -> Decimal:
    """Preserve Stage 1 Trades Decimal(38,18) scale exactly as V1 did."""

    return _finite_decimal(value, field_name)


def _day_start_ns(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp()) * SECOND_NS


def _utc_date(timestamp_ns: int) -> date:
    return datetime.fromtimestamp(timestamp_ns // SECOND_NS, tz=UTC).date()


def _flow_feature_id(
    instrument: str,
    trigger_id: str,
    start: int,
    end: int,
    parameter_set_id: str,
) -> str:
    payload = "|".join(
        map(
            str,
            (
                "flow-feature-set-v1",
                instrument,
                trigger_id,
                start,
                end,
                parameter_set_id,
            ),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()
