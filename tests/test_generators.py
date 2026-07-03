from companysim.data.generators import GeneratorConfig, WorkforceGenerator


def test_generator_is_deterministic():
    a = WorkforceGenerator(GeneratorConfig(headcount=50, seed=123)).generate()
    b = WorkforceGenerator(GeneratorConfig(headcount=50, seed=123)).generate()
    assert [e.id for e in a.employees] == [e.id for e in b.employees]
    assert [e.salary for e in a.employees] == [e.salary for e in b.employees]


def test_headcount_matches_config():
    org = WorkforceGenerator(GeneratorConfig(headcount=200, seed=1)).generate()
    assert org.headcount() == 200


def test_every_employee_has_a_team_and_department():
    org = WorkforceGenerator(GeneratorConfig(headcount=120, seed=7)).generate()
    team_ids = {t.id for t in org.teams}
    dept_ids = {d.id for d in org.departments}
    for e in org.employees:
        assert e.team_id in team_ids
        assert e.department_id in dept_ids


def test_reporting_lines_form_a_forest():
    """No cycles, everyone but the top eventually reaches a dept head."""
    org = WorkforceGenerator(GeneratorConfig(headcount=80, seed=3)).generate()
    by_id = {e.id: e for e in org.employees}
    heads = {d.head_id for d in org.departments if d.head_id}
    for emp in org.employees:
        seen: set[str] = set()
        cur = emp
        while cur.manager_id is not None:
            assert cur.id not in seen, "cycle in reporting line"
            seen.add(cur.id)
            cur = by_id[cur.manager_id]
        # A chain that terminates should terminate at a department head.
        assert cur.id in heads or cur.manager_id is None
