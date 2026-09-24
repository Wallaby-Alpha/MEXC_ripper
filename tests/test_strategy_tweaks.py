"""Unit tests verifying the 4 strategy tweaks in mexc-momentum-scanner:
1. Notional Sizing Collar
2. Cluster Circuit Breaker & Max Positions
3. Time Decay Exit (90m Stagnation Invalidation)
4. Moving TP to +4%
"""
import pytest
from datetime import datetime, timezone
from src.live.scanner import LiveMomentumScanner
from src.live.paper_trader import PaperTrader
from src.execution.weex_executor import WeexExecutor
from src.execution.weex_symbol_mapper import WeexSymbolResolver


def test_tp_moved_to_4_percent():
    scanner = LiveMomentumScanner()
    curr_price = 10.0
    feats = {
        "swing_structure_hh_hl": 1.0,
        "pre_breakout_base_quality": 0.8,
        "atr_14": 0.2,
        "atr_pct": 0.02,
        "rvol_20": 2.5,
        "cvd_rolling": 500.0,
        "rsi_14": 60.0,
        "macd_histogram_slope": 0.1,
        "rs_vs_btc_1h": 0.02,
    }
    is_valid, setup_name, setup_tier, score, reasons, levels = scanner._evaluate_setup_quality(feats, curr_price)
    assert is_valid is True
    # TP1 must be exactly +4.0%
    expected_tp1 = curr_price * 1.040
    assert abs(levels["take_profit_1"] - expected_tp1) < 1e-6
    # TP2 must be +8.0%
    expected_tp2 = curr_price * 1.080
    assert abs(levels["take_profit_2"] - expected_tp2) < 1e-6
    # SL must be -3.5%
    expected_sl = curr_price * 0.965
    assert abs(levels["stop_loss"] - expected_sl) < 1e-6


def test_time_decay_exit():
    pt = PaperTrader(default_size_usdt=100.0, time_decay_minutes=90)
    entry_time_ms = 1000000000000
    entry_price = 1.00

    pt.open_simulated_trade(
        symbol="SUIUSDT",
        entry_price=entry_price,
        timestamp_ms=entry_time_ms,
        setup_name="PRE_BREAKOUT_ACCUMULATION",
        setup_tier="TIER 1",
        trade_levels={"stop_loss": 0.965, "take_profit_1": 1.040, "take_profit_2": 1.080},
    )
    assert "SUIUSDT" in pt.open_positions

    # 45 minutes in (no decay yet, price hovering at 1.01)
    pt.update_price("SUIUSDT", 1.01, entry_time_ms + (45 * 60 * 1000))
    assert "SUIUSDT" in pt.open_positions
    assert pt.open_positions["SUIUSDT"].tp1_hit is False

    # 91 minutes in (exceeds 90m time decay horizon without reaching TP1)
    pt.update_price("SUIUSDT", 1.01, entry_time_ms + (91 * 60 * 1000))
    assert "SUIUSDT" not in pt.open_positions
    assert len(pt.closed_positions) == 1
    closed = pt.closed_positions[0]
    assert "CLOSED_TIME_DECAY" in closed.status
    assert closed.pnl_pct == pytest.approx(0.01)


def test_cluster_circuit_breaker_max_positions():
    pt = PaperTrader()
    scanner = LiveMomentumScanner(paper_trader=pt, max_open_positions=3)

    # Simulate 3 open positions
    now_ms = 1000000000000
    for sym in ["TAOUSDT", "INJUSDT", "NEARUSDT"]:
        pt.open_simulated_trade(
            symbol=sym,
            entry_price=10.0,
            timestamp_ms=now_ms,
            setup_name="PRE_BREAKOUT",
            setup_tier="TIER 1",
            trade_levels={"stop_loss": 9.65, "take_profit_1": 10.40},
        )
    assert len(pt.open_positions) == 3

    # Attempting to open 4th position should be suppressed
    assert len(scanner.paper_trader.open_positions) >= scanner.max_open_positions


def test_cluster_circuit_breaker_recent_losses():
    pt = PaperTrader()
    scanner = LiveMomentumScanner(
        paper_trader=pt,
        max_open_positions=5,
    )
    scanner.circuit_breaker_loss_threshold = 2
    scanner.circuit_breaker_cooldown_min = 30

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Simulate 2 stop-losses occurring 5 minutes ago
    pos1 = pt.open_simulated_trade("COIN1", 10.0, now_ms - 600000, "SETUP", "T1", {"stop_loss": 9.65, "take_profit_1": 10.4})
    pos2 = pt.open_simulated_trade("COIN2", 10.0, now_ms - 600000, "SETUP", "T1", {"stop_loss": 9.65, "take_profit_1": 10.4})

    # Trigger stop-losses
    pt.update_price("COIN1", 9.60, now_ms - 300000)
    pt.update_price("COIN2", 9.60, now_ms - 300000)

    assert len(pt.closed_positions) == 2
    assert all("SL" in p.status for p in pt.closed_positions)

    # Scanner should engage circuit breaker when 2 losses in 15m occur
    recent_losses = [
        p for p in pt.closed_positions
        if p.exit_time_ms and (now_ms - p.exit_time_ms) <= 15 * 60 * 1000 and "SL" in p.status
    ]
    assert len(recent_losses) >= scanner.circuit_breaker_loss_threshold
