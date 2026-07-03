from companysim.data.generators import GeneratorConfig, WorkforceGenerator
from companysim.model.organization import OrganizationModel
from companysim.scenarios.events import Hire, Layoff, PolicyChange, Promotion
from companysim.scenarios.scenario import Scenario


def _model(scenario: Scenario, headcount: int = 100, seed: int = 3) -> OrganizationModel:
    org = WorkforceGenerator(GeneratorConfig(headcount=headcount, seed=seed)).generate()
    return OrganizationModel(org, seed=seed, scenario=scenario)


def test_layoff_reduces_active_headcount_on_matching_tick():
    scenario = Scenario(name="layoff", events=[Layoff(at_tick=2, fraction=0.20)])
    model = _model(scenario, headcount=100)
    hist = model.run(5)
    # Big drop between tick 1 and tick 2 (the layoff).
    drop = hist.loc[1, "active_headcount"] - hist.loc[2, "active_headcount"]
    assert drop >= 15, f"expected ~20% layoff, got drop={drop}"


def test_hire_grows_headcount_and_records_hires():
    org = WorkforceGenerator(GeneratorConfig(headcount=60, seed=5)).generate()
    dept = org.departments[0].id
    scenario = Scenario(name="hiring", events=[Hire(at_tick=1, count=10, department=dept)])
    model = OrganizationModel(org, seed=5, scenario=scenario)
    hist = model.run(3)
    assert hist.loc[1, "hires_this_tick"] == 10
    assert hist.loc[2, "active_headcount"] > hist.loc[0, "active_headcount"]


def test_promotion_bumps_at_least_one_employee():
    scenario = Scenario(name="promo", events=[Promotion(at_tick=0, count=3, from_level="IC2")])
    model = _model(scenario, headcount=200)
    before_ic2 = sum(1 for a in model.employees.values() if a.record.level == "IC2")
    model.run(1)
    after_ic2 = sum(1 for a in model.employees.values() if a.record.level == "IC2")
    assert before_ic2 - after_ic2 >= 1


def test_policy_change_shifts_engagement_this_tick():
    baseline = _model(Scenario(name="none"), headcount=80).run(1)
    boosted = _model(
        Scenario(name="boost", events=[PolicyChange(at_tick=0, delta=+0.15)]),
        headcount=80,
    ).run(1)
    assert boosted.loc[0, "mean_engagement"] > baseline.loc[0, "mean_engagement"]


def test_scenario_summary_groups_by_tick():
    scenario = Scenario(name="mix", events=[
        Layoff(at_tick=5, fraction=0.1),
        Hire(at_tick=5, count=3, department="dept_00"),
        PolicyChange(at_tick=10, delta=0.05),
    ])
    summary = scenario.summary()
    assert summary[5] == ["Layoff", "Hire"]
    assert summary[10] == ["PolicyChange"]
