from companysim.data.generators import GeneratorConfig, WorkforceGenerator
from companysim.model.organization import OrganizationModel


def _model(headcount: int = 60, seed: int = 5) -> OrganizationModel:
    org = WorkforceGenerator(GeneratorConfig(headcount=headcount, seed=seed)).generate()
    return OrganizationModel(org, seed=seed)


def test_step_produces_snapshot():
    model = _model()
    snap = model.step()
    assert snap.tick == 0
    assert 0 < snap.active_headcount <= 60
    assert 0.0 <= snap.mean_engagement <= 1.0


def test_run_returns_history_of_expected_length():
    model = _model()
    hist = model.run(10)
    assert len(hist) == 10
    assert list(hist.columns)[:2] == ["tick", "active_headcount"]


def test_headcount_is_non_increasing_over_time():
    """Nobody joins mid-sim yet, so active headcount only falls."""
    model = _model(headcount=100, seed=9)
    hist = model.run(20)
    hc = hist["active_headcount"].tolist()
    assert all(a >= b for a, b in zip(hc, hc[1:]))


def test_run_is_reproducible():
    a = _model(headcount=40, seed=11).run(8)
    b = _model(headcount=40, seed=11).run(8)
    assert a.equals(b)
