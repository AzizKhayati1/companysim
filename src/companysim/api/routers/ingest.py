"""Document ingestion — upload, extract, review, apply.

The staged half of the ingestion pipeline: uploads land as
``SourceDocumentRecord``, extraction stages ``ExtractedFactRecord`` rows,
and nothing touches ``EmployeeRecord`` until a human posts an explicit
approval to ``/apply``.

Two extraction paths, picked by document kind rather than by preference:
rosters go through the deterministic ``ingest.rules_parser`` (structured
CSV needs no model and must keep working in CI with no API key), while
performance reviews and resignation letters go through the flag-gated
``ingest.llm_parser``. Either way a failure parks the document as
``needs_review`` with a reason and stages nothing — the pipeline never
fabricates an extraction, because a wrong rating written into a model
feature is worse than no rating at all.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.db_models import (
    DepartmentRecord,
    EmployeeRecord,
    EmployeeWellbeingRecord,
    ExitNoteRecord,
    ExtractedFactRecord,
    OrgRecord,
    PerformanceReviewRecord,
    SourceDocumentRecord,
    TeamRecord,
)
from companysim.api.ingest_records import (
    DuplicateDocumentError,
    clear_document_extractions,
    employee_id_by_email,
    get_document,
    ingest_totals,
    list_documents,
    load_document_examples,
    mark_needs_review,
    pending_facts_for_document,
    record_ingested_exit_note,
    record_performance_review,
    save_document,
    save_extracted_facts,
    stamp_applied,
)
from companysim.api.llm_usage import record_llm_calls
from companysim.api.routers.employees import _DEFAULT_WELLBEING
from companysim.api.schemas import (
    ApplyFactsRequest,
    ApplyFactsResponse,
    DocumentCohortOut,
    DocumentDetailOut,
    DocumentLineageOut,
    ExtractDocumentResponse,
    ExtractedFactOut,
    IngestTotalsOut,
    LineageFieldOut,
    LineageTargetOut,
    SourceDocumentOut,
)
from companysim.ingest.documents import DocumentKind, extract_text
from companysim.ingest.llm_parser import (
    extract_cv,
    extract_offer_letter,
    extract_performance_review,
    extract_resignation_letter,
    is_ingest_llm_enabled,
)
from companysim.ingest.reconcile import (
    NAME_FIELD_TO_FK,
    NEW_HIRE_FIELD,
    RECONCILED_FIELDS,
    ProposedChange,
    reconcile_roster,
)
from companysim.ingest.rules_parser import parse_roster_csv
from companysim.ingest.schemas import RosterRow
from companysim.llm.usage import collect

router = APIRouter(prefix="/orgs/{org_id}/documents", tags=["documents"])

# Coercions for applying a staged string value back onto EmployeeRecord —
# restricted to RECONCILED_FIELDS so a hand-crafted fact row can't write
# arbitrary attributes.
_FIELD_COERCERS = {
    "full_name": str, "level": str, "role": str,
    "tenure_months": lambda v: int(float(v)),
    "base_salary": float,
    "promotions_count": lambda v: int(float(v)),
}


def _get_org_or_404(db: Session, org_id: int) -> OrgRecord:
    org = db.get(OrgRecord, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    return org


def _get_doc_or_404(db: Session, org_id: int, document_id: int) -> SourceDocumentRecord:
    doc = get_document(db, org_id, document_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    return doc


def _doc_out(doc: SourceDocumentRecord) -> SourceDocumentOut:
    return SourceDocumentOut(
        id=doc.id, kind=doc.kind, filename=doc.filename, content_hash=doc.content_hash,
        uploaded_at=doc.uploaded_at.isoformat(),
        as_of_date=doc.as_of_date.isoformat() if doc.as_of_date else None,
        extraction_status=doc.extraction_status, extractor=doc.extractor,
        extraction_error=doc.extraction_error,
    )


def _fact_out(f: ExtractedFactRecord) -> ExtractedFactOut:
    return ExtractedFactOut(
        id=f.id, document_id=f.document_id, target_table=f.target_table,
        target_employee_id=f.target_employee_id, field_name=f.field_name,
        proposed_value=f.proposed_value, current_value=f.current_value,
        confidence=f.confidence, review_status=f.review_status,
        evidence_span=f.evidence_span,
        applied_at=f.applied_at.isoformat() if f.applied_at else None,
    )


@router.post("", response_model=SourceDocumentOut, status_code=201)
def upload_document(
    org_id: int,
    file: UploadFile = File(...),
    kind: str = Form(...),
    as_of_date: str | None = Form(None),
    db: Session = Depends(get_db),
):
    _get_org_or_404(db, org_id)
    if kind not in {k.value for k in DocumentKind}:
        raise HTTPException(400, f"Unknown document kind {kind!r}")
    parsed_date: date | None = None
    if as_of_date:
        try:
            parsed_date = date.fromisoformat(as_of_date)
        except ValueError:
            raise HTTPException(400, f"as_of_date {as_of_date!r} is not an ISO date") from None

    data = file.file.read()
    try:
        raw_text = extract_text(file.filename or "upload", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    try:
        doc = save_document(
            db, org_id, kind=kind, filename=file.filename or "upload",
            data=data, raw_text=raw_text, as_of_date=parsed_date,
        )
    except DuplicateDocumentError as exc:
        raise HTTPException(409, str(exc)) from None
    return _doc_out(doc)


@router.get("", response_model=list[SourceDocumentOut])
def get_documents(org_id: int, db: Session = Depends(get_db)):
    _get_org_or_404(db, org_id)
    return [_doc_out(d) for d in list_documents(db, org_id)]


@router.get("/cohort", response_model=DocumentCohortOut)
def get_document_cohort(org_id: int, db: Session = Depends(get_db)):
    """Whether this org's documents can currently produce labeled training
    examples, and why not when they can't — the denominator rule made
    visible instead of failing silently at retrain time.
    """
    _get_org_or_404(db, org_id)
    cohort = load_document_examples(db, org_id)
    if cohort is None:
        return DocumentCohortOut(
            usable=False,
            reason=(
                "No usable cohort: needs an extracted roster with an as-of date "
                "(the denominator) and at least one ingested resignation letter "
                "inside the outcome window."
            ),
        )
    return DocumentCohortOut(
        usable=True,
        reason="",
        window_start=cohort.window_start.isoformat(),
        window_end=cohort.window_end.isoformat(),
        n_positives=cohort.n_positives,
        n_negatives=cohort.n_negatives,
        base_rate=cohort.base_rate,
        n_unmatched_resignations=cohort.n_unmatched_resignations,
    )


@router.get("/totals", response_model=IngestTotalsOut)
def get_ingest_totals(org_id: int, db: Session = Depends(get_db)):
    _get_org_or_404(db, org_id)
    return IngestTotalsOut(**ingest_totals(db, org_id))


# What each destination column feeds once written. Kept here rather than in
# the frontend so the provenance shown to a reviewer is derived from the
# same module that does the writing, and can't drift from it.
_RATING_NOTE = "rating_last / rating_prev / rating_delta — 3 of the model's 18 numeric features"
_EMPLOYEE_FIELD_NOTE = "scoring_frame.build_scoring_frame → live at-risk scoring + training examples"


def _employee_names(db: Session, org_id: int) -> dict[int, str]:
    return {
        e.id: e.full_name
        for e in db.query(EmployeeRecord).filter_by(org_id=org_id).all()
    }


def _roster_targets(
    db: Session, org_id: int, doc: SourceDocumentRecord, names: dict[int, str],
) -> list[LineageTargetOut]:
    """One target per (employee, review state) — a roster's facts are
    per-field proposals, so they group by the employee they'd change."""
    facts = (
        db.query(ExtractedFactRecord)
        .filter_by(document_id=doc.id)
        .order_by(ExtractedFactRecord.id)
        .all()
    )
    grouped: dict[tuple[int | None, str], list[ExtractedFactRecord]] = {}
    for f in facts:
        if f.review_status == "rejected":
            continue  # rejected proposals wrote nothing; not part of lineage
        state = "applied" if f.applied_at is not None else "pending"
        grouped.setdefault((f.target_employee_id, state), []).append(f)

    targets: list[LineageTargetOut] = []
    for (employee_id, state), rows in grouped.items():
        is_new_hire = any(r.field_name == NEW_HIRE_FIELD for r in rows)
        fields = [
            LineageFieldOut(
                column=NAME_FIELD_TO_FK.get(r.field_name, r.field_name),
                value=("(whole row — creates the employee)"
                       if r.field_name == NEW_HIRE_FIELD else r.proposed_value),
                note=_EMPLOYEE_FIELD_NOTE,
            )
            for r in rows
        ]
        targets.append(LineageTargetOut(
            table="employees", state=state,
            employee_id=employee_id,
            employee_name=(
                "(new hire — not yet in this org)" if is_new_hire and employee_id is None
                else names.get(employee_id or -1)
            ),
            fields=fields,
        ))
    return targets


@router.get("/{document_id}/lineage", response_model=DocumentLineageOut)
def get_document_lineage(org_id: int, document_id: int, db: Session = Depends(get_db)):
    """Exactly which rows and columns this document produced, and what they
    feed. Reads the real rows rather than re-deriving from the raw text, so
    a document that extracted nothing honestly shows nothing.
    """
    doc = _get_doc_or_404(db, org_id, document_id)
    names = _employee_names(db, org_id)
    targets: list[LineageTargetOut] = []
    downstream: list[str] = []

    if doc.kind == DocumentKind.ROSTER.value:
        targets += _roster_targets(db, org_id, doc, names)
        if targets:
            downstream.append(
                "Employee fields feed build_scoring_frame, which powers both live "
                "at-risk scoring and the labeled examples collected from each run."
            )
        if doc.as_of_date:
            targets.append(LineageTargetOut(
                table="source_documents", state="written", row_id=doc.id,
                fields=[LineageFieldOut(
                    column="as_of_date", value=doc.as_of_date.isoformat(),
                    note="opens the cohort's outcome window (the denominator date)",
                )],
            ))
            downstream.append(
                "This roster's as-of date is the outcome window's start — it is what "
                "supplies the denominator that makes resignation letters usable as labels."
            )

    reviews = db.query(PerformanceReviewRecord).filter_by(document_id=doc.id).all()
    for r in reviews:
        targets.append(LineageTargetOut(
            table="performance_reviews", state="written", row_id=r.id,
            employee_id=r.employee_id, employee_name=names.get(r.employee_id),
            fields=[
                LineageFieldOut(column="review_period_end",
                                value=r.review_period_end.isoformat(),
                                note="orders reviews into last/prev; checked by the leakage guard"),
                LineageFieldOut(column="rating", value=f"{r.rating:g}", note=_RATING_NOTE),
                LineageFieldOut(column="summary_text",
                                value=r.summary_text or "(none)",
                                note="kept for human review only — never featurized"),
            ],
        ))
    if reviews:
        downstream.append(
            "Ratings replace the neutral 3.0/3.0/0.0 placeholders build_scoring_frame "
            "used to fake — this is the one gap document ingestion actually closes."
        )

    notes = (
        db.query(ExitNoteRecord)
        .filter(ExitNoteRecord.source_document_id == doc.id)
        .all()
    )
    for n in notes:
        targets.append(LineageTargetOut(
            table="exit_note_records", state="written", row_id=n.id,
            employee_id=n.employee_id, employee_name=names.get(n.employee_id or -1),
            fields=[
                LineageFieldOut(column="text", value=n.text,
                                note="the letter's own words — no feature is derived from it"),
                LineageFieldOut(column="sentiment", value=f"{n.sentiment:+.2f}",
                                note="ml.exit_notes.analyze_note — same lexicon as simulated notes"),
                LineageFieldOut(column="themes", value=n.themes or "(none matched)",
                                note="Exit Notes Insights theme frequency"),
            ],
        ))
    if notes and doc.as_of_date:
        targets.append(LineageTargetOut(
            table="source_documents", state="written", row_id=doc.id,
            fields=[LineageFieldOut(
                column="as_of_date", value=doc.as_of_date.isoformat(),
                note="the departure date — decides whether this exit falls in the outcome window",
            )],
        ))
        downstream.append(
            "A letter contributes the quit LABEL and its date, never a feature — it is "
            "written at the moment of the outcome, so anything it says about workload or "
            "morale would be temporal leakage."
        )

    return DocumentLineageOut(
        document_id=doc.id, kind=doc.kind,
        extraction_status=doc.extraction_status, extractor=doc.extractor,
        targets=targets, downstream=downstream,
    )


# Registered after the literal /cohort and /totals paths above: FastAPI
# matches in registration order, so a {document_id} route declared first
# would swallow them and 422 on the non-integer segment.
@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document_detail(org_id: int, document_id: int, db: Session = Depends(get_db)):
    doc = _get_doc_or_404(db, org_id, document_id)
    pending = pending_facts_for_document(db, doc.id)
    return DocumentDetailOut(
        **_doc_out(doc).model_dump(),
        raw_text=doc.raw_text,
        pending_facts=[_fact_out(f) for f in pending],
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(org_id: int, document_id: int, db: Session = Depends(get_db)):
    doc = _get_doc_or_404(db, org_id, document_id)
    db.delete(doc)
    db.commit()


def _empty_extract(doc: SourceDocumentRecord) -> ExtractDocumentResponse:
    return ExtractDocumentResponse(document=_doc_out(doc), n_facts_staged=0, facts=[])


def _extract_roster(db: Session, org_id: int, doc: SourceDocumentRecord):
    try:
        rows = parse_roster_csv(doc.raw_text)
    except ValueError as exc:
        mark_needs_review(db, doc, str(exc))
        return _empty_extract(doc)

    employees = db.query(EmployeeRecord).filter_by(org_id=org_id).all()
    existing = [
        {
            "id": e.id, "email": e.email,
            "department_id": e.department_id, "team_id": e.team_id,
            **{f: getattr(e, f) for f in RECONCILED_FIELDS},
        }
        for e in employees
    ]
    department_names = {
        d.id: d.name for d in db.query(DepartmentRecord).filter_by(org_id=org_id).all()
    }
    team_names = {t.id: t.name for t in db.query(TeamRecord).filter_by(org_id=org_id).all()}
    changes = reconcile_roster(
        rows, existing, department_names=department_names, team_names=team_names,
    )

    # Re-extraction replaces whatever is still awaiting review; approved/
    # rejected rows are history and stay.
    for stale in pending_facts_for_document(db, doc.id):
        db.delete(stale)
    facts = save_extracted_facts(db, doc, changes, extractor="rules")
    return ExtractDocumentResponse(
        document=_doc_out(doc), n_facts_staged=len(facts),
        facts=[_fact_out(f) for f in facts],
    )


def _extract_performance_review(db: Session, org_id: int, doc: SourceDocumentRecord):
    extracted = extract_performance_review(doc.raw_text)
    if extracted is None:
        mark_needs_review(
            db, doc,
            "The extractor could not read a complete performance review "
            "(employee email, review period end and rating are all required).",
        )
        return _empty_extract(doc)

    employee_id = employee_id_by_email(db, org_id).get(extracted.employee_email.strip().lower())
    if employee_id is None:
        mark_needs_review(
            db, doc,
            f"No employee in this org has email {extracted.employee_email!r}.",
        )
        return _empty_extract(doc)

    # Replace, don't append — re-extracting must be idempotent.
    clear_document_extractions(db, doc)
    record_performance_review(
        db, doc, employee_id=employee_id,
        review_period_end=extracted.review_period_end,
        rating=extracted.rating, summary_text=extracted.summary_text,
    )
    doc.extraction_status = "extracted"
    doc.extractor = _llm_extractor_label()
    doc.extraction_error = None
    # The review's own period end is what the temporal-leakage guard
    # checks, so keep it on the document too rather than only in the row.
    doc.as_of_date = extracted.review_period_end
    db.commit()
    db.refresh(doc)
    return _empty_extract(doc)


def _extract_resignation_letter(db: Session, org_id: int, doc: SourceDocumentRecord):
    extracted = extract_resignation_letter(doc.raw_text)
    if extracted is None:
        mark_needs_review(
            db, doc,
            "The extractor could not read a complete resignation letter "
            "(employee email and effective date are both required).",
        )
        return _empty_extract(doc)

    if not extracted.is_voluntary:
        # §5.6's distinction, enforced at ingest: an employer-initiated
        # exit is not attrition, and labelling it as one would teach the
        # model that being laid off looks like quitting.
        mark_needs_review(
            db, doc,
            "Document describes an employer-initiated exit (layoff/termination), "
            "not a voluntary resignation — not ingested as a quit label.",
        )
        return _empty_extract(doc)

    employee_id = employee_id_by_email(db, org_id).get(extracted.employee_email.strip().lower())
    if employee_id is None:
        mark_needs_review(
            db, doc,
            f"No employee in this org has email {extracted.employee_email!r}.",
        )
        return _empty_extract(doc)

    # Replace, don't append — re-extracting must be idempotent.
    clear_document_extractions(db, doc)
    record_ingested_exit_note(db, doc, employee_id=employee_id, text=extracted.note_text)
    doc.extraction_status = "extracted"
    doc.extractor = _llm_extractor_label()
    doc.extraction_error = None
    # The stated departure date IS the label's date — resignations_for_org
    # reads it back from here when assembling a cohort window.
    doc.as_of_date = extracted.effective_date
    db.commit()
    db.refresh(doc)
    return _empty_extract(doc)


def _stage_new_hire(
    db: Session, org_id: int, doc: SourceDocumentRecord, row: RosterRow, evidence: str,
    *, confidence: float,
):
    """Stage a hiring document as the same ``new_hire`` proposal an
    unmatched roster row produces.

    Deliberately reuses the roster path rather than adding a third way to
    create an employee: apply already knows how to resolve a department by
    name, place someone on a team, seed the wellbeing row, and refuse when
    the department doesn't exist. A parallel implementation would have to
    re-earn all four, and would drift.

    Confidence is the caller's, and it is not 1.0 — unlike a CSV cell, this
    value is a model's *reading* of prose, which is exactly the distinction
    ``ExtractedFactRecord.confidence`` exists to carry.
    """
    if employee_id_by_email(db, org_id).get(row.email.strip().lower()) is not None:
        mark_needs_review(
            db, doc,
            f"{row.email} is already an employee of this org — a hiring document "
            "should describe someone new. Use a roster to update an existing person.",
        )
        return _empty_extract(doc)

    for stale in pending_facts_for_document(db, doc.id):
        db.delete(stale)
    facts = save_extracted_facts(
        db, doc,
        [ProposedChange(
            target_employee_id=None, field_name=NEW_HIRE_FIELD,
            proposed_value=row.model_dump_json(), current_value=None,
            confidence=confidence, evidence_span=evidence,
        )],
        extractor=_llm_extractor_label(),
    )
    return ExtractDocumentResponse(
        document=_doc_out(doc), n_facts_staged=len(facts),
        facts=[_fact_out(f) for f in facts],
    )


def _department_names_lower(db: Session, org_id: int) -> dict[str, str]:
    """lowercased name -> canonical name, for resolving an extracted
    department against ones that actually exist."""
    return {
        d.name.strip().lower(): d.name
        for d in db.query(DepartmentRecord).filter_by(org_id=org_id).all()
    }


def _extract_offer_letter(db: Session, org_id: int, doc: SourceDocumentRecord):
    extracted = extract_offer_letter(doc.raw_text)
    if extracted is None:
        mark_needs_review(
            db, doc,
            "The extractor could not read a complete offer letter (candidate email, "
            "name and department are all required — an employee has to be placed "
            "somewhere).",
        )
        return _empty_extract(doc)

    # Verify the department exists, the same way the performance-review path
    # verifies the employee email resolves. Prompting alone is not enough:
    # asked for {"error": ...} when a field is missing, a model will instead
    # put its refusal *inside* the field — one real letter came back with
    # department_name="no department stated", which passes schema validation
    # and stages a plausible-looking proposal. Resolving the reference is a
    # structural check that catches that and every other unusable value.
    known = _department_names_lower(db, org_id)
    canonical = known.get(extracted.department_name.strip().lower())
    if canonical is None:
        mark_needs_review(
            db, doc,
            f"Offer letter names department {extracted.department_name!r}, which "
            f"doesn't exist in this org. Known departments: {', '.join(sorted(known.values()))}. "
            "Departments are never created from a document.",
        )
        return _empty_extract(doc)
    extracted = extracted.model_copy(update={"department_name": canonical})

    if extracted.start_date:
        doc.as_of_date = extracted.start_date
        db.commit()
    row = RosterRow(
        email=extracted.candidate_email, full_name=extracted.candidate_name,
        level=extracted.level, role=extracted.role,
        department_name=extracted.department_name, team_name=extracted.team_name,
        base_salary=extracted.base_salary, tenure_months=0, promotions_count=0,
    )
    return _stage_new_hire(
        db, org_id, doc, row,
        f"offer letter for {extracted.candidate_name} <{extracted.candidate_email}>: "
        f"{extracted.role or 'role unstated'} in {extracted.department_name}",
        confidence=0.85,
    )


def _extract_cv(db: Session, org_id: int, doc: SourceDocumentRecord):
    extracted = extract_cv(doc.raw_text)
    if extracted is None:
        mark_needs_review(
            db, doc,
            "The extractor could not read a candidate name and email from this CV.",
        )
        return _empty_extract(doc)

    # A CV's department is an aspiration, not a fact about the org, so an
    # unresolvable one is dropped rather than refused — the candidate is
    # still worth staging, and apply then gives the standard "names no
    # department" refusal. What they wrote stays visible in the evidence.
    known = _department_names_lower(db, org_id)
    target = (
        known.get(extracted.department_name.strip().lower())
        if extracted.department_name else None
    )
    row = RosterRow(
        email=extracted.candidate_email, full_name=extracted.candidate_name,
        level=extracted.level, role=extracted.most_recent_title,
        department_name=target,
        tenure_months=0, promotions_count=0,
    )
    experience = (
        f", {extracted.years_experience:g} yrs experience"
        if extracted.years_experience is not None else ""
    )
    if extracted.department_name and target is None:
        experience += f"; stated target department {extracted.department_name!r} not in this org"
    # Lower than an offer letter: a CV is the candidate's own account of
    # themselves, and the fields it fills are the ones it is least
    # authoritative about (level and department are the org's call).
    return _stage_new_hire(
        db, org_id, doc, row,
        f"CV for {extracted.candidate_name} <{extracted.candidate_email}>: "
        f"{extracted.most_recent_title or 'title unstated'}{experience}",
        confidence=0.6,
    )


def _llm_extractor_label() -> str:
    """``provider:model`` — stamped onto every document this path touches.

    Both halves are deployment settings now, so the label is resolved per
    call rather than baked in as a constant. A document extracted under
    Groq and one re-extracted under Bedrock stay distinguishable in the
    lineage view, which is the only way to explain a changed reading of
    the same file after a provider switch.
    """
    from companysim.llm import provider  # noqa: PLC0415

    return f"{provider.active_provider()}:{provider.model_id()}"


_LLM_KINDS = {
    DocumentKind.PERFORMANCE_REVIEW.value: _extract_performance_review,
    DocumentKind.RESIGNATION_LETTER.value: _extract_resignation_letter,
    DocumentKind.OFFER_LETTER.value: _extract_offer_letter,
    DocumentKind.CV.value: _extract_cv,
}


@router.post("/{document_id}/extract", response_model=ExtractDocumentResponse)
def extract_document(org_id: int, document_id: int, db: Session = Depends(get_db)):
    doc = _get_doc_or_404(db, org_id, document_id)

    if doc.kind == DocumentKind.ROSTER.value:
        return _extract_roster(db, org_id, doc)

    handler = _LLM_KINDS.get(doc.kind)
    if handler is None:
        mark_needs_review(
            db, doc, f"No parser for kind {doc.kind!r} yet.",
        )
        return _empty_extract(doc)

    if not is_ingest_llm_enabled():
        mark_needs_review(
            db, doc,
            "Free-text extraction needs COMPANYSIM_LLM_INGEST=1, a GROQ_API_KEY, "
            "and the 'llm' extra installed. Nothing was extracted.",
        )
        return _empty_extract(doc)

    # Tokens are recorded even when the handler parks the document — a
    # refused extraction still paid for the read that refused it.
    with collect() as calls:
        result = handler(db, org_id, doc)
    record_llm_calls(db, calls, org_id=org_id)
    return result


def _create_employee_from_roster_row(
    db: Session, org_id: int, row: RosterRow,
    department_ids: dict[str, int], team_ids: dict[str, int],
) -> tuple[EmployeeRecord | None, str | None]:
    """Create a new hire from a roster row, or return why we can't.

    Departments and teams are resolved by name and never created: a
    roster naming an unknown department is far more likely a typo or a
    stale export than a genuine reorg, and silently inventing org
    structure from a spreadsheet is exactly the kind of unreviewed write
    this whole staging pipeline exists to prevent. With no team named,
    the employee joins the department's first team — an org's structure
    has to place everyone somewhere, and that's stated here rather than
    hidden.
    """
    if not row.department_name:
        return None, "roster row names no department"
    dept_id = department_ids.get(row.department_name.strip().lower())
    if dept_id is None:
        return None, f"department {row.department_name!r} does not exist in this org"

    team_id = None
    if row.team_name:
        team_id = team_ids.get(row.team_name.strip().lower())
        if team_id is None:
            return None, f"team {row.team_name!r} does not exist in this org"
    else:
        first = (
            db.query(TeamRecord)
            .filter_by(org_id=org_id, department_id=dept_id)
            .order_by(TeamRecord.id)
            .first()
        )
        if first is None:
            return None, f"department {row.department_name!r} has no team to place them in"
        team_id = first.id

    emp = EmployeeRecord(
        org_id=org_id, department_id=dept_id, team_id=team_id,
        full_name=row.full_name or row.email.split("@")[0],
        email=row.email,
        level=row.level or "IC1",
        role=row.role or "Individual Contributor",
        tenure_months=row.tenure_months if row.tenure_months is not None else 0,
        base_salary=row.base_salary if row.base_salary is not None else 70_000.0,
        work_mode="hybrid",
        promotions_count=row.promotions_count or 0,
        # Same neutral day-0 latents a manually-added employee gets — a
        # roster says nothing about wellbeing, and inventing values would
        # be exactly the fabrication this pipeline refuses elsewhere.
        productivity=0.5, engagement=0.5, collaboration=0.5, turnover_risk=0.4,
    )
    db.add(emp)
    db.flush()
    db.add(EmployeeWellbeingRecord(employee_id=emp.id, **_DEFAULT_WELLBEING))
    return emp, None


@router.post("/{document_id}/apply", response_model=ApplyFactsResponse)
def apply_facts(
    org_id: int, document_id: int, body: ApplyFactsRequest, db: Session = Depends(get_db),
):
    doc = _get_doc_or_404(db, org_id, document_id)
    pending = pending_facts_for_document(db, doc.id)
    approved_ids = set(body.approved_fact_ids)

    department_ids = {
        d.name.strip().lower(): d.id
        for d in db.query(DepartmentRecord).filter_by(org_id=org_id).all()
    }
    team_ids = {
        t.name.strip().lower(): t.id
        for t in db.query(TeamRecord).filter_by(org_id=org_id).all()
    }

    n_applied = 0
    n_rejected = 0
    n_created = 0
    unapplied: list[str] = []

    def reject(fact: ExtractedFactRecord, message: str | None = None) -> None:
        nonlocal n_rejected
        fact.review_status = "rejected"
        n_rejected += 1
        if message:
            unapplied.append(message)

    for fact in pending:
        if fact.id not in approved_ids:
            reject(fact)
            continue

        if fact.field_name == NEW_HIRE_FIELD:
            try:
                row = RosterRow.model_validate_json(fact.proposed_value)
            except ValueError:
                reject(fact, f"fact {fact.id}: staged new-hire row is unreadable")
                continue
            emp, error = _create_employee_from_roster_row(
                db, org_id, row, department_ids, team_ids,
            )
            if emp is None:
                reject(fact, f"fact {fact.id} (new hire {row.email}): {error}")
                continue
            stamp_applied(db, fact)
            n_applied += 1
            n_created += 1
            continue

        emp = db.query(EmployeeRecord).filter_by(org_id=org_id, id=fact.target_employee_id).first()
        if emp is None:
            reject(fact, f"fact {fact.id} ({fact.field_name}): employee no longer exists")
            continue

        if fact.field_name in NAME_FIELD_TO_FK:
            lookup = department_ids if fact.field_name == "department_name" else team_ids
            resolved = lookup.get(fact.proposed_value.strip().lower())
            if resolved is None:
                reject(
                    fact,
                    f"fact {fact.id} ({fact.field_name}): "
                    f"{fact.proposed_value!r} does not exist in this org",
                )
                continue
            setattr(emp, NAME_FIELD_TO_FK[fact.field_name], resolved)
            stamp_applied(db, fact)
            n_applied += 1
            continue

        coerce = _FIELD_COERCERS.get(fact.field_name)
        if coerce is None:
            reject(fact, f"fact {fact.id} ({fact.field_name}): unknown field")
            continue
        setattr(emp, fact.field_name, coerce(fact.proposed_value))
        stamp_applied(db, fact)
        n_applied += 1

    db.commit()
    return ApplyFactsResponse(
        n_applied=n_applied, n_rejected=n_rejected,
        n_employees_created=n_created, unapplied=unapplied,
    )
