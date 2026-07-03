"""Train models on synthetic-org data.

Two training entry points:

- :func:`train_turnover_model` — the project's headline model. Trained on
  :mod:`companysim.ml.turnover_labels` (real simulated exit events) with
  :mod:`companysim.ml.turnover_features` (leakage-free observable features).
  This is what ``scripts/train_turnover_model.py`` versions and gates on.
- :func:`train_behavioral_models` — auxiliary trajectory-preview regressors
  (productivity / engagement / collaboration) plus a legacy turnover
  classifier trained directly on the generator's internal latents. Kept for
  intervention-effect previews in the dashboard; not the evaluated
  deliverable, since its targets are a closed-form function of a subset of
  its own features (see module docstring in ``ml/registry.py``).

Optional MLflow logging is invoked if the library is present; otherwise we
just persist to joblib.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from companysim.data.generators import GeneratorConfig, WorkforceGenerator
from companysim.ml.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES, build_dataset
from companysim.ml.registry import BehavioralModelBundle, TurnoverModelBundle
from companysim.ml.turnover_features import (
    CATEGORICAL_FEATURES as TURNOVER_CATEGORICAL_FEATURES,
    FEATURE_COLUMNS as TURNOVER_FEATURE_COLUMNS,
    NUMERIC_FEATURES as TURNOVER_NUMERIC_FEATURES,
    assert_no_leakage,
)

TURNOVER_THRESHOLD: float = 0.6


@dataclass
class TrainReport:
    productivity_r2: float
    productivity_mae: float
    engagement_r2: float
    engagement_mae: float
    collaboration_r2: float
    collaboration_mae: float
    turnover_auc: float
    n_train: int
    n_test: int

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _pipeline(estimator: Any) -> Pipeline:
    preprocessor = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), list(CATEGORICAL_FEATURES)),
        ("num", StandardScaler(), list(NUMERIC_FEATURES)),
    ])
    return Pipeline([("prep", preprocessor), ("model", estimator)])


def train_behavioral_models(
    *,
    headcount: int = 5_000,
    seed: int = 2024,
    test_size: float = 0.25,
    mlflow_run: bool = False,
) -> tuple[BehavioralModelBundle, TrainReport]:
    """Generate a large synthetic org, train the bundle, return report."""
    org = WorkforceGenerator(GeneratorConfig(headcount=headcount, seed=seed)).generate()
    X, y = build_dataset(org)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=seed,
    )

    prod = _pipeline(GradientBoostingRegressor(random_state=seed)).fit(X_train, y_train["productivity"])
    eng = _pipeline(GradientBoostingRegressor(random_state=seed)).fit(X_train, y_train["engagement"])
    coll = _pipeline(GradientBoostingRegressor(random_state=seed)).fit(X_train, y_train["collaboration"])

    y_turn_train = (y_train["turnover_risk"] > TURNOVER_THRESHOLD).astype(int)
    y_turn_test = (y_test["turnover_risk"] > TURNOVER_THRESHOLD).astype(int)
    turn = _pipeline(GradientBoostingClassifier(random_state=seed)).fit(X_train, y_turn_train)

    report = TrainReport(
        productivity_r2=float(r2_score(y_test["productivity"], prod.predict(X_test))),
        productivity_mae=float(mean_absolute_error(y_test["productivity"], prod.predict(X_test))),
        engagement_r2=float(r2_score(y_test["engagement"], eng.predict(X_test))),
        engagement_mae=float(mean_absolute_error(y_test["engagement"], eng.predict(X_test))),
        collaboration_r2=float(r2_score(y_test["collaboration"], coll.predict(X_test))),
        collaboration_mae=float(mean_absolute_error(y_test["collaboration"], coll.predict(X_test))),
        turnover_auc=_safe_auc(y_turn_test, turn.predict_proba(X_test)[:, 1]),
        n_train=int(len(X_train)),
        n_test=int(len(X_test)),
    )

    bundle = BehavioralModelBundle(
        productivity_model=prod,
        engagement_model=eng,
        collaboration_model=coll,
        turnover_classifier=turn,
        turnover_threshold=TURNOVER_THRESHOLD,
        metadata={"seed": seed, "headcount": headcount, **report.as_dict()},
    )

    if mlflow_run:
        _log_to_mlflow_if_available(report, bundle)

    return bundle, report


@dataclass
class TurnoverTrainReport:
    auc: float
    precision_at_10: float
    precision_at_20: float
    base_rate: float
    n_train: int
    n_test: int

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def train_turnover_model(
    cohort: pd.DataFrame,
    *,
    seed: int = 2024,
    test_size: float = 0.25,
) -> tuple[TurnoverModelBundle, TurnoverTrainReport]:
    """Train the headline turnover classifier.

    ``cohort`` is a merged features+label frame — one row per
    (employee_id, replicate) — as produced by joining
    :func:`companysim.ml.turnover_features.build_feature_frame` onto
    :class:`companysim.ml.turnover_labels.LabeledCohort.labels`. Must
    contain every column in ``TURNOVER_FEATURE_COLUMNS`` plus
    ``quit_within_horizon``.
    """
    features = cohort[list(TURNOVER_FEATURE_COLUMNS)]
    assert_no_leakage(features)
    y = cohort["quit_within_horizon"].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        features, y, test_size=test_size, random_state=seed, stratify=y,
    )

    preprocessor = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), list(TURNOVER_CATEGORICAL_FEATURES)),
        ("num", StandardScaler(), list(TURNOVER_NUMERIC_FEATURES)),
    ])
    classifier = Pipeline([
        ("prep", preprocessor),
        ("model", GradientBoostingClassifier(random_state=seed)),
    ])
    classifier.fit(X_train, y_train)

    proba = classifier.predict_proba(X_test)[:, 1]
    y_test_arr = y_test.to_numpy()
    report = TurnoverTrainReport(
        auc=_safe_auc(y_test, proba),
        precision_at_10=precision_at_k(y_test_arr, proba, 0.10),
        precision_at_20=precision_at_k(y_test_arr, proba, 0.20),
        base_rate=float(y.mean()),
        n_train=int(len(X_train)),
        n_test=int(len(X_test)),
    )
    bundle = TurnoverModelBundle(
        classifier=classifier,
        metadata={"seed": seed, **report.as_dict()},
    )
    return bundle, report


def precision_at_k(y_true: np.ndarray, y_score: np.ndarray, k_frac: float) -> float:
    """Fraction of true positives among the top ``k_frac`` highest-scored rows.

    The metric a retention program actually cares about: "if we can only
    intervene on the riskiest 10% of the workforce, how many of them were
    really going to quit?"
    """
    n = len(y_true)
    k = max(1, int(round(n * k_frac)))
    order = np.argsort(-y_score)[:k]
    return float(y_true[order].mean())


def _safe_auc(y_true: pd.Series, y_score: np.ndarray) -> float:
    if y_true.nunique() < 2:
        return float("nan")
    return float(roc_auc_score(y_true, y_score))


def _log_to_mlflow_if_available(report: TrainReport, bundle: BehavioralModelBundle) -> None:
    try:
        import mlflow  # noqa: PLC0415
    except ImportError:
        return
    with mlflow.start_run(run_name="behavioral_bundle"):
        for k, v in report.as_dict().items():
            if isinstance(v, (int, float)):
                mlflow.log_metric(k, float(v))
        mlflow.log_params({
            "seed": bundle.metadata.get("seed"),
            "headcount": bundle.metadata.get("headcount"),
            "turnover_threshold": bundle.turnover_threshold,
        })
