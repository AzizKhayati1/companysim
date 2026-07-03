"""Human factors — psychological, wellbeing, and life-context modeling.

Draws on established organizational-psychology and occupational-health
frameworks used in workplace intervention research:

- Big Five personality (Costa & McCrae, 1992) — stable trait dimensions
- Maslach Burnout Inventory (Maslach & Jackson, 1981) — exhaustion,
  cynicism, professional efficacy
- Job Demand-Control-Support model (Karasek 1979; Johnson & Hall 1988) —
  workload / autonomy / support interactions
- Adverse Childhood Experiences (Felitti et al., 1998) — early-life
  adversity index, well-validated as a life-course predictor of adult
  wellbeing
- Adult attachment theory (Bowlby / Hazan & Shaver) — secure, anxious,
  avoidant, fearful styles
- Psychological safety (Edmondson, 1999) — team-level trust construct
- Effort-Reward Imbalance (Siegrist, 1996) — chronic stress mechanism

**Everything here is synthetic.** No real person is described. The purpose
is to give the simulation enough behavioral surface area to model
interventions (EAP programs, workload rebalancing, manager training,
flexible-work policies) and observe plausible downstream effects on
productivity, engagement, and turnover.

**Ethical scope.** This data is a *research testbed for organizational
policy simulation*. It is not intended for scoring, ranking, or making
decisions about real employees, and must not be used to profile
individuals. See the project README for the broader ethics stance on
synthetic HR data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# ---- Categorical vocabularies -----------------------------------------------

EDUCATION_LEVELS: list[str] = [
    "High School", "Some College", "Associate", "Bachelor",
    "Master", "PhD", "Bootcamp / Vocational",
]
EDUCATION_WEIGHTS: list[float] = [0.05, 0.08, 0.06, 0.48, 0.22, 0.06, 0.05]

# Attachment style (Hazan & Shaver, 1987 — four-category model).
ATTACHMENT_STYLES: list[str] = ["secure", "anxious", "avoidant", "fearful"]
ATTACHMENT_WEIGHTS: list[float] = [0.55, 0.15, 0.20, 0.10]

# Recent-life-event categories. Only presence + type are stored — no dates,
# no narrative content. Frequencies are rough US population priors for a
# rolling 12-month window (multiple events possible in reality; we sample
# at most one for tractability).
LIFE_EVENT_TYPES: list[str] = [
    "none", "bereavement", "birth_or_adoption", "moved_house",
    "divorce_or_separation", "serious_illness", "caregiving_onset",
    "financial_shock",
]
LIFE_EVENT_WEIGHTS: list[float] = [0.70, 0.04, 0.05, 0.07, 0.03, 0.04, 0.04, 0.03]

# EAP / mental-health service utilization (last 12 months, self-reported
# in the sim's synthetic pulse survey — a fraction of the workforce).
MH_ENGAGEMENT_LEVELS: list[str] = [
    "none", "self-help_apps", "therapy_occasional", "therapy_regular",
    "medication_only", "medication_and_therapy",
]
MH_ENGAGEMENT_WEIGHTS: list[float] = [0.55, 0.15, 0.10, 0.10, 0.03, 0.07]


# ---- Column groups (for downstream consumers) -------------------------------

BIG_FIVE: tuple[str, ...] = (
    "openness", "conscientiousness", "extraversion",
    "agreeableness", "neuroticism",
)

WELLBEING_STATE: tuple[str, ...] = (
    "mood", "stress_level", "sleep_quality", "energy_level",
    "burnout_exhaustion", "burnout_cynicism", "burnout_efficacy",
    "anxiety_symptom_score", "depression_symptom_score",
    "life_satisfaction",
)

LIFE_CONTEXT: tuple[str, ...] = (
    "education_level",
    "first_gen_professional",
    "childhood_ses_quintile",       # 1 (lowest) — 5 (highest)
    "ace_score",                    # 0–10 adverse childhood experiences
    "attachment_style",
    "financial_security_score",     # 0..1
    "caregiving_load",              # 0..1
    "commute_burden_minutes",
    "hours_slept_typical",
    "physical_health_score",        # 0..1
    "recent_life_event",
    "months_since_life_event",
    "social_support_score",         # non-work network, 0..1
)

WORK_ENVIRONMENT: tuple[str, ...] = (
    "workload_perceived",            # 0..1 (higher = more overloaded)
    "autonomy_score",                # 0..1
    "psychological_safety_perceived",  # 0..1
    "manager_support_score",         # 0..1
    "peer_support_score",            # 0..1
    "meaning_at_work_score",         # 0..1
    "growth_opportunity_score",      # 0..1
    "recognition_score",             # 0..1
    "role_clarity_score",            # 0..1
    "effort_reward_imbalance",       # 0..1 (higher = worse)
)

MENTAL_HEALTH_UTILIZATION: tuple[str, ...] = (
    "eap_utilization_last_year",     # bool → int 0/1
    "mental_health_engagement",      # categorical
    "wellness_program_participation",  # 0..1 proportion
)


# ---- Vectorized generators --------------------------------------------------


@dataclass
class HumanFactorsBundle:
    """DataFrame outputs of :func:`generate_human_factors`."""

    profile: pd.DataFrame               # one row per employee (static/current)
    wellness_snapshots: pd.DataFrame    # long: (employee_id, snapshot_date, ...)


def generate_human_factors(
    employees: pd.DataFrame,
    *,
    rng: np.random.Generator,
    reference_date,
    pulse_weeks: int = 12,
) -> HumanFactorsBundle:
    """Generate human-factor profiles and a rolling wellness pulse.

    ``employees`` must contain the columns: ``employee_id``, ``level``,
    ``tenure_months``, ``age``, ``department_id``, ``team_id``,
    ``productivity``, ``engagement``, ``turnover_risk``.

    The wellness pulse is one row per employee per week (last
    ``pulse_weeks`` weeks) — the sort of pulse-survey data a real
    engagement platform (Lattice, CultureAmp, Peakon) would produce.
    """
    n = len(employees)
    ids = employees["employee_id"].to_numpy()

    # --- Big Five: independent Betas, mode ~0.5, moderate spread. ---
    openness           = _beta(rng, 5, 5, n)
    conscientiousness  = _beta(rng, 6, 4, n)
    extraversion       = _beta(rng, 5, 5, n)
    agreeableness      = _beta(rng, 6, 4, n)
    neuroticism        = _beta(rng, 4, 6, n)

    # --- Life context ---
    education = rng.choice(EDUCATION_LEVELS, size=n, p=EDUCATION_WEIGHTS)
    first_gen = rng.random(n) < 0.28  # ~28% of US professionals
    childhood_ses = rng.choice([1, 2, 3, 4, 5], size=n,
                                p=[0.12, 0.18, 0.28, 0.26, 0.16])
    # ACE score correlates inversely with childhood SES on average.
    ace_lambda = 2.5 - 0.35 * childhood_ses
    ace = np.clip(rng.poisson(np.maximum(0.5, ace_lambda), size=n), 0, 10)

    attachment = rng.choice(ATTACHMENT_STYLES, size=n, p=ATTACHMENT_WEIGHTS)

    # Financial security: mildly correlated with level and childhood SES.
    level_idx = employees["level"].map(_LEVEL_SENIORITY_LOCAL).to_numpy()
    financial_security = np.clip(
        0.35 + 0.05 * level_idx + 0.04 * childhood_ses
        + rng.normal(0, 0.10, n),
        0, 1,
    )
    caregiving_load = np.clip(
        _beta(rng, 2, 5, n) + _age_caregiving_bump(employees["age"].to_numpy()),
        0, 1,
    )
    commute_burden = np.clip(
        rng.gamma(1.8, 22, n).astype(int), 0, 150,
    )
    hours_slept = np.clip(rng.normal(7.0, 1.0, n), 3.0, 10.0).round(2)
    physical_health = np.clip(
        0.75 - 0.005 * (employees["age"].to_numpy() - 30)
        + rng.normal(0, 0.12, n),
        0, 1,
    )
    life_event = rng.choice(LIFE_EVENT_TYPES, size=n, p=LIFE_EVENT_WEIGHTS)
    months_since_event = np.where(
        life_event == "none",
        -1,
        rng.integers(0, 12, size=n),
    )
    social_support = np.clip(
        0.4 + 0.15 * (attachment == "secure").astype(float)
        - 0.10 * (attachment == "avoidant").astype(float)
        + rng.normal(0, 0.15, n),
        0, 1,
    )

    # --- Wellbeing state (current) ---
    # Neuroticism drives anxiety/depression symptoms; life events push them up.
    life_event_hit = (life_event != "none").astype(float)
    anxiety = np.clip(
        0.25 + 0.45 * neuroticism + 0.15 * life_event_hit
        - 0.10 * social_support + rng.normal(0, 0.10, n),
        0, 1,
    )
    depression = np.clip(
        0.20 + 0.45 * neuroticism + 0.15 * life_event_hit
        - 0.12 * social_support - 0.10 * physical_health
        + rng.normal(0, 0.10, n),
        0, 1,
    )
    stress = np.clip(
        0.30 + 0.30 * neuroticism + 0.15 * life_event_hit
        + 0.10 * caregiving_load - 0.20 * financial_security
        + rng.normal(0, 0.10, n),
        0, 1,
    )
    sleep_quality = np.clip(
        0.4 + 0.06 * (hours_slept - 6.0) - 0.20 * stress
        - 0.10 * anxiety + rng.normal(0, 0.10, n),
        0, 1,
    )
    energy = np.clip(
        0.4 + 0.25 * sleep_quality + 0.15 * physical_health
        - 0.20 * depression + rng.normal(0, 0.08, n),
        0, 1,
    )
    mood = np.clip(
        0.35 + 0.30 * (1 - neuroticism) - 0.25 * depression
        + 0.15 * social_support + rng.normal(0, 0.08, n),
        0, 1,
    )
    life_satisfaction = np.clip(
        0.30 + 0.20 * financial_security + 0.20 * social_support
        + 0.15 * mood - 0.15 * depression + rng.normal(0, 0.08, n),
        0, 1,
    )

    # --- Burnout (Maslach subscales) ---
    # Bootstrapped from turnover_risk + neuroticism as latent drivers; the
    # dynamic build-up over ticks happens in the agent step. Coefficient on
    # turnover_risk kept high (0.55) because self-reported burnout is one of
    # the strongest real-world correlates of actual attrition — a pulse
    # survey genuinely does carry most of what "true" risk represents, it's
    # just noisier and lagged. A weak coefficient here would understate how
    # informative real engagement-platform data actually is.
    turnover_risk = employees["turnover_risk"].to_numpy()
    burnout_exhaustion = np.clip(
        0.12 + 0.55 * turnover_risk + 0.15 * neuroticism
        + 0.08 * stress + rng.normal(0, 0.06, n),
        0, 1,
    )
    burnout_cynicism = np.clip(
        0.15 + 0.30 * turnover_risk + 0.15 * neuroticism
        - 0.10 * agreeableness + rng.normal(0, 0.08, n),
        0, 1,
    )
    burnout_efficacy = np.clip(
        0.55 + 0.30 * employees["productivity"].to_numpy()
        - 0.15 * burnout_exhaustion + rng.normal(0, 0.06, n),
        0, 1,
    )

    # --- Work environment perceptions ---
    workload = np.clip(
        0.45 + 0.20 * (level_idx > 6).astype(float)     # managers report higher
        + 0.10 * neuroticism - 0.10 * autonomy_seed(level_idx, rng)
        + rng.normal(0, 0.10, n),
        0, 1,
    )
    autonomy = np.clip(
        0.35 + 0.05 * level_idx + 0.05 * openness
        + rng.normal(0, 0.10, n),
        0, 1,
    )
    psych_safety = np.clip(
        0.55 + 0.15 * agreeableness - 0.10 * neuroticism
        + rng.normal(0, 0.12, n),
        0, 1,
    )
    manager_support = np.clip(
        0.55 + 0.20 * psych_safety - 0.15 * workload
        + rng.normal(0, 0.10, n),
        0, 1,
    )
    peer_support = np.clip(
        0.55 + 0.15 * extraversion + 0.10 * agreeableness
        + 0.10 * psych_safety + rng.normal(0, 0.10, n),
        0, 1,
    )
    meaning = np.clip(
        0.45 + 0.15 * openness + 0.15 * conscientiousness
        + 0.10 * autonomy - 0.10 * burnout_cynicism
        + rng.normal(0, 0.10, n),
        0, 1,
    )
    growth = np.clip(
        0.4 + 0.10 * openness + 0.10 * (level_idx < 8).astype(float)
        + 0.10 * meaning + rng.normal(0, 0.10, n),
        0, 1,
    )
    recognition = np.clip(
        0.4 + 0.15 * manager_support + 0.10 * psych_safety
        + rng.normal(0, 0.10, n),
        0, 1,
    )
    role_clarity = np.clip(
        0.55 + 0.10 * conscientiousness + 0.10 * manager_support
        + rng.normal(0, 0.10, n),
        0, 1,
    )
    # Effort-Reward Imbalance rises when workload high but recognition low.
    eri = np.clip(0.5 + 0.3 * workload - 0.3 * recognition
                    + rng.normal(0, 0.05, n), 0, 1)

    # --- Mental health service utilization (subset engages) ---
    eap_util = (rng.random(n) < (0.08 + 0.20 * burnout_exhaustion)).astype(int)
    mh_engagement = rng.choice(MH_ENGAGEMENT_LEVELS, size=n, p=MH_ENGAGEMENT_WEIGHTS)
    wellness_participation = np.clip(
        _beta(rng, 3, 5, n) + 0.15 * conscientiousness,
        0, 1,
    )

    profile = pd.DataFrame({
        "employee_id": ids,
        # Big Five
        "openness": _round(openness),
        "conscientiousness": _round(conscientiousness),
        "extraversion": _round(extraversion),
        "agreeableness": _round(agreeableness),
        "neuroticism": _round(neuroticism),
        # Life context
        "education_level": education,
        "first_gen_professional": first_gen.astype(int),
        "childhood_ses_quintile": childhood_ses,
        "ace_score": ace,
        "attachment_style": attachment,
        "financial_security_score": _round(financial_security),
        "caregiving_load": _round(caregiving_load),
        "commute_burden_minutes": commute_burden,
        "hours_slept_typical": hours_slept,
        "physical_health_score": _round(physical_health),
        "recent_life_event": life_event,
        "months_since_life_event": months_since_event,
        "social_support_score": _round(social_support),
        # Wellbeing state (current)
        "mood": _round(mood),
        "stress_level": _round(stress),
        "sleep_quality": _round(sleep_quality),
        "energy_level": _round(energy),
        "anxiety_symptom_score": _round(anxiety),
        "depression_symptom_score": _round(depression),
        "life_satisfaction": _round(life_satisfaction),
        # Burnout
        "burnout_exhaustion": _round(burnout_exhaustion),
        "burnout_cynicism": _round(burnout_cynicism),
        "burnout_efficacy": _round(burnout_efficacy),
        # Work environment
        "workload_perceived": _round(workload),
        "autonomy_score": _round(autonomy),
        "psychological_safety_perceived": _round(psych_safety),
        "manager_support_score": _round(manager_support),
        "peer_support_score": _round(peer_support),
        "meaning_at_work_score": _round(meaning),
        "growth_opportunity_score": _round(growth),
        "recognition_score": _round(recognition),
        "role_clarity_score": _round(role_clarity),
        "effort_reward_imbalance": _round(eri),
        # Mental health utilization
        "eap_utilization_last_year": eap_util,
        "mental_health_engagement": mh_engagement,
        "wellness_program_participation": _round(wellness_participation),
    })

    wellness = _wellness_snapshots(
        ids=ids, mood_baseline=mood, stress_baseline=stress,
        sleep_baseline=sleep_quality, energy_baseline=energy,
        burnout_baseline=burnout_exhaustion,
        reference_date=reference_date,
        weeks=pulse_weeks,
        rng=rng,
    )
    return HumanFactorsBundle(profile=profile, wellness_snapshots=wellness)


# ---- Helpers ----------------------------------------------------------------


_LEVEL_SENIORITY_LOCAL: dict[str, int] = {
    "IC1": 1, "IC2": 2, "IC3": 3, "IC4": 4, "IC5": 5,
    "M1": 6, "M2": 7, "M3": 8, "VP": 9, "CXO": 10,
}


def _beta(rng: np.random.Generator, a: float, b: float, n: int) -> np.ndarray:
    return rng.beta(a, b, n)


def _round(x: np.ndarray) -> np.ndarray:
    return np.round(x, 4)


def _age_caregiving_bump(age: np.ndarray) -> np.ndarray:
    # 30-50yo have elevated caregiving loads (kids + aging parents).
    return np.where((age >= 30) & (age <= 55), 0.10, 0.0)


def autonomy_seed(level_idx: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return np.clip(0.5 + 0.03 * level_idx + rng.normal(0, 0.05, len(level_idx)), 0, 1)


def _wellness_snapshots(
    *,
    ids: np.ndarray,
    mood_baseline: np.ndarray,
    stress_baseline: np.ndarray,
    sleep_baseline: np.ndarray,
    energy_baseline: np.ndarray,
    burnout_baseline: np.ndarray,
    reference_date,
    weeks: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """One pulse-survey row per employee per week, ``weeks`` weeks back."""
    from datetime import timedelta  # noqa: PLC0415

    frames: list[pd.DataFrame] = []
    for w in range(weeks):
        snap_date = reference_date - timedelta(days=w * 7)
        # AR(1)-ish walk around the baseline.
        drift = rng.normal(0, 0.06, size=len(ids))
        mood_w = np.clip(mood_baseline + drift, 0, 1)
        stress_w = np.clip(stress_baseline + rng.normal(0, 0.07, len(ids)), 0, 1)
        sleep_w = np.clip(sleep_baseline + rng.normal(0, 0.06, len(ids)), 0, 1)
        energy_w = np.clip(energy_baseline + rng.normal(0, 0.06, len(ids)), 0, 1)
        burnout_w = np.clip(burnout_baseline + rng.normal(0, 0.05, len(ids)), 0, 1)
        # Randomly drop ~25% of rows to reflect real pulse-survey response
        # rates rather than perfectly complete panels.
        keep = rng.random(len(ids)) > 0.25
        frames.append(pd.DataFrame({
            "employee_id": ids[keep],
            "snapshot_date": snap_date,
            "mood": np.round(mood_w[keep], 4),
            "stress_level": np.round(stress_w[keep], 4),
            "sleep_quality": np.round(sleep_w[keep], 4),
            "energy_level": np.round(energy_w[keep], 4),
            "burnout_exhaustion": np.round(burnout_w[keep], 4),
        }))
    return pd.concat(frames, ignore_index=True)


# ---- Per-agent sampling for the sim ----------------------------------------


@dataclass
class HumanProfile:
    """Compact per-agent record consumed by :class:`EmployeeAgent.step`."""

    # Personality (stable over the sim horizon)
    conscientiousness: float
    neuroticism: float
    extraversion: float

    # Baselines
    baseline_workload: float
    autonomy: float
    meaning: float
    manager_support: float
    peer_support: float
    psychological_safety: float
    social_support: float
    financial_security: float
    caregiving_load: float
    physical_health: float

    # Dynamic state (mutated by step)
    burnout: float
    stress: float
    sleep_quality: float
    mood: float

    @classmethod
    def sample(cls, rng: np.random.Generator) -> "HumanProfile":
        """Independent sample for a sim-only employee (no dataset row)."""
        neuroticism = float(rng.beta(4, 6))
        return cls(
            conscientiousness=float(rng.beta(6, 4)),
            neuroticism=neuroticism,
            extraversion=float(rng.beta(5, 5)),
            baseline_workload=float(np.clip(0.45 + rng.normal(0, 0.12), 0, 1)),
            autonomy=float(np.clip(0.55 + rng.normal(0, 0.12), 0, 1)),
            meaning=float(np.clip(0.55 + rng.normal(0, 0.12), 0, 1)),
            manager_support=float(np.clip(0.60 + rng.normal(0, 0.12), 0, 1)),
            peer_support=float(np.clip(0.60 + rng.normal(0, 0.12), 0, 1)),
            psychological_safety=float(np.clip(0.60 + rng.normal(0, 0.12), 0, 1)),
            social_support=float(np.clip(0.55 + rng.normal(0, 0.12), 0, 1)),
            financial_security=float(np.clip(0.55 + rng.normal(0, 0.15), 0, 1)),
            caregiving_load=float(np.clip(rng.beta(2, 5), 0, 1)),
            physical_health=float(np.clip(0.65 + rng.normal(0, 0.12), 0, 1)),
            burnout=float(np.clip(0.25 + 0.35 * neuroticism + rng.normal(0, 0.05), 0, 1)),
            stress=float(np.clip(0.30 + 0.30 * neuroticism + rng.normal(0, 0.08), 0, 1)),
            sleep_quality=float(np.clip(0.55 + rng.normal(0, 0.12), 0, 1)),
            mood=float(np.clip(0.55 + rng.normal(0, 0.10), 0, 1)),
        )

    @classmethod
    def from_row(cls, row: "pd.Series") -> "HumanProfile":
        """Build a profile from a row of the ``human_factors`` table.

        This is what makes the exported dataset and the running simulation
        describe the *same* synthetic population: a turnover-label run that
        starts from a dataset snapshot and forward-simulates from it needs
        the agent's day-0 state to match what the feature row says, not an
        independently-sampled fiction. Column names differ slightly (the
        dataset favors descriptive suffixes like ``_score`` /
        ``_perceived``); this is a straight rename, no re-derivation.
        """
        return cls(
            conscientiousness=float(row["conscientiousness"]),
            neuroticism=float(row["neuroticism"]),
            extraversion=float(row["extraversion"]),
            baseline_workload=float(row["workload_perceived"]),
            autonomy=float(row["autonomy_score"]),
            meaning=float(row["meaning_at_work_score"]),
            manager_support=float(row["manager_support_score"]),
            peer_support=float(row["peer_support_score"]),
            psychological_safety=float(row["psychological_safety_perceived"]),
            social_support=float(row["social_support_score"]),
            financial_security=float(row["financial_security_score"]),
            caregiving_load=float(row["caregiving_load"]),
            physical_health=float(row["physical_health_score"]),
            burnout=float(row["burnout_exhaustion"]),
            stress=float(row["stress_level"]),
            sleep_quality=float(row["sleep_quality"]),
            mood=float(row["mood"]),
        )

    def as_public_dict(self) -> dict[str, Any]:
        """Fields safe to expose in aggregate metrics — no life-context PII."""
        return {
            "burnout": self.burnout,
            "stress": self.stress,
            "sleep_quality": self.sleep_quality,
            "mood": self.mood,
            "psychological_safety": self.psychological_safety,
            "workload": self.baseline_workload,
            "meaning": self.meaning,
        }
