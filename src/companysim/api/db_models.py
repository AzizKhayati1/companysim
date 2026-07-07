"""ORM models — the persisted, editable mirror of a generated org.

Employee/Department/Team mirror `companysim.data.schemas`; EmployeeWellbeing
mirrors the columns `companysim.data.human_factors.generate_human_factors`
produces. Everything is persisted at org-creation time (see
`companysim.api.seed.create_org`), even the fields not yet exposed as
editable in the UI — so nothing about the original generator is lost, and
more fields can become editable later without a schema change.
"""
from __future__ import annotations

from datetime import datetime, timezone

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
    the employee's current wellbeing snapshot). ``*_pulse_trend`` and
    ``rating_*`` aren't stored here — they're always the same constant
    placeholder in that adapter (no week-by-week history or performance
    reviews in this schema), so they're reconstructed at read time instead
    of persisted as dead columns. ``quit_within_horizon`` is organic-only
    (see ``OrganizationModel.organic_quit_ids``) — never true just because
    an injected Layoff/Termination event removed the employee.
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

    org: Mapped["OrgRecord"] = relationship(back_populates="training_examples")
