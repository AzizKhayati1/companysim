"""CLI wrapper around companysim.ml.gate.run_training_gate.

Train the turnover classifier and gate its promotion to production. See
``src/companysim/ml/gate.py`` for the full pipeline (also used by the
webapp's "Train model" page) — this script is just the terminal UX on
top of it.

Usage:

    python scripts/train_turnover_model.py
    python scripts/train_turnover_model.py --seed 123 --tolerance 0.03
"""
from __future__ import annotations

import argparse
import sys

from companysim.ml.gate import EVAL_CONFIG, PRODUCTION_PATH, run_training_gate


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
    print("Training candidate model...")
    print(f"Evaluating candidate on fixed holdout "
          f"(headcount={EVAL_CONFIG.headcount}, seed={EVAL_CONFIG.seed})...")

    result = run_training_gate(
        headcount=args.headcount, replicates=args.replicates, horizon=args.horizon,
        seed=args.seed, tolerance=args.tolerance, force_promote=args.force_promote,
    )

    print(f"  train-split metrics: {result.train_report}")
    print(f"  candidate holdout metrics: {result.candidate_eval}")
    if result.production_eval is not None:
        print(f"  production holdout metrics: {result.production_eval}")
    else:
        print("No existing production bundle - first run bootstraps it.")

    print(f"\nDecision: {result.decision} - {result.reason}")
    if result.decision == "PROMOTE":
        print(f"Saved new production bundle -> {PRODUCTION_PATH.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
