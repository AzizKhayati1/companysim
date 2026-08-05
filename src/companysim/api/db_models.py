"""ORM models — the persisted, editable mirror of a generated org.

Employee/Department/Team mirror `companysim.data.schemas`; EmployeeWellbeing
mirrors the columns `companysim.data.human_factors.generate_human_factors`
produces. Everything is persisted at org-creation time (see
`companysim.api.seed.create_org`), even the fields not yet exposed as
editable in the UI — so nothing about the original generator is lost, and
more fields can become editable later without a schema change.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from companysim.api.database import Base

# Single source of truth for the EmployeeWellbeingRecord's data columns
# (excludes id/employee_id) — reused by seed.py (DB insert) and
# converters.py (DB -> DataFrame for HumanProfile.from_row).
WELLBEING_COLUMNS: tuple[str, ...] = (
    "openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism",
    "education_level", "first_gen_professional", "childhood_ses_quintile", "ace_score",
    "attachment_style", "financial_security_score", "caregiving_load",
    "commute_burden_minutes", "hours_slept_typical", "physical_health_score",
    "recent_life_event", "months_since_life_event", "social_support_score",
    "mood", "stress_level", "sleep_quality", "energy_level",
    "anxiety_symptom_score", "depression_symptom_score", "life_satisfaction",
    "burnout_exhaustion", "burnout_cynicism", "burnout_efficacy",
    "workload_perceived", "autonomy_score", "psychological_safety_perceived",
    "manager_support_score", "peer_support_score", "meaning_at_work_score",
    "growth_opportunity_score", "recognition_score", "role_clarity_score",
    "effort_reward_imbalance", "eap_utilization_last_year", "mental_health_engagement",
    "wellness_program_participation",
)


class OrgRecord(Base):
    __tablename__ = "orgs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    seed: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    departments: Mapped[list["DepartmentRecord"]] = relationship(
        back_populates="org", cascade="all, delete-orphan",
    )
    teams: Mapped[list["TeamRecord"]] = relationship(
        back_populates="org", cascade="all, delete-orphan",
    )
    employees: Mapped[list["EmployeeRecord"]] = relationship(
        back_populates="org", cascade="all, delete-orphan",
        foreign_keys="EmployeeRecord.org_id",
    )
    runs: Mapped[list["RunRecord"]] = relationship(
        back_populates="org", cascade="all, delete-orphan",
    )
    training_examples: Mapped[list["TurnoverTrainingExample"]] = relationship(
        back_populates="org", cascade="all, delete-orphan",
    )
    risk_snapshots: Mapped[list["EmployeeRiskSnapshot"]] = relationship(
        back_populates="org", cascade="all, delete-orphan",
    )
    exit_note_records: Mapped[list["ExitNoteRecord"]] = relationship(
        back_populates="org", cascade="all, delete-orphan",
    )
    source_documents: Mapped[list["SourceDocumentRecord"]] = relationship(
        back_populates="org", cascade="all, delete-orphan",
    )
    extracted_facts: Mapped[list["ExtractedFactRecord"]] = relationship(
        back_populates="org", cascade="all, delete-orphan",
    )
    performance_reviews: Mapped[list["PerformanceReviewRecord"]] = relationship(
        back_populates="org", cascade="all, delete-orphan",
    )


class DepartmentRecord(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    name: Mapped[str]
    salary_multiplier: Mapped[float] = mapped_column(default=1.0)
    head_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", use_alter=True), nullable=True,
    )

    org: Mapped["OrgRecord"] = relationship(back_populates="departments")


class TeamRecord(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    name: Mapped[str]
    manager_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", use_alter=True), nullable=True,
    )

    org: Mapped["OrgRecord"] = relationship(back_populates="teams")


class EmployeeRecord(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)

    full_name: Mapped[str]
    email: Mapped[str]
    level: Mapped[str]
    role: Mapped[str]
    tenure_months: Mapped[int]
    base_salary: Mapped[float]
    work_mode: Mapped[str] = mapped_column(default="hybrid")
    promotions_count: Mapped[int] = mapped_column(default=0)

    # Sim-facing latents, seeded once at creation. A simulation run reads
    # these as day-0 state but never writes results back — edits only
    # happen through the CRUD endpoints.
    productivity: Mapped[float]
    engagement: Mapped[float]
    collaboration: Mapped[float]
    turnover_risk: Mapped[float]

    org: Mapped["OrgRecord"] = relationship(back_populates="employees", foreign_keys=[org_id])
    wellbeing: Mapped["EmployeeWellbeingRecord"] = relationship(
        back_populates="employee", uselist=False, cascade="all, delete-orphan",
    )


class EmployeeWellbeingRecord(Base):
    """1:1 with EmployeeRecord — mirrors generate_human_factors' profile columns."""

    __tablename__ = "employee_wellbeing"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), unique=True)

    # Big Five
    openness: Mapped[float]
    conscientiousness: Mapped[float]
    extraversion: Mapped[float]
    agreeableness: Mapped[float]
    neuroticism: Mapped[float]

    # Life context
    education_level: Mapped[str]
    first_gen_professional: Mapped[int]
    childhood_ses_quintile: Mapped[int]
    ace_score: Mapped[int]
    attachment_style: Mapped[str]
    financial_security_score: Mapped[float]
    caregiving_load: Mapped[float]
    commute_burden_minutes: Mapped[int]
    hours_slept_typical: Mapped[float]
    physical_health_score: Mapped[float]
    recent_life_event: Mapped[str]
    months_since_life_event: Mapped[int]
    social_support_score: Mapped[float]

    # Wellbeing state
    mood: Mapped[float]
    stress_level: Mapped[float]
    sleep_quality: Mapped[float]
    energy_level: Mapped[float]
    anxiety_symptom_score: Mapped[float]
    depression_symptom_score: Mapped[float]
    life_satisfaction: Mapped[float]

    # Burnout (Maslach subscales)
    burnout_exhaustion: Mapped[float]
    burnout_cynicism: Mapped[float]
    burnout_efficacy: Mapped[float]

    # Work environment
    workload_perceived: Mapped[float]
    autonomy_score: Mapped[float]
    psychological_safety_perceived: Mapped[float]
    manager_support_score: Mapped[float]
    peer_support_score: Mapped[float]
    meaning_at_work_score: Mapped[float]
    growth_opportunity_score: Mapped[float]
    recognition_score: Mapped[float]
    role_clarity_score: Mapped[float]
    effort_reward_imbalance: Mapped[float]

    # Mental health utilization
    eap_utilization_last_year: Mapped[int]
    mental_health_engagement: Mapped[str]
    wellness_program_participation: Mapped[float]

    employee: Mapped["EmployeeRecord"] = relationship(back_populates="wellbeing")


class RunRecord(Base):
    """A saved simulate/diagnose call — request + response as submitted and
    returned, so a past run can be reopened exactly as it looked (the sim is
    seeded, but this avoids depending on that to reproduce a historical view).
    """

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    run_type: Mapped[str]  # "simulate" | "diagnose"
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    summary: Mapped[str]
    request_json: Mapped[str] = mapped_column(Text)
    response_json: Mapped[str] = mapped_column(Text)

    org: Mapped["OrgRecord"] = relationship(back_populates="runs")


class TurnoverTrainingExample(Base):
    """A labeled example collected from a real webapp simulate/diagnose run.

    Features mirror ``api.scoring_frame.build_scoring_frame``'s
    ``FEATURE_COLUMNS``-shaped output (job/comp facts exact, pulse "mean" =
    the employee's current wellbeing snapshot). ``*_pulse_trend`` is still
    a constant placeholder in that adapter (no week-by-week pulse history
    in this schema) and so is reconstructed at read time rather than
    persisted as a dead column.

    ``rating_last``/``rating_prev``/``rating_delta`` *used* to be in that
    same category and deliberately weren't stored. They are stored now:
    once ``PerformanceReviewRecord`` exists, ``build_scoring_frame`` reads
    real ratings for any employee who has reviews ingested, so the value
    varies per employee and per collection time and can no longer be
    reconstructed from a constant. Rows collected before document
    ingestion existed carry the old 3.0/3.0/0.0 — which is exactly what
    they were, so the backfill is honest rather than an approximation.

    ``quit_within_horizon`` is organic-only (see
    ``OrganizationModel.organic_quit_ids``) — never true just because an
    injected Layoff/Termination event removed the employee.
    """

    __tablename__ = "turnover_training_examples"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    # Plain int, no FK — lineage/debugging only, so this row survives even
    # if the employee is later edited or deleted from the org.
    employee_id: Mapped[int]
    collected_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    horizon_ticks: Mapped[int]
    quit_within_horizon: Mapped[bool]

    level: Mapped[str]
    department_id: Mapped[str]
    role: Mapped[str]
    tenure_months: Mapped[int]
    base_salary: Mapped[float]
    team_size: Mapped[int]
    is_manager: Mapped[int]
    promotions_count: Mapped[int]
    mood_pulse_mean: Mapped[float]
    stress_level_pulse_mean: Mapped[float]
    sleep_quality_pulse_mean: Mapped[float]
    energy_level_pulse_mean: Mapped[float]
    burnout_exhaustion_pulse_mean: Mapped[float]
    # server_default backfills pre-ingestion rows with the constant they
    # actually had, so the migration doesn't need to guess.
    rating_last: Mapped[float] = mapped_column(default=3.0, server_default="3.0")
    rating_prev: Mapped[float] = mapped_column(default=3.0, server_default="3.0")
    rating_delta: Mapped[float] = mapped_column(default=0.0, server_default="0.0")

    org: Mapped["OrgRecord"] = relationship(back_populates="training_examples")


class EmployeeRiskSnapshot(Base):
    """The production model's predicted turnover risk for one employee, at
    the moment a Simulate/Diagnose run happened — one row per employee per
    run. Powers the per-employee risk-history trend view. Unlike
    ``TurnoverTrainingExample`` this has no minimum-horizon gate and is
    recorded for every run (including Monte Carlo replicates), since it only
    reflects the current org state, not a simulated outcome.
    """

    __tablename__ = "employee_risk_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    # FK for lineage only, no cascade tied to it — matches
    # TurnoverTrainingExample.run_id, so deleting an individual run (Run
    # History's Delete button) doesn't silently destroy risk history.
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    # Plain int, no FK — survives even if the employee is later edited or
    # deleted from the org (same reasoning as TurnoverTrainingExample).
    employee_id: Mapped[int]
    computed_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    turnover_probability: Mapped[float]
    risk_tier: Mapped[str]
    model_available: Mapped[bool]

    org: Mapped["OrgRecord"] = relationship(back_populates="risk_snapshots")


class ExitNoteRecord(Base):
    """One row per individual exit-interview note — generated in real time
    during a Diagnose run (see ``api.exit_note_records.record_exit_notes``,
    called from ``routers.diagnose``), or recovered after the fact by
    ``scripts/backfill_exit_note_records.py`` from the sample quotes a
    historical run happened to save in its ``RunRecord.response_json``
    (``is_backfilled=True`` on those rows). Powers the Exit Notes Insights
    page's theme-frequency, sentiment-trend, and recent-quotes views.
    """

    __tablename__ = "exit_note_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    # Lineage-only FK, no cascade — matches EmployeeRiskSnapshot.run_id, so
    # deleting a run via Run History doesn't erase insight history.
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    # Nullable only for backfilled rows: a historical run's response_json
    # only kept sample_quotes' text, with no employee linkage to recover.
    # Real-time rows always populate this.
    employee_id: Mapped[int | None] = mapped_column(nullable=True)
    text: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[float]
    # Comma-joined theme keys from exit_notes._THEME_KEYWORDS ("" when none
    # matched) — plain delimited text, not a JSON column: no other column
    # in this schema stores structured JSON, and the theme lexicon is a
    # fixed, small, comma-free snake_case set.
    themes: Mapped[str] = mapped_column(Text, default="")
    is_llm_generated: Mapped[bool] = mapped_column(default=False)
    # True only for rows recovered by the backfill script, so the UI can
    # visually distinguish "real, fully-attributed" from "recovered,
    # approximate" provenance.
    is_backfilled: Mapped[bool] = mapped_column(default=False)
    # Set only for notes lifted from a real uploaded resignation letter
    # (``routers/ingest.py``). Null for every simulated note. Deliberately a
    # nullable FK rather than a third ``is_*`` boolean alongside
    # is_llm_generated/is_backfilled: three orthogonal booleans would leave
    # provenance implicit, and this way an ingested note keeps a live link
    # back to the document it was quoted from.
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id"), nullable=True,
    )
    generated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    org: Mapped["OrgRecord"] = relationship(back_populates="exit_note_records")
    source_document: Mapped["SourceDocumentRecord | None"] = relationship(
        back_populates="exit_notes",
    )


class SourceDocumentRecord(Base):
    """An uploaded real-world document (roster CSV, performance review,
    resignation letter, ...) plus its extracted plain text and provenance —
    the raw-material end of the document-ingestion pipeline (see
    ``api.ingest_records`` and ``companysim.ingest``).

    ``raw_text`` is stored rather than the original bytes: every parser
    downstream (rules today, LLM later) consumes text, re-upload is cheap
    if the original is ever needed again, and keeping binary blobs out of
    SQLite keeps the DB browsable. ``content_hash`` (sha256 of the upload
    bytes) dedups repeat uploads per org — the same export uploaded twice
    would otherwise stage the same change set twice. ``as_of_date`` is the
    date the document's facts are true *as of*, supplied at upload because
    it usually isn't recoverable from file contents — it exists so the
    later cohort-building phase can enforce its temporal-leakage guard
    (features must predate the outcome window; a resignation letter is
    written *at* the outcome). ``extraction_status`` is the document's
    lifecycle ("pending" → "extracted" | "needs_review", and
    "needs_review" explicitly means "we refused to fabricate an extraction
    for this kind", not "something crashed" — crashes land in
    ``extraction_error``).
    """

    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    kind: Mapped[str]  # ingest.documents.DocumentKind values
    filename: Mapped[str]
    content_hash: Mapped[str]
    raw_text: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    as_of_date: Mapped[date | None] = mapped_column(nullable=True)
    extraction_status: Mapped[str] = mapped_column(default="pending")
    # Which parser produced the staged facts ("rules" today, "groq:<model>"
    # once the LLM path lands) — per-fact provenance would be redundant
    # since one extract pass uses one parser for the whole document.
    extractor: Mapped[str | None] = mapped_column(nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    org: Mapped["OrgRecord"] = relationship(back_populates="source_documents")
    # Deleting an upload withdraws everything it asserted. All three
    # children cascade for the same reason: a staged proposal, an ingested
    # review and an ingested exit note only exist *because* this document
    # said so, and none of them can be audited once the evidence is gone.
    # (Changes already applied to EmployeeRecord are not children and
    # correctly survive — those are the org's own data now.)
    facts: Mapped[list["ExtractedFactRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan",
    )
    performance_reviews: Mapped[list["PerformanceReviewRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan",
    )
    exit_notes: Mapped[list["ExitNoteRecord"]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan",
    )


class ExtractedFactRecord(Base):
    """One proposed change staged from a document — the human-review gate
    between "a parser read something" and "the org's data changed".

    Nothing extracted is ever applied directly to ``EmployeeRecord``;
    every fact sits here as pending until a person approves it (see
    ``routers/ingest.py``'s apply endpoint). ``evidence_span`` is the
    verbatim source text the value came from — same checkability
    discipline as ``ml.diagnostics`` (every claim traces to something
    inspectable), and the only defense against a parser misreading a
    salary once the LLM path exists. ``target_employee_id`` is a plain
    int, no FK — same lineage-survives-deletion reasoning as
    ``TurnoverTrainingExample.employee_id``. ``document_id`` *is* a real
    cascading FK, deliberately: an unapplied fact is meaningless without
    the document whose evidence it quotes, so deleting an upload withdraws
    its staged proposals (already-applied changes live in
    ``EmployeeRecord`` itself and survive). Values are stored as strings
    (``proposed_value``/``current_value``) because one staging table
    serves fields of every type — the apply step coerces using the live
    ORM column's Python type, not a per-fact type tag.
    """

    __tablename__ = "extracted_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    target_table: Mapped[str]  # "employees" (only value in Phase 2)
    target_employee_id: Mapped[int | None] = mapped_column(nullable=True)
    field_name: Mapped[str]
    proposed_value: Mapped[str]
    current_value: Mapped[str | None] = mapped_column(nullable=True)
    confidence: Mapped[float]
    review_status: Mapped[str] = mapped_column(default="pending")
    evidence_span: Mapped[str] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(nullable=True)

    document: Mapped["SourceDocumentRecord"] = relationship(back_populates="facts")
    org: Mapped["OrgRecord"] = relationship(back_populates="extracted_facts")


class LlmUsageRecord(Base):
    """One billed Groq request — the row behind the token counter.

    Written by ``api.llm_usage`` from whatever a router's
    ``companysim.llm.usage.collect()`` block accumulated, so the LLM
    modules themselves stay free of any database import (see that module's
    docstring for why the sink exists).

    One row per *request*, not per user action: a tool-calling chat answer
    makes several round trips and each is billed separately, so collapsing
    them would under-report. ``org_id`` is nullable and carries no
    ForeignKey — chat and ingest are org-scoped but exit notes are
    generated inside a run that may outlive the org, and a usage/billing
    log should survive a deleted org rather than cascade away with it.
    That's the opposite choice from ``ExitNoteRecord``, and deliberately:
    an exit note without its org is meaningless, a token charge isn't.
    """

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int | None] = mapped_column(nullable=True)
    feature: Mapped[str]  # companysim.llm.usage.FEATURE_* values
    model: Mapped[str]
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    # From the provider, not summed locally — Groq bills on its own count.
    total_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), index=True,
    )


class PerformanceReviewRecord(Base):
    """One ingested performance review — the first real *feature* source in
    this schema, and the reason document ingestion earns its place in the
    ML pipeline rather than just the org editor.

    ``api.scoring_frame`` has always had to fake
    ``rating_last``/``rating_prev``/``rating_delta`` at a neutral 3.0/3.0/0.0
    because the webapp had no performance-review history to read (see that
    module's docstring). Rows here are what turn three of the turnover
    model's eighteen numeric features from dead constants into real signal;
    an employee with no reviews ingested still falls back to the same
    neutral constants, so ingestion is purely additive.

    ``review_period_end`` — not the upload time — is what orders reviews
    into last/prev, because that's the date the rating describes and the
    date the temporal-leakage guard checks against an outcome window
    (``ml.turnover_features.assert_no_temporal_leakage``). ``rating`` is a
    float on the generator's 1..5 scale, matching
    ``data/datasets.py``'s ``performance_history`` table so the offline
    pipeline and the webapp mean the same thing by "a 3".
    """

    __tablename__ = "performance_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    # Plain int, no FK — lineage survives an employee edit/delete, same
    # reasoning as TurnoverTrainingExample.employee_id.
    employee_id: Mapped[int]
    # Cascading FK: a review only exists because a document was ingested,
    # and deleting that upload should withdraw what it asserted.
    document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    review_period_end: Mapped[date]
    rating: Mapped[float]
    summary_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    org: Mapped["OrgRecord"] = relationship(back_populates="performance_reviews")
    document: Mapped["SourceDocumentRecord"] = relationship(back_populates="performance_reviews")
