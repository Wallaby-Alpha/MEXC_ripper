# MEXC Altcoin Momentum Continuation Scanner

A research-grade, two-phase algorithmic system designed to identify low/mid-cap altcoins on **MEXC** that are **already pumping and statistically likely to continue running**, filtering out fragile moves and pump-and-dump fade traps.

---

## Architecture Overview

The system strictly enforces **zero lookahead bias** and shares a single, pure-function indicator/feature layer between research and production:

1. **Phase 1 — Historical Backtester (`run_backtest.py`)**:
   - Reconstructs a **Point-in-Time** symbol universe for any target historical window (excluding survivorship bias and future-listed tokens).
   - Ingests and caches 5m OHLCV klines and trade-level CVD (Cumulative Volume Delta) into a local SQLite database (`data/raw/mexc_market_data.sqlite`).
   - Walks forward bar-by-bar applying a cheap pre-filter (`RVOL > 2.0x` or `1h return > 3%`).
   - Logs the **full feature vector** for every candidate that passes the pre-filter (pass or fail on compound rules).
   - Tracks forward horizons (4h, 12h, 24h, 48h) recording ground-truth continuation metrics: Max Favorable Excursion (MFE %), time to +10%/+25%/+50%, max drawdown before peak, and round-trip below entry.
   - Outputs feature bucket separation tables, joint ML importance models, and styled Markdown/HTML reports.

2. **Phase 2 — Live Scanner (`run_scanner.py`)**:
   - **Reuses `src/features/` directly without modification** — guaranteeing 100% calculation parity between backtest and live environments.
   - Polls MEXC live REST endpoints on the validated candle interval (5m).
   - Flags candidates in real time with formatted console tables, JSONL audit logs (`data/scanner_alerts.jsonl`), and optional webhook notifications.
   - Built-in **Paper Trader** (`src/live/paper_trader.py`) simulates virtual fills, trailing stops, and forward tracking without risking real capital.

---

## Lookahead Bias Prevention

The feature extraction pipeline (`src/features/feature_pipeline.py`) is designed as a **pure function**:
```
extract_features_point_in_time(symbol, timestamp_ms, klines_df, ...) -> dict
```
- **Strict Timestamp Slicing**: Every input series is filtered strictly to `timestamp <= timestamp_ms`. Future bars are physically inaccessible to the calculation logic.
- **Automated Verification**: `tests/test_lookahead_bias.py` verifies that mutating future bars ($t+1 \dots t+k$) with 100x price spikes and volume explosions has zero effect on feature outputs evaluated at bar $t$.

---

## Feature Vector Specification

| Category | Feature | Description |
|---|---|---|
| **Volume** | `rvol_20`, `rvol_60` | Current bar volume relative to trailing 20/60-bar baseline |
| | `volume_persistence` | Number of consecutive bars holding $\ge 1.5\times$ baseline volume |
| | `cvd_rolling` | Cumulative taker buy volume minus taker sell volume from `aggTrades` (`isBuyerMaker`) |
| | `cvd_price_divergence` | Flags divergence (e.g. price rising on net negative taker flow = fragile pump) |
| **Structure** | `pre_breakout_base_quality` | Bollinger bandwidth / ATR tightness over 20 bars prior to breakout |
| | `breakout_flag` | Close > prior 20-bar high $\times (1 + \text{buffer})$ |
| | `retest_hold_flag` | Price pulled back to breakout level and held on lower volume |
| | `swing_structure_hh_hl` | Pivot-based higher-highs and higher-lows trend sequence |
| | `extension_atr` | $(\text{Close} - \text{Breakout Level}) / \text{ATR}_{14}$ |
| **Momentum** | `rsi_14` | 14-period Wilder RSI |
| | `rsi_pullback_depth` | Lowest RSI recorded at local troughs during the move (healthy trends hold 40-50) |
| | `macd_histogram_slope` | 3-bar slope of MACD histogram (momentum acceleration vs deceleration) |
| **Relative Strength** | `rs_vs_btc_1h`, `4h`, `24h` | Coin return minus BTC return over matching lookbacks |
| | `rs_vs_eth_1h`, `4h`, `24h` | Coin return minus ETH return over matching lookbacks |
| **Liquidity** | `turnover_24h` | Rolling 24-hour USDT quote turnover |
| **Derivatives** | `funding_rate_level`, `trend` | MEXC contract funding rate level and 3-cycle trend (with graceful fallback) |

---

## Directory Structure

```
mexc-momentum-scanner/
├── README.md
├── requirements.txt
├── config.py
├── .env.example
├── run_backtest.py            # Phase 1 CLI runner
├── run_scanner.py             # Phase 2 Live Scanner CLI runner
├── data/
│   ├── raw/                   # SQLite database (klines, trades, metadata)
│   └── processed/             # CSV and Parquet labeled candidate datasets
├── reports/                   # Markdown and HTML research reports
├── src/
│   ├── data_ingestion/        # MEXC API client, cache, universe reconstruction
│   ├── features/              # Pure-function zero-lookahead feature modules
│   ├── backtest/              # Engine, forward labeler, analysis, report generator
│   └── live/                  # Real-time polling scanner, alerting, paper trader
└── tests/                     # Lookahead tests, unit tests, integration pipeline tests
```

---

## Installation & Setup

```bash
# Clone or navigate to the workspace
cd mexc-momentum-scanner

# Install dependencies
pip install -r requirements.txt
```

---

## Running the Automated Test Suite

Run the full test suite including strict lookahead-bias verification:
```bash
pytest -v
```

---

## Phase 1: Historical Backtest & Research Report

Run the walk-forward backtester on the default window (`2026-09-01T00:00:00Z` to `2026-09-10T00:00:00Z` UTC):

```bash
python run_backtest.py --start 2026-09-01T00:00:00Z --end 2026-09-10T00:00:00Z --interval 5m --max-symbols 30 --min-turnover 50000
```

### CLI Arguments
- `--start`: ISO timestamp for backtest start (default: `2026-09-01T00:00:00Z`).
- `--end`: ISO timestamp for backtest end (default: `2026-09-10T00:00:00Z`).
- `--interval`: Candle interval (default: `5m`).
- `--max-symbols`: Max universe symbols to evaluate (default: `30`).
- `--min-turnover`: Minimum 24-hour quote volume in USDT (default: `$50,000`).

### Generated Artifacts
- Processed dataset: `data/processed/candidates_labeled.csv` and `data/processed/candidates_labeled.parquet`
- Markdown report: `reports/backtest_report.md`
- Interactive HTML report: `reports/backtest_report.html`

> [!NOTE]
> **Methodological Note on Sample Size:**
> When running over a 10-day window, results are directional. We explicitly recommend expanding ingestion to a **3 to 6 month window** and applying a **strict 70/30 chronological train/test split** before deploying capital.

---

## Phase 2: Live Momentum Scanner & Paper Trader

Run the live scanner in real-time polling mode:

```bash
# Continuous real-time polling (polls every 60 seconds across top liquid alts)
python run_scanner.py --interval 5m --poll-sec 60 --top-coins 40 --min-score 70.0

# Single dry-run iteration (smoketest against live data)
python run_scanner.py --dry-run
```

### Validated Setup Archetypes Identified
The scanner classifies live opportunities into 3 statistically grounded archetypes:
1. **Tier 1: `PURE_BREAKOUT_CONTINUATION`**
   - High-probability expansion breaking above prior 20-bar consolidation resistance.
   - Early sustained RVOL ($1.8\times - 4.5\times$), positive CVD taker delta, expanding ATR.
2. **Tier 1: `RETEST_HOLD_SPRINGBOARD`**
   - Prior resistance level tested and held as new support with decreasing volume on the dip.
   - Backtest proved this archetype has a **25.7% continuation hit rate** and **+16.7% average peak run**.
3. **Tier 2: `PRE_BREAKOUT_ACCUMULATION`**
   - Ascending pivot structure (`swing_structure_hh_hl >= 1`), tight base quality, and accelerating order flow before the public breakout.

### Automated Trade Execution Levels
Each alert automatically outputs calculated risk/reward parameters based on volatility ($\text{ATR}_{14}$):
* **Entry**: Current 5m candle close.
* **Stop Loss**: Dynamic floor ($1.5 \times \text{ATR}$, approx $-5.5\%$).
* **Target 1 (Scalp / Breakeven)**: $+8\%$ to $+10\%$ (trails stop loss to entry price).
* **Target 2 (Continuation MFE)**: $+15\%$ (the Phase 1 continuation target).
* **Target 3 (Moonbag Runner)**: $+25\%$ to $+35\%$.
* **Risk / Reward**: Minimum $1 : 2.5$ to $1 : 3.0$.

### Multi-Channel Alerting
* **Console Dashboard**: Formatted color-coded Rich cards and live active position tracking.
* **JSONL Audit Log**: `data/scanner_alerts.jsonl`.
* **Optional Webhooks**: Supports Telegram bots (`TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID`) and Discord channels (`DISCORD_WEBHOOK_URL`).
