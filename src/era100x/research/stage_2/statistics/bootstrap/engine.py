"""Vectorized weekly aggregation, cluster bootstrap and BH correction."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import numpy as np

from era100x.research.stage_2.baselines.conditional.v14_contracts import COMBINATION_ORDER
from era100x.research.stage_2.baselines.placebo.contracts import PlaceboMatchMatrix

from .contracts import (
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
    AnalysisScope,
    BootstrapSummary,
    ClusterSufficientStatistic,
    FdrFamilySummary,
    MetricFamily,
)
from .formatting import canonical_hash, decimal_text

NS = 1_000_000_000
WEEK_NS = 7 * 24 * 60 * 60 * NS
PRIMARY = ("G1-PRIMARY-V1", "T2", "target=20|stop=25")
METRIC_FAMILIES: tuple[MetricFamily, ...] = (
    "REAL_EVENT_DELTA",
    "PLACEBO_DELTA",
    "PAIRED_REAL_MINUS_PLACEBO",
)


def utc_monday_week_start_ns(timestamp_ns: int) -> int:
    if timestamp_ns < 0:
        raise ValueError("negative event timestamp")
    instant = datetime.fromtimestamp(timestamp_ns / NS, UTC)
    midnight = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = midnight - timedelta(days=midnight.weekday())
    return int(monday.timestamp()) * NS


def cluster_id(instrument: str, week_start_ns: int) -> str:
    return f"{instrument}|{week_start_ns}"


@dataclass(slots=True)
class _MutableStatistic:
    real_count: int
    placebo_count: int
    paired_count: int
    arrays: list[list[int]]

    @classmethod
    def empty(cls) -> _MutableStatistic:
        return cls(0, 0, 0, [[0] * len(COMBINATION_ORDER) for _ in range(8)])


def _strict_values(cells: Sequence[Any]) -> list[int]:
    if (
        len(cells) != len(COMBINATION_ORDER)
        or tuple(cell.combination_id for cell in cells) != COMBINATION_ORDER
    ):
        raise ValueError("T18 outcome combination order drift")
    return [int(cell.strict_target_first) for cell in cells]


def _control_values(controls: Sequence[Sequence[Any]]) -> list[int]:
    if len(controls) != 5:
        raise ValueError("T18 source matrix must bind five controls")
    result = [0] * len(COMBINATION_ORDER)
    for cells in controls:
        for index, value in enumerate(_strict_values(cells)):
            result[index] += value
    return result


def aggregate_match_matrices(
    *,
    matrix_json_values: Iterable[str],
    anchor_by_identity: Mapping[tuple[str, str], int],
    instrument: str,
    period: str,
    fold: str,
    parameter_set_id: str,
    time_combination_id: str,
) -> tuple[ClusterSufficientStatistic, ...]:
    mutable: dict[int, _MutableStatistic] = {}
    seen: set[tuple[str, str]] = set()
    for raw in matrix_json_values:
        matrix = PlaceboMatchMatrix.model_validate_json(raw, strict=True)
        identity = (matrix.source_episode_id, matrix.source_h2_path_hash)
        if identity in seen:
            raise ValueError("duplicate T18 source matrix identity")
        seen.add(identity)
        try:
            anchor_ns = anchor_by_identity[identity]
        except KeyError as error:
            raise ValueError("T18 source matrix has no prepared-Episode anchor") from error
        week = utc_monday_week_start_ns(anchor_ns)
        item = mutable.setdefault(week, _MutableStatistic.empty())
        real_event = _strict_values(matrix.real_event_outcomes)
        real_controls = _control_values(matrix.real_control_outcomes)
        item.real_count += 1
        for index in range(len(COMBINATION_ORDER)):
            item.arrays[0][index] += real_event[index]
            item.arrays[1][index] += real_controls[index]
        if matrix.status != "MATCHED":
            continue
        placebo_event = _strict_values(matrix.placebo_event_outcomes)
        placebo_controls = _control_values(matrix.placebo_control_outcomes)
        item.placebo_count += 1
        item.paired_count += 1
        for index in range(len(COMBINATION_ORDER)):
            item.arrays[2][index] += placebo_event[index]
            item.arrays[3][index] += placebo_controls[index]
            item.arrays[4][index] += real_event[index]
            item.arrays[5][index] += real_controls[index]
            item.arrays[6][index] += placebo_event[index]
            item.arrays[7][index] += placebo_controls[index]
    output: list[ClusterSufficientStatistic] = []
    for week, item in sorted(mutable.items()):
        output.append(
            ClusterSufficientStatistic.seal(
                {
                    "instrument": instrument,
                    "pre_registered_period": period,
                    "evaluation_fold": fold,
                    "parameter_set_id": parameter_set_id,
                    "time_combination_id": time_combination_id,
                    "week_start_ns": week,
                    "cluster_id": cluster_id(instrument, week),
                    "real_count": item.real_count,
                    "placebo_count": item.placebo_count,
                    "paired_count": item.paired_count,
                    "real_event_success": tuple(item.arrays[0]),
                    "real_control_success": tuple(item.arrays[1]),
                    "placebo_event_success": tuple(item.arrays[2]),
                    "placebo_control_success": tuple(item.arrays[3]),
                    "paired_real_event_success": tuple(item.arrays[4]),
                    "paired_real_control_success": tuple(item.arrays[5]),
                    "paired_placebo_event_success": tuple(item.arrays[6]),
                    "paired_placebo_control_success": tuple(item.arrays[7]),
                }
            )
        )
    return tuple(output)


def _derived_seed(metric: MetricFamily, group_key: str) -> int:
    payload = f"S2P15T18|{metric}|{group_key}|{BOOTSTRAP_SEED}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _merge_cluster_statistics(
    statistics: Sequence[ClusterSufficientStatistic],
) -> tuple[ClusterSufficientStatistic, ...]:
    grouped: dict[str, list[ClusterSufficientStatistic]] = defaultdict(list)
    for item in statistics:
        grouped[item.cluster_id].append(item)
    result: list[ClusterSufficientStatistic] = []
    array_fields = (
        "real_event_success",
        "real_control_success",
        "placebo_event_success",
        "placebo_control_success",
        "paired_real_event_success",
        "paired_real_control_success",
        "paired_placebo_event_success",
        "paired_placebo_control_success",
    )
    for key, items in sorted(grouped.items()):
        first = items[0]
        arrays = {
            field: tuple(
                sum(getattr(item, field)[index] for item in items)
                for index in range(len(COMBINATION_ORDER))
            )
            for field in array_fields
        }
        result.append(
            ClusterSufficientStatistic.seal(
                {
                    "instrument": first.instrument,
                    "pre_registered_period": first.pre_registered_period,
                    "evaluation_fold": first.evaluation_fold,
                    "parameter_set_id": first.parameter_set_id,
                    "time_combination_id": first.time_combination_id,
                    "week_start_ns": first.week_start_ns,
                    "cluster_id": key,
                    "real_count": sum(item.real_count for item in items),
                    "placebo_count": sum(item.placebo_count for item in items),
                    "paired_count": sum(item.paired_count for item in items),
                    **arrays,
                }
            )
        )
    return tuple(result)


def _arrays(
    statistics: Sequence[ClusterSufficientStatistic], metric: MetricFamily
) -> tuple[np.ndarray[Any, np.dtype[np.int64]], ...]:
    if metric == "REAL_EVENT_DELTA":
        count = np.asarray([item.real_count for item in statistics], dtype=np.int64)
        event = np.asarray([item.real_event_success for item in statistics], dtype=np.int64)
        controls = np.asarray([item.real_control_success for item in statistics], dtype=np.int64)
        zeros = np.zeros_like(event)
        return count, event, controls, zeros, zeros
    if metric == "PLACEBO_DELTA":
        count = np.asarray([item.placebo_count for item in statistics], dtype=np.int64)
        event = np.asarray([item.placebo_event_success for item in statistics], dtype=np.int64)
        controls = np.asarray([item.placebo_control_success for item in statistics], dtype=np.int64)
        zeros = np.zeros_like(event)
        return count, event, controls, zeros, zeros
    count = np.asarray([item.paired_count for item in statistics], dtype=np.int64)
    return (
        count,
        np.asarray([item.paired_real_event_success for item in statistics], dtype=np.int64),
        np.asarray([item.paired_real_control_success for item in statistics], dtype=np.int64),
        np.asarray([item.paired_placebo_event_success for item in statistics], dtype=np.int64),
        np.asarray([item.paired_placebo_control_success for item in statistics], dtype=np.int64),
    )


def _metric_values(
    counts: np.ndarray[Any, np.dtype[np.int64]],
    event: np.ndarray[Any, np.dtype[np.int64]],
    controls: np.ndarray[Any, np.dtype[np.int64]],
    other_event: np.ndarray[Any, np.dtype[np.int64]],
    other_controls: np.ndarray[Any, np.dtype[np.int64]],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    denominator = counts.astype(np.float64)
    first = event.astype(np.float64) / denominator[:, None]
    first -= controls.astype(np.float64) / (denominator[:, None] * 5.0)
    if np.any(other_event) or np.any(other_controls):
        first -= other_event.astype(np.float64) / denominator[:, None]
        first += other_controls.astype(np.float64) / (denominator[:, None] * 5.0)
    return first


def bootstrap_group(
    *,
    statistics: Sequence[ClusterSufficientStatistic],
    metric: MetricFamily,
    group_key: str,
    batch_size: int = 250,
    iterations: int = BOOTSTRAP_ITERATIONS,
) -> tuple[np.ndarray[Any, np.dtype[np.float64]], np.ndarray[Any, np.dtype[np.float64]], int]:
    eligible = sorted(
        (
            item
            for item in statistics
            if getattr(
                item,
                {
                    "REAL_EVENT_DELTA": "real_count",
                    "PLACEBO_DELTA": "placebo_count",
                    "PAIRED_REAL_MINUS_PLACEBO": "paired_count",
                }[metric],
            )
            > 0
        ),
        key=lambda item: item.cluster_id,
    )
    if len(eligible) < 2:
        return (
            np.empty((0, len(COMBINATION_ORDER)), dtype=np.float64),
            np.empty(len(COMBINATION_ORDER), dtype=np.float64),
            sum(
                getattr(
                    item,
                    {
                        "REAL_EVENT_DELTA": "real_count",
                        "PLACEBO_DELTA": "placebo_count",
                        "PAIRED_REAL_MINUS_PLACEBO": "paired_count",
                    }[metric],
                )
                for item in eligible
            ),
        )
    counts, event, controls, other_event, other_controls = _arrays(eligible, metric)
    totals = (
        np.asarray([counts.sum()], dtype=np.int64),
        event.sum(axis=0, keepdims=True),
        controls.sum(axis=0, keepdims=True),
        other_event.sum(axis=0, keepdims=True),
        other_controls.sum(axis=0, keepdims=True),
    )
    estimate = _metric_values(*totals)[0]
    rng = np.random.Generator(np.random.PCG64(_derived_seed(metric, group_key)))
    replicates = np.empty((iterations, len(COMBINATION_ORDER)), dtype=np.float64)
    offset = 0
    while offset < iterations:
        size = min(batch_size, iterations - offset)
        sampled = rng.integers(0, len(eligible), size=(size, len(eligible)), endpoint=False)
        weights = np.zeros((size, len(eligible)), dtype=np.int64)
        rows = np.repeat(np.arange(size), len(eligible))
        np.add.at(weights, (rows, sampled.reshape(-1)), 1)
        sampled_counts = weights @ counts
        sampled_event = weights @ event
        sampled_controls = weights @ controls
        sampled_other_event = weights @ other_event
        sampled_other_controls = weights @ other_controls
        replicates[offset : offset + size] = _metric_values(
            sampled_counts,
            sampled_event,
            sampled_controls,
            sampled_other_event,
            sampled_other_controls,
        )
        offset += size
    return replicates, estimate, int(counts.sum())


def summarize_bootstrap(
    *,
    statistics: Sequence[ClusterSufficientStatistic],
    instrument: str,
    scope: AnalysisScope,
    period: str | None,
    fold: str | None,
    parameter_set_id: str,
    time_combination_id: str,
    metric: MetricFamily,
    iterations: int = BOOTSTRAP_ITERATIONS,
) -> tuple[BootstrapSummary, ...]:
    statistics = _merge_cluster_statistics(statistics)
    group_key = "|".join(
        (instrument, scope, period or "ALL", fold or "ALL", parameter_set_id, time_combination_id)
    )
    replicates, estimate, episode_count = bootstrap_group(
        statistics=statistics,
        metric=metric,
        group_key=group_key,
        iterations=iterations,
    )
    cluster_count = sum(
        getattr(
            item,
            {
                "REAL_EVENT_DELTA": "real_count",
                "PLACEBO_DELTA": "placebo_count",
                "PAIRED_REAL_MINUS_PLACEBO": "paired_count",
            }[metric],
        )
        > 0
        for item in statistics
    )
    output: list[BootstrapSummary] = []
    for index, combination in enumerate(COMBINATION_ORDER):
        primary = (parameter_set_id, time_combination_id, combination) == PRIMARY
        common: dict[str, object] = {
            "instrument": instrument,
            "analysis_scope": scope,
            "pre_registered_period": period,
            "evaluation_fold": fold,
            "parameter_set_id": parameter_set_id,
            "time_combination_id": time_combination_id,
            "combination_id": combination,
            "metric_family": metric,
            "cluster_count": cluster_count,
            "episode_count": episode_count,
            "meets_200_cluster_baseline": cluster_count >= 200,
            "fdr_role": "PRIMARY_NOT_ADJUSTED" if primary else "EXPLORATORY_BH",
        }
        if cluster_count < 2:
            output.append(
                BootstrapSummary.seal(
                    {
                        **common,
                        "status": "INSUFFICIENT_CLUSTERS",
                        "estimate": None,
                        "ci_lower": None,
                        "ci_upper": None,
                        "bootstrap_median": None,
                        "bootstrap_standard_error": None,
                        "raw_p_value": None,
                        "replicate_hash": None,
                    }
                )
            )
            continue
        values = replicates[:, index]
        lower, median, upper = np.quantile(values, [0.025, 0.5, 0.975], method="linear")
        standard_error = float(values.std(ddof=1))
        extreme = int(np.count_nonzero(np.abs(values - estimate[index]) >= abs(estimate[index])))
        raw_p = Decimal(extreme + 1) / Decimal(iterations + 1)
        replicate_text = tuple(decimal_text(float(value)) for value in values)
        output.append(
            BootstrapSummary.seal(
                {
                    **common,
                    "status": "PASS",
                    "estimate": decimal_text(float(estimate[index])),
                    "ci_lower": decimal_text(float(lower)),
                    "ci_upper": decimal_text(float(upper)),
                    "bootstrap_median": decimal_text(float(median)),
                    "bootstrap_standard_error": decimal_text(standard_error),
                    "raw_p_value": decimal_text(raw_p),
                    "replicate_hash": canonical_hash(replicate_text),
                }
            )
        )
    return tuple(output)


def _family_id(summary: BootstrapSummary) -> str:
    if summary.analysis_scope == "FOLD":
        scope_key = f"{summary.pre_registered_period}|{summary.evaluation_fold}"
    elif summary.analysis_scope == "PERIOD":
        scope_key = str(summary.pre_registered_period)
    else:
        scope_key = "ALL"
    return "|".join((summary.instrument, summary.metric_family, summary.analysis_scope, scope_key))


def apply_bh(
    summaries: Sequence[BootstrapSummary],
) -> tuple[tuple[BootstrapSummary, ...], tuple[FdrFamilySummary, ...]]:
    groups: dict[str, list[tuple[int, BootstrapSummary]]] = defaultdict(list)
    result = list(summaries)
    for index, summary in enumerate(summaries):
        if summary.fdr_role == "EXPLORATORY_BH":
            groups[_family_id(summary)].append((index, summary))
    family_summaries: list[FdrFamilySummary] = []
    for family_id, items in sorted(groups.items()):
        valid = [(index, summary) for index, summary in items if summary.raw_p_value is not None]
        ranked = sorted(
            valid,
            key=lambda pair: (
                Decimal(cast(str, pair[1].raw_p_value)),
                pair[1].parameter_set_id,
                pair[1].time_combination_id,
                pair[1].combination_id,
            ),
        )
        hypothesis_count = len(items)
        adjusted: list[Decimal] = [Decimal(1)] * len(ranked)
        running = Decimal(1)
        for reverse_index in range(len(ranked) - 1, -1, -1):
            rank = reverse_index + 1
            p_value = Decimal(cast(str, ranked[reverse_index][1].raw_p_value))
            candidate = min(Decimal(1), p_value * Decimal(hypothesis_count) / Decimal(rank))
            running = min(running, candidate)
            adjusted[reverse_index] = running
        significant = 0
        for (index, summary), q_value in zip(ranked, adjusted, strict=True):
            flag = q_value <= Decimal("0.10")
            significant += int(flag)
            updated = summary.model_copy(
                update={
                    "adjusted_q_value": decimal_text(q_value),
                    "fdr_significant": flag,
                    "summary_hash": "0" * 64,
                }
            )
            result[index] = updated.model_copy(update={"summary_hash": updated.computed_hash()})
        exemplar = items[0][1]
        family_summaries.append(
            FdrFamilySummary.seal(
                {
                    "family_id": family_id,
                    "instrument": exemplar.instrument,
                    "metric_family": exemplar.metric_family,
                    "analysis_scope": exemplar.analysis_scope,
                    "hypothesis_count": hypothesis_count,
                    "tested_hypothesis_count": len(ranked),
                    "significant_count": significant,
                }
            )
        )
    return tuple(result), tuple(family_summaries)


def group_statistics_for_scopes(
    statistics: Sequence[ClusterSufficientStatistic],
) -> dict[
    tuple[str, AnalysisScope, str | None, str | None, str, str], list[ClusterSufficientStatistic]
]:
    groups: dict[
        tuple[str, AnalysisScope, str | None, str | None, str, str],
        list[ClusterSufficientStatistic],
    ] = defaultdict(list)
    for item in statistics:
        common = (item.instrument, item.parameter_set_id, item.time_combination_id)
        groups[
            (common[0], "FOLD", item.pre_registered_period, item.evaluation_fold, *common[1:])
        ].append(item)
        groups[(common[0], "PERIOD", item.pre_registered_period, None, *common[1:])].append(item)
        groups[(common[0], "OVERALL", None, None, *common[1:])].append(item)
    return groups


def compute_all_summaries(
    statistics: Sequence[ClusterSufficientStatistic],
    *,
    iterations: int = BOOTSTRAP_ITERATIONS,
    progress: Callable[[MetricFamily, int, int], None] | None = None,
) -> tuple[tuple[BootstrapSummary, ...], tuple[FdrFamilySummary, ...]]:
    summaries: list[BootstrapSummary] = []
    groups = sorted(group_statistics_for_scopes(statistics).items())
    for metric in METRIC_FAMILIES:
        for index, (key, items) in enumerate(groups, start=1):
            instrument, scope, period, fold, parameter, timing = key
            summaries.extend(
                summarize_bootstrap(
                    statistics=items,
                    instrument=instrument,
                    scope=scope,
                    period=period,
                    fold=fold,
                    parameter_set_id=parameter,
                    time_combination_id=timing,
                    metric=metric,
                    iterations=iterations,
                )
            )
            if progress is not None:
                progress(metric, index, len(groups))
    return apply_bh(summaries)
