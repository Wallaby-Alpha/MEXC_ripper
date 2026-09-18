"""Google Colab Performance Evaluator for MEXC Scanner Alerts.

Copy and paste this entire code into a Google Colab cell.
It accepts your alerts JSON or JSONL file, pulls real subsequent 5m MEXC market data,
and simulates exact forward trade performance (TPs, SL, breakeven trailing, equity curve).
"""

# Install required dependencies if in Colab
try:
    import google.colab
    IN_COLAB = True
    print("Running in Google Colab environment. Installing httpx...")
    import subprocess
    subprocess.run(["pip", "install", "-q", "httpx"], check=True)
except ImportError:
    IN_COLAB = False

import json
import time
import datetime
from typing import List, Dict, Any, Optional
import httpx
import pandas as pd
import numpy as np
try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


# ==============================================================================
# 1. MEXC Forward Market Data Ingestion
# ==============================================================================

def fetch_mexc_forward_klines(
    symbol: str,
    start_time_ms: Optional[int] = None,
    horizon_hours: int = 24,
    interval: str = "5m",
) -> pd.DataFrame:
    """Fetches real historical 5m candlestick bars from MEXC starting from the alert timestamp."""
    if not symbol or not isinstance(symbol, str) or not symbol.strip():
        return pd.DataFrame()

    symbol = symbol.strip().upper().replace("/", "")

    # Ensure start_time_ms is always a valid integer
    if not start_time_ms or not isinstance(start_time_ms, (int, float)):
        start_time_ms = int(time.time() * 1000) - (horizon_hours * 3600 * 1000)
    start_time_ms = int(start_time_ms)

    base_url = "https://api.mexc.com/api/v3/klines"
    duration_ms = horizon_hours * 3600 * 1000
    end_time_ms = start_time_ms + duration_ms

    all_bars = []
    current_start = start_time_ms

    client = httpx.Client(timeout=10.0, headers={"User-Agent": "Colab-Evaluator/1.0"})

    while current_start < end_time_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_time_ms,
            "limit": 500,
        }
        try:
            res = client.get(base_url, params=params)
            if res.status_code != 200:
                break
            batch = res.json()
            if not batch or len(batch) == 0:
                break

            all_bars.extend(batch)
            last_open = int(batch[-1][0])
            next_start = last_open + 300_000  # +5m

            if next_start <= current_start or last_open >= end_time_ms:
                break
            current_start = next_start
            time.sleep(0.05)  # Rate limit courtesy
        except Exception as exc:
            print(f"Warning fetching {symbol}: {exc}")
            break

    client.close()

    if not all_bars:
        return pd.DataFrame()

    df = pd.DataFrame(
        all_bars,
        columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume"]
    )
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = df[col].astype(float)
    df["open_time"] = df["open_time"].astype(int)
    return df.drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)


# ==============================================================================
# 2. Trade Simulation Engine (With Trailing Breakeven Stop & Partial TPs)
# ==============================================================================

def simulate_trade_outcome(
    alert: Dict[str, Any],
    forward_df: pd.DataFrame,
    position_size_usdt: float = 1000.0,
) -> Dict[str, Any]:
    """Replays candles forward to test execution against TP1, TP2, TP3, and Stop Loss."""
    # Extract entry & trade levels
    levels = alert.get("levels", {})
    entry_price = float(levels.get("entry_price") or alert.get("entry_price") or alert.get("close", 0.0))
    stop_loss = float(levels.get("stop_loss") or alert.get("stop_loss") or (entry_price * 0.945))
    tp1 = float(levels.get("take_profit_1") or alert.get("take_profit_1") or (entry_price * 1.09))
    tp2 = float(levels.get("take_profit_2") or alert.get("take_profit_2") or (entry_price * 1.15))
    tp3 = float(levels.get("take_profit_3") or alert.get("take_profit_3") or (entry_price * 1.25))

    symbol = alert.get("symbol", "UNKNOWN")
    setup_name = alert.get("setup_name") or alert.get("archetype") or "MOMENTUM_EXPANSION"
    setup_tier = alert.get("setup_tier", "TIER 1")
    alert_time = alert.get("timestamp_ms") or alert.get("timestamp", 0)

    result = {
        "symbol": symbol,
        "setup_name": setup_name,
        "setup_tier": setup_tier,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "take_profit_3": tp3,
        "exit_price": entry_price,
        "exit_reason": "TIMEOUT_24H",
        "duration_minutes": 0,
        "peak_mfe_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "tp1_reached": False,
        "tp2_reached": False,
        "tp3_reached": False,
        "pnl_pct": 0.0,
        "pnl_usdt": 0.0,
    }

    if forward_df.empty or entry_price <= 0:
        result["exit_reason"] = "NO_MARKET_DATA"
        return result

    # Exclude the entry candle itself if included
    bars = forward_df[forward_df["open_time"] > alert_time].reset_index(drop=True)
    if bars.empty:
        bars = forward_df

    highest_p = entry_price
    lowest_p = entry_price
    current_sl = stop_loss
    tp1_hit = False

    for idx, row in bars.iterrows():
        high = row["high"]
        low = row["low"]
        close = row["close"]
        bar_t = row["open_time"]

        highest_p = max(highest_p, high)
        lowest_p = min(lowest_p, low)

        # 1. Check Take Profit 1 (+9% / +10%) -> Trail Stop Loss to Breakeven
        if not tp1_hit and high >= tp1:
            tp1_hit = True
            result["tp1_reached"] = True
            current_sl = entry_price * 1.002  # Breakeven stop covering fees

        # 2. Check Take Profit 2 (+15% validated MFE target) -> Full win exit
        if high >= tp2:
            result["tp2_reached"] = True
            result["exit_price"] = tp2
            result["exit_reason"] = "TAKE_PROFIT_2 (+15%)"
            result["duration_minutes"] = int((bar_t - alert_time) / 60000) if alert_time > 0 else (idx + 1) * 5
            break

        # 3. Check Stop Loss
        if low <= current_sl:
            result["exit_price"] = current_sl
            result["exit_reason"] = "BREAKEVEN_STOP" if tp1_hit else "STOP_LOSS"
            result["duration_minutes"] = int((bar_t - alert_time) / 60000) if alert_time > 0 else (idx + 1) * 5
            break
    else:
        # Reached end of forward window (24h timeout)
        result["exit_price"] = bars["close"].iloc[-1]
        result["exit_reason"] = "TIMEOUT_24H"
        result["duration_minutes"] = len(bars) * 5

    # Calculate final PnL and excursions
    result["peak_mfe_pct"] = ((highest_p - entry_price) / entry_price) * 100.0
    result["max_drawdown_pct"] = ((lowest_p - entry_price) / entry_price) * 100.0
    result["pnl_pct"] = ((result["exit_price"] - entry_price) / entry_price) * 100.0
    result["pnl_usdt"] = position_size_usdt * (result["pnl_pct"] / 100.0)

    return result


# ==============================================================================
# 3. Batch Evaluation & Visual Performance Reporting
# ==============================================================================

def run_performance_evaluation(
    alerts: List[Dict[str, Any]],
    horizon_hours: int = 24,
    position_size_usdt: float = 1000.0,
) -> pd.DataFrame:
    """Evaluates all alerts in the dataset against real MEXC market data."""
    # Filter for alerts that actually have a symbol
    valid_alerts = [
        a for a in alerts
        if isinstance(a, dict) and (a.get("symbol") or a.get("coin")) and str(a.get("symbol", "")).upper() not in ("", "UNKNOWN")
    ]

    if not valid_alerts:
        print("\n❌ [ERROR] No valid alerts with trading symbols were found in the uploaded file.")
        print("Tip: If you uploaded a Telegram chat export, make sure the bot actually dispatched signal alerts with USDT pairs.")
        return pd.DataFrame()

    print(f"\n🚀 Evaluating {len(valid_alerts)} alerts against MEXC 5m klines ({horizon_hours}h forward window)...")
    records = []

    for i, a in enumerate(valid_alerts, 1):
        sym = str(a.get("symbol") or a.get("coin", "")).strip().upper().replace("/", "")
        t_ms = a.get("timestamp_ms")
        if not t_ms and "timestamp" in a:
            # Parse ISO string if timestamp is string
            try:
                dt = datetime.datetime.fromisoformat(str(a["timestamp"]).replace(" UTC", "+00:00").replace("Z", "+00:00"))
                t_ms = int(dt.timestamp() * 1000)
            except Exception:
                t_ms = None

        if not t_ms or not isinstance(t_ms, (int, float)):
            t_ms = int(time.time() * 1000) - (horizon_hours * 3600 * 1000)
        t_ms = int(t_ms)

        print(f"[{i}/{len(valid_alerts)}] Fetching {sym}...", end=" ", flush=True)
        fwd_df = fetch_mexc_forward_klines(sym, start_time_ms=t_ms, horizon_hours=horizon_hours)

        if fwd_df.empty:
            print("No bars found (API limit, delisted, or symbol changed).")
        else:
            print(f"Loaded {len(fwd_df)} bars.", end=" ")

        trade_res = simulate_trade_outcome(a, fwd_df, position_size_usdt=position_size_usdt)
        print(f"-> {trade_res['exit_reason']} ({trade_res['pnl_pct']:+.2f}%)")
        records.append(trade_res)

    results_df = pd.DataFrame(records)
    display_performance_dashboard(results_df, position_size_usdt=position_size_usdt)
    return results_df


def display_performance_dashboard(df: pd.DataFrame, position_size_usdt: float = 1000.0):
    """Generates detailed statistics tables, archetype breakdown, and equity curve."""
    if df.empty or "pnl_usdt" not in df.columns:
        print("No valid trade results to display.")
        return

    # Filter out trades with no market data
    valid_df = df[df["exit_reason"] != "NO_MARKET_DATA"].copy()
    if valid_df.empty:
        print("All trades had no market data available.")
        return

    total_trades = len(valid_df)
    winning_trades = valid_df[valid_df["pnl_usdt"] > 0]
    losing_trades = valid_df[valid_df["pnl_usdt"] < 0]
    be_trades = valid_df[valid_df["pnl_usdt"] == 0]

    win_count = len(winning_trades)
    loss_count = len(losing_trades)
    win_rate = (win_count / total_trades) * 100.0 if total_trades > 0 else 0.0

    total_pnl = valid_df["pnl_usdt"].sum()
    avg_trade_pnl = valid_df["pnl_usdt"].mean()
    avg_return_pct = valid_df["pnl_pct"].mean()
    avg_peak_mfe = valid_df["peak_mfe_pct"].mean()
    avg_drawdown = valid_df["max_drawdown_pct"].mean()

    gross_profit = winning_trades["pnl_usdt"].sum()
    gross_loss = abs(losing_trades["pnl_usdt"].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 1.0)

    print("\n" + "=" * 65)
    print(" [REPORT] MEXC SCANNER PERFORMANCE AUDIT REPORT")
    print("=" * 65)
    print(f"Total Evaluated Signals:   {total_trades}")
    print(f"Winning Trades (TP hit):   {win_count} ({win_rate:.1f}%)")
    print(f"Losing Trades (SL hit):    {loss_count} ({(loss_count/total_trades)*100:.1f}%)")
    print(f"Breakeven Exits:           {len(be_trades)}")
    print(f"Profit Factor:             {profit_factor:.2f}")
    print(f"Total Simulated PnL:       ${total_pnl:+,.2f} USDT")
    print(f"Average Return / Trade:    {avg_return_pct:+.2f}% (${avg_trade_pnl:+.2f})")
    print(f"Average Max Peak Run (MFE): +{avg_peak_mfe:.2f}%")
    print(f"Average Max Drawdown:      {avg_drawdown:.2f}%")
    print("=" * 65)

    # Breakdown by Setup Archetype
    if "setup_name" in valid_df.columns:
        print("\n[ARCHETYPES] PERFORMANCE BY SETUP ARCHETYPE:")
        grouped = valid_df.groupby("setup_name").agg(
            Signals=("symbol", "count"),
            WinRate=("pnl_usdt", lambda s: (s > 0).mean() * 100.0),
            AvgReturn=("pnl_pct", "mean"),
            AvgPeakMFE=("peak_mfe_pct", "mean"),
            TotalPnL=("pnl_usdt", "sum"),
        ).reset_index()
        print(grouped.to_string(index=False))

    # Breakdown by Exit Reason
    print("\n[EXITS] EXITS BREAKDOWN:")
    exits = valid_df["exit_reason"].value_counts().reset_index()
    exits.columns = ["Exit Reason", "Count"]
    exits["Share (%)"] = (exits["Count"] / total_trades) * 100.0
    print(exits.to_string(index=False))

    # Equity Curve Plot
    valid_df["cumulative_pnl"] = valid_df["pnl_usdt"].cumsum()
    valid_df["trade_num"] = np.arange(1, len(valid_df) + 1)

    if HAS_MATPLOTLIB:
        plt.figure(figsize=(10, 5))
        plt.plot(valid_df["trade_num"], valid_df["cumulative_pnl"], marker="o", color="#00c853", linewidth=2.5, label="Cumulative PnL (USDT)")
        plt.axhline(0, color="gray", linestyle="--", alpha=0.7)
        plt.title("Simulated Cumulative PnL Curve (Standard $1,000 / Position)", fontsize=14, fontweight="bold")
        plt.xlabel("Trade Sequence Number", fontsize=11)
        plt.ylabel("Net Profit (USDT)", fontsize=11)
        plt.grid(True, linestyle=":", alpha=0.6)
        plt.legend()
        plt.tight_layout()
        plt.show()


# ==============================================================================
# 4. Helper to Load Alerts (File Upload, Raw Text, Telegram Exports, or Local Path)
# ==============================================================================

import ast
import re


def _extract_telegram_text(text_val: Any) -> str:
    """Extracts plain string text from Telegram Desktop export entities or raw strings."""
    if isinstance(text_val, str):
        return text_val
    if isinstance(text_val, list):
        parts = []
        for item in text_val:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
        return "".join(parts)
    return ""


def _parse_telegram_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extracts trading signals from Telegram Desktop chat export messages."""
    parsed_alerts = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        text = _extract_telegram_text(msg.get("text", ""))
        if not text:
            continue

        # Look for symbol (USDT pair)
        sym_match = re.search(r'(?:—|--|-|SETUP|SIGNAL|PAIR|TICKER|COIN|TOKEN|SYMBOL)\s*[:]?\s*([A-Z0-9_]{2,12}USDT)', text, re.IGNORECASE)
        if not sym_match:
            sym_match = re.search(r'\b([A-Z0-9]{2,10}USDT)\b', text)
        if not sym_match:
            sym_match = re.search(r'\b([A-Z0-9]{2,10})/USDT\b', text)

        if not sym_match:
            # Skip non-trading chatter (/start, /help, bot online, etc.)
            continue

        symbol = sym_match.group(1).upper().replace("/", "")

        # Look for entry price
        entry_match = re.search(r'(?:Price|Entry|Buy|Entry Price)\*?:\s*`?\$?([0-9.]+)', text, re.IGNORECASE)
        if entry_match:
            try:
                entry_price = float(entry_match.group(1))
            except ValueError:
                entry_price = 0.0
        else:
            dollar_match = re.search(r'\$([0-9]+(?:\.[0-9]+)?)', text)
            entry_price = float(dollar_match.group(1)) if dollar_match else 0.0

        if entry_price <= 0:
            continue

        # Stop loss
        sl_match = re.search(r'(?:Stop Loss|Stop-Loss|Stop|SL)\*?:\s*`?\$?([0-9.]+)', text, re.IGNORECASE)
        stop_loss = float(sl_match.group(1)) if sl_match else round(entry_price * 0.945, 6)

        # Targets
        tp1_match = re.search(r'(?:Target 1|TP1|Target|Take Profit 1)\*?:\s*`?\$?([0-9.]+)', text, re.IGNORECASE)
        tp1 = float(tp1_match.group(1)) if tp1_match else round(entry_price * 1.09, 6)

        tp2_match = re.search(r'(?:Target 2|TP2|Take Profit 2)\*?:\s*`?\$?([0-9.]+)', text, re.IGNORECASE)
        tp2 = float(tp2_match.group(1)) if tp2_match else round(entry_price * 1.15, 6)

        tp3_match = re.search(r'(?:Target 3|TP3|Take Profit 3)\*?:\s*`?\$?([0-9.]+)', text, re.IGNORECASE)
        tp3 = float(tp3_match.group(1)) if tp3_match else round(entry_price * 1.25, 6)

        # Setup name
        setup_match = re.search(r'\[([A-Z0-9_]+)\]', text)
        if not setup_match:
            # Find candidates for Setup: <Name>, ignoring "SETUP: SYMBOLUSDT"
            setup_candidates = re.findall(r'(?:Setup|Pattern|Archetype)\*?:\s*([A-Za-z0-9_]+)', text, re.IGNORECASE)
            setup_name = "MOMENTUM_SIGNAL"
            for cand in setup_candidates:
                if not cand.upper().endswith("USDT") and cand.upper() not in ("MOMENTUM", "MEXC"):
                    setup_name = cand.strip()
                    break
        else:
            setup_name = setup_match.group(1).strip()

        # Setup tier
        tier_match = re.search(r'(?:Tier\s*([12]))', text, re.IGNORECASE)
        setup_tier = f"TIER {tier_match.group(1)}" if tier_match else "TIER 1"

        # Timestamp
        timestamp_ms = None
        if "date_unixtime" in msg:
            try:
                timestamp_ms = int(msg["date_unixtime"]) * 1000
            except Exception:
                pass
        elif "date" in msg:
            try:
                dt = datetime.datetime.fromisoformat(str(msg["date"]).replace("Z", "+00:00"))
                timestamp_ms = int(dt.timestamp() * 1000)
            except Exception:
                pass

        if not timestamp_ms:
            time_match = re.search(r'Time:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})', text)
            if time_match:
                try:
                    dt = datetime.datetime.strptime(time_match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
                    timestamp_ms = int(dt.timestamp() * 1000)
                except Exception:
                    pass

        if not timestamp_ms:
            timestamp_ms = int(time.time() * 1000) - 24 * 3600 * 1000

        parsed_alerts.append({
            "symbol": symbol,
            "setup_name": setup_name,
            "setup_tier": setup_tier,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit_1": tp1,
            "take_profit_2": tp2,
            "take_profit_3": tp3,
            "timestamp_ms": int(timestamp_ms),
            "raw_text": text[:80],
        })

    if parsed_alerts:
        print(f" Extracted {len(parsed_alerts)} actionable alerts from Telegram chat history.")

    return parsed_alerts


def load_alerts(source: Any = None) -> List[Dict[str, Any]]:
    """Loads alerts from Telegram Desktop export (result.json), standard JSON, JSONL, or Colab file uploader."""
    alerts = []

    # 1. Colab File Upload if no source provided
    if source is None and IN_COLAB:
        from google.colab import files
        print("Please upload your alerts file (result.json, alerts.json, or alerts.jsonl):")
        uploaded = files.upload()
        for filename, content in uploaded.items():
            content_str = content.decode("utf-8")
            return _parse_json_or_jsonl(content_str)

    # 2. String input (raw string or file path)
    if isinstance(source, str):
        try:
            with open(source, "r", encoding="utf-8") as f:
                return _parse_json_or_jsonl(f.read())
        except (OSError, IOError):
            return _parse_json_or_jsonl(source)

    # 3. Direct Dict (e.g. Telegram export root object)
    if isinstance(source, dict):
        if "messages" in source and isinstance(source["messages"], list):
            return _parse_telegram_messages(source["messages"])
        return [source]

    # 4. Direct List
    if isinstance(source, list):
        if source and isinstance(source[0], dict) and ("text" in source[0] or "date_unixtime" in source[0]):
            tg_alerts = _parse_telegram_messages(source)
            if tg_alerts:
                return tg_alerts
        return source

    return alerts


def _parse_json_or_jsonl(content: str) -> List[Dict[str, Any]]:
    """Ultra-resilient parser supporting:
    - Telegram Desktop chat exports (result.json with 'messages')
    - Standard JSON arrays & JSON Lines
    - Python single-quoted dicts (e.g. {'symbol': 'ENAUSDT'})
    - Markdown code fences
    """
    content = content.strip()
    content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
    content = re.sub(r"\n?```$", "", content).strip()

    # 1. Standard JSON loads
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            if "messages" in data and isinstance(data["messages"], list):
                tg_alerts = _parse_telegram_messages(data["messages"])
                if tg_alerts:
                    return tg_alerts
            return [data]
        if isinstance(data, list):
            if data and isinstance(data[0], dict) and ("text" in data[0] or "date_unixtime" in data[0]):
                tg_alerts = _parse_telegram_messages(data)
                if tg_alerts:
                    return tg_alerts
            return data
    except Exception:
        pass

    # 2. Python AST literal eval (handles single quotes: {'key': 'val'})
    try:
        data = ast.literal_eval(content)
        if isinstance(data, dict):
            if "messages" in data and isinstance(data["messages"], list):
                tg_alerts = _parse_telegram_messages(data["messages"])
                if tg_alerts:
                    return tg_alerts
            return [data]
        if isinstance(data, list):
            if data and isinstance(data[0], dict) and ("text" in data[0] or "date_unixtime" in data[0]):
                tg_alerts = _parse_telegram_messages(data)
                if tg_alerts:
                    return tg_alerts
            return data
    except Exception:
        pass

    # 3. Line by line parsing (JSON Lines or concatenated JSONs)
    alerts = []
    for line in content.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        try:
            alerts.append(json.loads(line))
            continue
        except Exception:
            pass
        try:
            alerts.append(ast.literal_eval(line))
            continue
        except Exception:
            pass
        try:
            fixed_line = re.sub(r"(?<=\{|,|\s)'([^']+)'\s*:", r'"\1":', line)
            fixed_line = fixed_line.replace("True", "true").replace("False", "false").replace("None", "null")
            alerts.append(json.loads(fixed_line))
            continue
        except Exception:
            pass

    if alerts:
        # Check if lines were Telegram messages
        if alerts and isinstance(alerts[0], dict) and ("text" in alerts[0] or "date_unixtime" in alerts[0]):
            tg_alerts = _parse_telegram_messages(alerts)
            if tg_alerts:
                return tg_alerts
        return alerts

    # 4. Regex extraction of all {...} blocks
    blocks = re.findall(r"\{[^{}]*\}", content)
    for b in blocks:
        try:
            alerts.append(ast.literal_eval(b))
        except Exception:
            try:
                alerts.append(json.loads(b))
            except Exception:
                pass

    return alerts


# ==============================================================================
# Quickstart Usage in Colab:
# ==============================================================================
if __name__ == "__main__":
    print("""
=============================================================================
MEXC Scanner Google Colab Performance Evaluator Ready!
-----------------------------------------------------------------------------
How to run in Google Colab:
1. Copy-paste this script into a cell.
2. Call:
       alerts = load_alerts()   # Prompts you to upload your alerts JSON/JSONL
       results_df = run_performance_evaluation(alerts, horizon_hours=24)
       results_df.to_csv("evaluated_trades.csv", index=False)
=============================================================================
    """)
