"""Employee agent.

Wraps an :class:`Employee` record and a :class:`HumanProfile` and evolves
their joint state one discrete tick at a time (nominally one work week).

The step logic composes three layers that mirror how workplace-wellbeing
research models the same dynamics:

1. *Wellbeing state* (burnout, stress, sleep, mood) drifts under load,
   support, and recovery — Karasek's Demand-Control-Support framing.
2. *Engagement / collaboration* respond to team climate + psychological
   safety + meaning; low wellbeing drags them down.
3. *Productivity* is engagement-gated but also directly damped by burnout
   and low sleep — the mechanism most empirically supported for
   presenteeism.

The turnover Bernoulli feeds off engagement, burnout, and life-event
shocks, mirroring the compound-risk pattern in longitudinal turnover
studies.

These are *simulated* dynamics on synthetic profiles. See
:mod:`companysim.data.human_factors` for the framework citations and the
ethics scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from companysim.data.human_factors import HumanProfile
from companysim.data.schemas import Employee


@dataclass
class TickOutcome:
    """Everything an employee produced in a single tick."""

    employee_id: str
    productivity: float
    engagement: float
    collaboration: float
    turnover_risk: float
    burnout: float = 0.0
    stress: float = 0.0
    sleep_quality: float = 0.0
    mood: float = 0.0
    quit: bool = False


@dataclass
class EmployeeAgent:
    record: Employee
    _rng: np.random.Generator = field(default_factory=np.random.default_rng)
    profile: HumanProfile | None = None

    # Mutable per-tick state — these drift; the record holds the baseline.
    productivity: float = 0.0
    engagement: float = 0.0
    collaboration: float = 0.0
    turnover_risk: float = 0.0
    active: bool = True

    def __post_init__(self) -> None:
        self.productivity = self.record.productivity
        self.engagement = self.record.engagement
        self.collaboration = self.record.collaboration
        self.turnover_risk = self.record.turnover_risk
        if self.profile is None:
            self.profile = HumanProfile.sample(self._rng)

    # ---- accessors ----
    @property
    def burnout(self) -> float:
        return self.profile.burnout

    @property
    def stress(self) -> float:
        return self.profile.stress

    @property
    def sleep_quality(self) -> float:
        return self.profile.sleep_quality

    @property
    def mood(self) -> float:
        return self.profile.mood

    # ---- lifecycle ----

    def step(self, team_climate: float, team_psych_safety: float = 0.6) -> TickOutcome:
        """Advance the agent one tick.

        ``team_climate`` — 0..1 signal of peer engagement/collaboration.
        ``team_psych_safety`` — 0..1 team-level psychological safety
        (Edmondson): amplifies engagement gains and dampens burnout.
        """
        if not self.active:
            return TickOutcome(
                employee_id=self.record.id,
                productivity=0.0, engagement=0.0,
                collaboration=0.0, turnover_risk=1.0,
                burnout=self.burnout, stress=self.stress,
                sleep_quality=self.sleep_quality, mood=self.mood,
                quit=True,
            )

        p = self.profile
        assert p is not None  # __post_init__ guarantees this

        # --- 1) Wellbeing dynamics ---
        # Effective workload = perceived workload dampened by autonomy.
        effective_load = _clamp(p.baseline_workload * (1.15 - 0.30 * p.autonomy))

        # Burnout builds under sustained load, decays with recovery
        # (sleep + peer/manager support). Neuroticism accelerates uptake.
        # Persistence set high (0.95) because burnout is a slow-building,
        # slow-recovering state over a quarter, not a weekly reset — a low
        # persistence washes out day-0 individual differences within a few
        # ticks, which both misrepresents the construct and (operationally)
        # destroys any hope of a turnover model learning from early signal.
        # Input coefficients are scaled by (1-0.95)/(1-0.90)=0.5 so the
        # steady-state equilibrium is unchanged from the original — only the
        # *rate* of convergence (memory of day-0 state) changes.
        recovery = 0.5 * p.sleep_quality + 0.25 * p.manager_support + 0.25 * p.peer_support
        p.burnout = _clamp(
            0.95 * p.burnout
            + 0.05 * effective_load
            - 0.03 * recovery
            + 0.015 * p.neuroticism
            + self._rng.normal(0, 0.02)
        )

        # Stress: chronic load + life adversity − social support.
        p.stress = _clamp(
            0.85 * p.stress
            + 0.10 * effective_load
            + 0.05 * (1 - p.financial_security)
            + 0.05 * p.caregiving_load
            - 0.08 * (p.social_support + p.peer_support) / 2
            + self._rng.normal(0, 0.03)
        )

        # Sleep quality: physical baseline − stress load, small random shocks.
        p.sleep_quality = _clamp(
            0.85 * p.sleep_quality
            + 0.10 * p.physical_health
            - 0.10 * p.stress
            + self._rng.normal(0, 0.04)
        )

        # Mood: buoyed by team climate + meaning, dragged by burnout + stress.
        p.mood = _clamp(
            0.80 * p.mood
            + 0.08 * team_climate
            + 0.05 * p.meaning
            - 0.08 * p.burnout
            - 0.05 * p.stress
            + self._rng.normal(0, 0.03)
        )

        # --- 2) Engagement and collaboration ---
        self.engagement = _clamp(
            0.6 * self.engagement
            + 0.15 * self.record.engagement
            + 0.10 * team_climate
            + 0.10 * (0.5 * team_psych_safety + 0.5 * p.meaning)
            - 0.10 * p.burnout
            + 0.05 * p.mood
            + self._rng.normal(0, 0.03)
        )
        self.collaboration = _clamp(
            0.70 * self.collaboration
            + 0.12 * self.record.collaboration
            + 0.10 * team_climate
            + 0.08 * team_psych_safety
            + 0.05 * p.extraversion
            - 0.05 * p.burnout
            + self._rng.normal(0, 0.03)
        )

        # --- 3) Productivity ---
        # Engagement-gated, damped by burnout and poor sleep, boosted by
        # conscientiousness and autonomy (control/mastery).
        self.productivity = _clamp(
            0.55 * self.productivity
            + 0.25 * self.record.productivity * (0.5 + 0.5 * self.engagement)
            + 0.10 * team_climate
            + 0.05 * p.conscientiousness
            + 0.05 * p.autonomy
            - 0.15 * p.burnout
            - 0.05 * (1 - p.sleep_quality)
            + self._rng.normal(0, 0.04)
        )

        # --- 4) Turnover risk ---
        # Compound risk: low engagement + high burnout + low meaning +
        # low manager support. Persistence raised to 0.90 (from 0.80) for
        # the same reason as burnout above — quitting intent builds over
        # months, and a fast-decaying EMA erases day-0 risk differences
        # before they can compound into an actual exit. Coefficients scaled
        # by (1-0.90)/(1-0.80)=0.5 to hold the equilibrium level fixed.
        self.turnover_risk = _clamp(
            0.90 * self.turnover_risk
            + 0.05 * (1.0 - self.engagement)
            + 0.05 * p.burnout
            + 0.025 * (1.0 - p.meaning)
            + 0.025 * (1.0 - p.manager_support)
            + self._rng.normal(0, 0.02)
        )

        # Actual quit probability is convex in risk — mild dissatisfaction
        # rarely triggers an exit, but risk crossing a threshold does. Power
        # 4 (vs. a gentler cubic) sharpens that separation, matching the
        # empirical "tipping point" pattern in real voluntary-turnover data
        # where a small high-risk minority accounts for most actual exits.
        quit_now = bool(self._rng.random() < (self.turnover_risk ** 4) * 0.055)
        if quit_now:
            self.active = False

        return TickOutcome(
            employee_id=self.record.id,
            productivity=self.productivity,
            engagement=self.engagement,
            collaboration=self.collaboration,
            turnover_risk=self.turnover_risk,
            burnout=p.burnout,
            stress=p.stress,
            sleep_quality=p.sleep_quality,
            mood=p.mood,
            quit=quit_now,
        )


def _clamp(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))
