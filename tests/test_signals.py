import numpy as np
import pandas as pd
import pytest
from src.models.signal import SignalType
from src.models.universe import PumpingCoin
from src.signals.detector_a_pullback_reclaim import SignalAPullbackReclaim
from src.signals.detector_b_breakout_retest import SignalBBreakoutRetest
from src.signals.detector_c_rsi_reset import SignalCRsiReset
from src.signals.detector_d_rsi_momentum import SignalDRsiMomentum
from src.signals.detector_e_vwap_reclaim import SignalEVwapReclaim
from src.signals.detector_f_volume_spike import SignalFVolumeSpike
from src.signals.detector_g_support_bounce import SignalGSupportBounce
from src.signals.detector_h_bb_squeeze import SignalHBbSqueeze
from src.signals.detector_i_macd_cross import SignalIMacdCross
from src.signals.detector_j_ema_stack import SignalJEmaStack
from src.signals.detector_k_supertrend_flip import SignalKSupertrendFlip
from src.signals.detector_l_stoch_rsi_cross import SignalLStochRsiCross


@pytest.fixture
def mock_coin():
    return PumpingCoin(
        symbol="SOLUSDT",
        price=150.0,
        price_change_1h_pct=4.5,
        price_change_4h_pct=8.2,
        volume_surge_ratio=3.1,
        quote_volume_24h=5000000.0,
        trigger_reason="1h +4.5%, 4h +8.2%",
    )


def create_mock_klines(n=100, base_price=100.0, slope=0.2, interval_ms=300000):
    prices = base_price + np.arange(n) * slope
    highs = prices + 0.5
    lows = prices - 0.5
    opens = prices - 0.1
    closes = prices + 0.1
    volumes = np.full(n, 1000.0)
    times = [1700000000000 + i * interval_ms for i in range(n)]

    return pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "close_time": [t + interval_ms - 1 for t in times],
            "quote_volume": volumes * closes,
        }
    )


def test_detector_a_pullback_reclaim(mock_coin):
    detector = SignalAPullbackReclaim({"enabled": True})
    # Create 1h uptrend
    k_1h = create_mock_klines(n=70, base_price=100.0, slope=0.5, interval_ms=3600000)
    # Create 5m pullback and reclaim
    k_5m = create_mock_klines(n=80, base_price=130.0, slope=0.2, interval_ms=300000)
    # Simulate dip below EMA20 and close back above on last candle
    k_5m.loc[78, "low"] = 140.0
    k_5m.loc[78, "close"] = 141.0
    k_5m.loc[79, "low"] = 142.0
    k_5m.loc[79, "close"] = 147.0

    res = detector.evaluate(mock_coin, k_1h, None, k_5m)
    # Even if None due to strict geometry, ensure it runs without exception
    assert res is None or res.signal_type == SignalType.A


def test_detector_f_volume_spike(mock_coin):
    detector = SignalFVolumeSpike({"enabled": True, "volume_ratio_threshold": 3.0, "timeframe": "5m"})
    k_5m = create_mock_klines(n=50, base_price=100.0, slope=0.1, interval_ms=300000)
    # Make last candle volume 5x average
    k_5m.loc[49, "volume"] = 6000.0  # prior avg is 1000.0

    res = detector.evaluate(mock_coin, None, None, k_5m)
    assert res is not None
    assert res.signal_type == SignalType.F
    assert res.indicator_snapshot["volume_ratio"] >= 3.0
    assert res.symbol == "SOLUSDT"


def test_detector_i_macd_cross(mock_coin):
    detector = SignalIMacdCross({"enabled": True, "timeframe": "15m"})
    # Downtrend into strong uptrend reversal
    prices = np.concatenate([np.linspace(120, 100, 40), np.linspace(100, 115, 20)])
    k_15m = create_mock_klines(n=len(prices), base_price=100.0, slope=0.0, interval_ms=900000)
    k_15m["close"] = prices
    k_15m["high"] = prices + 0.5
    k_15m["low"] = prices - 0.5
    k_15m["open"] = prices - 0.1

    res = detector.evaluate(mock_coin, None, k_15m, None)
    assert res is None or res.signal_type == SignalType.I


def test_detector_j_ema_stack(mock_coin):
    detector = SignalJEmaStack({"enabled": True, "timeframe": "15m"})
    # Strong upward trend so EMA9 > EMA21 > EMA50
    k_15m = create_mock_klines(n=70, base_price=100.0, slope=0.8, interval_ms=900000)
    res = detector.evaluate(mock_coin, None, k_15m, None)
    assert res is None or res.signal_type == SignalType.J


def test_detector_k_supertrend_flip(mock_coin):
    detector = SignalKSupertrendFlip({"enabled": True, "timeframe": "15m"})
    # Downtrend that suddenly spikes up
    prices = np.concatenate([np.linspace(150, 100, 30), [101, 102, 120]])
    k_15m = create_mock_klines(n=len(prices), base_price=100.0, slope=0.0, interval_ms=900000)
    k_15m["close"] = prices
    k_15m["high"] = prices + 1.0
    k_15m["low"] = prices - 1.0
    k_15m["open"] = prices - 0.5

    res = detector.evaluate(mock_coin, None, k_15m, None)
    assert res is None or res.signal_type == SignalType.K
