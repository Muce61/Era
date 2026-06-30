# P4 Evidence Audit

data_layer: expanded_discovery
oos_status: not_oos

Old left-labeled 15m outputs are marked `time_alignment_invalid` and excluded from candidate selection.

| artifact_path                                                                   | artifact_type         | validity_status          | exclusion_reason                                      | exists   |
|:--------------------------------------------------------------------------------|:----------------------|:-------------------------|:------------------------------------------------------|:---------|
| research_core/rb2_low_leverage_portfolio/rb2_backtest_summary.csv               | rb2_summary           | canonical_valid          |                                                       | True     |
| research_core/rb2_low_leverage_portfolio/rb2_portfolio_summary.csv              | rb2_portfolio         | canonical_valid          |                                                       | True     |
| research_core/realistic_replay_4_symbol/realistic_4_symbol_summary.csv          | rb1_realistic_summary | valid_internal_discovery | different leverage/prototype scope                    | True     |
| research_core/long_history_10_symbol_review/ten_symbol_long_history_summary.csv | legacy_long_history   | time_alignment_invalid   | left-labeled 15m result invalidated by RB1            | True     |
| research_core/high_leverage_gate/gate_leverage_summary.csv                      | h3_high_leverage      | not_applicable           | high leverage and gate research, not freeze candidate | True     |
| research_core/leverage_research_l2/leverage_l2_summary.csv                      | l2_high_leverage      | not_applicable           | leverage research superseded by low leverage RB2      | True     |
