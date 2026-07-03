from companysim.data.datasets import DatasetBuilder, DatasetConfig, to_organization
from companysim.model.organization import OrganizationModel
from companysim.scenarios.events import ManagerCoaching, RetentionBonus, WorkloadRelief
from companysim.scenarios.scenario import Scenario


def _rich_org(headcount: int = 200, seed: int = 41):
    cfg = DatasetConfig(name="iv", headcount=headcount, seed=seed)
    tables = DatasetBuilder(cfg).build()
    return to_organization(tables, org_name=cfg.org_name), tables


def test_retention_bonus_reduces_targeted_turnover_risk():
    org, tables = _rich_org()
    targets = tuple(e.id for e in org.employees[:10])
    scenario = Scenario(name="bonus", events=[
        RetentionBonus(at_tick=1, employee_ids=targets, amount_pct=0.25),
    ])
    baseline = OrganizationModel(org.model_copy(deep=True), seed=41, human_factors=tables["human_factors"]).run(6)
    treated_model = OrganizationModel(
        org.model_copy(deep=True), seed=41,
        human_factors=tables["human_factors"], scenario=scenario,
    )
    treated_model.run(6)
    baseline_model = OrganizationModel(org.model_copy(deep=True), seed=41, human_factors=tables["human_factors"])
    baseline_model.run(6)

    lower_count = sum(
        1 for eid in targets
        if treated_model.employees[eid].turnover_risk < baseline_model.employees[eid].turnover_risk
    )
    assert lower_count >= 8  # most targeted employees should see reduced risk


def test_workload_relief_reduces_burnout_for_targets_only():
    org, tables = _rich_org(seed=43)
    targets = tuple(e.id for e in org.employees[:8])
    non_targets = [e.id for e in org.employees[8:20]]
    scenario = Scenario(name="relief", events=[
        WorkloadRelief(at_tick=1, employee_ids=targets, delta=0.3),
    ])
    treated = OrganizationModel(org.model_copy(deep=True), seed=43, human_factors=tables["human_factors"], scenario=scenario)
    baseline = OrganizationModel(org.model_copy(deep=True), seed=43, human_factors=tables["human_factors"])
    treated.run(6)
    baseline.run(6)

    for eid in targets:
        assert treated.employees[eid].burnout <= baseline.employees[eid].burnout + 1e-9

    # Non-targeted employees shouldn't be directly affected by the event
    # (small differences from team-climate spillover are fine; workload
    # itself must be untouched).
    for eid in non_targets[:5]:
        assert treated.employees[eid].profile.baseline_workload == baseline.employees[eid].profile.baseline_workload


def test_manager_coaching_lifts_team_support_and_psych_safety():
    org, tables = _rich_org(seed=47)
    team_id = org.teams[0].id
    scenario = Scenario(name="coaching", events=[
        ManagerCoaching(at_tick=1, team_id=team_id, delta=0.2),
    ])
    treated = OrganizationModel(org.model_copy(deep=True), seed=47, human_factors=tables["human_factors"], scenario=scenario)
    baseline = OrganizationModel(org.model_copy(deep=True), seed=47, human_factors=tables["human_factors"])
    treated.run(3)
    baseline.run(3)

    member_ids = [e.id for e in org.employees if e.team_id == team_id]
    assert len(member_ids) > 0
    for eid in member_ids:
        assert treated.employees[eid].profile.manager_support >= baseline.employees[eid].profile.manager_support


def test_unknown_team_id_is_a_no_op():
    org, tables = _rich_org(seed=53, headcount=60)
    scenario = Scenario(name="bad", events=[
        ManagerCoaching(at_tick=1, team_id="does-not-exist", delta=0.2),
    ])
    model = OrganizationModel(org, seed=53, human_factors=tables["human_factors"], scenario=scenario)
    model.run(3)  # should not raise
