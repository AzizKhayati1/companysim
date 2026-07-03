"""Model registry — persist/load trained model bundles.

Bundle format is a single ``.joblib`` file containing sklearn pipelines plus
metadata. Simple by design; the MLflow model registry can slot in later
without changing callers.

Two bundle types:

- :class:`TurnoverModelBundle` — the project's headline model. Predicts
  probability of voluntary exit within the label horizon from realistic,
  non-leaky features (see :mod:`companysim.ml.turnover_features`). This is
  what the MLOps promotion gate (``scripts/train_turnover_model.py``)
  versions and compares across retrains.
- :class:`BehavioralModelBundle` — auxiliary trajectory-preview models
  (productivity / engagement / collaboration regressors). Useful for
  showing predicted drift under an intervention, but these predict the
  simulation's own internal latents from features that generated them —
  not a claim about real-world predictive validity. Kept as a secondary
  tool, not the project's evaluated deliverable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline


@dataclass
class BehavioralModelBundle:
    productivity_model: Pipeline
    engagement_model: Pipeline
    collaboration_model: Pipeline
    turnover_classifier: Pipeline
    turnover_threshold: float = 0.6
    metadata: dict[str, Any] = field(default_factory=dict)

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        """Return per-employee predictions from an observable feature frame."""
        prod = self.productivity_model.predict(features)
        eng = self.engagement_model.predict(features)
        coll = self.collaboration_model.predict(features)
        turn_proba = self.turnover_classifier.predict_proba(features)[:, 1]
        out = pd.DataFrame({
            "productivity": prod,
            "engagement": eng,
            "collaboration": coll,
            "turnover_probability": turn_proba,
        })
        out["high_turnover_risk"] = (out["turnover_probability"] >= self.turnover_threshold).astype(int)
        return out


@dataclass
class TurnoverModelBundle:
    """The project's headline model: P(voluntary exit within horizon)."""

    classifier: Pipeline
    high_risk_threshold: float = 0.5
    medium_risk_threshold: float = 0.25
    metadata: dict[str, Any] = field(default_factory=dict)

    def predict_risk(self, features: pd.DataFrame) -> pd.DataFrame:
        """Score a feature frame (as produced by
        :func:`companysim.ml.turnover_features.build_feature_frame`).

        Extra columns (e.g. ``employee_id``) are fine — the underlying
        ColumnTransformer selects only the columns it was fit on.
        """
        proba = self.classifier.predict_proba(features)[:, 1]
        tier = np.where(
            proba >= self.high_risk_threshold, "high",
            np.where(proba >= self.medium_risk_threshold, "medium", "low"),
        )
        out = pd.DataFrame({"turnover_probability": proba, "risk_tier": tier})
        if "employee_id" in features.columns:
            out.insert(0, "employee_id", features["employee_id"].to_numpy())
        return out


def save_bundle(bundle: BehavioralModelBundle | TurnoverModelBundle, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    return path


def load_bundle(
    path: str | Path,
    expected_type: type = BehavioralModelBundle,
) -> BehavioralModelBundle | TurnoverModelBundle:
    obj = joblib.load(Path(path))
    if not isinstance(obj, expected_type):
        raise TypeError(f"Expected {expected_type.__name__}, got {type(obj).__name__}")
    return obj
