"""Train the behavioral bundle and persist it to models/behavioral.joblib."""
from __future__ import annotations

from pathlib import Path

from companysim.ml.registry import save_bundle
from companysim.ml.train import train_behavioral_models


def main() -> None:
    bundle, report = train_behavioral_models(headcount=5_000, seed=2024, mlflow_run=True)
    path = Path("models/behavioral.joblib")
    save_bundle(bundle, path)
    print(f"Saved bundle -> {path.resolve()}")
    print("Metrics:")
    for k, v in report.as_dict().items():
        print(f"  {k:>22} = {v}")


if __name__ == "__main__":
    main()
