"""Run Research Core R7 prototype attribution."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import (
    DISCOVERY_DATA_PATH,
    RANDOM_SEED,
    REPO_ROOT,
    RESEARCH_ROOT,
    append_run_log,
    current_git_commit,
    ensure_research_dirs,
    file_sha256,
    stable_hash,
)
from research_core.prototype_attribution_analysis import (
    HORIZONS,
    PROTOTYPES,
    decision_summary,
    event_summary,
    incremental_attribution,
    period_summary,
    prototype_masks,
    stability_summary,
    stage_strategy_overlap_note,
    tail_dependence,
)


REQUIRED_INPUTS = [
    RESEARCH_ROOT / "events" / "event_candidates.parquet",
    RESEARCH_ROOT / "family_validation" / "family_scores.parquet",
    RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv",
    RESEARCH_ROOT / "family_validation" / "r6_decision_summary.csv",
    RESEARCH_ROOT / "family_validation" / "family_score_group_summary.csv",
    RESEARCH_ROOT / "family_validation" / "walk_forward_family_summary.csv",
    RESEARCH_ROOT / "family_validation" / "c1_overlap_audit.csv",
    RESEARCH_ROOT / "bootstrap" / "role_classification.csv",
    RESEARCH_ROOT / "logs" / "run_log.csv",
]


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing R7 inputs: " + ", ".join(missing))
    events = pd.read_parquet(RESEARCH_ROOT / "events" / "event_candidates.parquet")
    scores = pd.read_parquet(RESEARCH_ROOT / "family_validation" / "family_scores.parquet")
    events["signal_time"] = pd.to_datetime(events["signal_time"], utc=True)
    scores["signal_time"] = pd.to_datetime(scores["signal_time"], utc=True)
    if len(events) != len(scores):
        raise ValueError(f"event/scores row mismatch: {len(events)} != {len(scores)}")
    metadata = {
        "r6_decision_hash": file_sha256(RESEARCH_ROOT / "family_validation" / "r6_decision_summary.csv"),
        "family_scores_hash": file_sha256(RESEARCH_ROOT / "family_validation" / "family_scores.parquet"),
        "events_hash": file_sha256(RESEARCH_ROOT / "events" / "event_candidates.parquet"),
    }
    return events.reset_index(drop=True), scores.reset_index(drop=True), metadata


def build_report(
    event_df: pd.DataFrame,
    incremental_df: pd.DataFrame,
    stability_df: pd.DataFrame,
    tail_df: pd.DataFrame,
    decision_df: pd.DataFrame,
) -> str:
    h16 = event_df[event_df["horizon"] == 16].copy()
    inc16 = incremental_df[incremental_df["horizon"] == 16].copy()
    stable16 = stability_df[stability_df["horizon"] == 16].copy()
    tail16 = tail_df[tail_df["horizon"] == 16].copy()
    candidates = decision_df[decision_df["decision_status"] == "candidate_for_R8_backtest"]["prototype"].tolist()

    def proto_line(name: str) -> str:
        row = h16[h16["prototype"] == name].iloc[0]
        decision = decision_df[decision_df["prototype"] == name].iloc[0]
        return (
            f"- `{name}`: events={int(row['event_count'])}, "
            f"h16_mean={row['mean_fwd_ret']:.6f}, "
            f"month_positive={decision['positive_month_rate_h16']:.2%}, "
            f"tail={decision['tail_dependence_status_h16']}, "
            f"decision={decision['decision_status']}"
        )

    lines = [
        "# R7 Prototype Attribution Report",
        "",
        "data_layer: discovery",
        "data_coverage: 2024-01-01 00:00 UTC to 2026-06-24 12:05 UTC",
        "oos_status: not_oos",
        "simulation_approval: not_allowed",
        "",
        "R7 only compares event-level forward labels. It does not run trade accounting and does not create deployable strategy rules.",
        "",
        "## H16 Prototype Snapshot",
        "",
        *[proto_line(p) for p in PROTOTYPES],
        "",
        "## H16 Incremental Attribution",
        "",
    ]
    for _, row in inc16.iterrows():
        lines.append(
            f"- `{row['comparison']}`: incremental_mean={row['incremental_mean_ret']:.6f}, "
            f"plus_1atr_delta={row['incremental_plus_1atr_rate']:.6f}, "
            f"mae_delta={row['incremental_mae_improvement']:.6f}, "
            f"interpretation={row['interpretation']}"
        )
    lines.extend([
        "",
        "## Required Answers",
        "",
    ])
    lookup = inc16.set_index("comparison")
    decisions = decision_df.set_index("prototype")
    lines.extend([
        f"1. P3 momentum 是否优于 P0：`{lookup.loc['P3_vs_P0', 'interpretation']}`，h16 增量均值 {lookup.loc['P3_vs_P0', 'incremental_mean_ret']:.6f}。",
        f"2. P4 breakout 是否优于 P0：`{lookup.loc['P4_vs_P0', 'interpretation']}`，h16 增量均值 {lookup.loc['P4_vs_P0', 'incremental_mean_ret']:.6f}。",
        f"3. P5 交集是否优于单因子：P5 决策 `{decisions.loc['P5_MOMENTUM_AND_BREAKOUT_TOP40', 'decision_status']}`；需要同时对照 P3/P4，不视为独立策略结论。",
        f"4. P6 并集是否更稳健：P6 月度正收益率 {decisions.loc['P6_MOMENTUM_OR_BREAKOUT_TOP20', 'positive_month_rate_h16']:.2%}，尾部状态 `{decisions.loc['P6_MOMENTUM_OR_BREAKOUT_TOP20', 'tail_dependence_status_h16']}`。",
        f"5. P7 是否改善 C1：`{lookup.loc['P7_vs_P1', 'interpretation']}`。",
        f"6. P8 是否改善 C1：`{lookup.loc['P8_vs_P1', 'interpretation']}`；若 C1 重合高，只能作为 C1 强度解释。",
        f"7. 极端事件依赖：{tail16[['prototype', 'tail_dependence_status']].to_dict(orient='records')}。",
        f"8. 月度/季度稳定：{stable16[['prototype', 'stability_status']].to_dict(orient='records')}。",
        f"9. 可进入 R8 最小回测：{candidates if candidates else 'none'}。",
        "10. 仍然禁止称为 OOS / 模拟盘：是。当前数据仍是 discovery，R7 不允许模拟盘准入。",
        "",
        "## R7 Decision Summary",
        "",
        decision_df.to_markdown(index=False),
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    ensure_research_dirs()
    out_dir = RESEARCH_ROOT / "prototypes"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_dir = RESEARCH_ROOT / "reports"
    events, scores, metadata = load_inputs()
    masks = prototype_masks(events, scores)

    event_df = event_summary(events, masks)
    incremental_df = incremental_attribution(event_df)
    monthly_df = period_summary(events, masks, "month_group")
    quarterly_df = period_summary(events, masks, "quarter_group")
    stability_df = stability_summary(monthly_df, quarterly_df)
    tail_df = tail_dependence(events, masks)
    decision_df = decision_summary(event_df, incremental_df, stability_df, tail_df, events, masks)

    event_df.to_csv(out_dir / "prototype_event_summary.csv", index=False)
    incremental_df.to_csv(out_dir / "prototype_incremental_attribution.csv", index=False)
    monthly_df.to_csv(out_dir / "prototype_monthly_summary.csv", index=False)
    quarterly_df.to_csv(out_dir / "prototype_quarterly_summary.csv", index=False)
    stability_df.to_csv(out_dir / "prototype_stability_summary.csv", index=False)
    tail_df.to_csv(out_dir / "prototype_tail_dependence.csv", index=False)
    decision_df.to_csv(out_dir / "prototype_decision_summary.csv", index=False)
    (out_dir / "stage_strategy_overlap_note.md").write_text(stage_strategy_overlap_note(REPO_ROOT), encoding="utf-8")
    (report_dir / "R7_prototype_attribution_report.md").write_text(
        build_report(event_df, incremental_df, stability_df, tail_df, decision_df),
        encoding="utf-8",
    )

    config_hash = stable_hash({
        "stage": "R7",
        "prototypes": PROTOTYPES,
        "horizons": HORIZONS,
        "thresholds": {
            "top20": 0.80,
            "top40": 0.60,
            "decision_event_count_h16": 50,
            "positive_month_rate_h16": 0.60,
        },
        **metadata,
    })
    append_run_log({
        "run_id": "R7_PROTOTYPE_ATTRIBUTION",
        "stage": "R7",
        "script": "research_core/run_prototype_attribution.py",
        "config_hash": config_hash,
        "data_hash": file_sha256(DISCOVERY_DATA_PATH) if DISCOVERY_DATA_PATH.exists() else metadata["events_hash"],
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "discovery",
        "status": "success",
        "notes": "R7 event-level prototype attribution; not OOS; no strategy rule generated.",
    })


if __name__ == "__main__":
    main()
