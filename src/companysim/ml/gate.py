"""MLOps promotion gate — retrain the turnover model, evaluate it against a
fixed benchmark, and decide whether to promote it to production.

Shared by ``scripts/train_turnover_model.py`` (CLI) and the webapp's
``/model/train`` endpoint — both need the exact same
build -> train -> evaluate -> decide -> (maybe) promote -> log pipeline,
so there's exactly one place this logic lives.

1. Build a training cohort from a (rolling) seed.
2. Train a candidate model.
3. Evaluate the candidate on a *fixed* held-out cohort — same seed every
   run, so it acts as a stable benchmark across retrains, never mixed into
   training data.
4. Load the current production bundle (if any) and evaluate it on the same
   fixed cohort.
5. Promote the candidate only if it doesn't regress AUC beyond a small
   tolerance. Otherwise leave production untouched and say why.

Every run appends a line to ``models/turnover_promotion_log.jsonl`` — a
lightweight audit trail of what was trained, evaluated, and decided.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from companysim.data.datasets import DatasetConfig
from companysim.ml.registry import TurnoverModelBundle, load_bundle, save_bundle
from companysim.ml.train import precision_at_k, train_turnover_model
from companysim.ml.turnover_features import FEATURE_COLUMNS, build_feature_frame
from companysim.ml.turnover_labels import build_turnover_cohort

PRODUCTION_PATH = Path("models/turnover_production.joblib")
LOG_PATH = Path("models/turnover_promotion_log.jsonl")

# Fixed benchmark — never regenerated with a different seed, so every
# retrain is judged against the exact same held-out population.
EVAL_CONFIG = DatasetConfig(name="eval_holdout", headcount=1500, seed=999_999)
EVAL_SIM_SEED = 888_888
EVAL_REPLICATES = 3
EVAL_HORIZON_TICKS = 12


@dataclass
class GateResult:
    decision: str  # "PROMOTE" | "BLOCK"
    reason: str
    candidate_eval: dict[str, Any]
    production_eval: dict[str, Any] | None
    train_report: dict[str, Any] = field(default_factory=dict)
    promoted_at: str | None = None
    n_live_examples: int = 0


def evaluate_bundle_on_holdout(bundle: TurnoverModelBundle) -> dict[str, Any]:
    from sklearn.metrics import roc_auc_score  # noqa: PLC0415

    cohort = build_turnover_cohort(
        EVAL_CONFIG, horizon_ticks=EVAL_HORIZON_TICKS,
        replicates=EVAL_REPLICATES, sim_base_seed=EVAL_SIM_SEED,
    )
    feats = build_feature_frame(cohort.tables)
    merged = cohort.labels.merge(feats, on="employee_id")
    y = merged["quit_within_horizon"].astype(int).to_numpy()
    proba = bundle.classifier.predict_proba(merged[list(FEATURE_COLUMNS)])[:, 1]
    return {
        "auc": float(roc_auc_score(y, proba)) if len(set(y)) > 1 else float("nan"),
        "precision_at_10": precision_at_k(y, proba, 0.10),
        "precision_at_20": precision_at_k(y, proba, 0.20),
        "base_rate": float(y.mean()),
        "n": int(len(y)),
    }


def _decide(
    candidate_eval: dict[str, Any], production_eval: dict[str, Any] | None,
    tolerance: float, force: bool,
) -> tuple[str, str]:
    if force:
        return "PROMOTE", "forced"
    if production_eval is None:
        return "PROMOTE", "no existing production bundle (bootstrap)"
    cand_auc, prod_auc = candidate_eval["auc"], production_eval["auc"]
    if cand_auc >= prod_auc - tolerance:
        return "PROMOTE", f"candidate AUC {cand_auc:.4f} within tolerance of production {prod_auc:.4f}"
    return "BLOCK", f"candidate AUC {cand_auc:.4f} regresses beyond tolerance vs. production {prod_auc:.4f}"


def _append_log(record: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def run_training_gate(
    *,
    headcount: int = 2000,
    replicates: int = 4,
    horizon: int = 12,
    seed: int = 2024,
    tolerance: float = 0.02,
    force_promote: bool = False,
    extra_examples: pd.DataFrame | None = None,
) -> GateResult:
    """``extra_examples``, when given, is a DataFrame already shaped like
    ``FEATURE_COLUMNS`` + ``quit_within_horizon`` — e.g. real labeled
    examples collected from webapp simulation runs
    (``api.training_examples.load_collected_examples``) — concatenated onto
    the freshly-generated synthetic cohort before training. This module
    stays DB-agnostic: it only ever sees an already-built DataFrame, never
    a database session.
    """
    train_cfg = DatasetConfig(name="train", headcount=headcount, seed=seed)
    cohort = build_turnover_cohort(train_cfg, horizon_ticks=horizon, replicates=replicates)
    feats = build_feature_frame(cohort.tables)
    merged = cohort.labels.merge(feats, on="employee_id")

    n_live_examples = 0
    if extra_examples is not None and not extra_examples.empty:
        n_live_examples = len(extra_examples)
        merged = pd.concat([merged, extra_examples], ignore_index=True)

    candidate, train_report = train_turnover_model(merged, seed=seed)
    candidate_eval = evaluate_bundle_on_holdout(candidate)

    production_eval: dict[str, Any] | None = None
    if PRODUCTION_PATH.exists():
        production = load_bundle(PRODUCTION_PATH, expected_type=TurnoverModelBundle)
        production_eval = evaluate_bundle_on_holdout(production)

    decision, reason = _decide(candidate_eval, production_eval, tolerance, force_promote)

    promoted_at: str | None = None
    if decision == "PROMOTE":
        promoted_at = datetime.now(timezone.utc).isoformat()
        candidate.metadata.update({
            "trained_at": promoted_at,
            "training_seed": seed,
            "training_headcount": headcount,
            "holdout_eval": candidate_eval,
            "n_live_examples": n_live_examples,
        })
        save_bundle(candidate, PRODUCTION_PATH)

    result = GateResult(
        decision=decision, reason=reason, candidate_eval=candidate_eval,
        production_eval=production_eval, train_report=train_report.as_dict(),
        promoted_at=promoted_at, n_live_examples=n_live_examples,
    )
    _append_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": decision, "reason": reason,
        "candidate_eval": candidate_eval, "production_eval": production_eval,
        "n_live_examples": n_live_examples,
        "training_seed": seed, "training_headcount": headcount,
    })
    return result


def get_production_status() -> dict[str, Any] | None:
    """Current production bundle's metadata, or None if none exists yet."""
    if not PRODUCTION_PATH.exists():
        return None
    bundle = load_bundle(PRODUCTION_PATH, expected_type=TurnoverModelBundle)
    return bundle.metadata
