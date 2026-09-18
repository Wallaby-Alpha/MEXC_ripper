# MEXC Altcoin Momentum Continuation: Backtest Findings

*Generated: 2026-09-18 00:54:20 UTC*

---

## 1. Executive Summary
| Metric | Value |
|---|---|
| **Total Candidates Evaluated** | `5,750` |
| **Successful Continuations (+15% with <=8% DD)** | `1,110` (`19.3%`) |
| **Average 24h Forward Return** | `-0.44%` |
| **Average Max Favorable Excursion (24h Peak)** | `+13.08%` |
| **Average Max Drawdown (24h Trough)** | `-9.09%` |

> [!WARNING]
> **Lookahead-Bias Free & Temporal Split Recommendation**
> All features in this study were computed strictly point-in-time using only candles prior to or at bar close.
> However, because this initial discovery phase spans a 10-day historical window, the sample size is directional.
> **Recommended Next Step**: Before hardcoding rules or allocating live capital, expand the backtest ingestion to a **3 to 6 month window** and execute a **strict chronological train/test split** (first 70% in time for feature calibration, last 30% held out to test persistence).

## 2. Feature Bucket Performance Breakdown
This section isolates which preconditions separated pumps that continued from those that faded:

### Feature: `rvol_20`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(-0.001, 0.942]` | 1438 | **28.2%** | -2.02% | +18.70% | -13.99% |
| `(0.942, 2.331]` | 1437 | **21.6%** | +0.82% | +14.43% | -8.57% |
| `(2.331, 3.671]` | 1437 | **14.0%** | -0.07% | +9.79% | -6.78% |
| `(3.671, 680.864]` | 1438 | **13.5%** | -0.48% | +9.39% | -7.00% |

### Feature: `rvol_60`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(-0.001, 0.945]` | 1438 | **27.7%** | -1.90% | +18.72% | -14.11% |
| `(0.945, 2.126]` | 1437 | **21.1%** | +0.58% | +13.56% | -8.24% |
| `(2.126, 3.642]` | 1437 | **14.6%** | -0.13% | +10.13% | -6.96% |
| `(3.642, 321.689]` | 1438 | **13.8%** | -0.30% | +9.90% | -7.02% |

### Feature: `volume_persistence`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(-0.001, 1.0]` | 4699 | **20.5%** | -0.16% | +13.59% | -9.18% |
| `(1.0, 7.0]` | 1051 | **13.8%** | -1.66% | +10.79% | -8.64% |

### Feature: `cvd_rolling`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(93152.73, 3365812183.881]` | 1438 | **28.4%** | -1.81% | +16.95% | -12.03% |
| `(-58040969020.256996, -58128.7]` | 1438 | **22.0%** | +0.85% | +16.13% | -10.07% |
| `(88.341, 93152.73]` | 1437 | **15.7%** | -0.96% | +10.89% | -8.20% |
| `(-58128.7, 88.341]` | 1437 | **11.1%** | +0.17% | +8.35% | -6.04% |

### Feature: `cvd_price_divergence`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `0.0` | 4088 | **20.0%** | -0.73% | +13.19% | -9.22% |
| `1.0` | 1238 | **18.1%** | +0.46% | +14.09% | -9.61% |
| `-1.0` | 424 | **15.8%** | -0.19% | +9.10% | -6.31% |

### Feature: `pre_breakout_base_quality`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(0.0752, 0.354]` | 1438 | **29.0%** | -2.96% | +21.85% | -17.35% |
| `(0.354, 0.557]` | 1437 | **26.2%** | +0.27% | +16.30% | -10.13% |
| `(0.557, 0.777]` | 1437 | **16.1%** | +0.91% | +9.27% | -5.47% |
| `(0.777, 0.996]` | 1438 | **5.9%** | +0.04% | +4.90% | -3.38% |

### Feature: `breakout_flag`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `1.0` | 499 | **26.1%** | -0.96% | +17.18% | -11.24% |
| `0.0` | 5251 | **18.7%** | -0.39% | +12.69% | -8.88% |

### Feature: `retest_hold_flag`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `1.0` | 631 | **25.7%** | -1.87% | +16.74% | -12.27% |
| `0.0` | 5119 | **18.5%** | -0.26% | +12.63% | -8.69% |

### Feature: `swing_structure_hh_hl`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `2.0` | 750 | **23.2%** | -1.35% | +14.11% | -10.75% |
| `1.0` | 2098 | **20.4%** | -1.04% | +14.19% | -10.31% |
| `0.0` | 2902 | **17.5%** | +0.24% | +12.01% | -7.77% |

### Feature: `extension_atr`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(-3.314, -1.568]` | 1437 | **21.4%** | +0.22% | +14.14% | -9.03% |
| `(-0.369, 12.744]` | 1438 | **20.7%** | -0.35% | +13.38% | -8.85% |
| `(-69.334, -3.314]` | 1438 | **18.0%** | +0.63% | +11.28% | -7.13% |
| `(-1.568, -0.369]` | 1437 | **17.1%** | -2.26% | +13.52% | -11.34% |

### Feature: `atr_pct`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(0.00777, 0.0152]` | 1437 | **30.8%** | +1.58% | +17.41% | -9.17% |
| `(0.0152, 0.11]` | 1438 | **25.8%** | -3.72% | +21.34% | -18.48% |
| `(0.00362, 0.00777]` | 1437 | **17.0%** | +0.36% | +10.01% | -5.68% |
| `(-0.0009654, 0.00362]` | 1438 | **3.6%** | +0.03% | +3.57% | -3.01% |

### Feature: `rsi_14`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(68.623, 100.0]` | 1438 | **25.9%** | -1.84% | +15.37% | -10.54% |
| `(45.186, 57.549]` | 1437 | **18.0%** | +0.19% | +12.78% | -8.89% |
| `(57.549, 68.623]` | 1437 | **17.5%** | -0.62% | +13.91% | -10.47% |
| `(-0.0009999697, 45.186]` | 1438 | **15.7%** | +0.52% | +10.26% | -6.44% |

### Feature: `rsi_pullback_depth`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(33.327, 41.376]` | 1434 | **21.1%** | +1.20% | +14.04% | -7.91% |
| `(-0.0009999806000000001, 33.327]` | 1441 | **20.7%** | -1.02% | +13.67% | -9.51% |
| `(41.376, 47.622]` | 1438 | **17.9%** | +0.39% | +11.63% | -7.82% |
| `(47.622, 100.0]` | 1437 | **17.6%** | -2.32% | +12.98% | -11.10% |

### Feature: `macd_histogram_slope`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(-9.54e-06, 4.29e-11]` | 1437 | **22.3%** | +0.51% | +12.78% | -7.66% |
| `(4.29e-11, 1.05e-05]` | 1437 | **21.2%** | -0.02% | +12.34% | -7.79% |
| `(-0.267, -9.54e-06]` | 1438 | **17.3%** | -1.07% | +13.16% | -10.16% |
| `(1.05e-05, 0.362]` | 1438 | **16.4%** | -1.16% | +14.03% | -10.73% |

### Feature: `rs_vs_btc_1h`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(0.0466, 0.531]` | 1438 | **29.4%** | -2.79% | +20.65% | -15.78% |
| `(0.0123, 0.0466]` | 1437 | **22.7%** | +0.26% | +14.59% | -9.40% |
| `(-0.35, -0.0024]` | 1438 | **15.9%** | +0.57% | +11.05% | -7.05% |
| `(-0.0024, 0.0123]` | 1437 | **9.2%** | +0.21% | +6.01% | -4.11% |

### Feature: `rs_vs_btc_4h`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(0.047, 0.74]` | 1438 | **27.0%** | -2.34% | +19.69% | -14.69% |
| `(-0.575, -0.00914]` | 1438 | **20.8%** | +0.39% | +14.66% | -9.58% |
| `(0.00863, 0.047]` | 1437 | **19.4%** | +0.18% | +11.70% | -7.49% |
| `(-0.00914, 0.00863]` | 1437 | **10.0%** | +0.03% | +6.25% | -4.57% |

### Feature: `turnover_24h`
| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |
|---|---|---|---|---|---|
| `(114500.57, 256432.791]` | 1437 | **28.7%** | +4.04% | +17.55% | -6.89% |
| `(47350.561, 69051.106]` | 1438 | **20.7%** | +0.23% | +12.13% | -7.37% |
| `(69051.106, 114500.57]` | 1437 | **16.1%** | -0.49% | +9.43% | -7.38% |
| `(256432.791, 2609100.034]` | 1438 | **11.8%** | -5.54% | +13.21% | -14.69% |

## 3. Joint Feature Importance (Logistic Regression & Decision Tree)
Logistic Regression standardized coefficients (positive = favors continuation, negative = favors fade):

| Feature | Standardized Weight (LR) | Importance (Tree) |
|---|---|---|
| `pre_breakout_base_quality` | `-0.5559` | `0.0000` |
| `cvd_rolling` | `+0.3807` | `0.0786` |
| `turnover_24h` | `-0.3380` | `0.1430` |
| `atr_pct` | `+0.1876` | `0.5406` |
| `rsi_14` | `+0.1809` | `0.0086` |
| `rs_vs_btc_1h` | `-0.1645` | `0.0000` |
| `breakout_flag` | `+0.1353` | `0.0000` |
| `volume_persistence` | `-0.1204` | `0.0000` |
| `rsi_pullback_depth` | `-0.0995` | `0.0000` |
| `extension_atr` | `-0.0954` | `0.0000` |

## 4. Notable Candidate Cases
### Top Continued Movers
| Symbol | Timestamp (UTC) | Entry Price | MFE (24h) | Return (24h) | RVOL 20 | Breakout Flag |
|---|---|---|---|---|---|---|
| `CATEUSDT` | 2026-09-08 20:35 | `$0.0261` | **+137.2%** | +86.6% | 0.7x | 0 |
| `CATEUSDT` | 2026-09-08 20:40 | `$0.0261` | **+136.6%** | +86.2% | 1.5x | 0 |
| `CATEUSDT` | 2026-09-08 22:15 | `$0.0265` | **+133.0%** | +82.7% | 4.6x | 1 |

### Deepest Fades / Traps
| Symbol | Timestamp (UTC) | Entry Price | Max Drawdown | Return (24h) | RVOL 20 | Round-Tripped |
|---|---|---|---|---|---|---|
| `BTRUSDT` | 2026-09-01 07:40 | `$0.2054` | **-75.9%** | -73.3% | 3.8x | 1 |
| `BTRUSDT` | 2026-09-01 07:55 | `$0.2085` | **-76.3%** | -73.1% | 3.6x | 0 |
| `BTRUSDT` | 2026-09-01 07:50 | `$0.2098` | **-76.4%** | -72.8% | 4.2x | 0 |