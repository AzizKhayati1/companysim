"""End-to-end tests for what document ingestion actually changes downstream.

The point of Phases 3-4 isn't "documents can be uploaded" — it's that
ingesting them moves real numbers in the ML pipeline. These tests assert
that chain:

- ingested performance reviews turn ``scoring_frame``'s ``rating_*``
  placeholders into real per-employee values, and an org with no reviews
  is byte-for-byte unchanged (ingestion is purely additive)
- collected training examples now *store* those ratings instead of
  reconstructing a constant
- ``ml.gate`` records an example-provenance breakdown, so an AUC move can
  be attributed rather than merely observed
- roster reconciliation covers department/team by name, and apply
  resolves the name or refuses with a reason
- apply can create a new hire, and still refuses when the roster names a
  department the org doesn't have
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.db_models import EmployeeRecord, SourceDocumentRecord
from companysim.api.ingest_records import record_performance_review
from companysim.api.main import app
from companysim.api.scoring_frame import NEUTRAL_RATING, build_scoring_frame, rating_features
from companysim.api.training_examples import load_collected_examples
from companysim.ingest.reconcile import NEW_HIRE_FIELD, reconcile_roster
from companysim.ingest.schemas import RosterRow
from companysim.ml.turnover_features import FEATURE_COLUMNS


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


def _make_org(client, headcount: int = 20) -> dict:
    return client.post("/orgs", json={"name": "Acme", "headcount": headcount, "seed": 7}).json()


def _a_document(db, org_id: int) -> SourceDocumentRecord:
    doc = SourceDocumentRecord(
        org_id=org_id, kind="performance_review", filename="r.txt",
        content_hash="hash", raw_text="text", extraction_status="extracted",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


# ---- ratings: placeholder -> real signal -------------------------------


def test_org_without_reviews_keeps_neutral_rating_placeholders(client, db_session_factory):
    org = _make_org(client)
    db = db_session_factory()
    frame = build_scoring_frame(db, org["id"])
    assert (frame["rating_last"] == NEUTRAL_RATING).all()
    assert (frame["rating_prev"] == NEUTRAL_RATING).all()
    assert (frame["rating_delta"] == 0.0).all()


def test_ingested_reviews_become_real_rating_features(client, db_session_factory):
    org = _make_org(client)
    db = db_session_factory()
    employees = db.query(EmployeeRecord).filter_by(org_id=org["id"]).all()
    target, untouched = employees[0], employees[1]
    doc = _a_document(db, org["id"])

    record_performance_review(
        db, doc, employee_id=target.id, review_period_end=date(2025, 6, 30),
        rating=2.0, summary_text="older",
    )
    record_performance_review(
        db, doc, employee_id=target.id, review_period_end=date(2025, 12, 31),
        rating=4.5, summary_text="newer",
    )

    frame = build_scoring_frame(db, org["id"]).set_index("employee_id")
    assert frame.loc[target.id, "rating_last"] == 4.5   # most recent period end
    assert frame.loc[target.id, "rating_prev"] == 2.0
    assert frame.loc[target.id, "rating_delta"] == pytest.approx(2.5)
    # Everyone else is untouched — ingestion is additive, not global.
    assert frame.loc[untouched.id, "rating_last"] == NEUTRAL_RATING
    assert frame.loc[untouched.id, "rating_delta"] == 0.0


def test_single_review_sets_prev_equal_to_last(client, db_session_factory):
    """Matches ml.turnover_features._performance_features' offline choice,
    so 'one review' means the same thing in both pipelines."""
    org = _make_org(client)
    db = db_session_factory()
    emp = db.query(EmployeeRecord).filter_by(org_id=org["id"]).first()
    doc = _a_document(db, org["id"])
    record_performance_review(
        db, doc, employee_id=emp.id, review_period_end=date(2025, 12, 31),
        rating=5.0, summary_text="",
    )
    assert rating_features(db, org["id"])[emp.id] == (5.0, 5.0, 0.0)


def test_reviews_ordered_by_period_end_not_upload_order(client, db_session_factory):
    org = _make_org(client)
    db = db_session_factory()
    emp = db.query(EmployeeRecord).filter_by(org_id=org["id"]).first()
    doc = _a_document(db, org["id"])
    # Insert the NEWER period first, so row order and date order disagree.
    record_performance_review(
        db, doc, employee_id=emp.id, review_period_end=date(2025, 12, 31),
        rating=4.0, summary_text="",
    )
    record_performance_review(
        db, doc, employee_id=emp.id, review_period_end=date(2025, 3, 31),
        rating=1.0, summary_text="",
    )
    last, prev, delta = rating_features(db, org["id"])[emp.id]
    assert (last, prev) == (4.0, 1.0)
    assert delta == pytest.approx(3.0)


def test_collected_examples_store_real_ratings(client, db_session_factory):
    """rating_* used to be reconstructed as a constant at read time; with
    reviews ingested it must survive from collection to training frame."""
    org = _make_org(client)
    db = db_session_factory()
    emp = db.query(EmployeeRecord).filter_by(org_id=org["id"]).first()
    doc = _a_document(db, org["id"])
    record_performance_review(
        db, doc, employee_id=emp.id, review_period_end=date(2025, 12, 31),
        rating=4.5, summary_text="",
    )

    resp = client.post(
        f"/orgs/{org['id']}/simulate", json={"ticks": 8, "replicates": 1, "seed": 3},
    )
    assert resp.status_code == 200

    frame = load_collected_examples(db_session_factory())
    assert not frame.empty
    assert list(frame.columns) == [*FEATURE_COLUMNS, "quit_within_horizon"]
    assert 4.5 in set(frame["rating_last"])            # the ingested value survived
    assert set(frame["rating_last"]) != {NEUTRAL_RATING}  # not flattened to a constant


# ---- provenance in the promotion log -----------------------------------


def test_gate_records_example_provenance_breakdown(monkeypatch, tmp_path):
    """ml.gate must report WHICH source supplied examples, else an AUC move
    can't be attributed. Patched to avoid a real (slow) training run."""
    import companysim.ml.gate as gate

    monkeypatch.setattr(gate, "LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(gate, "PRODUCTION_PATH", tmp_path / "prod.joblib")
    monkeypatch.setattr(gate, "build_turnover_cohort", lambda *a, **k: _FakeCohort())
    monkeypatch.setattr(gate, "build_feature_frame", lambda tables: _fake_feature_frame())
    monkeypatch.setattr(gate, "train_turnover_model", lambda merged, seed: (_FakeBundle(), _FakeReport()))
    monkeypatch.setattr(gate, "evaluate_bundle_on_holdout", lambda bundle: {"auc": 0.7})
    monkeypatch.setattr(gate, "save_bundle", lambda bundle, path: None)

    counts = {"webapp_runs": 12, "documents": 5}
    result = gate.run_training_gate(extra_example_counts=counts)

    assert result.extra_example_counts == counts
    assert result.n_document_examples == 5

    entries = gate.load_promotion_log()
    assert entries[-1]["extra_example_counts"] == counts


def test_gate_without_counts_defaults_to_empty(monkeypatch, tmp_path):
    """The CLI path passes no breakdown; it must still work unchanged."""
    import companysim.ml.gate as gate

    monkeypatch.setattr(gate, "LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(gate, "PRODUCTION_PATH", tmp_path / "prod.joblib")
    monkeypatch.setattr(gate, "build_turnover_cohort", lambda *a, **k: _FakeCohort())
    monkeypatch.setattr(gate, "build_feature_frame", lambda tables: _fake_feature_frame())
    monkeypatch.setattr(gate, "train_turnover_model", lambda merged, seed: (_FakeBundle(), _FakeReport()))
    monkeypatch.setattr(gate, "evaluate_bundle_on_holdout", lambda bundle: {"auc": 0.7})
    monkeypatch.setattr(gate, "save_bundle", lambda bundle, path: None)

    result = gate.run_training_gate()
    assert result.extra_example_counts == {}
    assert result.n_document_examples == 0


class _FakeCohort:
    def __init__(self):
        import pandas as pd
        self.tables = {}
        self.labels = pd.DataFrame({"employee_id": [1, 2], "quit_within_horizon": [0, 1]})


def _fake_feature_frame():
    import pandas as pd
    return pd.DataFrame({"employee_id": [1, 2]})


class _FakeBundle:
    def __init__(self):
        self.metadata = {}


class _FakeReport:
    def as_dict(self):
        return {}


# ---- department / team reconciliation ----------------------------------


def test_reconcile_detects_department_and_team_by_name():
    changes = reconcile_roster(
        [RosterRow(email="a@x.com", department_name="Platform", team_name="Core")],
        [{"id": 1, "email": "a@x.com", "full_name": "A", "level": "IC2", "role": "Eng",
          "tenure_months": 10, "base_salary": 1.0, "promotions_count": 0,
          "department_id": 7, "team_id": 9}],
        department_names={7: "Sales"}, team_names={9: "Core"},
    )
    # Department differs (Sales -> Platform); team matches, so proposes nothing.
    assert [(c.field_name, c.proposed_value, c.current_value) for c in changes] == [
        ("department_name", "Platform", "Sales"),
    ]


def test_reconcile_skips_name_fields_when_maps_are_absent():
    changes = reconcile_roster(
        [RosterRow(email="a@x.com", department_name="Platform")],
        [{"id": 1, "email": "a@x.com", "full_name": "A", "level": "IC2", "role": "Eng",
          "tenure_months": 10, "base_salary": 1.0, "promotions_count": 0,
          "department_id": 7, "team_id": 9}],
    )
    assert changes == []


def test_apply_resolves_department_name_to_fk(client, db_session_factory):
    org = _make_org(client)
    emps = client.get(f"/orgs/{org['id']}/employees").json()
    depts = client.get(f"/orgs/{org['id']}/departments").json()
    target = emps[0]
    other_dept = next(d for d in depts if d["id"] != target["department_id"])

    csv_bytes = f"email,department\n{target['email']},{other_dept['name']}\n".encode()
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("roster.csv", csv_bytes, "text/csv")},
        data={"kind": "roster"},
    ).json()
    facts = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()["facts"]
    dept_fact = next(f for f in facts if f["field_name"] == "department_name")
    assert dept_fact["proposed_value"] == other_dept["name"]

    body = client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [dept_fact["id"]]},
    ).json()
    assert body["n_applied"] == 1

    db = db_session_factory()
    assert db.get(EmployeeRecord, target["id"]).department_id == other_dept["id"]


def test_apply_refuses_unknown_department_name(client):
    org = _make_org(client)
    target = client.get(f"/orgs/{org['id']}/employees").json()[0]
    csv_bytes = f"email,department\n{target['email']},Ministry of Silly Walks\n".encode()
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("roster.csv", csv_bytes, "text/csv")},
        data={"kind": "roster"},
    ).json()
    fact = next(
        f for f in client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()["facts"]
        if f["field_name"] == "department_name"
    )

    body = client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [fact["id"]]},
    ).json()
    assert body["n_applied"] == 0
    assert "Ministry of Silly Walks" in body["unapplied"][0]


# ---- new-hire creation -------------------------------------------------


def test_apply_creates_a_new_hire_from_a_roster_row(client, db_session_factory):
    org = _make_org(client)
    dept = client.get(f"/orgs/{org['id']}/departments").json()[0]
    before = len(client.get(f"/orgs/{org['id']}/employees").json())

    csv_bytes = (
        "email,full name,level,job title,department,base salary,tenure\n"
        f"new.hire@acme.test,New Hire,IC3,Engineer,{dept['name']},95000,4\n"
    ).encode()
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("roster.csv", csv_bytes, "text/csv")},
        data={"kind": "roster"},
    ).json()
    facts = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()["facts"]
    new_hire_fact = next(f for f in facts if f["field_name"] == NEW_HIRE_FIELD)

    body = client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [new_hire_fact["id"]]},
    ).json()
    assert body["n_applied"] == 1
    assert body["n_employees_created"] == 1

    after = client.get(f"/orgs/{org['id']}/employees").json()
    assert len(after) == before + 1
    created = next(e for e in after if e["email"] == "new.hire@acme.test")
    assert created["full_name"] == "New Hire"
    assert created["level"] == "IC3"
    assert created["base_salary"] == 95000.0
    assert created["department_id"] == dept["id"]

    # A wellbeing row must exist or every downstream frame silently drops
    # this employee (build_scoring_frame inner-joins on it).
    db = db_session_factory()
    frame = build_scoring_frame(db, org["id"])
    assert created["id"] in set(frame["employee_id"])


def test_apply_refuses_new_hire_with_unknown_department(client):
    org = _make_org(client)
    before = len(client.get(f"/orgs/{org['id']}/employees").json())
    csv_bytes = b"email,department\nghost@acme.test,Nonexistent Dept\n"
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("roster.csv", csv_bytes, "text/csv")},
        data={"kind": "roster"},
    ).json()
    fact = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()["facts"][0]

    body = client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [fact["id"]]},
    ).json()
    assert body["n_employees_created"] == 0
    assert "Nonexistent Dept" in body["unapplied"][0]
    assert len(client.get(f"/orgs/{org['id']}/employees").json()) == before


def test_apply_refuses_new_hire_with_no_department_named(client):
    org = _make_org(client)
    csv_bytes = b"email\nghost@acme.test\n"
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("roster.csv", csv_bytes, "text/csv")},
        data={"kind": "roster"},
    ).json()
    fact = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()["facts"][0]

    body = client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [fact["id"]]},
    ).json()
    assert body["n_employees_created"] == 0
    assert "names no department" in body["unapplied"][0]


# ---- cohort endpoint ---------------------------------------------------


def test_cohort_endpoint_reports_unusable_without_a_roster(client):
    org = _make_org(client)
    body = client.get(f"/orgs/{org['id']}/documents/cohort").json()
    assert body["usable"] is False
    assert "denominator" in body["reason"]


def test_full_cohort_path_produces_labeled_examples(client, db_session_factory):
    """The whole Phase-4 chain: an extracted roster establishes the
    denominator, a resignation letter supplies one positive, and everyone
    else on the roster becomes a labeled negative."""
    org = _make_org(client, headcount=20)
    emps = client.get(f"/orgs/{org['id']}/employees").json()
    leaver = emps[0]

    roster_csv = "email\n" + "\n".join(e["email"] for e in emps) + "\n"
    roster = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("roster.csv", roster_csv.encode(), "text/csv")},
        data={"kind": "roster", "as_of_date": "2026-01-01"},
    ).json()
    client.post(f"/orgs/{org['id']}/documents/{roster['id']}/extract")

    # Stand in for the LLM extract step: the letter's own effective date on
    # the document, and its text as an ExitNoteRecord.
    from companysim.api.ingest_records import record_ingested_exit_note

    db = db_session_factory()
    letter = SourceDocumentRecord(
        org_id=org["id"], kind="resignation_letter", filename="letter.txt",
        content_hash="letter-hash", raw_text="I am leaving.",
        as_of_date=date(2026, 2, 15), extraction_status="extracted",
    )
    db.add(letter)
    db.commit()
    db.refresh(letter)
    record_ingested_exit_note(
        db, letter, employee_id=leaver["id"],
        text="The workload was unsustainable and I was completely burned out.",
    )

    body = client.get(f"/orgs/{org['id']}/documents/cohort").json()
    assert body["usable"] is True
    assert body["window_start"] == "2026-01-01"
    assert body["n_positives"] == 1
    assert body["n_negatives"] == 19
    assert body["base_rate"] == pytest.approx(1 / 20)

    # And it reaches the model surface as pending training data.
    status = client.get("/model/status").json()
    assert status["pending_document_examples"] == 20


def test_lineage_is_empty_for_an_unextracted_document(client):
    """The honest empty state: a document that wrote nothing reports no
    targets, rather than re-deriving something plausible from its text."""
    org = _make_org(client)
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("letter.txt", b"I am resigning.", "text/plain")},
        data={"kind": "resignation_letter"},
    ).json()

    body = client.get(f"/orgs/{org['id']}/documents/{doc['id']}/lineage").json()
    assert body["targets"] == []
    assert body["downstream"] == []


def test_roster_lineage_tracks_pending_then_applied(client):
    org = _make_org(client)
    target = client.get(f"/orgs/{org['id']}/employees").json()[0]
    csv_bytes = f"email,level\n{target['email']},M3\n".encode()
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("roster.csv", csv_bytes, "text/csv")},
        data={"kind": "roster", "as_of_date": "2026-01-01"},
    ).json()
    fact = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()["facts"][0]

    before = client.get(f"/orgs/{org['id']}/documents/{doc['id']}/lineage").json()
    emp_target = next(t for t in before["targets"] if t["table"] == "employees")
    assert emp_target["state"] == "pending"
    assert emp_target["employee_name"] == target["full_name"]
    assert [f["column"] for f in emp_target["fields"]] == ["level"]
    assert emp_target["fields"][0]["value"] == "M3"
    # The roster's as-of date is itself a tracked destination.
    assert any(t["table"] == "source_documents" for t in before["targets"])

    client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [fact["id"]]},
    )
    after = client.get(f"/orgs/{org['id']}/documents/{doc['id']}/lineage").json()
    assert next(t for t in after["targets"] if t["table"] == "employees")["state"] == "applied"


def test_lineage_omits_rejected_facts(client):
    """A rejected proposal wrote nothing, so it is not provenance."""
    org = _make_org(client)
    target = client.get(f"/orgs/{org['id']}/employees").json()[0]
    csv_bytes = f"email,level\n{target['email']},M3\n".encode()
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("roster.csv", csv_bytes, "text/csv")},
        data={"kind": "roster"},
    ).json()
    client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract")

    # Approve nothing — every staged fact is rejected.
    client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": []},
    )
    body = client.get(f"/orgs/{org['id']}/documents/{doc['id']}/lineage").json()
    assert [t for t in body["targets"] if t["table"] == "employees"] == []


def test_review_lineage_names_the_rating_features_it_feeds(client, db_session_factory):
    org = _make_org(client)
    db = db_session_factory()
    emp = db.query(EmployeeRecord).filter_by(org_id=org["id"]).first()
    doc = _a_document(db, org["id"])
    record_performance_review(
        db, doc, employee_id=emp.id, review_period_end=date(2025, 12, 31),
        rating=4.5, summary_text="Strong quarter.",
    )

    body = client.get(f"/orgs/{org['id']}/documents/{doc.id}/lineage").json()
    target = next(t for t in body["targets"] if t["table"] == "performance_reviews")
    assert target["state"] == "written"
    assert target["employee_id"] == emp.id
    rating_field = next(f for f in target["fields"] if f["column"] == "rating")
    assert rating_field["value"] == "4.5"
    assert "rating_last" in rating_field["note"]
    assert any("placeholder" in d for d in body["downstream"])


def test_deleting_a_document_cascades_its_reviews_and_notes(client, db_session_factory):
    """Regression: deleting a resignation letter used to orphan its exit
    note — the note stayed visible in Insights while resignations_for_org
    (which joins through source_documents) silently dropped its label, so
    the same exit both existed and didn't. Found by deleting an uploaded
    letter and finding a note pointing at a document id that was gone.

    Changes already applied to EmployeeRecord are deliberately NOT
    cascaded — those are the org's own data once approved.
    """
    from companysim.api.db_models import ExitNoteRecord, PerformanceReviewRecord
    from companysim.api.ingest_records import record_ingested_exit_note

    org = _make_org(client)
    db = db_session_factory()
    emp = db.query(EmployeeRecord).filter_by(org_id=org["id"]).first()
    doc = _a_document(db, org["id"])
    record_performance_review(
        db, doc, employee_id=emp.id, review_period_end=date(2025, 12, 31),
        rating=4.0, summary_text="",
    )
    record_ingested_exit_note(db, doc, employee_id=emp.id, text="I was burned out.")
    assert db.query(PerformanceReviewRecord).filter_by(document_id=doc.id).count() == 1
    assert db.query(ExitNoteRecord).filter_by(source_document_id=doc.id).count() == 1

    assert client.delete(f"/orgs/{org['id']}/documents/{doc.id}").status_code == 204

    db2 = db_session_factory()
    assert db2.query(PerformanceReviewRecord).filter_by(document_id=doc.id).count() == 0
    assert db2.query(ExitNoteRecord).filter_by(source_document_id=doc.id).count() == 0
    # No orphan left behind pointing at a document that no longer exists.
    assert db2.query(ExitNoteRecord).filter(
        ExitNoteRecord.source_document_id.isnot(None),
    ).count() == 0


def test_ingest_totals_endpoint_counts_reviews_and_notes(client, db_session_factory):
    org = _make_org(client)
    db = db_session_factory()
    emp = db.query(EmployeeRecord).filter_by(org_id=org["id"]).first()
    doc = _a_document(db, org["id"])
    record_performance_review(
        db, doc, employee_id=emp.id, review_period_end=date(2025, 12, 31),
        rating=4.0, summary_text="",
    )

    body = client.get(f"/orgs/{org['id']}/documents/totals").json()
    assert body["n_performance_reviews"] == 1
    assert body["n_ingested_exit_notes"] == 0
