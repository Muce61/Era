"""Run BTC/SOL/BNB cross-asset validation for R8 prototypes."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from research_core.common import (
    RANDOM_SEED,
    RESEARCH_ROOT,
    append_run_log,
    current_git_commit,
    ensure_research_dirs,
    file_sha256,
    stable_hash,
)
from research_core.cross_asset_validation_analysis import (
    CROSS_ASSET_SYMBOLS,
    cross_asset_decision,
    default_symbol_paths,
    run_cross_asset_symbol,
)
from research_core.minimal_backtest_analysis import load_params


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_report(quality: pd.DataFrame, summary: pd.DataFrame, decision: pd.DataFrame) -> str:
    fixed = summary[summary["sizing_mode"] == "fixed_2x"]
    lines = [
        "# Cross-Asset Validation Report",
        "",
        "data_layer: cross_asset_internal_validation",
        "symbols: BTCUSDT, SOLUSDT, BNBUSDT",
        "oos_status: not_oos",
        "simulation_approval: not_allowed",
        "",
        "This test applies ETH discovery-fitted family score metadata and ETH discovery score thresholds to other assets. It is cross-asset validation, not time OOS.",
        "",
        "## Data Quality",
        "",
        quality.to_markdown(index=False),
        "",
        "## Fixed 2x Summary",
        "",
        fixed.to_markdown(index=False),
        "",
        "## Prototype Decisions",
        "",
        decision.to_markdown(index=False),
        "",
        "## Plain Conclusions",
        "",
    ]
    supported = decision[decision["decision_status"] == "cross_asset_supported"]["prototype"].tolist()
    weak = decision[decision["decision_status"] == "weak_cross_asset_support"]["prototype"].tolist()
    failed = decision[decision["decision_status"] == "cross_asset_failed"]["prototype"].tolist()
    lines.extend([
        f"- 横向强支持: {supported if supported else 'none'}",
        f"- 横向弱支持: {weak if weak else 'none'}",
        f"- 横向失败/降级: {failed if failed else 'none'}",
        "- 这一步不能替代 R9 时间 OOS，不能作为模拟盘准入。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    ensure_research_dirs()
    out = RESEARCH_ROOT / "cross_asset_validation"
    trades_dir = out / "prototype_trades"
    equity_dir = out / "equity_curves"
    events_dir = out / "events"
    scores_dir = out / "scores"
    for path in [out, trades_dir, equity_dir, events_dir, scores_dir]:
        path.mkdir(parents=True, exist_ok=True)

    metadata = pd.read_csv(RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv")
    discovery_scores = pd.read_parquet(RESEARCH_ROOT / "family_validation" / "family_scores.parquet")
    params = load_params(load_json(RESEARCH_ROOT.parent / "configs" / "stage4_c1_frozen.json"))

    quality_frames = []
    event_summary_frames = []
    backtest_summary_frames = []
    tail_frames = []
    threshold_frames = []
    data_hash_payload = {}
    for symbol in CROSS_ASSET_SYMBOLS:
        paths = default_symbol_paths(symbol)
        data_hash_payload[symbol] = [file_sha256(path) for path in paths if path.exists()]
        result = run_cross_asset_symbol(symbol, paths, metadata, discovery_scores, params)
        quality_frames.append(result["quality"])
        event_summary_frames.append(result["event_summary"])
        backtest_summary_frames.append(result["backtest_summary"])
        if not result["tail"].empty:
            tail_frames.append(result["tail"])
        threshold_frames.append(result["thresholds"])
        result["events"].to_parquet(events_dir / f"{symbol}_event_candidates.parquet", index=False)
        result["events"].head(200).to_csv(events_dir / f"{symbol}_event_candidates_sample.csv", index=False)
        result["scores"].to_parquet(scores_dir / f"{symbol}_family_scores.parquet", index=False)
        result["trades"].to_csv(trades_dir / f"{symbol}_trades.csv", index=False)
        result["equity"].to_csv(equity_dir / f"{symbol}_equity.csv", index=False)

    quality = pd.concat(quality_frames, ignore_index=True)
    event_summary = pd.concat(event_summary_frames, ignore_index=True)
    summary = pd.concat(backtest_summary_frames, ignore_index=True)
    tail = pd.concat(tail_frames, ignore_index=True) if tail_frames else pd.DataFrame()
    thresholds = pd.concat(threshold_frames, ignore_index=True)
    decision = cross_asset_decision(summary, tail)

    quality.to_csv(out / "cross_asset_data_quality.csv", index=False)
    event_summary.to_csv(out / "cross_asset_event_summary.csv", index=False)
    summary.to_csv(out / "cross_asset_backtest_summary.csv", index=False)
    tail.to_csv(out / "cross_asset_tail_dependence.csv", index=False)
    thresholds.to_csv(out / "cross_asset_thresholds_used.csv", index=False)
    decision.to_csv(out / "cross_asset_decision_summary.csv", index=False)
    (RESEARCH_ROOT / "reports" / "cross_asset_validation_report.md").write_text(
        write_report(quality, summary, decision),
        encoding="utf-8",
    )

    append_run_log({
        "run_id": "CROSS_ASSET_VALIDATION",
        "stage": "CROSS_ASSET",
        "script": "research_core/run_cross_asset_validation.py",
        "config_hash": stable_hash({
            "symbols": CROSS_ASSET_SYMBOLS,
            "prototypes": ["P1", "P2", "P3", "P4", "P5", "P6"],
            "threshold_source": "ETH discovery family_scores quantiles",
            "metadata_hash": file_sha256(RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv"),
        }),
        "data_hash": stable_hash(data_hash_payload),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "cross_asset_internal_validation",
        "status": "success",
        "notes": "BTC/SOL/BNB cross-asset validation; not OOS; no deployable rule generated.",
    })


if __name__ == "__main__":
    main()
