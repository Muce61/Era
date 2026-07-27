"""Deterministic T20 projection and result-blind evidence-card selection."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from html import escape
from typing import Any, cast

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.acceptance.canonical_json import canonical_content_hash

from .contracts import LIFECYCLE_DECISION, RESEARCH_DECISION
from .governance import SourceBindings

PRIMARY_PARAMETER = "G1-PRIMARY-V1"
PRIMARY_TIMING = "T2"
PRIMARY_COMBINATION = "target=20|stop=25"
EVENT_CARD_NAMESPACE = "S2P17T20|EVENT_CARD"
EVENT_CARD_SEED = "20260716"
STRATA = tuple(
    (instrument, period) for instrument in ("BTCUSDT", "ETHUSDT") for period in ("P1", "P2", "P3")
)


def _selection_token(instrument: str, period: str, episode_id: str) -> str:
    payload = f"{EVENT_CARD_NAMESPACE}|{instrument}|{period}|{episode_id}|{EVENT_CARD_SEED}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def select_event_identities(sources: SourceBindings) -> list[dict[str, Any]]:
    """Select one matched Primary identity per stratum without reading outcomes."""

    parquet = pq.ParquetFile(sources.upstreams.upstreams.t16.match_path)
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    columns = [
        "instrument",
        "pre_registered_period",
        "parameter_set_id",
        "time_combination_id",
        "market_episode_id",
        "source_h2_path_hash",
        "status",
        "match_level",
    ]
    for row_group in range(parquet.metadata.num_row_groups):
        rows = parquet.read_row_group(row_group, columns=columns).to_pylist()
        for row_offset, row in enumerate(rows):
            if (
                row["parameter_set_id"] != PRIMARY_PARAMETER
                or row["time_combination_id"] != PRIMARY_TIMING
                or row["status"] != "MATCHED"
            ):
                continue
            key = (str(row["instrument"]), str(row["pre_registered_period"]))
            if key not in STRATA:
                continue
            token = _selection_token(key[0], key[1], str(row["market_episode_id"]))
            candidate = {
                "instrument": key[0],
                "pre_registered_period": key[1],
                "market_episode_id": str(row["market_episode_id"]),
                "source_h2_path_hash": str(row["source_h2_path_hash"]),
                "match_level": str(row["match_level"]),
                "selection_token": token,
                "_row_group": row_group,
                "_row_offset": row_offset,
            }
            current = selected.get(key)
            if current is None or token < current["selection_token"]:
                selected[key] = candidate
    result: list[dict[str, Any]] = []
    for instrument, period in STRATA:
        item = selected.get((instrument, period))
        if item is None:
            result.append(
                {
                    "instrument": instrument,
                    "pre_registered_period": period,
                    "selection_status": "NO_ELIGIBLE_VERIFIED_EVENT",
                }
            )
        else:
            result.append({**item, "selection_status": "SELECTED"})
    return result


def public_blind_selection(selected: list[dict[str, Any]]) -> dict[str, Any]:
    items = [
        {key: value for key, value in item.items() if not key.startswith("_")} for item in selected
    ]
    payload: dict[str, Any] = {
        "schema_name": "s2p17-t20-blind-event-selection",
        "schema_version": "1.0",
        "namespace": EVENT_CARD_NAMESPACE,
        "seed": EVENT_CARD_SEED,
        "selection_read_outcomes": False,
        "items": items,
    }
    payload["selection_hash"] = canonical_content_hash(payload)
    return payload


def _prepared_rows(
    sources: SourceBindings, selected_paths: dict[str, str]
) -> dict[str, dict[str, Any]]:
    parquet = pq.ParquetFile(sources.upstreams.upstreams.t16.prepared_episodes_path)
    columns = [
        "instrument",
        "market_episode_id",
        "classification_row_hash",
        "parameter_set_id",
        "time_combination_id",
        "canonical_key_level_id",
        "anchor_ns",
        "requested_window_end_ns",
        "reference_price",
        "pre_registered_period",
        "evaluation_fold",
        "high_timeframe_trend_state",
        "source_quality_status",
        "source_gap_codes",
        "source_ambiguity_codes",
    ]
    result: dict[str, dict[str, Any]] = {}
    for batch in parquet.iter_batches(columns=columns, batch_size=32_768):
        for row in batch.to_pylist():
            episode_id = str(row["market_episode_id"])
            if (
                episode_id in selected_paths
                and str(row["classification_row_hash"]) == selected_paths[episode_id]
                and row["parameter_set_id"] == PRIMARY_PARAMETER
                and row["time_combination_id"] == PRIMARY_TIMING
            ):
                if episode_id in result:
                    raise ValueError("selected event identity is not unique in prepared episodes")
                result[episode_id] = cast(dict[str, Any], row)
    if set(result) != set(selected_paths):
        raise ValueError("selected event lacks one prepared-episode binding")
    return result


def _outcome_rows(
    sources: SourceBindings, selected: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    parquet = pq.ParquetFile(sources.upstreams.upstreams.t16.match_path)
    by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        if item.get("selection_status") == "SELECTED":
            by_group[int(item["_row_group"])].append(item)
    outcomes: dict[str, dict[str, Any]] = {}
    for row_group, items in sorted(by_group.items()):
        table = parquet.read_row_group(
            row_group, columns=["market_episode_id", "source_h2_path_hash", "matrix_json"]
        )
        episode_ids = table["market_episode_id"].to_pylist()
        path_hashes = table["source_h2_path_hash"].to_pylist()
        matrices = table["matrix_json"].to_pylist()
        for item in items:
            offset = int(item["_row_offset"])
            if (
                episode_ids[offset] != item["market_episode_id"]
                or path_hashes[offset] != item["source_h2_path_hash"]
            ):
                raise ValueError("selected event physical lookup drift")
            matrix = json.loads(str(matrices[offset]))
            event_outcomes = cast(list[dict[str, Any]], matrix["event_outcomes"])
            outcome = next(
                (
                    value
                    for value in event_outcomes
                    if value.get("combination_id") == PRIMARY_COMBINATION
                ),
                None,
            )
            if outcome is None or len(event_outcomes) != 30:
                raise ValueError("selected event Primary outcome binding drift")
            outcomes[str(item["market_episode_id"])] = {
                "label": str(outcome["label"]),
                "label_reason": str(outcome["label_reason"]),
                "strict_target_first": int(outcome["strict_target_first"]),
                "matrix_output_hash": str(matrix["output_hash"]),
            }
    return outcomes


def attach_event_evidence(
    sources: SourceBindings, selected: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    selected_paths = {
        str(item["market_episode_id"]): str(item["source_h2_path_hash"])
        for item in selected
        if item.get("selection_status") == "SELECTED"
    }
    prepared = _prepared_rows(sources, selected_paths)
    outcomes = _outcome_rows(sources, selected)
    cards: list[dict[str, Any]] = []
    for item in selected:
        if item.get("selection_status") != "SELECTED":
            cards.append(
                {
                    **{key: value for key, value in item.items() if not key.startswith("_")},
                    "card_type": "EVENT_EVIDENCE_CARD",
                    "historical_evidence_only": True,
                }
            )
            continue
        episode_id = str(item["market_episode_id"])
        row = prepared[episode_id]
        outcome = outcomes[episode_id]
        card: dict[str, Any] = {
            "card_type": "EVENT_EVIDENCE_CARD",
            "instrument": item["instrument"],
            "pre_registered_period": item["pre_registered_period"],
            "evaluation_fold": row["evaluation_fold"],
            "market_episode_id": episode_id,
            "source_h2_path_hash": item["source_h2_path_hash"],
            "classification_row_hash": row["classification_row_hash"],
            "canonical_key_level_id": row["canonical_key_level_id"],
            "anchor_ns": row["anchor_ns"],
            "window_end_ns": row["requested_window_end_ns"],
            "reference_price": str(row["reference_price"]),
            "reference_price_source": "CONTRACT_PRICE_1S_CLOSE",
            "setup_id": "KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0",
            "context_model_id": "CAUSAL_EMA20_1H@1.0",
            "high_timeframe_trend_state": row["high_timeframe_trend_state"],
            "parameter_set_id": PRIMARY_PARAMETER,
            "time_combination_id": PRIMARY_TIMING,
            "combination_id": PRIMARY_COMBINATION,
            "match_level": item["match_level"],
            "selection_token": item["selection_token"],
            "source_quality_status": row["source_quality_status"],
            "source_gap_codes": list(row["source_gap_codes"]),
            "source_ambiguity_codes": list(row["source_ambiguity_codes"]),
            **outcome,
            "historical_evidence_only": True,
            "prohibited_interpretations": [
                "PNL",
                "REAL_RETURN",
                "LIVE_EXECUTION",
                "STAGE2_PRIMARY_PASS",
            ],
        }
        card["card_hash"] = canonical_content_hash(card)
        cards.append(card)
    return cards


def _utc(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, UTC).strftime("%Y-%m-%d %H:%M:%SZ")


def render_event_card_svg(card: dict[str, Any]) -> str:
    if card.get("selection_status") == "NO_ELIGIBLE_VERIFIED_EVENT":
        title = f"{card['instrument']} · {card['pre_registered_period']}"
        return _svg_frame(
            title,
            "NO_ELIGIBLE_VERIFIED_EVENT",
            (
                "No verified event was available in this frozen stratum.",
                "No cross-period replacement was allowed.",
                "H2 historical evidence only · Stage 3 LOCKED",
            ),
            tone="#f59e0b",
        )
    title = f"{card['instrument']} · {card['pre_registered_period']} · {card['evaluation_fold']}"
    outcome = f"{card['label']} · strict={card['strict_target_first']}"
    return _svg_frame(
        title,
        outcome,
        (
            f"UTC  {_utc(int(card['anchor_ns']))} → {_utc(int(card['window_end_ns']))}",
            f"Reference  {card['reference_price']} · CONTRACT_PRICE_1S_CLOSE",
            f"Setup  {card['setup_id']} · Context  {card['context_model_id']}",
            f"Episode  {str(card['market_episode_id'])[:24]}…",
            f"H2 path  {str(card['source_h2_path_hash'])[:24]}…",
            "Verified path identity and First Passage result; raw Trade trajectory is not redrawn.",
            "H2 historical evidence only · not PnL, return or live execution · Stage 3 LOCKED",
        ),
        tone="#ef4444" if card["strict_target_first"] == 0 else "#22c55e",
    )


def render_explainer_svg() -> str:
    return _svg_frame(
        "EVENT_EXPLAINER",
        "ILLUSTRATIVE_FIXTURE",
        (
            "This diagram explains the evidence-card fields only.",
            "Identity → verified H2 window → frozen Primary label → source Hash chain.",
            "It is not a real event, price path, PnL, return or execution record.",
            "Stage 2 current evidence: NO-GO · Stage 3 LOCKED",
        ),
        tone="#3b82f6",
    )


def _svg_frame(title: str, badge: str, lines: tuple[str, ...], *, tone: str) -> str:
    escaped_lines = [
        f'<text x="72" y="{240 + index * 48}" class="body">{escape(line)}</text>'
        for index, line in enumerate(lines)
    ]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" '
        'viewBox="0 0 1200 675">'
        "<style>"
        ".title{font:700 34px ui-monospace,SFMono-Regular,Menlo,monospace;fill:#f8fafc}"
        ".badge{font:700 20px ui-monospace,SFMono-Regular,Menlo,monospace;fill:#f8fafc}"
        ".body{font:500 18px ui-monospace,SFMono-Regular,Menlo,monospace;fill:#cbd5e1}"
        ".meta{font:500 15px ui-monospace,SFMono-Regular,Menlo,monospace;fill:#64748b}"
        "</style>"
        '<rect width="1200" height="675" fill="#07111f"/>'
        '<rect x="36" y="36" width="1128" height="603" rx="24" fill="#0b1728" '
        'stroke="#23344d" stroke-width="2"/>'
        f'<rect x="72" y="72" width="12" height="76" rx="6" fill="{tone}"/>'
        f'<text x="108" y="114" class="title">{escape(title)}</text>'
        f'<rect x="108" y="137" width="430" height="52" rx="12" fill="{tone}" opacity="0.18"/>'
        f'<text x="132" y="171" class="badge">{escape(badge)}</text>'
        + "".join(escaped_lines)
        + '<text x="72" y="608" class="meta">S2P17-T20 · canonical SVG authority</text>'
        "</svg>\n"
    )


def final_decision(sources: SourceBindings) -> dict[str, Any]:
    cards = json.loads(sources.t19.cards_path.read_bytes())
    lifecycle = cast(dict[str, dict[str, Any]], cards["lifecycle"])
    result: dict[str, Any] = {
        "schema_name": "s2p17-t20-final-decision",
        "schema_version": "1.0",
        "engineering_status": "PASS",
        "h2_primary": str(cards["btc_primary"]),
        "eth_classification": str(cards["eth_classification"]),
        "h3_lifecycle": {
            instrument: str(lifecycle[instrument]["decision"])
            for instrument in ("BTCUSDT", "ETHUSDT")
        },
        "research_decision": RESEARCH_DECISION,
        "source_recommendation": str(cards["overall_recommendation"]),
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    if (
        result["h2_primary"] != "PRIMARY_FAILED"
        or result["source_recommendation"] != "NO_GO_CURRENT_EVIDENCE"
        or any(value != LIFECYCLE_DECISION for value in result["h3_lifecycle"].values())
    ):
        raise ValueError("T19 decision cannot support the frozen T20 closure")
    result["decision_hash"] = canonical_content_hash(result)
    return result


def evidence_index(sources: SourceBindings) -> dict[str, Any]:
    upstreams = sources.upstreams
    result: dict[str, Any] = {
        "schema_name": "s2p17-t20-evidence-index",
        "schema_version": "1.0",
        "T11": {
            "receipt_hash": upstreams.t11.receipt_hash,
            "manifest_hash": upstreams.t11.manifest_hash,
            "catalog_hash": upstreams.t11.catalog_hash,
            "output_hash": upstreams.t11.output_hash,
        },
        "T16": {
            "authority_hash": upstreams.upstreams.t16.authority_hash,
            "manifest_hash": upstreams.upstreams.t16.artifact_manifest_hash,
            "catalog_hash": upstreams.upstreams.t16.artifact_catalog_hash,
            "verify_hash": upstreams.upstreams.t16.verify_hash,
        },
        "T17": {
            "manifest_hash": upstreams.upstreams.t17.manifest_hash,
            "catalog_hash": upstreams.upstreams.t17.catalog_hash,
            "verify_hash": upstreams.upstreams.t17.verify_hash,
        },
        "T18": {
            "manifest_hash": upstreams.t18.manifest_hash,
            "catalog_hash": upstreams.t18.catalog_hash,
            "verify_hash": upstreams.t18.verify_hash,
        },
        "T19": {
            "authority_hash": sources.t19.authority_hash,
            "manifest_hash": sources.t19.manifest_hash,
            "catalog_hash": sources.t19.catalog_hash,
            "verify_hash": sources.t19.verify_hash,
        },
    }
    result["evidence_index_hash"] = canonical_content_hash(result)
    return result
