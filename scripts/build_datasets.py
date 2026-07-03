"""Generate three sized synthetic datasets and print their paths.

Writes to ``data/generated/{small,medium,large}/`` with seven tables each
(CSV + Parquet) plus a manifest.json describing the run.
"""
from __future__ import annotations

import time
from pathlib import Path

from companysim.data.datasets import DATASET_SIZES, build_and_save


def main(out_root: Path | None = None) -> None:
    root = Path(out_root) if out_root else Path("data") / "generated"
    root.mkdir(parents=True, exist_ok=True)

    for name, cfg in DATASET_SIZES.items():
        t0 = time.perf_counter()
        print(f"\nBuilding '{name}' - headcount={cfg.headcount:,}, seed={cfg.seed}...")
        bundle = build_and_save(cfg, root)
        dt = time.perf_counter() - t0
        print(f"  done in {dt:.1f}s -> {bundle.directory.resolve()}")
        for k, v in bundle.metadata["row_counts"].items():
            print(f"    {k:>22}: {v:>10,} rows")

    print("\nAll datasets written under:", root.resolve())


if __name__ == "__main__":
    main()
