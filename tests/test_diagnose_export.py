"""Tests for the notes-augmented diagnosis explanation and PDF export.

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


def _forced_quit_request(dept_id: int) -> dict:
    """A reorg shock big enough to force real quits in the diagnosed
    segment within a fairly short horizon, so notes_summary should be
    non-trivial (though quits are stochastic — see the docstring on
    test_diagnose_notes_summary_shape_is_always_valid for the graceful path).
    """
    return {
        "ticks": 20, "replicates": 1, "seed": 11,
        "events": [{"type": "reorg", "at_tick": 1,
                    "params": {"department_id": dept_id, "delta": 0.45}}],
    }


def _make_org_and_first_dept(client) -> tuple[dict, int]:
    org = client.post("/orgs", json={"name": "Acme", "headcount": 300, "seed": 11}).json()
    depts = client.get(f"/orgs/{org['id']}/departments").json()
    return org, depts[0]["id"]


def test_diagnose_notes_summary_shape_is_always_valid(client):
    org, dept_id = _make_org_and_first_dept(client)
    resp = client.post(f"/orgs/{org['id']}/diagnose", json=_forced_quit_request(dept_id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["problems_detected"] >= 1

    for report in body["reports"]:
        notes_summary = report.get("notes_summary")
        if notes_summary is None:
            # Honest "no exits in this segment during this run" path.
            assert "structural risk factors" in report["explanation"].lower()
        else:
            assert notes_summary["n_notes"] > 0
            assert -1.0 <= notes_summary["mean_sentiment"] <= 1.0
            assert str(notes_summary["n_notes"]) in report["explanation"]


def test_diagnose_with_no_problems_has_no_notes_summary(client):
    org = client.post("/orgs", json={"name": "Quiet Co", "headcount": 30, "seed": 99}).json()
    resp = client.post(f"/orgs/{org['id']}/diagnose", json={"ticks": 3, "replicates": 1, "seed": 99})
    assert resp.status_code == 200
    body = resp.json()
    for report in body["reports"]:
        assert report.get("notes_summary") is None


def test_diagnose_export_returns_pdf(client):
    org, dept_id = _make_org_and_first_dept(client)
    resp = client.post(f"/orgs/{org['id']}/diagnose/export", json=_forced_quit_request(dept_id))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content[:4] == b"%PDF"
    assert len(resp.content) > 500


def test_diagnose_export_with_no_problems_still_returns_valid_pdf(client):
    org = client.post("/orgs", json={"name": "Quiet Co", "headcount": 30, "seed": 99}).json()
    resp = client.post(f"/orgs/{org['id']}/diagnose/export", json={"ticks": 3, "replicates": 1, "seed": 99})
    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


def test_diagnose_export_same_seed_is_deterministic(client):
    # Byte-identical except for the embedded generation timestamp (fixed
    # width, "%H:%M"), so same-length is the robust invariant here rather
    # than full equality, which would flake across a minute boundary.
    org, dept_id = _make_org_and_first_dept(client)
    req = _forced_quit_request(dept_id)
    resp1 = client.post(f"/orgs/{org['id']}/diagnose/export", json=req)
    resp2 = client.post(f"/orgs/{org['id']}/diagnose/export", json=req)
    assert len(resp1.content) == len(resp2.content)
