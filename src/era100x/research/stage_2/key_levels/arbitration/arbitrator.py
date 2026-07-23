from __future__ import annotations

from decimal import Decimal

from era100x.research.stage_2.contracts.identity import stable_id
from era100x.research.stage_2.contracts.models import CanonicalKeyLevel, RawKeyLevel


def _distance_bps(left: Decimal, right: Decimal) -> Decimal:
    return abs(left - right) / min(left, right) * Decimal(10_000)


def arbitrate_key_levels(
    candidates: list[RawKeyLevel], *, merge_tolerance_bps: Decimal, expires_at_ns: int
) -> list[CanonicalKeyLevel]:
    if merge_tolerance_bps < 0:
        raise ValueError("merge tolerance cannot be negative")
    accepted = [candidate for candidate in candidates if candidate.quality_status == "ACCEPTED"]
    instruments = {candidate.instrument for candidate in accepted}
    if len(instruments) > 1:
        raise ValueError("mixed instruments")
    ordered = sorted(accepted, key=lambda item: (item.level_price, item.raw_key_level_id))
    groups: list[list[RawKeyLevel]] = []
    for candidate in ordered:
        if (
            not groups
            or _distance_bps(groups[-1][0].level_price, candidate.level_price)
            >= merge_tolerance_bps
        ):
            groups.append([candidate])
        else:
            groups[-1].append(candidate)

    results: list[CanonicalKeyLevel] = []
    for members in groups:
        winner = min(
            members,
            key=lambda item: (item.priority, item.source_end_ts, item.raw_key_level_id),
        )
        member_ids = tuple(sorted(item.raw_key_level_id for item in members))
        group_id = stable_id(
            "key-level-normalization-group",
            "v1",
            winner.instrument,
            merge_tolerance_bps,
            *member_ids,
        )
        key_level_id = stable_id(
            "canonical-key-level",
            "v1",
            winner.instrument,
            winner.raw_key_level_id,
            group_id,
            winner.parameter_set_id,
        )
        results.append(
            CanonicalKeyLevel(
                instrument=winner.instrument,
                data_run_id=winner.data_run_id,
                dataset_logical_hash=winner.dataset_logical_hash,
                config_hash=winner.config_hash,
                code_version=winner.code_version,
                parameter_set_id=winner.parameter_set_id,
                available_at_ts=max(item.available_at_ts for item in members),
                key_level_id=key_level_id,
                source_type=winner.source_type,
                source_id=winner.source_id,
                source_timeframe=winner.source_timeframe,
                source_start_ts=winner.source_start_ts,
                source_end_ts=winner.source_end_ts,
                level_price=winner.level_price,
                priority=winner.priority,
                normalization_group=group_id,
                member_key_level_ids=member_ids,
                formed_at_ns=winner.source_end_ts,
                expires_at_ns=expires_at_ns,
                status="ACTIVE",
                reason_code="ARBITRATION_PRIORITY_WINNER",
                metadata={
                    "merge_tolerance_bps": format(merge_tolerance_bps, "f"),
                    "member_count": len(members),
                    "winner_raw_key_level_id": winner.raw_key_level_id,
                },
            )
        )
    return sorted(results, key=lambda item: item.key_level_id)
