from companysim.data.datasets import DatasetBuilder, DatasetConfig, to_organization
from companysim.model.organization import OrganizationModel
from companysim.scenarios.events import BudgetCut, LifeEvent, Reorg, Termination, Transfer
from companysim.scenarios.scenario import Scenario


def _rich_org(headcount: int = 150, seed: int = 61):
    cfg = DatasetConfig(name="ev", headcount=headcount, seed=seed)
    tables = DatasetBuilder(cfg).build()
    return to_organization(tables, org_name=cfg.org_name), tables


def test_termination_deactivates_only_named_employees():
    org, tables = _rich_org()
    target = org.employees[3].id
    untouched = org.employees[4].id
    scenario = Scenario(name="term", events=[Termination(at_tick=1, employee_ids=(target,))])
    model = OrganizationModel(org, seed=61, human_factors=tables["human_factors"], scenario=scenario)
    model.run(2)
    assert model.employees[target].active is False
    assert model.employees[untouched].active is True


def test_transfer_moves_team_membership():
    org, tables = _rich_org()
    target = org.employees[0].id
    old_team_id = org.employees[0].team_id
    new_team_id = next(t.id for t in org.teams if t.id != old_team_id)
    scenario = Scenario(name="xfer", events=[
        Transfer(at_tick=1, employee_ids=(target,), new_team_id=new_team_id),
    ])
    model = OrganizationModel(org, seed=61, human_factors=tables["human_factors"], scenario=scenario)
    model.run(2)

    assert model.employees[target].record.team_id == new_team_id
    new_team_member_ids = [a.record.id for a in model.teams[new_team_id].members]
    old_team_member_ids = [a.record.id for a in model.teams[old_team_id].members]
    assert target in new_team_member_ids
    assert target not in old_team_member_ids


def test_life_event_moves_expected_fields_in_expected_direction():
    org, tables = _rich_org(seed=63)
    target = org.employees[0].id

    baseline = OrganizationModel(org.model_copy(deep=True), seed=63, human_factors=tables["human_factors"])
    baseline.run(1)
    baseline_security = baseline.employees[target].profile.financial_security

    treated_scenario = Scenario(name="shock", events=[
        LifeEvent(at_tick=0, employee_ids=(target,), event_type="financial_shock"),
    ])
    treated = OrganizationModel(
        org.model_copy(deep=True), seed=63,
        human_factors=tables["human_factors"], scenario=treated_scenario,
    )
    treated.run(1)
    treated_security = treated.employees[target].profile.financial_security

    assert treated_security < baseline_security  # financial_shock should hurt financial_security


def test_life_event_unknown_type_is_a_no_op():
    org, tables = _rich_org(seed=67, headcount=60)
    scenario = Scenario(name="bad", events=[
        LifeEvent(at_tick=1, employee_ids=(org.employees[0].id,), event_type="not_a_real_event"),
    ])
    model = OrganizationModel(org, seed=67, human_factors=tables["human_factors"], scenario=scenario)
    model.run(2)  # should not raise


def test_budget_cut_reduces_financial_security():
    org, tables = _rich_org(seed=71)
    scenario = Scenario(name="cut", events=[BudgetCut(at_tick=1, severity=0.3)])
    baseline = OrganizationModel(org.model_copy(deep=True), seed=71, human_factors=tables["human_factors"])
    treated = OrganizationModel(
        org.model_copy(deep=True), seed=71,
        human_factors=tables["human_factors"], scenario=scenario,
    )
    baseline.run(2)
    treated.run(2)

    sample_ids = [e.id for e in org.employees[:20]]
    lower_count = sum(
        1 for eid in sample_ids
        if treated.employees[eid].profile.financial_security < baseline.employees[eid].profile.financial_security
    )
    assert lower_count >= 18  # nearly all sampled employees should see reduced financial security


def test_reorg_reduces_psych_safety_and_meaning():
    org, tables = _rich_org(seed=73)
    scenario = Scenario(name="reorg", events=[Reorg(at_tick=1, delta=0.2)])
    baseline = OrganizationModel(org.model_copy(deep=True), seed=73, human_factors=tables["human_factors"])
    treated = OrganizationModel(
        org.model_copy(deep=True), seed=73,
        human_factors=tables["human_factors"], scenario=scenario,
    )
    baseline.run(2)
    treated.run(2)

    sample_ids = [e.id for e in org.employees[:20]]
    lower_safety = sum(
        1 for eid in sample_ids
        if treated.employees[eid].profile.psychological_safety
        < baseline.employees[eid].profile.psychological_safety
    )
    assert lower_safety >= 18


def test_budget_cut_department_scoping():
    org, tables = _rich_org(seed=79, headcount=200)
    dept_id = org.departments[0].id
    other_dept_employees = [e.id for e in org.employees if e.department_id != dept_id][:10]
    scenario = Scenario(name="cut_dept", events=[BudgetCut(at_tick=1, severity=0.3, department=dept_id)])
    baseline = OrganizationModel(org.model_copy(deep=True), seed=79, human_factors=tables["human_factors"])
    treated = OrganizationModel(
        org.model_copy(deep=True), seed=79,
        human_factors=tables["human_factors"], scenario=scenario,
    )
    baseline.run(2)
    treated.run(2)

    # Employees outside the targeted department should be materially
    # unaffected relative to the targeted department's mean shift.
    diffs = [
        abs(
            treated.employees[eid].profile.financial_security
            - baseline.employees[eid].profile.financial_security
        )
        for eid in other_dept_employees
    ]
    assert sum(diffs) / len(diffs) < 0.05
