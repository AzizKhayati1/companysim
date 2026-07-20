"""Tests for the per-employee risk-history snapshot feature:

- Every Simulate run (single *and* Monte Carlo) and every Diagnose run
  records one ``EmployeeRiskSnapshot`` row per employee — unlike
  ``TurnoverTrainingExample``, there's no minimum-horizon gate and Monte
  Carlo runs are not excluded, since a snapshot only reflects current org
  state, not a simulated outcome.
- ``GET /orgs/{id}/employees/{id}/risk-history`` returns points ordered
  oldest-first.
- Deleting an org cascades and removes its snapshots.
- ``score_current_employees`` still produces plausible tiers with no
  production model on disk (the ``/at-risk`` fallback path).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.db_models import EmployeeRiskSnapshot
from companysim.api.main import app


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def client(db_session_factory):
    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_simulate_single_creates_one_snapshot_per_employee(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 25, "seed": 1}).json()
    resp = client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 4, "replicates": 1, "seed": 1})
    assert resp.status_code == 200

    db = db_session_factory()
    rows = db.query(EmployeeRiskSnapshot).filter_by(org_id=org["id"]).all()
    assert len(rows) == 25
    assert all(0.0 <= r.turnover_probability <= 1.0 for r in rows)
    assert all(r.risk_tier in ("low", "medium", "high") for r in rows)


def test_monte_carlo_simulate_also_creates_snapshots(client, db_session_factory):
    """Differs from TurnoverTrainingExample, which skips Monte Carlo runs —
    a risk snapshot only depends on current org state, not the run's own
    simulated outcome, so it's valid for every run mode."""
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 2}).json()
    resp = client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 8, "replicates": 5, "seed": 2})
    assert resp.status_code == 200

    db = db_session_factory()
    rows = db.query(EmployeeRiskSnapshot).filter_by(org_id=org["id"]).all()
    assert len(rows) == 20


def test_short_ticks_still_creates_snapshots(client, db_session_factory):
    """No minimum-horizon gate — unlike training examples, a 1-tick run
    still snapshots current risk."""
    org = client.post("/orgs", json={"name": "Acme", "headcount": 15, "seed": 3}).json()
    resp = client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 1, "replicates": 1, "seed": 3})
    assert resp.status_code == 200

    db = db_session_factory()
    rows = db.query(EmployeeRiskSnapshot).filter_by(org_id=org["id"]).all()
    assert len(rows) == 15


def test_diagnose_also_creates_snapshots(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 30, "seed": 4}).json()
    resp = client.post(f"/orgs/{org['id']}/diagnose", json={"ticks": 8, "replicates": 1, "seed": 4})
    assert resp.status_code == 200

    db = db_session_factory()
    rows = db.query(EmployeeRiskSnapshot).filter_by(org_id=org["id"]).all()
    assert len(rows) == 30


def test_risk_history_endpoint_returns_ordered_points(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 10, "seed": 5}).json()
    emp_id = client.get(f"/orgs/{org['id']}/employees").json()[0]["id"]

    for seed in (10, 11, 12):
        resp = client.post(
            f"/orgs/{org['id']}/simulate", json={"ticks": 3, "replicates": 1, "seed": seed},
        )
        assert resp.status_code == 200

    history = client.get(f"/orgs/{org['id']}/employees/{emp_id}/risk-history").json()
    assert len(history) == 3
    timestamps = [point["computed_at"] for point in history]
    assert timestamps == sorted(timestamps)
    assert all("turnover_probability" in point and "risk_tier" in point for point in history)


def test_risk_history_for_missing_employee_is_404(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 5, "seed": 6}).json()
    resp = client.get(f"/orgs/{org['id']}/employees/999999/risk-history")
    assert resp.status_code == 404


def test_risk_drivers_endpoint_returns_score_descending_list(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 60, "seed": 22}).json()
    emp_id = client.get(f"/orgs/{org['id']}/employees").json()[0]["id"]

    resp = client.get(f"/orgs/{org['id']}/employees/{emp_id}/risk-drivers")
    assert resp.status_code == 200
    drivers = resp.json()
    assert isinstance(drivers, list)
    scores = [d["score"] for d in drivers]
    assert scores == sorted(scores, reverse=True)
    for d in drivers:
        assert d["segment_type"] == "employee"
        assert d["segment_id"] == str(emp_id)
        assert d["score"] > 0


def test_risk_drivers_for_missing_employee_is_404(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 5, "seed": 23}).json()
    resp = client.get(f"/orgs/{org['id']}/employees/999999/risk-drivers")
    assert resp.status_code == 404


def test_risk_trend_endpoint_returns_one_point_per_run(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 8, "seed": 20}).json()

    for seed in (30, 31, 32):
        resp = client.post(
            f"/orgs/{org['id']}/simulate", json={"ticks": 3, "replicates": 1, "seed": seed},
        )
        assert resp.status_code == 200

    trend = client.get(f"/orgs/{org['id']}/at-risk/trend").json()
    assert len(trend) == 3
    timestamps = [point["computed_at"] for point in trend]
    assert timestamps == sorted(timestamps)
    for point in trend:
        assert point["employee_count"] == 8
        assert 0.0 <= point["mean_risk"] <= 1.0


def test_risk_trend_endpoint_empty_for_org_with_no_runs(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 5, "seed": 21}).json()
    trend = client.get(f"/orgs/{org['id']}/at-risk/trend").json()
    assert trend == []


def test_deleting_org_cascades_risk_snapshots(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 12, "seed": 7}).json()
    client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 3, "replicates": 1, "seed": 7})

    db = db_session_factory()
    assert db.query(EmployeeRiskSnapshot).filter_by(org_id=org["id"]).count() == 12

    del_resp = client.delete(f"/orgs/{org['id']}")
    assert del_resp.status_code == 204

    db2 = db_session_factory()
    assert db2.query(EmployeeRiskSnapshot).filter_by(org_id=org["id"]).count() == 0


def test_at_risk_endpoint_works_without_production_model(client):
    """No trained model on disk in the test environment by default (or if
    there is one, this just confirms the endpoint still responds sanely
    either way) — the fallback path in score_current_employees must still
    produce a valid, orderable response."""
    org = client.post("/orgs", json={"name": "Acme", "headcount": 15, "seed": 8}).json()
    resp = client.get(f"/orgs/{org['id']}/at-risk")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["employees"]) == 15
    probs = [e["turnover_probability"] for e in body["employees"]]
    assert probs == sorted(probs, reverse=True)
    assert all(e["risk_tier"] in ("low", "medium", "high") for e in body["employees"])
