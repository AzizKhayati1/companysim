from companysim.data.generators import GeneratorConfig
from companysim.mc.runner import MonteCarloRunner
from companysim.scenarios.events import Layoff
from companysim.scenarios.scenario import BASELINE, Scenario


def test_bands_have_expected_columns():
    result = MonteCarloRunner(
        scenario=BASELINE,
        generator_config=GeneratorConfig(headcount=40, seed=1),
        replicates=5, ticks=8, base_seed=100,
    ).run()
    for prefix in ("active_headcount", "mean_engagement", "mean_productivity"):
        for suffix in ("_p05", "_p50", "_p95"):
            assert prefix + suffix in result.bands.columns


def test_replicates_diverge_but_ordering_holds():
    runner = MonteCarloRunner(
        scenario=Scenario(name="lay", events=[Layoff(at_tick=3, fraction=0.15)]),
        generator_config=GeneratorConfig(headcount=80, seed=2),
        replicates=8, ticks=10, base_seed=200,
    )
    result = runner.run()
    assert len(result.per_run) == 8
    # Different seeds should give slightly different endpoints — not all equal.
    endpoints = [r.iloc[-1]["mean_engagement"] for r in result.per_run]
    assert len(set(round(e, 4) for e in endpoints)) > 1
    # p05 <= p50 <= p95 must hold at every tick.
    b = result.bands
    assert (b["mean_engagement_p05"] <= b["mean_engagement_p50"]).all()
    assert (b["mean_engagement_p50"] <= b["mean_engagement_p95"]).all()


def test_band_for_returns_expected_shape():
    result = MonteCarloRunner(
        scenario=BASELINE,
        generator_config=GeneratorConfig(headcount=30, seed=4),
        replicates=3, ticks=5, base_seed=300,
    ).run()
    band = result.band_for("active_headcount")
    assert list(band.columns) == ["tick", "active_headcount_p05",
                                  "active_headcount_p50", "active_headcount_p95"]
    assert len(band) == 5
