from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from era100x.research.stage_2.baselines.conditional.v14_contracts import (
    COMBINATION_ORDER,
    OutcomeCell,
)
from era100x.research.stage_2.baselines.placebo.contracts import PlaceboMatchMatrix
from era100x.research.stage_2.statistics.bootstrap.contracts import BootstrapSummary
from era100x.research.stage_2.statistics.bootstrap.engine import (
    _derived_seed,
    aggregate_match_matrices,
    apply_bh,
    bootstrap_group,
    summarize_bootstrap,
    utc_monday_week_start_ns,
)
from era100x.research.stage_2.statistics.bootstrap.formatting import canonical_json


def _hash(value: int) -> str:
    return f"{value:064x}"


def _cells(success: bool) -> tuple[OutcomeCell, ...]:
    return tuple(
        OutcomeCell(
            combination_id=combination,
            label="TARGET_FIRST" if success else "EXPIRED",
            label_reason="TARGET_OBSERVED_FIRST" if success else "HORIZON_EXPIRED_WITHOUT_TOUCH",
            strict_target_first=1 if success else 0,
        )
        for combination in COMBINATION_ORDER
    )


def _matrix(index: int, *, matched: bool, real: bool, placebo: bool) -> PlaceboMatchMatrix:
    controls = (_cells(False),) * 5
    payload: dict[str, object] = {
        "source_episode_id": _hash(index),
        "source_h2_path_hash": _hash(index + 100),
        "source_real_matrix_hash": _hash(index + 200),
        "selection_hash": _hash(index + 300),
        "status": "MATCHED" if matched else "UNMATCHED_CONTROLS",
        "placebo_event_candidate_id": _hash(index + 400),
        "placebo_event_outcome_matrix_id": _hash(index + 500) if matched else None,
        "placebo_event_outcomes": _cells(placebo) if matched else (),
        "placebo_control_candidate_ids": (
            tuple(_hash(index * 10 + value) for value in range(5)) if matched else ()
        ),
        "placebo_control_outcome_matrix_ids": (
            tuple(_hash(index * 10 + value + 20) for value in range(5)) if matched else ()
        ),
        "placebo_control_outcomes": controls if matched else (),
        "real_event_outcomes": _cells(real),
        "real_control_outcomes": controls,
    }
    return PlaceboMatchMatrix.seal(payload)


def _statistics() -> tuple[object, ...]:
    monday = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
    matrices = (
        _matrix(1, matched=True, real=True, placebo=False),
        _matrix(2, matched=True, real=False, placebo=True),
        _matrix(3, matched=False, real=True, placebo=False),
    )
    anchors = {
        (matrix.source_episode_id, matrix.source_h2_path_hash): monday + index * 7 * 86400 * 10**9
        for index, matrix in enumerate(matrices)
    }
    return aggregate_match_matrices(
        matrix_json_values=(matrix.model_dump_json() for matrix in matrices),
        anchor_by_identity=anchors,
        instrument="BTCUSDT",
        period="P3",
        fold="F3",
        parameter_set_id="G1-PRIMARY-V1",
        time_combination_id="T2",
    )


def test_utc_monday_boundary_and_cross_year() -> None:
    sunday = int(datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp() * 10**9)
    monday = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 10**9)
    assert utc_monday_week_start_ns(sunday) == int(
        datetime(2023, 12, 25, tzinfo=UTC).timestamp() * 10**9
    )
    assert utc_monday_week_start_ns(monday) == monday


def test_aggregate_reconciles_real_placebo_and_unmatched() -> None:
    statistics = _statistics()
    assert sum(item.real_count for item in statistics) == 3  # type: ignore[attr-defined]
    assert sum(item.placebo_count for item in statistics) == 2  # type: ignore[attr-defined]
    assert sum(item.paired_count for item in statistics) == 2  # type: ignore[attr-defined]


def test_bootstrap_is_deterministic_and_order_independent() -> None:
    statistics = _statistics()
    first, estimate, count = bootstrap_group(
        statistics=statistics,  # type: ignore[arg-type]
        metric="REAL_EVENT_DELTA",
        group_key="BTC|OVERALL",
        iterations=5000,
    )
    second, second_estimate, second_count = bootstrap_group(
        statistics=tuple(reversed(statistics)),  # type: ignore[arg-type]
        metric="REAL_EVENT_DELTA",
        group_key="BTC|OVERALL",
        iterations=5000,
    )
    assert count == second_count == 3
    assert np.array_equal(estimate, second_estimate)
    assert np.array_equal(first, second)


def test_vectorized_bootstrap_matches_episode_weighted_reference() -> None:
    statistics = tuple(sorted(_statistics(), key=lambda item: item.cluster_id))  # type: ignore[attr-defined]
    iterations = 37
    actual, actual_estimate, _ = bootstrap_group(
        statistics=statistics,  # type: ignore[arg-type]
        metric="REAL_EVENT_DELTA",
        group_key="REFERENCE_EQUIVALENCE",
        batch_size=7,
        iterations=iterations,
    )
    rng = np.random.Generator(
        np.random.PCG64(_derived_seed("REAL_EVENT_DELTA", "REFERENCE_EQUIVALENCE"))
    )
    expected = np.empty_like(actual)
    for replicate in range(iterations):
        selected = rng.integers(0, len(statistics), size=len(statistics), endpoint=False)
        count = sum(statistics[index].real_count for index in selected)  # type: ignore[attr-defined]
        event = sum(statistics[index].real_event_success[0] for index in selected)  # type: ignore[attr-defined]
        control = sum(statistics[index].real_control_success[0] for index in selected)  # type: ignore[attr-defined]
        expected[replicate, 0] = event / count - control / (count * 5)
    total_count = sum(item.real_count for item in statistics)  # type: ignore[attr-defined]
    expected_estimate = (
        sum(item.real_event_success[0] for item in statistics) / total_count  # type: ignore[attr-defined]
        - sum(item.real_control_success[0] for item in statistics) / (total_count * 5)  # type: ignore[attr-defined]
    )
    assert np.array_equal(actual[:, 0], expected[:, 0])
    assert actual_estimate[0] == expected_estimate


def test_paired_metric_excludes_unmatched_placebo() -> None:
    summary = summarize_bootstrap(
        statistics=_statistics(),  # type: ignore[arg-type]
        instrument="BTCUSDT",
        scope="OVERALL",
        period=None,
        fold=None,
        parameter_set_id="G1-PRIMARY-V1",
        time_combination_id="T2",
        metric="PAIRED_REAL_MINUS_PLACEBO",
        iterations=100,
    )[0]
    assert summary.episode_count == 2
    assert summary.cluster_count == 2


def _summary(index: int, p_value: str, *, primary: bool = False) -> BootstrapSummary:
    return BootstrapSummary.seal(
        {
            "instrument": "BTCUSDT",
            "analysis_scope": "OVERALL",
            "pre_registered_period": None,
            "evaluation_fold": None,
            "parameter_set_id": "G1-PRIMARY-V1" if primary else f"G1-X-{index}",
            "time_combination_id": "T2",
            "combination_id": "target=20|stop=25",
            "metric_family": "REAL_EVENT_DELTA",
            "status": "PASS",
            "cluster_count": 300,
            "episode_count": 1000,
            "meets_200_cluster_baseline": True,
            "estimate": "0.100000000000000000",
            "ci_lower": "0.010000000000000000",
            "ci_upper": "0.200000000000000000",
            "bootstrap_median": "0.100000000000000000",
            "bootstrap_standard_error": "0.010000000000000000",
            "raw_p_value": p_value,
            "replicate_hash": _hash(index + 800),
            "fdr_role": "PRIMARY_NOT_ADJUSTED" if primary else "EXPLORATORY_BH",
        }
    )


def test_bh_is_monotone_and_primary_is_not_adjusted() -> None:
    adjusted, families = apply_bh(
        (
            _summary(1, "0.010000000000000000"),
            _summary(2, "0.020000000000000000"),
            _summary(3, "0.200000000000000000"),
            _summary(4, "0.001000000000000000", primary=True),
        )
    )
    exploratory = [item for item in adjusted if item.fdr_role == "EXPLORATORY_BH"]
    assert [item.adjusted_q_value for item in exploratory] == [
        "0.030000000000000000",
        "0.030000000000000000",
        "0.200000000000000000",
    ]
    primary = next(item for item in adjusted if item.fdr_role == "PRIMARY_NOT_ADJUSTED")
    assert primary.adjusted_q_value is None
    assert families[0].hypothesis_count == 3


def test_canonical_json_rejects_binary_float() -> None:
    try:
        canonical_json({"bad": 0.1})
    except ValueError as error:
        assert "binary float" in str(error)
    else:  # pragma: no cover
        raise AssertionError("binary float was accepted")
