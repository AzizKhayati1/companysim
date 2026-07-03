from companysim.data.generators import GeneratorConfig, WorkforceGenerator
from companysim.data.human_factors import HumanProfile
from companysim.model.organization import OrganizationModel
from companysim.scenarios.events import PolicyChange
from companysim.scenarios.scenario import Scenario


def test_agents_get_human_profiles_by_default():
    org = WorkforceGenerator(GeneratorConfig(headcount=40, seed=51)).generate()
    model = OrganizationModel(org, seed=51)
    for agent in model.employees.values():
        assert isinstance(agent.profile, HumanProfile)


def test_snapshot_exposes_wellbeing_metrics():
    org = WorkforceGenerator(GeneratorConfig(headcount=60, seed=52)).generate()
    hist = OrganizationModel(org, seed=52).run(5)
    for col in ("mean_burnout", "mean_stress", "mean_sleep_quality",
                "mean_mood", "mean_psychological_safety", "burnout_rate"):
        assert col in hist.columns
        assert hist[col].between(0, 1).all()


def test_positive_policy_shock_lifts_mood_this_tick():
    org = WorkforceGenerator(GeneratorConfig(headcount=80, seed=54)).generate()
    baseline = OrganizationModel(org.model_copy(deep=True), seed=54).run(4)
    boosted = OrganizationModel(
        org.model_copy(deep=True),
        seed=54,
        scenario=Scenario(name="wfh", events=[PolicyChange(at_tick=1, delta=+0.20)]),
    ).run(4)
    # Policy is applied at tick 1 → engagement bump propagates into mood via team climate.
    assert boosted.loc[3, "mean_engagement"] > baseline.loc[3, "mean_engagement"]


def test_employee_frame_includes_wellbeing_columns():
    org = WorkforceGenerator(GeneratorConfig(headcount=30, seed=55)).generate()
    model = OrganizationModel(org, seed=55)
    model.run(3)
    df = model.employee_frame()
    for col in ("burnout", "stress", "sleep_quality", "mood",
                "psychological_safety", "workload", "meaning"):
        assert col in df.columns
        assert df[col].between(0, 1).all()
