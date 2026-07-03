"""Materialize a turnover-labeled cohort to disk (features + real exit labels).

Standalone from ``train_turnover_model.py`` so the cohort can be inspected,
version-controlled, or handed to a different training script without
re-running the (relatively expensive) forward simulation each time.

Usage:

    python scripts/build_turnover_cohort.py --headcount 3000 --replicates 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from companysim.data.datasets import DatasetConfig
from companysim.ml.turnover_features import build_feature_frame
from companysim.ml.turnover_labels import build_turnover_cohort


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headcount", type=int, default=3000)
    parser.add_argument("--replicates", type=int, default=5)
    parser.add_argument("--horizon", type=int, default=12)
    parser.add_argument("--seed", type=int, default=2024)
    parser.add_argument("--out", type=str, default="data/generated/turnover_cohort.parquet")
    args = parser.parse_args(argv)

    cfg = DatasetConfig(name="turnover_cohort", headcount=args.headcount, seed=args.seed)
    print(f"Building cohort: headcount={args.headcount}, replicates={args.replicates}, "
          f"horizon={args.horizon} ticks, seed={args.seed}...")
    cohort = build_turnover_cohort(cfg, horizon_ticks=args.horizon, replicates=args.replicates)

    feats = build_feature_frame(cohort.tables)
    merged = cohort.labels.merge(feats, on="employee_id")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(out_path, index=False)
    merged.to_csv(out_path.with_suffix(".csv"), index=False)

    print(f"\nRows: {len(merged):,}  (employees={args.headcount:,} x replicates={args.replicates})")
    print(f"Positive rate (quit within {args.horizon} ticks): {merged['quit_within_horizon'].mean():.4f}")
    print(f"Saved -> {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
