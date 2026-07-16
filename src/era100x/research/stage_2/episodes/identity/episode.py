from __future__ import annotations

from dataclasses import dataclass

from era100x.research.stage_2.contracts.identity import market_episode_identity, stable_id
from era100x.research.stage_2.contracts.models import (
    CandidateInclusionRecord,
    CanonicalKeyLevel,
    FlowFeatureSet,
    HoldEvent,
    MarketEpisode,
    PriceTriggerFact,
    ReclaimEvent,
    SweepEpisode,
)


def build_market_episode(
    level: CanonicalKeyLevel,
    sweep: SweepEpisode,
    reclaim: ReclaimEvent,
    hold: HoldEvent,
    trigger: PriceTriggerFact,
    flow: FlowFeatureSet | None,
    *,
    variant: str,
    venue: str = "BINANCE_USDM",
) -> MarketEpisode:
    if not (
        sweep.status == "DETECTED"
        and reclaim.status == "RECLAIMED"
        and hold.hold_result == "PASS"
        and trigger.status == "PASS"
    ):
        raise ValueError("incomplete event chain")
    ids = {
        level.instrument,
        sweep.instrument,
        reclaim.instrument,
        hold.instrument,
        trigger.instrument,
    }
    if len(ids) != 1:
        raise ValueError("mixed instruments")
    if variant == "V1_FLOW" and (flow is None or flow.status != "PASS"):
        raise ValueError("V1_FLOW requires a passing G4 fact")
    if variant == "V1_PRICE" and flow is not None:
        raise ValueError("V1_PRICE cannot consume G4")
    market_id = market_episode_identity(
        venue, level.instrument, level.key_level_id, sweep.sweep_start_ts
    )
    flow_id = flow.flow_feature_set_id if flow is not None else "NO_FLOW"
    candidate_version_id = stable_id(
        "candidate-version",
        "v1",
        market_id,
        variant,
        trigger.trigger_version,
        flow_id,
        level.parameter_set_id,
        level.data_run_id,
        level.dataset_logical_hash,
        level.config_hash,
        level.code_version,
    )
    return MarketEpisode.model_validate(
        {
            "instrument": level.instrument,
            "data_run_id": level.data_run_id,
            "dataset_logical_hash": level.dataset_logical_hash,
            "config_hash": level.config_hash,
            "code_version": level.code_version,
            "parameter_set_id": level.parameter_set_id,
            "available_at_ts": max(
                hold.available_at_ts,
                trigger.available_at_ts,
                flow.available_at_ts if flow is not None else 0,
            ),
            "market_episode_id": market_id,
            "candidate_version_id": candidate_version_id,
            "venue": venue,
            "canonical_key_level_id": level.key_level_id,
            "sweep_id": sweep.sweep_id,
            "reclaim_id": reclaim.reclaim_id,
            "hold_id": hold.hold_id,
            "trigger_id": trigger.trigger_id,
            "flow_feature_set_id": None if flow is None else flow.flow_feature_set_id,
            "variant": variant,
            "sweep_start_ns": sweep.sweep_start_ts,
            "episode_status": "CANDIDATE",
            "consumed": False,
            "consumed_by_intent_id": None,
        }
    )


class CandidateInclusionLedger:
    """Research-only deduplication; it never mutates EntryIntent consumption."""

    def __init__(self) -> None:
        self._keys: set[tuple[str, str]] = set()

    def include(self, episode: MarketEpisode) -> CandidateInclusionRecord:
        key = (episode.market_episode_id, episode.candidate_version_id)
        included = key not in self._keys
        if included:
            self._keys.add(key)
        inclusion_id = stable_id("candidate-inclusion", "v1", *key)
        return CandidateInclusionRecord(
            instrument=episode.instrument,
            data_run_id=episode.data_run_id,
            dataset_logical_hash=episode.dataset_logical_hash,
            config_hash=episode.config_hash,
            code_version=episode.code_version,
            parameter_set_id=episode.parameter_set_id,
            available_at_ts=episode.available_at_ts,
            inclusion_id=inclusion_id,
            market_episode_id=episode.market_episode_id,
            candidate_version_id=episode.candidate_version_id,
            included=included,
            reason_code="CANDIDATE_INCLUDED" if included else "DUPLICATE_CANDIDATE",
            deduplication_key=f"{episode.market_episode_id}:{episode.candidate_version_id}",
        )


class EpisodeConsumptionLedger:
    def __init__(self) -> None:
        self._consumed: dict[str, str] = {}

    def consume(self, market_episode_id: str, intent_id: str) -> None:
        if market_episode_id in self._consumed:
            raise ValueError("MarketEpisode already consumed")
        self._consumed[market_episode_id] = intent_id


@dataclass(frozen=True, slots=True)
class AboveLevelInterval:
    start_ns: int
    end_ns: int


def eligible_for_new_episode(
    *,
    previous_episode_end_ns: int,
    new_crossing_ns: int,
    above_level_interval: AboveLevelInterval,
    minimum_gap_seconds: int,
    rearm_seconds: int,
    level_active: bool,
) -> bool:
    if not level_active:
        return False
    gap_ns = minimum_gap_seconds * 1_000_000_000
    rearm_ns = rearm_seconds * 1_000_000_000
    return (
        new_crossing_ns - previous_episode_end_ns >= gap_ns
        and above_level_interval.end_ns == new_crossing_ns
        and above_level_interval.end_ns - above_level_interval.start_ns >= rearm_ns
        and above_level_interval.start_ns >= previous_episode_end_ns
    )
