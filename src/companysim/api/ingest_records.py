"""Persist and query uploaded documents + their staged facts.

The DB-coupled glue between ``companysim.ingest`` (pure parsing/diffing)
and ``routers/ingest.py`` — mirrors ``exit_note_records.py``'s
persist+query-in-one-module pattern for the same reason: the queries are
small and have no other consumer, so a separate adapter module would be
ceremony. The one rule enforced here rather than in the router is dedup:
``save_document`` refuses a repeat ``content_hash`` within an org, so the
same export uploaded twice can't stage its change set twice.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from companysim.api.db_models import (
    EmployeeRecord,
    ExitNoteRecord,
    ExtractedFactRecord,
    PerformanceReviewRecord,
    SourceDocumentRecord,
)
from companysim.ingest.cohorts import CohortValidationError, build_document_cohort
from companysim.ingest.documents import DocumentKind
from companysim.ingest.reconcile import ProposedChange
from companysim.ml.exit_notes import analyze_note
from companysim.ml.turnover_features import FEATURE_COLUMNS


class DuplicateDocumentError(Exception):
    """Raised when an org already holds a document with this content hash."""


def content_hash_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_document(
    db: Session, org_id: int, *, kind: str, filename: str, data: bytes,
    raw_text: str, as_of_date: date | None,
) -> SourceDocumentRecord:
    digest = content_hash_of(data)
    exists = (
        db.query(SourceDocumentRecord)
        .filter_by(org_id=org_id, content_hash=digest)
        .first()
    )
    if exists is not None:
        raise DuplicateDocumentError(
            f"Document already uploaded for this org (id={exists.id}, "
            f"filename={exists.filename!r})."
        )
    doc = SourceDocumentRecord(
        org_id=org_id, kind=kind, filename=filename, content_hash=digest,
        raw_text=raw_text, as_of_date=as_of_date, extraction_status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def list_documents(db: Session, org_id: int) -> list[SourceDocumentRecord]:
    return (
        db.query(SourceDocumentRecord)
        .filter_by(org_id=org_id)
        .order_by(SourceDocumentRecord.uploaded_at.desc())
        .all()
    )


def get_document(db: Session, org_id: int, document_id: int) -> SourceDocumentRecord | None:
    return (
        db.query(SourceDocumentRecord)
        .filter_by(org_id=org_id, id=document_id)
        .first()
    )


def save_extracted_facts(
    db: Session, document: SourceDocumentRecord, changes: list[ProposedChange],
    *, extractor: str,
) -> list[ExtractedFactRecord]:
    """Stage ``changes`` as pending facts and mark the document extracted.
    Committing facts and status together keeps the two consistent — a
    document is never "extracted" with its facts lost to a failed second
    commit.
    """
    facts = [
        ExtractedFactRecord(
            document_id=document.id, org_id=document.org_id,
            target_table="employees",
            target_employee_id=c.target_employee_id,
            field_name=c.field_name, proposed_value=c.proposed_value,
            current_value=c.current_value, confidence=c.confidence,
            review_status="pending", evidence_span=c.evidence_span,
        )
        for c in changes
    ]
    db.add_all(facts)
    document.extraction_status = "extracted"
    document.extractor = extractor
    document.extraction_error = None
    db.commit()
    for f in facts:
        db.refresh(f)
    return facts


def pending_facts_for_document(
    db: Session, document_id: int,
) -> list[ExtractedFactRecord]:
    return (
        db.query(ExtractedFactRecord)
        .filter_by(document_id=document_id, review_status="pending")
        .order_by(ExtractedFactRecord.id)
        .all()
    )


def mark_needs_review(db: Session, document: SourceDocumentRecord, reason: str) -> None:
    """The honest-refusal path: a kind we can't parse yet stages nothing
    and says so, instead of fabricating an extraction (same stance as
    ``org_chat.py``'s no-fallback policy for free-form questions)."""
    document.extraction_status = "needs_review"
    document.extraction_error = reason
    db.commit()


def stamp_applied(db: Session, fact: ExtractedFactRecord) -> None:
    fact.review_status = "approved"
    fact.applied_at = datetime.now(timezone.utc)


def clear_document_extractions(db: Session, document: SourceDocumentRecord) -> int:
    """Delete the rows a previous extraction of ``document`` wrote, so
    re-extracting replaces rather than appends.

    The roster path gets this for free by deleting stale *pending facts*
    before re-staging. The LLM paths write straight to
    ``PerformanceReviewRecord`` / ``ExitNoteRecord`` instead, so without
    this every re-run silently duplicates: three clicks of Extract on one
    resignation letter produced three identical exit notes, and a
    duplicated performance review is worse still — it lands as both
    ``rating_last`` and ``rating_prev``, flattening ``rating_delta`` to
    0.0 and telling the model a rating never moved.

    Returns the number of rows removed. Does not commit; the caller
    commits alongside the fresh rows so the replace is atomic.
    """
    removed = (
        db.query(PerformanceReviewRecord)
        .filter_by(document_id=document.id)
        .delete(synchronize_session=False)
    )
    removed += (
        db.query(ExitNoteRecord)
        .filter_by(source_document_id=document.id)
        .delete(synchronize_session=False)
    )
    return removed


def employee_id_by_email(db: Session, org_id: int) -> dict[str, int]:
    """Lowercased email -> employee id, the match key every document kind
    resolves people through (see ``ingest.schemas``)."""
    return {
        e.email.strip().lower(): e.id
        for e in db.query(EmployeeRecord).filter_by(org_id=org_id).all()
    }


def record_performance_review(
    db: Session, document: SourceDocumentRecord, *, employee_id: int,
    review_period_end: date, rating: float, summary_text: str,
) -> PerformanceReviewRecord:
    review = PerformanceReviewRecord(
        org_id=document.org_id, employee_id=employee_id, document_id=document.id,
        review_period_end=review_period_end, rating=rating, summary_text=summary_text,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def record_ingested_exit_note(
    db: Session, document: SourceDocumentRecord, *, employee_id: int, text: str,
) -> ExitNoteRecord | None:
    """Persist a real resignation letter's own words as an ``ExitNoteRecord``.

    Sentiment and themes come from ``ml.exit_notes.analyze_note`` — the
    same lexicon and keyword→theme mapping applied to simulated notes, so
    the Exit Notes Insights page aggregates real and simulated text on one
    scale rather than two incomparable ones. ``run_id=0`` marks "no
    simulation run produced this"; the column is a lineage-only FK with no
    cascade (see ``db_models.ExitNoteRecord``), and ``source_document_id``
    is the provenance that actually matters for an ingested note.
    """
    if not text.strip():
        return None
    sentiment, themes = analyze_note(text)
    note = ExitNoteRecord(
        org_id=document.org_id, run_id=0, employee_id=employee_id, text=text,
        sentiment=sentiment, themes=",".join(themes),
        is_llm_generated=False, is_backfilled=False, source_document_id=document.id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def resignations_for_org(db: Session, org_id: int) -> dict[int, date]:
    """employee_id -> effective date, from ingested resignation letters.

    Reads ``PerformanceReviewRecord``'s sibling provenance path: a
    resignation letter's effective date is stored as the document's
    ``as_of_date`` (set by the extract step from the letter's own stated
    date), so no extra table is needed for what is one date per document.
    """
    docs = (
        db.query(SourceDocumentRecord)
        .filter_by(org_id=org_id, kind=DocumentKind.RESIGNATION_LETTER.value)
        .filter(SourceDocumentRecord.as_of_date.isnot(None))
        .all()
    )
    notes = {
        n.source_document_id: n.employee_id
        for n in db.query(ExitNoteRecord).filter(
            ExitNoteRecord.org_id == org_id,
            ExitNoteRecord.source_document_id.isnot(None),
        ).all()
    }
    out: dict[int, date] = {}
    for doc in docs:
        employee_id = notes.get(doc.id)
        if employee_id is None:
            continue
        # Earliest stated departure wins if the same person somehow has
        # two letters — the first exit is the one that ends their tenure.
        existing = out.get(employee_id)
        if existing is None or doc.as_of_date < existing:
            out[employee_id] = doc.as_of_date
    return out


def load_document_examples(db: Session, org_id: int, *, window_end: date | None = None):
    """A validated :class:`~companysim.ingest.cohorts.DocumentCohort` for
    ``org_id``, or ``None`` if this org can't honestly produce one.

    Requires a roster document to establish the denominator: its
    ``as_of_date`` is the outcome window's start, and every employee it
    covers is a cohort member (a negative unless a resignation letter puts
    them in the window). Returning ``None`` rather than an empty frame is
    deliberate — the caller reports "no usable cohort" instead of silently
    contributing nothing that looks like contributing zero.
    """
    from companysim.api.scoring_frame import build_scoring_frame  # noqa: PLC0415

    roster_docs = [
        d for d in db.query(SourceDocumentRecord)
        .filter_by(org_id=org_id, kind=DocumentKind.ROSTER.value, extraction_status="extracted")
        .all()
        if d.as_of_date is not None
    ]
    if not roster_docs:
        return None
    roster_doc = max(roster_docs, key=lambda d: d.as_of_date)

    frame = build_scoring_frame(db, org_id)
    if frame.empty:
        return None
    feature_rows = frame[["employee_id", *FEATURE_COLUMNS]].to_dict("records")

    resignations = resignations_for_org(db, org_id)
    if window_end is None:
        latest = max(resignations.values(), default=None)
        if latest is None:
            return None
        window_end = latest

    # Only reviews dated on or before the window start may contribute a
    # feature; a later one is what assert_no_temporal_leakage exists to
    # catch, and surfacing it as a validation error beats quietly
    # excluding it.
    review_dates = {
        f"review#{r.id}": r.review_period_end
        for r in db.query(PerformanceReviewRecord).filter_by(org_id=org_id).all()
    }
    try:
        return build_document_cohort(
            roster_employee_ids=[int(r["employee_id"]) for r in feature_rows],
            feature_rows=feature_rows,
            resignations=resignations,
            window_start=roster_doc.as_of_date,
            window_end=window_end,
            feature_source_dates=review_dates,
        )
    except CohortValidationError:
        return None


def load_all_document_examples(db: Session) -> tuple[pd.DataFrame, int]:
    """Every org's usable document cohort, concatenated into one
    ``FEATURE_COLUMNS`` + label frame for ``ml.gate.run_training_gate``.

    Orgs without a usable cohort contribute nothing and don't block the
    rest — one org missing a roster shouldn't cost every other org its
    real data.
    """
    from companysim.api.db_models import OrgRecord  # noqa: PLC0415

    frames = []
    for (org_id,) in db.query(OrgRecord.id).all():
        cohort = load_document_examples(db, org_id)
        if cohort is not None and not cohort.frame.empty:
            frames.append(cohort.frame)
    if not frames:
        return pd.DataFrame(columns=[*FEATURE_COLUMNS, "quit_within_horizon"]), 0
    merged = pd.concat(frames, ignore_index=True)
    return merged, len(merged)


def ingest_totals(db: Session, org_id: int) -> dict[str, Any]:
    n_documents = db.query(SourceDocumentRecord).filter_by(org_id=org_id).count()
    n_pending_facts = (
        db.query(ExtractedFactRecord)
        .filter_by(org_id=org_id, review_status="pending")
        .count()
    )
    n_applied_facts = (
        db.query(ExtractedFactRecord)
        .filter_by(org_id=org_id, review_status="approved")
        .count()
    )
    n_reviews = db.query(PerformanceReviewRecord).filter_by(org_id=org_id).count()
    n_ingested_notes = (
        db.query(ExitNoteRecord)
        .filter(
            ExitNoteRecord.org_id == org_id,
            ExitNoteRecord.source_document_id.isnot(None),
        )
        .count()
    )
    return {
        "n_documents": n_documents,
        "n_pending_facts": n_pending_facts,
        "n_applied_facts": n_applied_facts,
        "n_performance_reviews": n_reviews,
        "n_ingested_exit_notes": n_ingested_notes,
    }
