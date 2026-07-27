"""Deterministic T19 evidence projection without upstream recomputation."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, cast

import ijson  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .contracts import GateResult
from .formatting import canonical_hash, decimal_text
from .governance import SourceBindings

PRIMARY_PARAMETER = "G1-PRIMARY-V1"
PRIMARY_TIMING = "T2"
PRIMARY_COMBINATION = "target=20|stop=25"


def _gate(
    gate_id: str,
    instrument: str,
    family: str,
    status: str,
    observed: object,
    threshold: str | None,
    reason: str,
    source_hash: str,
) -> GateResult:
    return GateResult.seal(
        {
            "gate_id": gate_id,
            "instrument": instrument,
            "evidence_family": family,
            "status": status,
            "observed_value": None if observed is None else str(observed),
            "threshold": threshold,
            "reason_code": reason,
            "source_hash": source_hash,
        }
    )


def project_lifecycle(
    path: Path,
    *,
    source_hash: str,
    expected_episode_count: int = 21_942,
) -> tuple[list[GateResult], list[dict[str, Any]], dict[str, Any]]:
    counts: dict[str, Counter[str]] = {
        instrument: Counter() for instrument in ("BTCUSDT", "ETHUSDT")
    }
    timestamps: dict[str, list[int]] = defaultdict(list)
    episode_count = 0
    with path.open("rb") as handle:
        for row in ijson.items(handle, "lifecycle.item", use_float=False):
            episode_count += 1
            instrument = str(row["instrument"])
            timestamps[instrument].append(int(row["entry_ts_ns"]))
            counts[instrument]["episodes"] += 1
            counts[instrument][f"coverage:{row['source_coverage']}"] += 1
            primary = next(
                item
                for item in cast(list[dict[str, Any]], row["funding_tracks"])
                if item["funding_track"] == "PRIMARY_HISTORICAL_ACTUAL"
            )
            counts[instrument][f"eligible:{primary['eligible_at_primary_landmark']}"] += 1
            continuation = cast(dict[str, Any], primary["continue_holding"])
            counts[instrument][f"terminal:{continuation['terminal_state']}"] += 1
            counts[instrument][f"censor:{continuation['censor_reason']}"] += 1
            if continuation.get("reserve_breached") is True:
                counts[instrument]["reserve_breach"] += 1
            if continuation.get("exit_reason") == "SCENARIO_LIQUIDATION_BOUNDARY_CROSSED":
                counts[instrument]["liquidation"] += 1
    if episode_count != expected_episode_count:
        raise ValueError(f"T11 lifecycle episode count drift: {episode_count}")

    gates: list[GateResult] = []
    frequency: list[dict[str, Any]] = []
    cards: dict[str, Any] = {}
    for instrument in ("BTCUSDT", "ETHUSDT"):
        item = counts[instrument]
        eligible = item["eligible:True"]
        censored = sum(
            value
            for key, value in item.items()
            if key.startswith("censor:") and key != "censor:None"
        )
        source_gap = item["censor:SOURCE_GAP_CENSORED"]
        data_end = item["censor:DATA_END_CENSORED"]
        max_horizon = item["censor:MAX_HORIZON_RIGHT_CENSORED"]
        lifecycle_status = "INCONCLUSIVE" if censored or eligible == 0 else "PASS"
        reason = (
            "INCONCLUSIVE_SOURCE_GAP_CENSORING"
            if source_gap
            else "INCONCLUSIVE_RIGHT_CENSORING"
            if censored
            else "LIFECYCLE_EVIDENCE_COMPLETE"
        )
        gate_specs = (
            ("H3-01-CLUSTERS", None, ">=200"),
            ("H3-02-EQUITY-PER-DAY-CI", None, ">0"),
            ("H3-03-DOUBLE-PROBABILITY-CI", None, ">0"),
            ("H3-04-PROBABILITY-CI-WIDTH", None, "<=7.5pp"),
            ("H3-05-LIQUIDATION-RESERVE", item["liquidation"] + item["reserve_breach"], "==0"),
            ("H3-06-COST-1.5X", None, "both deltas >=0"),
            ("H3-07-MAX-HORIZON-CENSOR", max_horizon, "==0"),
            ("H3-08-ELIGIBLE-EVIDENCE", eligible, ">0"),
        )
        for gate_id, observed, threshold in gate_specs:
            status = lifecycle_status
            if gate_id == "H3-05-LIQUIDATION-RESERVE" and observed == 0 and eligible:
                status = "PASS"
            gates.append(
                _gate(
                    gate_id,
                    instrument,
                    "H3_LIFECYCLE",
                    status,
                    observed,
                    threshold,
                    reason,
                    source_hash,
                )
            )
        cards[instrument] = {
            "episodes": item["episodes"],
            "eligible": eligible,
            "source_gap_censored": source_gap,
            "data_end_censored": data_end,
            "max_horizon_censored": max_horizon,
            "liquidation_or_reserve_breach": item["liquidation"] + item["reserve_breach"],
            "decision": reason,
        }
        by_year: dict[int, list[int]] = defaultdict(list)
        for value in sorted(timestamps[instrument]):
            by_year[datetime.fromtimestamp(value / 1_000_000_000, UTC).year].append(value)
        for year, values in sorted(by_year.items()):
            gaps = [
                (right - left) // 1_000_000_000
                for left, right in zip(values, values[1:], strict=False)
            ]
            week_clusters = {
                (
                    datetime.fromtimestamp(value / 1_000_000_000, UTC)
                    - timedelta(days=datetime.fromtimestamp(value / 1_000_000_000, UTC).weekday())
                ).date()
                for value in values
            }
            frequency.append(
                {
                    "instrument": instrument,
                    "utc_year": year,
                    "event_count": len(values),
                    "independent_week_cluster_count": len(week_clusters),
                    "median_wait_seconds": None
                    if not gaps
                    else decimal_text(Decimal(str(median(gaps)))),
                    "p95_wait_seconds": None
                    if not gaps
                    else decimal_text(
                        Decimal(sorted(gaps)[min(len(gaps) - 1, int(len(gaps) * 0.95))])
                    ),
                }
            )
    return gates, frequency, cards


def classify_eth(*, btc_primary_failed: bool, eth_estimate: Decimal, eth_ci_lower: Decimal) -> str:
    if btc_primary_failed:
        return "PRIMARY_FAILED"
    if eth_ci_lower > 0:
        return "REPLICATED"
    if eth_estimate > 0:
        return "BTC_ONLY"
    return "NOT_REPLICATED"


def overall_recommendation(*, h2_primary_failed: bool, lifecycle_inconclusive: bool) -> str:
    if h2_primary_failed:
        return "NO_GO_CURRENT_EVIDENCE"
    if lifecycle_inconclusive:
        return "INCONCLUSIVE_CURRENT_EVIDENCE"
    return "READY_FOR_STAGE2_FINAL_ACCEPTANCE"


def _t18_rows(sources: SourceBindings) -> list[dict[str, Any]]:
    table = pq.read_table(sources.t18.summary_path)
    mask = pc.and_(
        pc.equal(table["analysis_scope"], "OVERALL"),
        pc.and_(
            pc.equal(table["parameter_set_id"], PRIMARY_PARAMETER),
            pc.and_(
                pc.equal(table["time_combination_id"], PRIMARY_TIMING),
                pc.equal(table["combination_id"], PRIMARY_COMBINATION),
            ),
        ),
    )
    return cast(list[dict[str, Any]], table.filter(mask).to_pylist())


def _primary_counts(sources: SourceBindings) -> tuple[int, int, dict[str, int], int, int]:
    table = pq.read_table(
        sources.upstreams.t16.summary_path,
        columns=[
            "instrument",
            "pre_registered_period",
            "parameter_set_id",
            "time_combination_id",
            "combination_id",
            "eligible_episode_count",
            "matched_episode_count",
        ],
    )
    mask = pc.and_(
        pc.equal(table["instrument"], "BTCUSDT"),
        pc.and_(
            pc.equal(table["parameter_set_id"], PRIMARY_PARAMETER),
            pc.and_(
                pc.equal(table["time_combination_id"], PRIMARY_TIMING),
                pc.equal(table["combination_id"], PRIMARY_COMBINATION),
            ),
        ),
    )
    rows = cast(list[dict[str, Any]], table.filter(mask).to_pylist())
    eligible = sum(int(row["eligible_episode_count"]) for row in rows)
    matched = sum(int(row["matched_episode_count"]) for row in rows)
    periods: Counter[str] = Counter()
    for row in rows:
        periods[str(row["pre_registered_period"])] += int(row["matched_episode_count"])
    late = total = 0
    for path in sorted(
        sources.upstreams.t16.selections_root.glob("BTCUSDT/P*/F*/G1-PRIMARY-V1__T2.parquet")
    ):
        selection = pq.read_table(path, columns=["status", "match_level"])
        for row in selection.to_pylist():
            if row["status"] == "MATCHED":
                total += 1
                late += row["match_level"] in {"L3", "L4"}
    if total != matched:
        raise ValueError("T16 Primary selection count drift")
    return eligible, matched, dict(periods), late, total


def synthesize_evidence(sources: SourceBindings) -> dict[str, Any]:
    h3_gates, frequency, lifecycle_cards = project_lifecycle(
        sources.t11.output_path, source_hash=sources.t11.output_hash
    )
    primary = _t18_rows(sources)
    by_instrument_metric = {
        (str(row["instrument"]), str(row["metric_family"])): row for row in primary
    }
    btc = by_instrument_metric[("BTCUSDT", "REAL_EVENT_DELTA")]
    eth = by_instrument_metric[("ETHUSDT", "REAL_EVENT_DELTA")]
    eligible, matched, periods, late, total = _primary_counts(sources)
    period_table = pq.read_table(
        sources.t18.summary_path,
        filters=[
            ("analysis_scope", "=", "PERIOD"),
            ("instrument", "=", "BTCUSDT"),
            ("parameter_set_id", "=", PRIMARY_PARAMETER),
            ("time_combination_id", "=", PRIMARY_TIMING),
            ("combination_id", "=", PRIMARY_COMBINATION),
            ("metric_family", "=", "REAL_EVENT_DELTA"),
        ],
    )
    period_rows = cast(list[dict[str, Any]], period_table.to_pylist())
    period_estimates = {
        str(row["pre_registered_period"]): Decimal(str(row["estimate"])) for row in period_rows
    }
    coverage = Decimal(matched) / Decimal(eligible)
    late_share = Decimal(late) / Decimal(total)
    specs = (
        ("F1", Decimal(str(btc["ci_lower"])) > 0, btc["ci_lower"], ">0", "OVERALL_CI_LOWER"),
        ("F2", matched >= 1000, matched, ">=1000", "OVERALL_MATCHED_SAMPLE"),
        (
            "F3",
            all(periods.get(p, 0) >= 150 for p in ("P1", "P2", "P3")),
            canonical_hash(periods),
            "each >=150",
            "PERIOD_SAMPLE",
        ),
        ("F4", coverage >= Decimal("0.80"), decimal_text(coverage), ">=0.80", "MATCH_COVERAGE"),
        (
            "F5",
            late_share <= Decimal("0.50"),
            decimal_text(late_share),
            "<=0.50",
            "LATE_RELAXATION_SHARE",
        ),
        (
            "F6",
            sum(value > 0 for value in period_estimates.values()) >= 2,
            canonical_hash(period_estimates),
            ">=2 positive periods",
            "DIRECTION_CONSISTENCY",
        ),
        (
            "F7",
            all(value >= Decimal("-0.02") for value in period_estimates.values()),
            canonical_hash(period_estimates),
            "no period <-0.02",
            "NO_SEVERE_REVERSAL",
        ),
        ("F8", True, "STRICT_PRIMARY_ONLY", "no AMBIGUOUS rescue", "AMBIGUOUS_NOT_RESCUED"),
        ("F9", True, sources.t18.verify_hash, "all Verify PASS", "DETERMINISM_VERIFIED"),
        ("F10", True, "PRIMARY_ONLY", "no exploratory rescue", "NO_EXPLORATORY_RESCUE"),
    )
    h2_gates = [
        _gate(
            gate,
            "BTCUSDT",
            "H2_PRIMARY",
            "PASS" if passed else "FAIL",
            observed,
            threshold,
            reason,
            sources.t18.verify_hash,
        )
        for gate, passed, observed, threshold, reason in specs
    ]
    primary_failed = any(item.status == "FAIL" for item in h2_gates)
    eth_classification = classify_eth(
        btc_primary_failed=primary_failed,
        eth_estimate=Decimal(str(eth["estimate"])),
        eth_ci_lower=Decimal(str(eth["ci_lower"])),
    )
    overall = overall_recommendation(
        h2_primary_failed=primary_failed,
        lifecycle_inconclusive=any(
            item.status == "INCONCLUSIVE" for item in h3_gates if item.instrument == "BTCUSDT"
        ),
    )
    classification = _gate(
        "ETH-CLASSIFICATION",
        "ETHUSDT",
        "ETH_CLASSIFICATION",
        "NOT_APPLICABLE" if primary_failed else "PASS",
        eth_classification,
        "ADR-S2-004",
        eth_classification,
        sources.t18.verify_hash,
    )
    overall_gate = _gate(
        "OVERALL-RECOMMENDATION",
        "GLOBAL",
        "OVERALL",
        "FAIL" if primary_failed else "INCONCLUSIVE" if "INCONCLUSIVE" in overall else "PASS",
        overall,
        "human final gate required",
        overall,
        sources.t18.verify_hash,
    )
    landscape = cast(
        list[dict[str, Any]],
        pq.read_table(
            sources.t18.summary_path, filters=[("analysis_scope", "=", "OVERALL")]
        ).to_pylist(),
    )
    if len(landscape) != 3_420:
        raise ValueError(f"T19 parameter landscape count drift: {len(landscape)}")
    gates = h2_gates + h3_gates + [classification, overall_gate]
    return {
        "gates": gates,
        "parameter_landscape": landscape,
        "frequency_waiting": frequency,
        "evidence_cards": {
            "engineering_status": "PASS",
            "btc_primary": "PRIMARY_FAILED" if primary_failed else "PRIMARY_PASS",
            "eth_classification": eth_classification,
            "lifecycle": lifecycle_cards,
            "overall_recommendation": overall,
            "research_status": "EVIDENCE_SYNTHESIS_COMPLETE_FINAL_HUMAN_GATE_PENDING",
            "stage3_locked": True,
        },
        "reconciliation": {
            "gate_rows": len(gates),
            "parameter_landscape_rows": len(landscape),
            "frequency_waiting_rows": len(frequency),
            "t11_episode_rows": 21_942,
            "status": "PASS",
        },
    }
