"""FastAPI backend tests — org CRUD + simulate, against an isolated
in-memory DB (StaticPool so all sessions in a test share one connection,
since :memory: SQLite is otherwise per-connection).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_create_org_matches_headcount(client):
    resp = client.post("/orgs", json={"name": "Acme", "headcount": 60, "seed": 1})
    assert resp.status_code == 201
    body = resp.json()
    assert body["headcount"] == 60
    assert body["department_count"] == 9


def test_patch_employee_salary_reflected_on_get(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 2}).json()
    emps = client.get(f"/orgs/{org['id']}/employees").json()
    emp_id = emps[0]["id"]

    resp = client.patch(f"/orgs/{org['id']}/employees/{emp_id}", json={"base_salary": 999999.0})
    assert resp.status_code == 200
    assert resp.json()["base_salary"] == 999999.0

    refetched = client.get(f"/orgs/{org['id']}/employees").json()
    updated = next(e for e in refetched if e["id"] == emp_id)
    assert updated["base_salary"] == 999999.0


def test_simulate_single_run_shape(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 3}).json()
    resp = client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 5, "replicates": 1, "seed": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "single"
    assert len(body["rows"]) == 5
    assert "active_headcount" in body["columns"]


def test_simulate_monte_carlo_shape(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 4}).json()
    resp = client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 4, "replicates": 5, "seed": 4})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "monte_carlo"
    assert len(body["rows"]) == 4
    assert "active_headcount_p50" in body["columns"]


def test_simulate_with_layoff_event_reduces_headcount(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 100, "seed": 5}).json()
    resp = client.post(f"/orgs/{org['id']}/simulate", json={
        "ticks": 3, "replicates": 1, "seed": 5,
        "events": [{"type": "layoff", "at_tick": 1, "params": {"fraction": 0.2}}],
    })
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert rows[2]["active_headcount"] < rows[0]["active_headcount"]


def test_department_delete_blocked_while_referenced(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 30, "seed": 6}).json()
    depts = client.get(f"/orgs/{org['id']}/departments").json()
    resp = client.delete(f"/orgs/{org['id']}/departments/{depts[0]['id']}")
    assert resp.status_code == 400


def test_diagnose_detects_problem_from_injected_reorg(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 300, "seed": 11}).json()
    depts = client.get(f"/orgs/{org['id']}/departments").json()

    resp = client.post(f"/orgs/{org['id']}/diagnose", json={
        "ticks": 15, "replicates": 1, "seed": 11,
        "events": [{"type": "reorg", "at_tick": 1,
                    "params": {"department_id": depts[0]["id"], "delta": 0.35}}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["problems_detected"] >= 1
    assert len(body["reports"]) == body["problems_detected"]
    report = body["reports"][0]
    assert report["explanation"]
    assert len(report["explanation"]) > 20
    assert report["recommendation"]["event_type"] in {
        "workload_relief", "manager_coaching", "retention_bonus", "policy_change",
    }


def test_diagnose_with_no_problems_returns_empty_reports(client):
    # Tiny org, short horizon, no scenario events — shouldn't trip any thresholds.
    org = client.post("/orgs", json={"name": "Quiet Co", "headcount": 30, "seed": 99}).json()
    resp = client.post(f"/orgs/{org['id']}/diagnose", json={"ticks": 3, "replicates": 1, "seed": 99})
    assert resp.status_code == 200
    body = resp.json()
    assert body["problems_detected"] == len(body["reports"])


def test_at_risk_ranking_is_sorted_descending(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 150, "seed": 21}).json()
    resp = client.get(f"/orgs/{org['id']}/at-risk", params={"top_k": 25})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["employees"]) == 25
    probs = [e["turnover_probability"] for e in body["employees"]]
    assert probs == sorted(probs, reverse=True)
    assert all(e["risk_tier"] in {"low", "medium", "high"} for e in body["employees"])


def test_at_risk_top_k_is_respected(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 50, "seed": 22}).json()
    resp = client.get(f"/orgs/{org['id']}/at-risk", params={"top_k": 5})
    assert resp.status_code == 200
    assert len(resp.json()["employees"]) == 5


def test_compare_intervention_targets_requested_count(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 200, "seed": 23}).json()
    resp = client.post(f"/orgs/{org['id']}/at-risk/compare-intervention", json={
        "intervention_type": "retention_bonus", "top_k": 15,
        "horizon_ticks": 8, "replicates": 5, "seed": 23,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_employee_count"] == 15
    assert body["estimated_cost"] > 0  # retention_bonus always has a nonzero cost
    assert body["quits_avoided_p05"] <= body["quits_avoided_p50"] <= body["quits_avoided_p95"]


def test_compare_intervention_workload_relief_has_zero_cost(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 200, "seed": 24}).json()
    resp = client.post(f"/orgs/{org['id']}/at-risk/compare-intervention", json={
        "intervention_type": "workload_relief", "top_k": 10,
        "horizon_ticks": 8, "replicates": 5, "seed": 24,
    })
    assert resp.status_code == 200
    assert resp.json()["estimated_cost"] == 0


def test_compare_intervention_manager_coaching_targets_teams(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 200, "seed": 25}).json()
    resp = client.post(f"/orgs/{org['id']}/at-risk/compare-intervention", json={
        "intervention_type": "manager_coaching", "top_k": 15,
        "horizon_ticks": 8, "replicates": 5, "seed": 25,
    })
    assert resp.status_code == 200
    assert resp.json()["target_employee_count"] == 15


def test_compare_intervention_unknown_type_rejected(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 50, "seed": 26}).json()
    resp = client.post(f"/orgs/{org['id']}/at-risk/compare-intervention", json={
        "intervention_type": "not_a_real_type", "top_k": 5,
    })
    assert resp.status_code == 400


def test_create_employee_then_delete(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 7}).json()
    depts = client.get(f"/orgs/{org['id']}/departments").json()
    teams = client.get(f"/orgs/{org['id']}/teams").json()
    team = next(t for t in teams if t["department_id"] == depts[0]["id"])

    resp = client.post(f"/orgs/{org['id']}/employees", json={
        "full_name": "New Hire", "department_id": depts[0]["id"], "team_id": team["id"],
    })
    assert resp.status_code == 201
    new_id = resp.json()["id"]

    del_resp = client.delete(f"/orgs/{org['id']}/employees/{new_id}")
    assert del_resp.status_code == 204

    remaining = client.get(f"/orgs/{org['id']}/employees").json()
    assert new_id not in [e["id"] for e in remaining]
