"""Extraction contracts — what a parser is *allowed* to pull from a document.

One pydantic model per document kind (only ``RosterRow`` exists in Phase 2).
These schemas are the ethical boundary as much as the type boundary:

    NO psychological or life-context fields (ace_score, attachment_style,
    childhood_ses_quintile, anxiety/depression scores, ...) may EVER appear
    in an extraction schema. ``data/human_factors.py`` documents those as
    internal latent variables a real employer does not and should not
    measure — they exist for population realism in the *synthetic*
    generator only. Ingesting them from real documents about real people
    would break that stated ethic, so the restriction is enforced here at
    the schema level (a parser physically has nowhere to put such a value),
    not by a runtime check.

Same structural trick :class:`ResignationLetterExtract` uses against
temporal leakage — make the wrong thing unrepresentable rather than
detected.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class RosterRow(BaseModel):
    """One employee line from a roster export. ``email`` is the match key
    against ``EmployeeRecord`` (names collide and get re-formatted;
    emails are stable identifiers in every real HRIS export), so it's the
    only required field.
    """

    email: str
    full_name: str | None = None
    level: str | None = None
    role: str | None = None
    department_name: str | None = None
    team_name: str | None = None
    tenure_months: int | None = None
    base_salary: float | None = None
    promotions_count: int | None = None


class OfferLetterExtract(BaseModel):
    """A signed/issued offer — the document that actually hires someone.

    Carries everything :func:`companysim.ingest.reconcile.reconcile_roster`
    would have produced for an unmatched roster row, because that is exactly
    what it becomes: a ``new_hire`` proposal. ``department_name`` is
    required rather than optional — an employee has to be placed somewhere,
    and an offer letter that doesn't say where is not actionable, so the
    honest response is to refuse the extraction rather than stage a
    proposal that apply will only reject later.
    """

    candidate_email: str
    candidate_name: str
    department_name: str
    level: str | None = None
    role: str | None = None
    team_name: str | None = None
    base_salary: float | None = None
    start_date: date | None = None


class CvExtract(BaseModel):
    """A candidate CV / résumé.

    Deliberately weaker than :class:`OfferLetterExtract`: a CV states who
    someone is and what they've done, but not what you are hiring them
    *into*. Department and salary are the org's decision, made in an offer,
    not facts the candidate asserts — so they are optional here and a CV
    that omits them stages a proposal that apply will refuse with "names no
    department". That refusal is the correct outcome, not a gap: a CV alone
    should not be able to put someone on the payroll.

    ``years_experience`` and ``most_recent_title`` are captured for the
    reviewer's judgement and are **not** featurized — nothing in
    ``FEATURE_COLUMNS`` corresponds to them, and inventing a mapping from a
    self-reported CV to a model feature is exactly the kind of
    unaccountable inference this pipeline avoids.
    """

    candidate_email: str
    candidate_name: str
    most_recent_title: str | None = None
    years_experience: float | None = Field(default=None, ge=0, le=60)
    department_name: str | None = None
    level: str | None = None


class PerformanceReviewExtract(BaseModel):
    """A performance review's structured content — the only extraction
    schema that carries a model *feature* (``rating``), and therefore the
    only one subject to the temporal-leakage guard
    (``ml.turnover_features.assert_no_temporal_leakage``).

    ``review_period_end`` is required precisely because that guard needs
    it: a review with no date can't be proven to predate an outcome
    window, so it can never be used safely and there's no point ingesting
    it. ``summary_text`` is free prose kept for human review only — it is
    never featurized.
    """

    employee_email: str
    review_period_end: date
    rating: float = Field(ge=1.0, le=5.0)
    summary_text: str = ""


class ResignationLetterExtract(BaseModel):
    """A resignation letter's structured content — deliberately label-only.

    This schema has NO feature fields, and that absence is the design.
    A resignation letter is written *at* the moment of the outcome it
    describes, so anything it says about workload, manager support or
    morale is post-outcome information; featurizing it would be textbook
    temporal leakage dressed up as insight. Making the fields
    unrepresentable is a stronger guarantee than a runtime check, because
    a parser then has physically nowhere to put such a value.

    What it may contribute: the quit *label* (with its date, so a cohort
    can decide whether the exit falls inside its outcome window) and the
    note *text*, which flows into ``ExitNoteRecord`` for the same
    sentiment/theme analysis ``ml.exit_notes.analyze_note`` already runs
    over simulated notes.
    """

    employee_email: str
    effective_date: date
    is_voluntary: bool = True
    note_text: str = ""
