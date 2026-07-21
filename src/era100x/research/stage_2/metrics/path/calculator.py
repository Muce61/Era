"""Pure S2-T12 MFE, MAE and activation-timing calculations."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from era100x.research.stage_2.paths.extraction.models import ExtractedHistoricalPath

from .models import ActivationTiming, HistoricalPathMetrics

BPS = Decimal("10000")
PROHIBITED_INTERPRETATIONS = (
    "PNL",
    "RETURN",
    "REAL_RETURN",
    "LIVE_PROTECTION_ACTIVATION",
    "TARGET_FIRST",
    "STOP_FIRST",
    "ROUND_SUCCESS",
)


def _signed_move_bps(price: Decimal, reference_price: Decimal) -> Decimal:
    return (price / reference_price - Decimal(1)) * BPS


def _thresholds(values: Iterable[Decimal]) -> tuple[Decimal, ...]:
    thresholds = tuple(sorted(set(values)))
    if not thresholds or any(value <= 0 for value in thresholds):
        raise ValueError("activation thresholds must contain positive Decimal values")
    return thresholds


def _base_payload(
    path: ExtractedHistoricalPath,
    *,
    evidence_level: str,
    reference_price: Decimal,
    window_truncated: bool,
    activations: tuple[ActivationTiming, ...],
) -> dict[str, object]:
    source = path.h1_source if evidence_level == "H1" else path.h2_source
    return {
        "instrument": path.instrument,
        "market_episode_id": path.market_episode_id,
        "canonical_candidate_id": path.canonical_candidate_id,
        "candidate_version_id": path.candidate_version_id,
        "canonical_payload_hash": path.canonical_payload_hash,
        "parameter_set_id": path.parameter_set_id,
        "evidence_level": evidence_level,
        "reference_price_type": source.reference_price_type,
        "reference_price": reference_price,
        "window_start_ns": path.window_start_ns,
        "window_end_ns": path.window_end_ns,
        "window_truncated": window_truncated,
        "activations": activations,
        "source_quality_status": path.quality_status,
        "source_gap_codes": tuple(sorted({gap.reason_code for gap in path.gaps})),
        "source_ambiguity_codes": path.ambiguity_codes,
        "prohibited_interpretations": PROHIBITED_INTERPRETATIONS,
        "source_path_hash": path.output_hash,
    }


def _empty_metrics(
    path: ExtractedHistoricalPath,
    *,
    evidence_level: str,
    reference_price: Decimal,
    thresholds: tuple[Decimal, ...],
    window_truncated: bool,
) -> HistoricalPathMetrics:
    activations = tuple(
        ActivationTiming(threshold_bps=value, activated=False) for value in thresholds
    )
    return HistoricalPathMetrics.seal(
        {
            **_base_payload(
                path,
                evidence_level=evidence_level,
                reference_price=reference_price,
                window_truncated=window_truncated,
                activations=activations,
            ),
            "observation_count": 0,
            "metric_status": "NO_OBSERVATIONS",
            "mfe_bps": None,
            "mae_bps": None,
            "mfe_first_ts_event_ns": None,
            "mae_first_ts_event_ns": None,
            "last_observation_ts_event_ns": None,
            "time_since_mfe_ns": None,
        }
    )


def compute_h1_path_metrics(
    path: ExtractedHistoricalPath,
    *,
    reference_price: Decimal,
    activation_thresholds_bps: Iterable[Decimal],
    window_truncated: bool = False,
) -> HistoricalPathMetrics:
    """Compute coarse-second Contract Price metrics without inferring intrasecond order."""

    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    thresholds = _thresholds(activation_thresholds_bps)
    if not path.h1_points:
        return _empty_metrics(
            path,
            evidence_level="H1",
            reference_price=reference_price,
            thresholds=thresholds,
            window_truncated=window_truncated,
        )

    favorable = tuple(
        (point.ts_event_ns, _signed_move_bps(point.high, reference_price))
        for point in path.h1_points
    )
    adverse = tuple(
        (point.ts_event_ns, _signed_move_bps(point.low, reference_price))
        for point in path.h1_points
    )
    return _computed_metrics(
        path,
        evidence_level="H1",
        reference_price=reference_price,
        thresholds=thresholds,
        favorable=favorable,
        adverse=adverse,
        window_truncated=window_truncated,
    )


def compute_h2_path_metrics(
    path: ExtractedHistoricalPath,
    *,
    reference_price: Decimal,
    activation_thresholds_bps: Iterable[Decimal],
    window_truncated: bool = False,
) -> HistoricalPathMetrics:
    """Compute Trade metrics in the frozen V2 stable event order."""

    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    thresholds = _thresholds(activation_thresholds_bps)
    if not path.h2_points:
        return _empty_metrics(
            path,
            evidence_level="H2",
            reference_price=reference_price,
            thresholds=thresholds,
            window_truncated=window_truncated,
        )
    moves = tuple(
        (point.ts_event_ns, _signed_move_bps(point.price, reference_price))
        for point in path.h2_points
    )
    return _computed_metrics(
        path,
        evidence_level="H2",
        reference_price=reference_price,
        thresholds=thresholds,
        favorable=moves,
        adverse=moves,
        window_truncated=window_truncated,
    )


def _computed_metrics(
    path: ExtractedHistoricalPath,
    *,
    evidence_level: str,
    reference_price: Decimal,
    thresholds: tuple[Decimal, ...],
    favorable: tuple[tuple[int, Decimal], ...],
    adverse: tuple[tuple[int, Decimal], ...],
    window_truncated: bool,
) -> HistoricalPathMetrics:
    raw_mfe = max(value for _, value in favorable)
    raw_mae = min(value for _, value in adverse)
    mfe = max(Decimal(0), raw_mfe)
    mae = min(Decimal(0), raw_mae)
    mfe_ts = (
        next(ts for ts, value in favorable if value == raw_mfe)
        if raw_mfe > 0
        else path.window_start_ns
    )
    mae_ts = (
        next(ts for ts, value in adverse if value == raw_mae)
        if raw_mae < 0
        else path.window_start_ns
    )
    last_ts = max(ts for ts, _ in favorable)
    activations: list[ActivationTiming] = []
    for threshold in thresholds:
        first_ts = next((ts for ts, value in favorable if value >= threshold), None)
        activations.append(
            ActivationTiming(
                threshold_bps=threshold,
                activated=first_ts is not None,
                first_activation_ts_event_ns=first_ts,
                time_to_activation_ns=(
                    None if first_ts is None else first_ts - path.window_start_ns
                ),
            )
        )
    return HistoricalPathMetrics.seal(
        {
            **_base_payload(
                path,
                evidence_level=evidence_level,
                reference_price=reference_price,
                window_truncated=window_truncated,
                activations=tuple(activations),
            ),
            "observation_count": len(favorable),
            "metric_status": "COMPUTED",
            "mfe_bps": mfe,
            "mae_bps": mae,
            "mfe_first_ts_event_ns": mfe_ts,
            "mae_first_ts_event_ns": mae_ts,
            "last_observation_ts_event_ns": last_ts,
            "time_since_mfe_ns": last_ts - mfe_ts,
        }
    )
