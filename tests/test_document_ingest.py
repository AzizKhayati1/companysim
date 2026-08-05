"""Tests for the document-ingestion pipeline (Phases 1–2):

- Upload stores a ``SourceDocumentRecord``; re-uploading identical bytes
  to the same org is a 409, not a silent duplicate change set.
- Extracting a roster CSV stages exactly the differing values as pending
  facts (unchanged values propose nothing), plus a new-hire marker for a
  roster row with no matching employee.
- Apply is opt-in per fact: approved ids land on ``EmployeeRecord``,
  everything else is rejected, and a new-hire fact is refused with a
  message rather than creating an employee.
- A resignation letter (no parser yet) extracts nothing and is honestly
  parked as ``needs_review``.
- ``reconcile_roster`` is exercised directly with plain dicts — no DB —
  proving the diff logic is genuinely DB-agnostic.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.db_models import ExtractedFactRecord, SourceDocumentRecord
from companysim.api.main import app
from companysim.ingest import llm_parser
from companysim.ingest.reconcile import NEW_HIRE_FIELD, reconcile_roster
from companysim.ingest.rules_parser import parse_roster_csv
from companysim.ingest.schemas import RosterRow


@pytest.fixture(autouse=True)
def _clear_ingest_llm_flag(monkeypatch):
    """These tests assert the deterministic path only — a developer with
    the ingest LLM configured in their shell must not silently exercise a
    different code path here."""
    monkeypatch.delenv(llm_parser._FLAG_VAR, raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # Pin the provider: these fixtures stub the Groq SDK, so a machine with
    # COMPANYSIM_LLM_PROVIDER=bedrock exported would otherwise route them
    # down the Bedrock branch and fail for a reason unrelated to the test.
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "groq")


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


def _upload(client, org_id: int, filename: str, content: bytes, kind: str):
    return client.post(
        f"/orgs/{org_id}/documents",
        files={"file": (filename, content, "text/plain")},
        data={"kind": kind},
    )


def _roster_csv_for(employees: list[dict], overrides: dict[str, dict] | None = None) -> bytes:
    """A roster CSV covering ``employees``, with per-email field overrides —
    deliberately messy headers to exercise the tolerant matcher."""
    overrides = overrides or {}
    lines = ["Email,Full Name,Level,Job Title,Base Salary,Tenure Months"]
    for e in employees:
        row = {
            "email": e["email"], "full_name": e["full_name"], "level": e["level"],
            "role": e["role"], "base_salary": e["base_salary"],
            "tenure_months": e["tenure_months"],
        }
        row.update(overrides.get(e["email"], {}))
        lines.append(
            f"{row['email']},{row['full_name']},{row['level']},{row['role']},"
            f"{row['base_salary']},{row['tenure_months']}"
        )
    return "\n".join(lines).encode()


# ---- Phase 1: upload/list/detail/delete --------------------------------


def test_upload_stores_document_and_duplicate_is_409(client, db_session_factory):
    org = _make_org(client)
    resp = _upload(client, org["id"], "roster.csv", b"email\na@x.com\n", "roster")
    assert resp.status_code == 201
    body = resp.json()
    assert body["extraction_status"] == "pending"
    assert body["kind"] == "roster"

    db = db_session_factory()
    row = db.query(SourceDocumentRecord).filter_by(org_id=org["id"]).one()
    assert row.raw_text == "email\na@x.com\n"

    dup = _upload(client, org["id"], "roster-again.csv", b"email\na@x.com\n", "roster")
    assert dup.status_code == 409

    # Same bytes into a *different* org is fine — dedup is per-org.
    other = _make_org(client, headcount=10)
    assert _upload(client, other["id"], "roster.csv", b"email\na@x.com\n", "roster").status_code == 201


def test_upload_rejects_unknown_kind_and_unsupported_type(client):
    org = _make_org(client)
    assert _upload(client, org["id"], "roster.csv", b"email\n", "payroll").status_code == 400
    assert _upload(client, org["id"], "roster.xlsx", b"PK\x03\x04", "roster").status_code == 400


def test_document_list_detail_delete_roundtrip(client):
    org = _make_org(client)
    doc = _upload(client, org["id"], "notes.txt", b"hello", "resignation_letter").json()

    listed = client.get(f"/orgs/{org['id']}/documents").json()
    assert [d["id"] for d in listed] == [doc["id"]]

    detail = client.get(f"/orgs/{org['id']}/documents/{doc['id']}").json()
    assert detail["raw_text"] == "hello"
    assert detail["pending_facts"] == []

    assert client.delete(f"/orgs/{org['id']}/documents/{doc['id']}").status_code == 204
    assert client.get(f"/orgs/{org['id']}/documents/{doc['id']}").status_code == 404


# ---- Phase 2: extract --------------------------------------------------


def test_roster_extract_stages_expected_facts(client):
    org = _make_org(client)
    emps = client.get(f"/orgs/{org['id']}/employees").json()
    target, unchanged = emps[0], emps[1]
    csv_bytes = _roster_csv_for(
        [target, unchanged],
        overrides={target["email"]: {"base_salary": 123456.0, "level": "M2"}},
    )
    doc = _upload(client, org["id"], "roster.csv", csv_bytes, "roster").json()

    resp = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract")
    assert resp.status_code == 200
    body = resp.json()
    assert body["document"]["extraction_status"] == "extracted"
    assert body["document"]["extractor"] == "rules"

    staged = {(f["target_employee_id"], f["field_name"]): f for f in body["facts"]}
    assert set(staged) == {(target["id"], "base_salary"), (target["id"], "level")}
    salary_fact = staged[(target["id"], "base_salary")]
    assert float(salary_fact["proposed_value"]) == 123456.0
    assert float(salary_fact["current_value"]) == target["base_salary"]
    assert salary_fact["confidence"] == 1.0
    assert target["email"] in salary_fact["evidence_span"]


def test_unchanged_roster_stages_zero_facts(client):
    org = _make_org(client)
    emps = client.get(f"/orgs/{org['id']}/employees").json()
    doc = _upload(client, org["id"], "roster.csv", _roster_csv_for(emps[:3]), "roster").json()

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["n_facts_staged"] == 0
    assert body["document"]["extraction_status"] == "extracted"


def test_unknown_roster_email_stages_new_hire_marker(client):
    org = _make_org(client)
    csv_bytes = b"email,level\nnew.person@example.com,IC3\n"
    doc = _upload(client, org["id"], "roster.csv", csv_bytes, "roster").json()

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["n_facts_staged"] == 1
    fact = body["facts"][0]
    assert fact["field_name"] == NEW_HIRE_FIELD
    assert fact["target_employee_id"] is None


def test_resignation_letter_extracts_nothing_and_needs_review(client, db_session_factory):
    """With the ingest LLM off (the default, and CI), a free-text document
    stages nothing and says why. The *reason* moved from "no parser" to
    "not configured" once ``ingest/llm_parser.py`` landed; the invariant
    that matters — zero fabricated facts — is unchanged. See
    tests/test_llm_ingest.py for the enabled path."""
    org = _make_org(client)
    doc = _upload(
        client, org["id"], "letter.txt",
        b"I am resigning effective two weeks from today.", "resignation_letter",
    ).json()

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["n_facts_staged"] == 0
    assert body["document"]["extraction_status"] == "needs_review"
    assert body["document"]["extraction_error"]

    db = db_session_factory()
    assert db.query(ExtractedFactRecord).filter_by(org_id=org["id"]).count() == 0


# ---- Phase 2: apply ----------------------------------------------------


def test_apply_subset_changes_only_approved_employees(client):
    org = _make_org(client)
    emps = client.get(f"/orgs/{org['id']}/employees").json()
    a, b = emps[0], emps[1]
    csv_bytes = _roster_csv_for(
        [a, b],
        overrides={
            a["email"]: {"base_salary": 111111.0},
            b["email"]: {"base_salary": 222222.0},
        },
    )
    doc = _upload(client, org["id"], "roster.csv", csv_bytes, "roster").json()
    facts = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()["facts"]
    fact_a = next(f for f in facts if f["target_employee_id"] == a["id"])

    resp = client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [fact_a["id"]]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_applied"] == 1
    assert body["n_rejected"] == 1
    assert body["unapplied"] == []

    emps_after = {e["id"]: e for e in client.get(f"/orgs/{org['id']}/employees").json()}
    assert emps_after[a["id"]]["base_salary"] == 111111.0
    assert emps_after[b["id"]]["base_salary"] == b["base_salary"]  # rejected — untouched

    # The reviewed facts are settled; nothing is left pending on the doc.
    detail = client.get(f"/orgs/{org['id']}/documents/{doc['id']}").json()
    assert detail["pending_facts"] == []


def test_apply_refuses_to_create_new_hires(client):
    org = _make_org(client)
    doc = _upload(
        client, org["id"], "roster.csv", b"email\nghost@example.com\n", "roster",
    ).json()
    fact = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()["facts"][0]

    body = client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [fact["id"]]},
    ).json()
    assert body["n_applied"] == 0
    assert len(body["unapplied"]) == 1
    assert "ghost@example.com" in body["unapplied"][0]

    # Headcount unchanged — nobody was created.
    assert len(client.get(f"/orgs/{org['id']}/employees").json()) == 20


# ---- Pure-function tests (no DB) ---------------------------------------


def test_reconcile_roster_emits_only_differences():
    rows = [
        RosterRow(email="jane@x.com", level="M1", base_salary=90000.0),
        RosterRow(email="omar@x.com", level="IC2", base_salary=80000.0),
    ]
    existing = [
        {"id": 1, "email": "JANE@x.com", "full_name": "Jane", "level": "IC3",
         "role": "Engineer", "tenure_months": 24, "base_salary": 90000.0,
         "promotions_count": 1},
        {"id": 2, "email": "omar@x.com", "full_name": "Omar", "level": "IC2",
         "role": "Engineer", "tenure_months": 12, "base_salary": 80000.0,
         "promotions_count": 0},
    ]
    changes = reconcile_roster(rows, existing)
    # Jane: level differs (case-insensitive email match); salary equal.
    # Omar: nothing differs. Fields absent from the rows propose nothing.
    assert len(changes) == 1
    change = changes[0]
    assert (change.target_employee_id, change.field_name) == (1, "level")
    assert (change.proposed_value, change.current_value) == ("M1", "IC3")
    assert change.confidence == 1.0
    assert "jane@x.com" in change.evidence_span


def test_reconcile_roster_flags_unmatched_email_as_new_hire():
    changes = reconcile_roster(
        [RosterRow(email="new@x.com", level="IC1")],
        [{"id": 1, "email": "old@x.com", "full_name": "Old", "level": "IC1",
          "role": "Engineer", "tenure_months": 1, "base_salary": 1.0, "promotions_count": 0}],
    )
    assert len(changes) == 1
    assert changes[0].field_name == NEW_HIRE_FIELD
    assert changes[0].target_employee_id is None


def test_parse_roster_csv_tolerates_header_variants_and_noise():
    text = (
        "Work Email,EMPLOYEE NAME,job-title,Annual Salary,tenure\n"
        'a@x.com,Ada Lovelace,Engineer,"120,000",36\n'
        ",Missing Email,Engineer,50000,1\n"
    )
    rows = parse_roster_csv(text)
    assert len(rows) == 1  # the email-less row is skipped
    row = rows[0]
    assert row.email == "a@x.com"
    assert row.full_name == "Ada Lovelace"
    assert row.role == "Engineer"
    assert row.base_salary == 120000.0
    assert row.tenure_months == 36


def test_parse_roster_csv_without_email_column_raises():
    with pytest.raises(ValueError, match="email"):
        parse_roster_csv("name,salary\nJane,90000\n")
