"""Tests for the flag-gated LLM document-extraction path.

Follows ``tests/test_llm_exit_notes.py``'s fake-Groq-client pattern: the
flag and key are cleared for every test, and a stubbed ``groq.Groq``
returns whatever JSON a given test wants. Covers the contract that
matters most here — **a failed extraction stages nothing**:

- disabled by default; flag alone and key alone are both insufficient
- a valid response creates a PerformanceReviewRecord / ExitNoteRecord
- malformed JSON, a schema violation, an ``{"error": ...}`` refusal, and
  an unknown email each park the document as ``needs_review`` with zero
  rows written
- an involuntary exit (layoff/termination) is refused as a quit label,
  which is §5.6's organic-vs-injected distinction enforced at ingest
- the resignation schema physically cannot carry a feature field
"""
from __future__ import annotations

import json
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.db_models import ExitNoteRecord, PerformanceReviewRecord
from companysim.api.main import app
from companysim.ingest import llm_parser
from companysim.ingest.schemas import ResignationLetterExtract


def _fake_groq_client(content: str | None = None, error: Exception | None = None):
    def _client_factory(api_key):
        def create(**kwargs):
            if error is not None:
                raise error
            message = types.SimpleNamespace(content=content, tool_calls=None)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)),
        )
    return _client_factory


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


@pytest.fixture(autouse=True)
def _clear_ingest_llm_flag(monkeypatch):
    monkeypatch.delenv(llm_parser._FLAG_VAR, raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # Pin the provider: these fixtures stub the Groq SDK, so a machine with
    # COMPANYSIM_LLM_PROVIDER=bedrock exported would otherwise route them
    # down the Bedrock branch and fail for a reason unrelated to the test.
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "groq")


@pytest.fixture()
def enabled_llm(monkeypatch):
    """Flag + key set; each test still installs its own fake response."""
    pytest.importorskip("groq", reason="groq extra not installed")
    monkeypatch.setenv(llm_parser._FLAG_VAR, "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    return monkeypatch


def _make_org(client) -> tuple[dict, dict]:
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 7}).json()
    employee = client.get(f"/orgs/{org['id']}/employees").json()[0]
    return org, employee


def _upload(client, org_id: int, kind: str, text: str = "some document text"):
    return client.post(
        f"/orgs/{org_id}/documents",
        files={"file": (f"{kind}.txt", text.encode(), "text/plain")},
        data={"kind": kind},
    ).json()


# ---- enablement --------------------------------------------------------


def test_disabled_by_default(client):
    assert llm_parser.is_ingest_llm_enabled() is False


def test_flag_alone_is_not_enough(monkeypatch):
    monkeypatch.setenv(llm_parser._FLAG_VAR, "1")
    assert llm_parser.is_ingest_llm_enabled() is False


def test_key_alone_is_not_enough(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    assert llm_parser.is_ingest_llm_enabled() is False


def test_flag_and_key_together_enable_it(enabled_llm):
    assert llm_parser.is_ingest_llm_enabled() is True


def test_extract_without_flag_stages_nothing_and_needs_review(client, db_session_factory):
    org, _ = _make_org(client)
    doc = _upload(client, org["id"], "performance_review")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["n_facts_staged"] == 0
    assert body["document"]["extraction_status"] == "needs_review"
    assert "COMPANYSIM_LLM_INGEST" in body["document"]["extraction_error"]

    db = db_session_factory()
    assert db.query(PerformanceReviewRecord).count() == 0


# ---- performance reviews ----------------------------------------------


def test_valid_performance_review_is_recorded(client, enabled_llm, db_session_factory):
    org, employee = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "employee_email": employee["email"],
        "review_period_end": "2025-12-31",
        "rating": 4.5,
        "summary_text": "Consistently strong delivery.",
    })))
    doc = _upload(client, org["id"], "performance_review")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["document"]["extraction_status"] == "extracted"
    assert body["document"]["extractor"].startswith("groq:")
    # The review's own period end becomes the document's as-of date, which
    # is what the temporal-leakage guard reads.
    assert body["document"]["as_of_date"] == "2025-12-31"

    db = db_session_factory()
    review = db.query(PerformanceReviewRecord).one()
    assert review.employee_id == employee["id"]
    assert review.rating == 4.5


@pytest.mark.parametrize(
    ("label", "content"),
    [
        ("malformed json", "not json at all"),
        ("model refusal", json.dumps({"error": "no rating stated"})),
        ("rating out of range", json.dumps({
            "employee_email": "x@y.com", "review_period_end": "2025-12-31", "rating": 47.0,
        })),
        ("missing required field", json.dumps({"rating": 4.0})),
        ("json array not object", json.dumps([{"rating": 4.0}])),
    ],
)
def test_bad_review_response_stages_nothing(
    client, enabled_llm, db_session_factory, label, content,
):
    org, _ = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=content))
    doc = _upload(client, org["id"], "performance_review")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["document"]["extraction_status"] == "needs_review", label
    assert body["n_facts_staged"] == 0, label

    db = db_session_factory()
    assert db.query(PerformanceReviewRecord).count() == 0, label


def test_api_error_stages_nothing(client, enabled_llm, db_session_factory):
    org, _ = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(error=RuntimeError("network down")))
    doc = _upload(client, org["id"], "performance_review")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["document"]["extraction_status"] == "needs_review"
    db = db_session_factory()
    assert db.query(PerformanceReviewRecord).count() == 0


def test_unknown_email_is_refused_not_guessed(client, enabled_llm, db_session_factory):
    org, _ = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "employee_email": "nobody@elsewhere.com",
        "review_period_end": "2025-12-31", "rating": 4.0,
    })))
    doc = _upload(client, org["id"], "performance_review")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["document"]["extraction_status"] == "needs_review"
    assert "nobody@elsewhere.com" in body["document"]["extraction_error"]
    db = db_session_factory()
    assert db.query(PerformanceReviewRecord).count() == 0


# ---- resignation letters ----------------------------------------------


def test_valid_resignation_letter_creates_exit_note(client, enabled_llm, db_session_factory):
    org, employee = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "employee_email": employee["email"],
        "effective_date": "2026-03-15",
        "is_voluntary": True,
        "note_text": "The workload was unsustainable and I felt unsupported by my manager.",
    })))
    doc = _upload(client, org["id"], "resignation_letter")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["document"]["extraction_status"] == "extracted"
    assert body["document"]["as_of_date"] == "2026-03-15"

    db = db_session_factory()
    note = db.query(ExitNoteRecord).one()
    assert note.employee_id == employee["id"]
    assert note.source_document_id == doc["id"]
    assert note.is_llm_generated is False  # the LLM read it; it didn't write it
    assert note.is_backfilled is False
    # Sentiment/themes come from the same analyzer used on simulated notes.
    assert -1.0 <= note.sentiment <= 1.0
    assert "workload" in note.themes.split(",")


def test_involuntary_exit_is_not_ingested_as_a_quit(client, enabled_llm, db_session_factory):
    """§5.6's layoff-vs-quit distinction, enforced at the ingest boundary."""
    org, employee = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "employee_email": employee["email"],
        "effective_date": "2026-03-15",
        "is_voluntary": False,
        "note_text": "Your position has been eliminated.",
    })))
    doc = _upload(client, org["id"], "resignation_letter")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["document"]["extraction_status"] == "needs_review"
    assert "employer-initiated" in body["document"]["extraction_error"]

    db = db_session_factory()
    assert db.query(ExitNoteRecord).count() == 0


def test_resignation_schema_cannot_carry_a_feature_field():
    """The structural half of the temporal-leakage defense: even if a model
    returns wellbeing scores, there is nowhere for them to land."""
    extracted = ResignationLetterExtract.model_validate({
        "employee_email": "a@b.com",
        "effective_date": "2026-03-15",
        "note_text": "burned out",
        "workload_perceived": 0.95,
        "burnout_exhaustion": 0.9,
        "rating": 1.0,
    })
    assert not hasattr(extracted, "workload_perceived")
    assert not hasattr(extracted, "burnout_exhaustion")
    assert not hasattr(extracted, "rating")
    assert set(extracted.model_dump()) == {
        "employee_email", "effective_date", "is_voluntary", "note_text",
    }


def test_re_extracting_replaces_rather_than_duplicates(client, enabled_llm, db_session_factory):
    """Regression: the LLM paths write straight to their tables instead of
    staging reviewable facts, so without an explicit clear each Extract
    click appended a duplicate. Found by clicking Extract three times in
    the UI and getting three identical exit notes."""
    org, employee = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "employee_email": employee["email"],
        "effective_date": "2026-03-15", "is_voluntary": True,
        "note_text": "The workload was unsustainable.",
    })))
    doc = _upload(client, org["id"], "resignation_letter")

    for _ in range(3):
        client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract")

    db = db_session_factory()
    assert db.query(ExitNoteRecord).filter_by(source_document_id=doc["id"]).count() == 1


def test_re_extracting_a_review_does_not_flatten_rating_delta(
    client, enabled_llm, db_session_factory,
):
    """The same duplication bug is worse for reviews: a doubled review lands
    as both rating_last and rating_prev, so rating_delta collapses to 0.0
    and the model is told the rating never moved."""
    org, employee = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "employee_email": employee["email"],
        "review_period_end": "2025-12-31", "rating": 4.5, "summary_text": "",
    })))
    doc = _upload(client, org["id"], "performance_review")

    for _ in range(2):
        client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract")

    db = db_session_factory()
    assert db.query(PerformanceReviewRecord).filter_by(document_id=doc["id"]).count() == 1
    from companysim.api.scoring_frame import rating_features
    last, prev, delta = rating_features(db, org["id"])[employee["id"]]
    assert (last, prev, delta) == (4.5, 4.5, 0.0)  # one review, not two


# ---- hiring documents (offer letters + CVs) ----------------------------


def test_offer_letter_stages_a_new_hire_that_apply_creates(
    client, enabled_llm, db_session_factory,
):
    """A hiring document reuses the roster new-hire path end to end, so
    approving one creates the employee and its wellbeing row."""
    org, _ = _make_org(client)
    dept = client.get(f"/orgs/{org['id']}/departments").json()[0]
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "candidate_email": "nadia.osei@example.test", "candidate_name": "Nadia Osei",
        "department_name": dept["name"], "level": "IC3", "role": "Backend Engineer",
        "team_name": None, "base_salary": 128000, "start_date": "2026-03-02",
    })))
    doc = _upload(client, org["id"], "offer_letter")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["n_facts_staged"] == 1
    fact = body["facts"][0]
    assert fact["field_name"] == "new_hire"
    assert fact["target_employee_id"] is None
    # Prose read by a model, not a CSV cell — confidence must say so.
    assert fact["confidence"] < 1.0
    assert body["document"]["as_of_date"] == "2026-03-02"

    before = len(client.get(f"/orgs/{org['id']}/employees").json())
    applied = client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [fact["id"]]},
    ).json()
    assert applied["n_employees_created"] == 1

    after = client.get(f"/orgs/{org['id']}/employees").json()
    assert len(after) == before + 1
    hire = next(e for e in after if e["email"] == "nadia.osei@example.test")
    assert (hire["level"], hire["base_salary"]) == ("IC3", 128000.0)
    assert hire["department_id"] == dept["id"]

    # Wellbeing row must exist or build_scoring_frame silently drops them.
    from companysim.api.scoring_frame import build_scoring_frame
    assert hire["id"] in set(build_scoring_frame(db_session_factory(), org["id"])["employee_id"])


def test_offer_letter_for_an_existing_employee_is_refused(
    client, enabled_llm, db_session_factory,
):
    """A hiring document describes someone new. Re-hiring an existing
    employee is a wrong-document error, not an update."""
    org, employee = _make_org(client)
    dept = client.get(f"/orgs/{org['id']}/departments").json()[0]
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "candidate_email": employee["email"], "candidate_name": employee["full_name"],
        "department_name": dept["name"], "level": "IC3", "role": "Engineer",
        "team_name": None, "base_salary": 100000, "start_date": "2026-06-01",
    })))
    doc = _upload(client, org["id"], "offer_letter")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["n_facts_staged"] == 0
    assert body["document"]["extraction_status"] == "needs_review"
    assert "already an employee" in body["document"]["extraction_error"]


def test_offer_letter_without_a_department_is_refused(client, enabled_llm):
    """department_name is required in the schema, so a letter that doesn't
    place the hire is refused at extraction rather than staged and then
    rejected at apply."""
    org, _ = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(
        content=json.dumps({"error": "no department stated"})))
    doc = _upload(client, org["id"], "offer_letter")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["n_facts_staged"] == 0
    assert body["document"]["extraction_status"] == "needs_review"


def test_offer_letter_with_an_unresolvable_department_is_refused(client, enabled_llm):
    """Regression, found on a real letter: asked to return {"error": ...}
    when the department is missing, the model instead returned
    department_name="no department stated" — a valid string that passed
    schema validation and staged a plausible-looking hire. Resolving the
    name against real departments is the structural check that catches it.
    """
    org, _ = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "candidate_email": "jordan.ellis@example.test", "candidate_name": "Jordan Ellis",
        "department_name": "no department stated", "level": None, "role": None,
        "team_name": None, "base_salary": 115000, "start_date": "2026-05-01",
    })))
    doc = _upload(client, org["id"], "offer_letter")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["n_facts_staged"] == 0
    assert body["document"]["extraction_status"] == "needs_review"
    error = body["document"]["extraction_error"]
    assert "no department stated" in error      # names what it read
    assert "Known departments" in error         # and what would have worked


def test_cv_with_an_unresolvable_department_still_stages_the_candidate(client, enabled_llm):
    """Softer than the offer path on purpose: a CV's department is the
    candidate's aspiration, not a claim about the org's structure."""
    org, _ = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "candidate_email": "someone@example.test", "candidate_name": "Some One",
        "most_recent_title": "Analyst", "years_experience": 4,
        "department_name": "Department of Whimsy", "level": None,
    })))
    doc = _upload(client, org["id"], "cv")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["n_facts_staged"] == 1
    fact = body["facts"][0]
    # Dropped from the payload so apply can't act on it...
    assert json.loads(fact["proposed_value"])["department_name"] is None
    # ...but preserved in the evidence so the reviewer still sees it.
    assert "Department of Whimsy" in fact["evidence_span"]


def test_cv_stages_a_candidate_but_apply_refuses_without_a_department(
    client, enabled_llm,
):
    """A CV alone must not be able to put someone on the payroll — it
    states what a candidate has done, not what they're hired into."""
    org, _ = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "candidate_email": "yusuf.demir@example.test", "candidate_name": "Yusuf Demir",
        "most_recent_title": "Senior Support Engineer", "years_experience": 8,
        "department_name": None, "level": None,
    })))
    doc = _upload(client, org["id"], "cv")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    fact = body["facts"][0]
    assert fact["field_name"] == "new_hire"
    assert "8 yrs experience" in fact["evidence_span"]
    # A CV is the candidate's own account — least authoritative of all.
    assert fact["confidence"] < 0.85

    before = len(client.get(f"/orgs/{org['id']}/employees").json())
    applied = client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [fact["id"]]},
    ).json()
    assert applied["n_employees_created"] == 0
    assert "names no department" in applied["unapplied"][0]
    assert len(client.get(f"/orgs/{org['id']}/employees").json()) == before


def test_cv_naming_a_target_department_can_be_hired(client, enabled_llm):
    org, _ = _make_org(client)
    dept = client.get(f"/orgs/{org['id']}/departments").json()[0]
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "candidate_email": "hana.kowalski@example.test", "candidate_name": "Hana Kowalski",
        "most_recent_title": "Staff Data Scientist", "years_experience": 11,
        "department_name": dept["name"], "level": "IC4",
    })))
    doc = _upload(client, org["id"], "cv")
    fact = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()["facts"][0]

    applied = client.post(
        f"/orgs/{org['id']}/documents/{doc['id']}/apply",
        json={"approved_fact_ids": [fact["id"]]},
    ).json()
    assert applied["n_employees_created"] == 1


def test_cv_schema_cannot_carry_a_salary():
    """Structural, like the resignation schema's missing feature fields: a
    CV does not set compensation, so there is nowhere to put one."""
    from companysim.ingest.schemas import CvExtract

    cv = CvExtract.model_validate({
        "candidate_email": "a@b.com", "candidate_name": "A B",
        "base_salary": 200000, "salary_expectation": 250000,
    })
    assert not hasattr(cv, "base_salary")
    assert not hasattr(cv, "salary_expectation")


def test_empty_note_text_records_no_exit_note(client, enabled_llm, db_session_factory):
    """A letter giving no reason still has a valid label, but there's no
    text to analyze — recording an empty note would pollute sentiment."""
    org, employee = _make_org(client)
    enabled_llm.setattr("groq.Groq", _fake_groq_client(content=json.dumps({
        "employee_email": employee["email"],
        "effective_date": "2026-03-15", "is_voluntary": True, "note_text": "",
    })))
    doc = _upload(client, org["id"], "resignation_letter")

    body = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()
    assert body["document"]["extraction_status"] == "extracted"
    db = db_session_factory()
    assert db.query(ExitNoteRecord).count() == 0
