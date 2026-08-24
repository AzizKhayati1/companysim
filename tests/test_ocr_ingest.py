"""Tests for OCR ingestion of photographed and scanned paper.

The contract under test is that paper is not a second pipeline. A
photograph produces the same ``raw_text`` a typed document would have, and
then travels the identical route: extraction, staging, human review. What
must differ is only what is genuinely different — that the text is a
*reading* of a page rather than a copy of it, which is recorded on the
document and discounts every fact staged from it.

No network: the OCR backends are stubbed, so these run in CI with no AWS
account and no Tesseract binary.
"""
from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.db_models import ExtractedFactRecord, SourceDocumentRecord
from companysim.api.ingest_records import OCR_CONFIDENCE_SCALE
from companysim.api.main import app
from companysim.ingest import documents, ocr

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8ffff3f0005fe02fea7b5c50f0000000049454e44ae426082"
)

LETTER = (
    "Meridian Analytics\n\n"
    "Dear Alison,\n\n"
    "I am resigning with effect from 30 September 2026.\n"
    "anna.daniels@meridiananalytics.example\n"
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("COMPANYSIM_OCR_PROVIDER", "COMPANYSIM_LLM_PROVIDER",
                "COMPANYSIM_LLM_INGEST", "GROQ_API_KEY",
                "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                "AWS_DEFAULT_REGION", "AWS_REGION", "AWS_PROFILE"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def db_session_factory():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
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


def _stub_bedrock_ocr(monkeypatch, text, *, usage=None):
    boto3 = pytest.importorskip("boto3")
    captured: dict = {}

    def converse(**kwargs):
        captured.update(kwargs)
        return {"output": {"message": {"content": [{"text": text}]}},
                "usage": usage if usage is not None
                else {"inputTokens": 1200, "outputTokens": 90, "totalTokens": 1290}}

    monkeypatch.setattr(boto3, "client",
                        lambda name, **k: types.SimpleNamespace(converse=converse))
    monkeypatch.setattr(boto3, "Session", lambda *a, **k: types.SimpleNamespace(
        get_credentials=lambda: object()))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("COMPANYSIM_OCR_PROVIDER", "bedrock")
    return captured


# ---- backend selection --------------------------------------------------


def test_no_backend_reports_a_specific_reason():
    assert ocr.active_provider() == ocr.PROVIDER_OFF
    problem = ocr.ocr_problem()
    assert problem and "Tesseract" in problem and "AWS" in problem
    assert ocr.is_available() is False


def test_bedrock_is_auto_selected_when_aws_is_configured(monkeypatch):
    """An extraction deployment already holds these credentials, so making
    someone configure a second service for the same document would be
    friction with nothing behind it."""
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setattr(boto3, "Session", lambda *a, **k: types.SimpleNamespace(
        get_credentials=lambda: object()))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    assert ocr.active_provider() == ocr.PROVIDER_BEDROCK
    assert ocr.is_available() is True


def test_explicit_off_beats_auto_selection(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setattr(boto3, "Session", lambda *a, **k: types.SimpleNamespace(
        get_credentials=lambda: object()))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("COMPANYSIM_OCR_PROVIDER", "off")
    assert ocr.active_provider() == ocr.PROVIDER_OFF


def test_tesseract_needs_the_binary_not_just_the_package(monkeypatch):
    """pytesseract imports cleanly with no Tesseract installed and fails
    only at call time, so an import check would advertise a backend that
    cannot run."""
    monkeypatch.setitem(__import__("sys").modules, "pytesseract",
                        types.SimpleNamespace(
                            get_tesseract_version=lambda: (_ for _ in ()).throw(
                                OSError("tesseract is not installed"))))
    monkeypatch.setitem(__import__("sys").modules, "PIL", types.SimpleNamespace())
    monkeypatch.setenv("COMPANYSIM_OCR_PROVIDER", "tesseract")
    assert ocr.is_available() is False
    assert "binary" in ocr.ocr_problem()


# ---- transcription ------------------------------------------------------


def test_image_is_transcribed_and_the_prompt_asks_for_verbatim_text(monkeypatch):
    captured = _stub_bedrock_ocr(monkeypatch, LETTER)
    text = ocr.image_to_text(PNG_1x1, ".png")
    assert "resigning" in text

    blocks = captured["messages"][0]["content"]
    assert blocks[0]["image"]["format"] == "png"
    assert blocks[0]["image"]["source"]["bytes"] == PNG_1x1
    # A vision model will happily summarise a document unless told not to;
    # a summary would silently become the note text a reviewer approves.
    assert "verbatim" in blocks[1]["text"]
    assert captured["inferenceConfig"]["temperature"] == 0.0


def test_jpg_maps_to_the_jpeg_format_converse_expects(monkeypatch):
    captured = _stub_bedrock_ocr(monkeypatch, LETTER)
    ocr.image_to_text(PNG_1x1, ".jpg")
    assert captured["messages"][0]["content"][0]["image"]["format"] == "jpeg"


def test_a_blank_page_refuses_rather_than_returning_empty_text(monkeypatch):
    """An empty document would reach review as a successful upload with
    nothing in it — the failure this pipeline avoids everywhere else."""
    _stub_bedrock_ocr(monkeypatch, ocr.NO_TEXT_SENTINEL)
    with pytest.raises(ValueError, match="No legible text"):
        ocr.image_to_text(PNG_1x1, ".png")


def test_an_unsupported_image_format_names_the_alternative(monkeypatch):
    _stub_bedrock_ocr(monkeypatch, LETTER)
    with pytest.raises(ValueError, match="textract"):
        ocr.image_to_text(PNG_1x1, ".tiff")


def test_an_oversized_image_fails_before_the_call(monkeypatch):
    _stub_bedrock_ocr(monkeypatch, LETTER)
    with pytest.raises(ValueError, match="limit is"):
        ocr.image_to_text(b"x" * (ocr.MAX_IMAGE_BYTES + 1), ".png")


def test_an_unavailable_backend_explains_itself_rather_than_crashing():
    with pytest.raises(ValueError, match="No OCR backend"):
        ocr.image_to_text(PNG_1x1, ".png")


# ---- the door -----------------------------------------------------------


def test_extract_text_routes_images_to_ocr_and_labels_the_source(monkeypatch):
    _stub_bedrock_ocr(monkeypatch, LETTER)
    text, source = documents.extract_text_with_source("letter.jpg", PNG_1x1)
    assert "resigning" in text
    assert source == "ocr:bedrock"
    assert documents.is_ocr_source(source) is True


def test_decoded_files_are_still_native():
    text, source = documents.extract_text_with_source("r.csv", b"email\na@b.com\n")
    assert source == documents.SOURCE_NATIVE
    assert documents.is_ocr_source(source) is False


def test_unsupported_types_list_the_image_formats_now_accepted():
    with pytest.raises(ValueError, match=r"\.png"):
        documents.extract_text_with_source("book.epub", b"x")


def test_a_scanned_pdf_without_ocr_says_it_is_a_scan():
    """Before OCR this was a dead end, and a phone's document mode is one
    of the commonest ways paper actually arrives."""
    from fpdf import FPDF

    doc = FPDF()
    doc.add_page()  # no text drawn: no text layer
    with pytest.raises(ValueError, match="scan or a photograph"):
        documents.extract_text_with_source("scan.pdf", bytes(doc.output()))


def test_a_pdf_with_a_real_text_layer_does_not_call_ocr(monkeypatch):
    """OCR costs money per page; a born-digital PDF must never pay it."""
    from fpdf import FPDF

    doc = FPDF()
    doc.add_page()
    doc.set_font("Helvetica", size=12)
    doc.multi_cell(0, 6, LETTER)

    def explode(*a, **k):
        raise AssertionError("OCR was called for a PDF that has a text layer")

    monkeypatch.setattr(ocr, "image_to_text", explode)
    text, source = documents.extract_text_with_source("typed.pdf", bytes(doc.output()))
    assert "resigning" in text
    assert source == documents.SOURCE_NATIVE


# ---- end to end through the API ----------------------------------------


def _make_org(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 7}).json()
    return org, client.get(f"/orgs/{org['id']}/employees").json()[0]


def test_a_photographed_letter_uploads_like_any_other_document(
    client, db_session_factory, monkeypatch,
):
    org, employee = _make_org(client)
    _stub_bedrock_ocr(monkeypatch, f"I am resigning. {employee['email']}\n30 September 2026")

    r = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("letter-photo.jpg", PNG_1x1, "image/jpeg")},
        data={"kind": "resignation_letter", "as_of_date": "2026-09-30"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["text_source"] == "ocr:bedrock"

    db = db_session_factory()
    doc = db.query(SourceDocumentRecord).one()
    # The transcription is persisted, so re-extracting never re-bills OCR.
    assert employee["email"] in doc.raw_text
    assert doc.text_source == "ocr:bedrock"


def test_ocr_tokens_are_metered_at_upload(client, db_session_factory, monkeypatch):
    """OCR is the only billable work an upload does, and it happens before
    any extraction — outside the block that meters extraction."""
    from companysim.api.db_models import LlmUsageRecord

    org, _ = _make_org(client)
    _stub_bedrock_ocr(monkeypatch, LETTER,
                      usage={"inputTokens": 1500, "outputTokens": 120, "totalTokens": 1620})

    client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("scan.png", PNG_1x1, "image/png")},
        data={"kind": "resignation_letter"},
    )

    db = db_session_factory()
    row = db.query(LlmUsageRecord).one()
    assert row.feature == "ocr"
    assert row.total_tokens == 1620
    assert row.org_id == org["id"]


def test_an_unreadable_photo_is_rejected_at_the_door(client, db_session_factory, monkeypatch):
    """Rejecting the upload beats storing an empty document: a blank row
    would look like a successful ingest that simply found nothing."""
    org, _ = _make_org(client)
    _stub_bedrock_ocr(monkeypatch, ocr.NO_TEXT_SENTINEL)

    r = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("blurry.jpg", PNG_1x1, "image/jpeg")},
        data={"kind": "resignation_letter"},
    )
    assert r.status_code == 400
    assert "No legible text" in r.json()["detail"]
    assert db_session_factory().query(SourceDocumentRecord).count() == 0


def test_facts_from_a_photograph_are_staged_at_lower_confidence(
    client, db_session_factory, monkeypatch,
):
    """OCR can turn a 3 into an 8 in a salary and no downstream check would
    catch it — both are valid numbers. The reviewer needs the difference."""
    org, employee = _make_org(client)
    _stub_bedrock_ocr(monkeypatch, f"email,level\n{employee['email']},M9\n")

    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("roster-photo.png", PNG_1x1, "image/png")},
        data={"kind": "roster"},
    ).json()
    client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract")

    db = db_session_factory()
    fact = db.query(ExtractedFactRecord).filter_by(field_name="level").one()
    # A CSV cell would be 1.0; the same value read off a photograph is not.
    assert fact.confidence == pytest.approx(OCR_CONFIDENCE_SCALE)
    assert fact.confidence < 1.0


# ---- status ------------------------------------------------------------


def test_status_reports_ocr_separately_from_the_llm_provider(client, monkeypatch):
    """"Can this server read a photograph" is a different question from
    "can it extract" — different backends, different failure modes — and
    the file picker's accept list is built from image_suffixes, so a wrong
    answer here greys the file out with no error to search for."""
    body = client.get("/llm/status").json()
    assert body["ocr_provider"] == "off"
    assert body["ocr_available"] is False
    assert "OCR backend" in body["ocr_problem"]
    assert ".jpg" in body["image_suffixes"]
    assert ".png" in body["image_suffixes"]


def test_status_reports_ocr_ready_when_a_backend_resolves(client, monkeypatch):
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setattr(boto3, "Session", lambda *a, **k: types.SimpleNamespace(
        get_credentials=lambda: object()))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")

    body = client.get("/llm/status").json()
    assert body["ocr_provider"] == "bedrock"
    assert body["ocr_available"] is True
    assert body["ocr_problem"] is None


def test_image_suffixes_match_what_the_door_actually_accepts(client):
    """The picker offers exactly what extract_text routes to OCR. If these
    drift, a file the backend would read cannot be selected."""
    body = client.get("/llm/status").json()
    assert set(body["image_suffixes"]) == ocr.IMAGE_SUFFIXES
    for suffix in body["image_suffixes"]:
        assert ocr.suffix_is_image(suffix)
