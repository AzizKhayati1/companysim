"""Train the turnover classifier and gate its promotion to production.

This operationalizes "automated retraining, continuous evaluation, and
monitoring" from the original project proposal with an actual decision
rule, not just metric logging:

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

Usage:

    python scripts/train_turnover_model.py
    python scripts/train_turnover_model.py --seed 123 --tolerance 0.03
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from companysim.data.datasets import DatasetConfig
from companysim.ml.registry import TurnoverModelBundle, load_bundle, save_bundle
from companysim.ml.train import train_turnover_model
from companysim.ml.turnover_features import build_feature_frame
from companysim.ml.turnover_labels import build_turnover_cohort

PRODUCTION_PATH = Path("models/turnover_production.joblib")
LOG_PATH = Path("models/turnover_promotion_log.jsonl")

# Fixed benchmark — never regenerated with a different seed, so every
# retrain is judged against the exact same held-out population.
EVAL_CONFIG = DatasetConfig(name="eval_holdout", headcount=1500, seed=999_999)
EVAL_SIM_SEED = 888_888
EVAL_REPLICATES = 3
EVAL_HORIZON_TICKS = 12


def evaluate_bundle_on_holdout(bundle: TurnoverModelBundle) -> dict:
    cohort = build_turnover_cohort(
        EVAL_CONFIG, horizon_ticks=EVAL_HORIZON_TICKS,
        replicates=EVAL_REPLICATES, sim_base_seed=EVAL_SIM_SEED,
    )
    feats = build_feature_frame(cohort.tables)
    merged = cohort.labels.merge(feats, on="employee_id")

    from sklearn.metrics import roc_auc_score  # noqa: PLC0415
    from companysim.ml.train import precision_at_k  # noqa: PLC0415
    from companysim.ml.turnover_features import FEATURE_COLUMNS  # noqa: PLC0415

    y = merged["quit_within_horizon"].astype(int).to_numpy()
    proba = bundle.classifier.predict_proba(merged[list(FEATURE_COLUMNS)])[:, 1]
    return {
        "auc": float(roc_auc_score(y, proba)) if len(set(y)) > 1 else float("nan"),
        "precision_at_10": precision_at_k(y, proba, 0.10),
        "precision_at_20": precision_at_k(y, proba, 0.20),
        "base_rate": float(y.mean()),
        "n": int(len(y)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headcount", type=int, default=2000, help="training cohort headcount")
    parser.add_argument("--replicates", type=int, default=4, help="training cohort replicates")
    parser.add_argument("--horizon", type=int, default=12, help="label horizon in ticks")
    parser.add_argument("--seed", type=int, default=2024, help="training cohort seed")
    parser.add_argument("--tolerance", type=float, default=0.02,
                         help="max AUC regression vs. production still allowed to promote")
    parser.add_argument("--force-promote", action="store_true",
                         help="promote regardless of the gate (for bootstrapping)")
    args = parser.parse_args(argv)

    print(f"Building training cohort: headcount={args.headcount}, "
          f"replicates={args.replicates}, seed={args.seed}...")
    train_cfg = DatasetConfig(name="train", headcount=args.headcount, seed=args.seed)
    cohort = build_turnover_cohort(train_cfg, horizon_ticks=args.horizon, replicates=args.replicates)
    feats = build_feature_frame(cohort.tables)
    merged = cohort.labels.merge(feats, on="employee_id")

    print("Training candidate model...")
    candidate, train_report = train_turnover_model(merged, seed=args.seed)
    print(f"  train-split metrics: {train_report.as_dict()}")

    print(f"Evaluating candidate on fixed holdout "
          f"(headcount={EVAL_CONFIG.headcount}, seed={EVAL_CONFIG.seed})...")
    candidate_eval = evaluate_bundle_on_holdout(candidate)
    print(f"  holdout metrics: {candidate_eval}")

    production_eval: dict | None = None
    if PRODUCTION_PATH.exists():
        print(f"Evaluating current production bundle ({PRODUCTION_PATH})...")
        production = load_bundle(PRODUCTION_PATH, expected_type=TurnoverModelBundle)
        production_eval = evaluate_bundle_on_holdout(production)
        print(f"  holdout metrics: {production_eval}")
    else:
        print("No existing production bundle - first run bootstraps it.")

    decision, reason = _decide(candidate_eval, production_eval, args.tolerance, args.force_promote)
    print(f"\nDecision: {decision} - {reason}")

    if decision == "PROMOTE":
        candidate.metadata.update({
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "training_seed": args.seed,
            "training_headcount": args.headcount,
            "holdout_eval": candidate_eval,
        })
        save_bundle(candidate, PRODUCTION_PATH)
        print(f"Saved new production bundle -> {PRODUCTION_PATH.resolve()}")

    _append_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "reason": reason,
        "candidate_eval": candidate_eval,
        "production_eval": production_eval,
        "training_seed": args.seed,
        "training_headcount": args.headcount,
    })
    return 0


def _decide(
    candidate_eval: dict, production_eval: dict | None, tolerance: float, force: bool,
) -> tuple[str, str]:
    if force:
        return "PROMOTE", "forced via --force-promote"
    if production_eval is None:
        return "PROMOTE", "no existing production bundle (bootstrap)"
    cand_auc, prod_auc = candidate_eval["auc"], production_eval["auc"]
    if cand_auc >= prod_auc - tolerance:
        return "PROMOTE", f"candidate AUC {cand_auc:.4f} within tolerance of production {prod_auc:.4f}"
    return "BLOCK", f"candidate AUC {cand_auc:.4f} regresses beyond tolerance vs. production {prod_auc:.4f}"


def _append_log(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


if __name__ == "__main__":
    sys.exit(main())
