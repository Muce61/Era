from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq

from era100x.research.stage_2.acceptance.final_acceptance.engine import (
    STRATA,
    attach_event_evidence,
    public_blind_selection,
    render_event_card_svg,
    render_explainer_svg,
    select_event_identities,
)


def _sources(tmp_path: Path, *, reverse: bool = False) -> SimpleNamespace:
    matches: list[dict[str, object]] = []
    prepared: list[dict[str, object]] = []
    outcomes = [
        {
            "combination_id": f"target={target}|stop={stop}",
            "label": "TARGET_FIRST" if stop == 25 else "EXPIRED",
            "label_reason": "TARGET_OBSERVED_FIRST"
            if stop == 25
            else "HORIZON_EXPIRED_WITHOUT_TOUCH",
            "strict_target_first": 1 if stop == 25 else 0,
        }
        for target in (20, 30, 40, 50, 70, 100)
        for stop in (15, 20, 25, 30, 35)
    ]
    for stratum_index, (instrument, period) in enumerate(STRATA):
        for candidate_index in range(2):
            episode_id = f"{instrument}-{period}-{candidate_index}"
            path_hash = f"{stratum_index * 2 + candidate_index + 1:064x}"
            matrix = {
                "market_episode_id": episode_id,
                "source_h2_path_hash": path_hash,
                "event_outcomes": outcomes,
                "output_hash": f"{100 + stratum_index * 2 + candidate_index:064x}",
            }
            matches.append(
                {
                    "instrument": instrument,
                    "pre_registered_period": period,
                    "parameter_set_id": "G1-PRIMARY-V1",
                    "time_combination_id": "T2",
                    "market_episode_id": episode_id,
                    "source_h2_path_hash": path_hash,
                    "status": "MATCHED",
                    "match_level": "L0",
                    "matrix_json": json.dumps(matrix, sort_keys=True, separators=(",", ":")),
                }
            )
            prepared.append(
                {
                    "instrument": instrument,
                    "market_episode_id": episode_id,
                    "classification_row_hash": path_hash,
                    "parameter_set_id": "G1-PRIMARY-V1",
                    "time_combination_id": "T2",
                    "canonical_key_level_id": f"{200 + stratum_index:064x}",
                    "anchor_ns": 1_600_000_000_000_000_000 + stratum_index,
                    "requested_window_end_ns": 1_600_000_180_000_000_000 + stratum_index,
                    "reference_price": Decimal("100.000000000000000000"),
                    "pre_registered_period": period,
                    "evaluation_fold": "F0",
                    "high_timeframe_trend_state": "ABOVE_EMA20",
                    "source_quality_status": "COMPLETE",
                    "source_gap_codes": [],
                    "source_ambiguity_codes": [],
                }
            )
    if reverse:
        matches.reverse()
        prepared.reverse()
    match_path = tmp_path / ("matches-r.parquet" if reverse else "matches.parquet")
    prepared_path = tmp_path / ("prepared-r.parquet" if reverse else "prepared.parquet")
    pq.write_table(pa.Table.from_pylist(matches), match_path, row_group_size=3)
    pq.write_table(pa.Table.from_pylist(prepared), prepared_path, row_group_size=4)
    t16 = SimpleNamespace(match_path=match_path, prepared_episodes_path=prepared_path)
    return SimpleNamespace(upstreams=SimpleNamespace(upstreams=SimpleNamespace(t16=t16)))


def _public(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {key: value for key, value in item.items() if not key.startswith("_")} for item in items
    ]


def test_selection_is_shuffle_deterministic_and_does_not_publish_physical_offsets(
    tmp_path: Path,
) -> None:
    first = select_event_identities(_sources(tmp_path))
    second = select_event_identities(_sources(tmp_path, reverse=True))
    assert _public(first) == _public(second)
    payload = public_blind_selection(first)
    assert payload["selection_read_outcomes"] is False
    assert len(payload["items"]) == 6
    assert all(not any(key.startswith("_") for key in item) for item in payload["items"])


def test_outcomes_attach_only_after_selection_and_keep_six_strata(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    selected = select_event_identities(sources)
    blind = public_blind_selection(selected)
    cards = attach_event_evidence(sources, selected)
    assert blind["selection_hash"]
    assert len(cards) == 6
    assert {(card["instrument"], card["pre_registered_period"]) for card in cards} == set(STRATA)
    assert all(card["combination_id"] == "target=20|stop=25" for card in cards)
    assert all(card["label"] == "TARGET_FIRST" for card in cards)
    assert all(card["historical_evidence_only"] is True for card in cards)


def test_visuals_distinguish_fixture_from_real_historical_card(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    card = attach_event_evidence(sources, select_event_identities(sources))[0]
    explainer = render_explainer_svg()
    real = render_event_card_svg(card)
    assert "ILLUSTRATIVE_FIXTURE" in explainer
    assert "not a real event" in explainer
    assert "ILLUSTRATIVE_FIXTURE" not in real
    assert "H2 historical evidence only" in real
    assert "raw Trade trajectory is not redrawn" in real
