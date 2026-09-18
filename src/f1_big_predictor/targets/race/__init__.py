"""Race target namespace."""

from .model import predict_race_target
from .types import RaceTargetConfig, RaceTargetInputs, RaceTargetPrediction

__all__ = ["RaceTargetConfig", "RaceTargetInputs", "RaceTargetPrediction", "predict_race_target"]
