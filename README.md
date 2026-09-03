# MEXC Altcoin Momentum Scanner + Multi-Signal Telegram Alerts

An autonomous, high-throughput, async market scanner and multi-signal research engine for MEXC spot markets. It continuously screens the universe for pumping coins, evaluates 12 independent entry heuristics concurrently (Signals A through L), dispatches tagged, rate-limited alerts to Telegram, and persists every indicator snapshot and forward price outcome (+5m, +15m, +1h, +4h, +24h) to SQLite for retrospective statistical validation.

---

## 🎯 Core Features

1. **Screening Layer (Pumping Universe)**:
   - Polls MEXC spot 24h tickers and computes 1h & 4h price changes.
   - Generous, broad filters (e.g. +3% 1h or +6% 4h, low $200k quote volume floor).
   - Filters out stablecoin pairs (`USDC`, `FDUSD`, `TUSD`, etc.) and leveraged tokens (`3L`, `3S`, `5L`, `5S`, `BULL`, `BEAR`, `DOWN`, `UP`).
   - Logs every `ENTER` and `EXIT` universe transition event to SQLite.

2. **Independent Signal Engine (Signals A through L)**:
   - **Signal A**: `[A] 🔁 PULLBACK RECLAIM` — HTF 1h EMA(50) uptrend + LTF 5m EMA(20/50) pullback and close reclaim.
   - **Signal B**: `[B] 🎯 BREAKOUT RETEST` — 15m prior resistance breakout with volume followed by retest & hold.
   - **Signal C**: `[C] 📉 RSI RESET` — 1h uptrend with 5m/15m RSI(14) pullback into 38–52 zone and upward reversal.
   - **Signal D**: `[D] 🚀 RSI MOMENTUM` — 1h RSI(14) crossing above 70 fresh momentum extension (the "chase" signal).
   - **Signal E**: `[E] 📊 VWAP RECLAIM` — 5m/15m VWAP dip and reclaim during 1h uptrend.
   - **Signal F**: `[F] 📢 VOLUME SPIKE` — 5m/15m candle volume $\ge 3\times$ 20-candle average with ATR range context.
   - **Signal G**: `[G] 🛟 SUPPORT BOUNCE` — 15m/1h swing-low pivot detection and reversal candle formation.
   - **Signal H**: `[H] 🎈 BB SQUEEZE BREAK` — 15m Bollinger Bands (20, 2) bandwidth squeeze followed by upper band close.
   - **Signal I**: `[I] ⚡ MACD CROSS` — 15m/1h MACD(12,26,9) bullish signal line cross with expanding histogram.
   - **Signal J**: `[J] 📐 EMA STACK` — 15m EMA(9) > EMA(21) > EMA(50) fresh alignment.
   - **Signal K (Bonus)**: `[K] 🟢 SUPERTREND FLIP` — 15m Supertrend(10, 3.0) bullish trend flip.
   - **Signal L (Bonus)**: `[L] 🔀 STOCH RSI CROSS` — 15m Stochastic RSI oversold ($<25$) bullish crossover.

3. **Telegram Alert Dispatcher**:
   - Distinct emojis and tags per signal type.
   - Exact message template with Symbol, Price (+1h/+4h %), Reasoning with numerical indicator values, Volume Surge, UTC Timestamp, and Signal UUID.
   - Asynchronous queue with rate limiting (~20 msgs/s) and FloodWait backoff.
   - Duplicate prevention on exact candle close timestamps.

4. **Forward-Return Tracker**:
   - Automated background worker that revisits logged signals at **+5m, +15m, +1h, +4h, +24h**.
   - Calculates return %, Max Favorable Excursion (Max Runup), and Max Adverse Excursion (Max Drawdown).
   - Backfills directly from historical MEXC klines.

5. **Analytics CLI & Data Exports**:
   - `python -m src.cli stats` — Database counts & health.
   - `python -m src.cli signals` — Breakdown of fires by signal type.
   - `python -m src.cli performance` — Win rates and average forward returns matrix.
   - `python -m src.cli export` — Export dataset to CSV for offline Python/Jupyter analysis.

---

## 🚀 Quickstart

### 1. Install Dependencies
```bash
python -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows:
.\venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env`:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
DRY_RUN=false
```
*(Note: If `DRY_RUN=true` or credentials are blank, alerts will be printed to console/logs instead of Telegram)*

### 3. Run a Single Test Scan
```bash
python -m src.cli scan-once
```

### 4. Start the Scanner Daemon
```bash
python -m src.main
```

---

## 📊 CLI Commands

| Command | Description |
|---|---|
| `python -m src.cli scan-once` | Runs a single scan cycle and exits |
| `python -m src.cli stats` | Displays total signals, universe events, and return status |
| `python -m src.cli signals` | Displays table of signal counts by type |
| `python -m src.cli performance` | Displays win rates at 15m/1h/24h and average returns |
| `python -m src.cli export` | Exports complete signal and outcome dataset to CSV in `exports/` |
| `python -m src.cli backfill` | Manually triggers forward return backfill |

---

## 🛠️ Configuration (`config.yaml`)

All parameters are customizable without code modifications in `config.yaml`:
- **`screening`**: 1h/4h % thresholds, volume surge multiplier, quote volume floor, excluded patterns.
- **`mexc`**: Request limits, concurrency limits, kline lookbacks.
- **`signals`**: Toggle individual signals `enabled: true/false` and adjust parameters (periods, tolerances, thresholds).
- **`forward_returns`**: Evaluation intervals (+5m, +15m, +1h, +4h, +24h) and check frequency.

---

## 🌐 DigitalOcean Droplet Deployment

### Option A: Systemd Service (Recommended)
1. Clone the repository to `/opt/mexc-momentum-scanner` on your droplet.
2. Set up virtualenv and install requirements:
   ```bash
   cd /opt/mexc-momentum-scanner
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy the systemd service file:
   ```bash
   sudo cp deploy/mexc-scanner.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable mexc-scanner
   sudo systemctl start mexc-scanner
   ```
4. View live logs:
   ```bash
   journalctl -u mexc-scanner -f
   ```

### Option B: Docker Compose
```bash
docker compose up -d --build
```
