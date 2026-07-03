from pathlib import Path

from companysim.data.generators import GeneratorConfig, WorkforceGenerator
from companysim.ml.features import FEATURE_COLUMNS, build_dataset, employee_features
from companysim.ml.registry import load_bundle, save_bundle
from companysim.ml.train import train_behavioral_models


def test_features_frame_has_expected_columns():
    org = WorkforceGenerator(GeneratorConfig(headcount=50, seed=1)).generate()
    X = employee_features(org)
    for col in FEATURE_COLUMNS:
        assert col in X.columns
    assert len(X) == 50


def test_dataset_is_aligned():
    org = WorkforceGenerator(GeneratorConfig(headcount=40, seed=2)).generate()
    X, y = build_dataset(org)
    assert len(X) == len(y) == 40
    assert y["productivity"].between(0, 1).all()


def test_training_produces_working_bundle(tmp_path: Path):
    # Small headcount to keep the test fast — accuracy will be modest,
    # we only assert the interfaces work end-to-end.
    bundle, report = train_behavioral_models(headcount=800, seed=7)
    assert report.n_train + report.n_test == 800
    org = WorkforceGenerator(GeneratorConfig(headcount=30, seed=9)).generate()
    X = employee_features(org).drop(columns=["id"])
    preds = bundle.predict(X)
    assert set(preds.columns) >= {"productivity", "engagement",
                                  "collaboration", "turnover_probability",
                                  "high_turnover_risk"}
    assert len(preds) == 30

    # Round-trip through the registry.
    path = save_bundle(bundle, tmp_path / "bundle.joblib")
    reloaded = load_bundle(path)
    preds2 = reloaded.predict(X)
    assert (preds["productivity"].values == preds2["productivity"].values).all()
