# Regime Classification Report

R3 compares fixed interpretable prototypes. Thresholds are fit on the discovery window only.

## Frozen Thresholds

|   atr_extreme_q90 |   jump_extreme_q95 |   trend_score_q60 |   range_score_q60 |   uncertain_band |
|------------------:|-------------------:|------------------:|------------------:|-----------------:|
|              0.92 |            3.77397 |          0.533118 |          0.550612 |             0.15 |

## Regime-3 Coverage

| prototype   | symbol   | regime     |   bars |   coverage |   avg_duration_bars |   avg_duration_minutes |   mean_fwd_ret_240m |   mean_fwd_mae_atr_120m |
|:------------|:---------|:-----------|-------:|-----------:|--------------------:|-----------------------:|--------------------:|------------------------:|
| Regime-3    | BNBUSDT  | EXTREME    |  30729 |   0.137397 |             13.6835 |                205.253 |         0.00115249  |                 1.44461 |
| Regime-3    | BNBUSDT  | RANGE      |  55241 |   0.246996 |             21.7508 |                326.262 |         0.00010711  |                 1.70442 |
| Regime-3    | BNBUSDT  | TRANSITION |  97475 |   0.435835 |             15.2456 |                228.684 |         0.000129669 |                 1.64911 |
| Regime-3    | BNBUSDT  | TREND      |  40206 |   0.179771 |             14.0266 |                210.399 |         0.000691944 |                 1.57133 |
| Regime-3    | BTCUSDT  | EXTREME    |  33344 |   0.146552 |             13.1992 |                197.988 |         0.000398967 |                 1.44461 |
| Regime-3    | BTCUSDT  | RANGE      |  55917 |   0.245763 |             22.9987 |                344.98  |         0.000249549 |                 1.73614 |
| Regime-3    | BTCUSDT  | TRANSITION |  98514 |   0.432983 |             14.7085 |                220.627 |         0.000160003 |                 1.63988 |
| Regime-3    | BTCUSDT  | TREND      |  39749 |   0.174702 |             13.4983 |                202.474 |         0.000253063 |                 1.53817 |
| Regime-3    | ETHUSDT  | EXTREME    |  32576 |   0.143176 |             12.2787 |                184.181 |         0.000693899 |                 1.43474 |
| Regime-3    | ETHUSDT  | RANGE      |  57015 |   0.250589 |             22.122  |                331.829 |         0.000199923 |                 1.74849 |
| Regime-3    | ETHUSDT  | TRANSITION |  96708 |   0.425045 |             14.7903 |                221.855 |         0.000253923 |                 1.65707 |
| Regime-3    | ETHUSDT  | TREND      |  41225 |   0.18119  |             14.2141 |                213.211 |         0.000335535 |                 1.52793 |
| Regime-3    | SOLUSDT  | EXTREME    |  27500 |   0.135907 |             13.2263 |                198.394 |         0.00205952  |                 1.37987 |
| Regime-3    | SOLUSDT  | RANGE      |  49796 |   0.246096 |             21.9696 |                329.543 |        -0.000533387 |                 1.70074 |
| Regime-3    | SOLUSDT  | TRANSITION |  87995 |   0.434878 |             14.6702 |                220.053 |         0.000563869 |                 1.58901 |
| Regime-3    | SOLUSDT  | TREND      |  37053 |   0.183119 |             14.2337 |                213.506 |         0.00087269  |                 1.49128 |

## Shortest Average Durations

| regime     |   avg_duration_bars |
|:-----------|--------------------:|
| EXTREME    |             13.0969 |
| TREND      |             13.9932 |
| TRANSITION |             14.8536 |
| RANGE      |             22.2102 |

## R3 Gate

Proceed to R4 only if RANGE coverage is non-trivial, state switching is not excessive, and ETH/BTC both have usable state histories. This report does not by itself approve MR strategy construction.
