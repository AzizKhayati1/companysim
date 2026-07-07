"""Tests for saved simulate/diagnose run history.

Same isolated in-memory DB fixture as ``test_api.py`` (StaticPool so all
sessions in a test share one connection).
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


def test_simulate_run_is_saved_to_history(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 1}).json()
    sim_resp = client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 5, "replicates": 1, "seed": 1})
    assert sim_resp.status_code == 200

    runs = client.get(f"/orgs/{org['id']}/runs").json()
    assert len(runs) == 1
    assert runs[0]["run_type"] == "simulate"
    assert "5 ticks" in runs[0]["summary"]


def test_diagnose_run_is_saved_and_filterable(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 2}).json()
    client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 3, "replicates": 1, "seed": 2})
    diag_resp = client.post(f"/orgs/{org['id']}/diagnose", json={"ticks": 3, "replicates": 1, "seed": 2})
    assert diag_resp.status_code == 200
    problems_detected = diag_resp.json()["problems_detected"]

    all_runs = client.get(f"/orgs/{org['id']}/runs").json()
    assert len(all_runs) == 2

    diagnose_runs = client.get(f"/orgs/{org['id']}/runs", params={"run_type": "diagnose"}).json()
    assert len(diagnose_runs) == 1
    assert f"{problems_detected} problem(s)" in diagnose_runs[0]["summary"]


def test_get_run_detail_matches_original_response(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 3}).json()
    sim_resp = client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 4, "replicates": 1, "seed": 3}).json()

    run_id = client.get(f"/orgs/{org['id']}/runs").json()[0]["id"]
    detail = client.get(f"/orgs/{org['id']}/runs/{run_id}").json()

    assert detail["run_type"] == "simulate"
    assert detail["request"]["ticks"] == 4
    assert detail["response"] == sim_resp


def test_get_missing_run_returns_404(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 4}).json()
    resp = client.get(f"/orgs/{org['id']}/runs/999")
    assert resp.status_code == 404


def test_delete_run_removes_it(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 5}).json()
    client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 3, "replicates": 1, "seed": 5})
    run_id = client.get(f"/orgs/{org['id']}/runs").json()[0]["id"]

    del_resp = client.delete(f"/orgs/{org['id']}/runs/{run_id}")
    assert del_resp.status_code == 204

    assert client.get(f"/orgs/{org['id']}/runs/{run_id}").status_code == 404
    assert client.get(f"/orgs/{org['id']}/runs").json() == []


def test_deleting_org_cascades_to_run_history(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 6}).json()
    client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 3, "replicates": 1, "seed": 6})
    assert len(client.get(f"/orgs/{org['id']}/runs").json()) == 1

    del_resp = client.delete(f"/orgs/{org['id']}")
    assert del_resp.status_code == 204

    # The org is gone, so the runs endpoint under it returns an empty list
    # rather than 404 (org existence isn't checked by the runs router) —
    # confirm the underlying rows were actually removed, not orphaned.
    assert client.get(f"/orgs/{org['id']}/runs").json() == []
