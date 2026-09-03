from typing import Any, Dict, List
from src.logger import get_logger
from src.signals.base import BaseSignalDetector
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

logger = get_logger("signals_registry")


class SignalRegistry:
    """Instantiates and registers all signal detectors based on user configuration."""

    DETECTOR_CLASSES = {
        "signal_a": SignalAPullbackReclaim,
        "signal_b": SignalBBreakoutRetest,
        "signal_c": SignalCRsiReset,
        "signal_d": SignalDRsiMomentum,
        "signal_e": SignalEVwapReclaim,
        "signal_f": SignalFVolumeSpike,
        "signal_g": SignalGSupportBounce,
        "signal_h": SignalHBbSqueeze,
        "signal_i": SignalIMacdCross,
        "signal_j": SignalJEmaStack,
        "signal_k": SignalKSupertrendFlip,
        "signal_l": SignalLStochRsiCross,
    }

    def __init__(self, signals_config: Dict[str, Dict[str, Any]]):
        self.detectors: List[BaseSignalDetector] = []
        self._initialize_detectors(signals_config)

    def _initialize_detectors(self, signals_config: Dict[str, Dict[str, Any]]) -> None:
        for key, detector_cls in self.DETECTOR_CLASSES.items():
            cfg = signals_config.get(key, {})
            # If enabled in config (default True if key present or not explicitly False)
            if cfg.get("enabled", True):
                detector = detector_cls(cfg)
                self.detectors.append(detector)
                logger.debug("Registered signal detector: %s (%s)", key, detector.signal_type.value)

        logger.info("SignalRegistry initialized with %d active detectors.", len(self.detectors))

    def get_active_detectors(self) -> List[BaseSignalDetector]:
        return [d for d in self.detectors if d.enabled]
