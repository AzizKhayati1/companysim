"""Rich synthetic HR dataset builder.

The sim-facing :class:`Employee` schema is deliberately minimal — just what
the agent step function needs. For dataset export we want everything a
real HRIS or people-analytics warehouse would expose: hire dates,
demographics, locations, compensation splits, performance history, and
normalized reporting edges.

Emits seven tables (CSV + Parquet), one dataset directory per size:

    employees.{csv,parquet}
    departments.{csv,parquet}
    teams.{csv,parquet}
    reporting_lines.{csv,parquet}      # (employee_id, manager_id) edge list
    performance_history.{csv,parquet}  # long: (employee_id, quarter, rating)
    compensation_history.{csv,parquet} # long: (employee_id, effective_date, base, bonus, equity)
    hire_events.{csv,parquet}          # (employee_id, hire_date, hire_source)

Everything is vectorized on numpy/pandas — 25k employees generates in a
few seconds. Faker is used only for names/emails, which is where per-row
Python overhead lives.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

from companysim.data.human_factors import generate_human_factors

# ---- Realism knobs ----------------------------------------------------------

_LEVELS: list[str] = ["IC1", "IC2", "IC3", "IC4", "IC5", "M1", "M2", "M3", "VP", "CXO"]
_LEVEL_WEIGHTS: list[float] = [0.14, 0.22, 0.20, 0.12, 0.06, 0.12, 0.08, 0.04, 0.015, 0.005]
_LEVEL_SALARY_MID: dict[str, float] = {
    "IC1": 60_000, "IC2": 85_000, "IC3": 115_000, "IC4": 145_000, "IC5": 180_000,
    "M1": 140_000, "M2": 180_000, "M3": 230_000, "VP": 320_000, "CXO": 480_000,
}
_LEVEL_BONUS_PCT: dict[str, float] = {
    "IC1": 0.05, "IC2": 0.07, "IC3": 0.10, "IC4": 0.12, "IC5": 0.15,
    "M1": 0.15, "M2": 0.20, "M3": 0.25, "VP": 0.35, "CXO": 0.55,
}
_LEVEL_EQUITY_MID: dict[str, float] = {
    "IC1": 5_000, "IC2": 12_000, "IC3": 25_000, "IC4": 55_000, "IC5": 110_000,
    "M1": 45_000, "M2": 90_000, "M3": 180_000, "VP": 400_000, "CXO": 1_200_000,
}
_LEVEL_SENIORITY: dict[str, int] = {lvl: i for i, lvl in enumerate(_LEVELS, start=1)}

_DEPARTMENTS: list[str] = [
    "Engineering", "Product", "Design", "Sales", "Marketing",
    "Customer Success", "Finance", "People", "Operations",
]
_DEPT_WEIGHTS: list[float] = [3.5, 1.2, 0.7, 2.0, 1.2, 1.2, 0.6, 0.6, 1.0]
_DEPT_SALARY_MULT: dict[str, float] = {
    "Engineering": 1.15, "Product": 1.10, "Design": 1.00,
    "Sales": 1.05, "Marketing": 0.92, "Customer Success": 0.88,
    "Finance": 1.00, "People": 0.90, "Operations": 0.90,
}

_ROLES_BY_DEPT: dict[str, list[str]] = {
    "Engineering": ["Backend Engineer", "Frontend Engineer", "Full-Stack Engineer",
                     "SRE", "ML Engineer", "Data Engineer", "Mobile Engineer",
                     "Security Engineer", "QA Engineer", "Platform Engineer"],
    "Product": ["Product Manager", "Senior PM", "Product Analyst",
                 "Technical PM", "Group PM"],
    "Design": ["Product Designer", "UX Researcher", "Design Systems Designer",
                "Brand Designer", "Motion Designer"],
    "Sales": ["Account Executive", "Enterprise AE", "SDR", "BDR",
                "Sales Engineer", "Sales Ops Analyst"],
    "Marketing": ["Content Marketer", "Growth Marketer", "Brand Manager",
                  "Product Marketer", "SEO Specialist"],
    "Customer Success": ["CSM", "Enterprise CSM", "Support Engineer",
                          "Onboarding Specialist", "Renewals Manager"],
    "Finance": ["FP&A Analyst", "Senior FP&A", "Accountant", "Controller",
                "Treasurer", "Tax Analyst"],
    "People": ["Recruiter", "Technical Recruiter", "HRBP",
                "People Ops Analyst", "L&D Specialist", "DEI Program Manager"],
    "Operations": ["Business Operations", "Legal Counsel", "Paralegal",
                    "IT Support", "Facilities Manager", "Procurement"],
}

_JOB_FAMILY: dict[str, str] = {
    "Engineering": "Technology", "Product": "Technology", "Design": "Design",
    "Sales": "Go-to-Market", "Marketing": "Go-to-Market",
    "Customer Success": "Go-to-Market",
    "Finance": "General & Administrative", "People": "General & Administrative",
    "Operations": "General & Administrative",
}

# Location distribution and cost-of-living multipliers on total comp.
_LOCATIONS: list[tuple[str, str, str, str, float, float]] = [
    # (city, state, country, timezone, weight, col_multiplier)
    ("San Francisco", "CA", "USA", "America/Los_Angeles", 0.14, 1.28),
    ("New York", "NY", "USA", "America/New_York",       0.13, 1.22),
    ("Seattle",       "WA", "USA", "America/Los_Angeles", 0.09, 1.15),
    ("Austin",        "TX", "USA", "America/Chicago",     0.07, 0.98),
    ("Boston",        "MA", "USA", "America/New_York",    0.06, 1.10),
    ("Los Angeles",   "CA", "USA", "America/Los_Angeles", 0.06, 1.12),
    ("Chicago",       "IL", "USA", "America/Chicago",     0.05, 0.98),
    ("Denver",        "CO", "USA", "America/Denver",      0.04, 1.02),
    ("Atlanta",       "GA", "USA", "America/New_York",    0.04, 0.95),
    ("Miami",         "FL", "USA", "America/New_York",    0.03, 1.00),
    ("Toronto",       "ON", "CAN", "America/Toronto",     0.04, 0.90),
    ("London",        "",   "GBR", "Europe/London",       0.05, 1.05),
    ("Berlin",        "",   "DEU", "Europe/Berlin",       0.03, 0.85),
    ("Dublin",        "",   "IRL", "Europe/Dublin",       0.02, 0.95),
    ("Bangalore",     "KA", "IND", "Asia/Kolkata",        0.04, 0.35),
    ("Singapore",     "",   "SGP", "Asia/Singapore",      0.02, 1.08),
    ("Sydney",        "NSW", "AUS", "Australia/Sydney",    0.02, 1.05),
    ("Remote — US",   "",   "USA", "America/New_York",    0.05, 1.00),
    ("Remote — EU",   "",   "DEU", "Europe/Berlin",       0.02, 0.90),
]

_WORK_MODES: list[str] = ["onsite", "hybrid", "remote"]
_WORK_MODE_WEIGHTS: list[float] = [0.30, 0.45, 0.25]

_GENDERS: list[str] = ["Female", "Male", "Non-binary", "Prefer not to say"]
_GENDER_WEIGHTS: list[float] = [0.44, 0.46, 0.05, 0.05]

# Opaque diversity buckets — deliberately unnamed so nothing about real-world
# groups leaks into the sim. Downstream models treat these as anonymous ids.
_DIVERSITY_BUCKETS: list[str] = ["A", "B", "C", "D", "E"]
_DIVERSITY_WEIGHTS: list[float] = [0.35, 0.22, 0.18, 0.15, 0.10]

_HIRE_SOURCES: list[str] = [
    "referral", "linkedin", "company_site", "recruiter",
    "university", "boomerang", "conference",
]
_HIRE_SOURCE_WEIGHTS: list[float] = [0.28, 0.22, 0.14, 0.20, 0.08, 0.04, 0.04]


# ---- Config -----------------------------------------------------------------


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    headcount: int
    seed: int = 42
    org_name: str = "Acme Corp"
    reference_date: date = date(2026, 7, 1)
    perf_quarters: int = 8  # 2 years of quarterly reviews
    comp_history_events: int = 3  # base + typically 2 raises
    wellness_pulse_weeks: int = 12  # weeks of pulse-survey history


@dataclass
class DatasetBundle:
    """Paths of every table in a materialized dataset."""

    directory: Path
    employees: Path
    departments: Path
    teams: Path
    reporting_lines: Path
    performance_history: Path
    compensation_history: Path
    hire_events: Path
    human_factors: Path
    wellness_snapshots: Path
    metadata: dict = field(default_factory=dict)

    def all_paths(self) -> list[Path]:
        return [
            self.employees, self.departments, self.teams,
            self.reporting_lines, self.performance_history,
            self.compensation_history, self.hire_events,
            self.human_factors, self.wellness_snapshots,
        ]


# ---- Builder ----------------------------------------------------------------


class DatasetBuilder:
    """Vectorized rich-dataset builder.

    Emits every table for one config. Same seed → identical output bytes.
    """

    def __init__(self, config: DatasetConfig) -> None:
        self.config = config
        self.rng = np.random.default_rng(config.seed)
        self.faker = Faker()
        Faker.seed(config.seed)

        self._employees: pd.DataFrame | None = None
        self._departments: pd.DataFrame | None = None
        self._teams: pd.DataFrame | None = None

    # ---- public API ----

    def build(self) -> dict[str, pd.DataFrame]:
        deps = self._build_departments()
        teams = self._build_teams(deps)
        emps = self._build_employees(deps, teams)
        # Post-build joins that need everyone in memory.
        teams = self._finalize_teams(teams, emps)
        emps = self._assign_managers(emps, teams, deps)
        deps = self._assign_dept_heads(deps, emps)

        reporting = self._reporting_edges(emps)
        perf = self._performance_history(emps)
        comp = self._compensation_history(emps)
        hires = self._hire_events(emps)

        # Human factors — psychological, wellbeing, life-context data
        # generated from validated OB frameworks. See human_factors.py for
        # the frameworks and the ethical scope.
        hf_bundle = generate_human_factors(
            emps,
            rng=self.rng,
            reference_date=self.config.reference_date,
            pulse_weeks=self.config.wellness_pulse_weeks,
        )

        # Cache for later save() calls if the caller wants them.
        self._employees, self._departments, self._teams = emps, deps, teams

        return {
            "employees": emps,
            "departments": deps,
            "teams": teams,
            "reporting_lines": reporting,
            "performance_history": perf,
            "compensation_history": comp,
            "hire_events": hires,
            "human_factors": hf_bundle.profile,
            "wellness_snapshots": hf_bundle.wellness_snapshots,
        }

    def save(self, tables: dict[str, pd.DataFrame], out_dir: Path) -> DatasetBundle:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        for name, df in tables.items():
            csv_path = out_dir / f"{name}.csv"
            parquet_path = out_dir / f"{name}.parquet"
            df.to_csv(csv_path, index=False)
            df.to_parquet(parquet_path, index=False)
            # Store the CSV path in the bundle; parquet lives alongside.
            written[name] = csv_path

        metadata = {
            "dataset_name": self.config.name,
            "headcount": self.config.headcount,
            "seed": self.config.seed,
            "org_name": self.config.org_name,
            "reference_date": self.config.reference_date.isoformat(),
            "row_counts": {name: int(len(df)) for name, df in tables.items()},
        }
        (out_dir / "manifest.json").write_text(
            _json_dumps(metadata), encoding="utf-8"
        )

        return DatasetBundle(
            directory=out_dir,
            employees=written["employees"],
            departments=written["departments"],
            teams=written["teams"],
            reporting_lines=written["reporting_lines"],
            performance_history=written["performance_history"],
            compensation_history=written["compensation_history"],
            hire_events=written["hire_events"],
            human_factors=written["human_factors"],
            wellness_snapshots=written["wellness_snapshots"],
            metadata=metadata,
        )

    # ---- internals ----

    def _build_departments(self) -> pd.DataFrame:
        rows = []
        for i, name in enumerate(_DEPARTMENTS):
            rows.append({
                "department_id": f"dept_{i:02d}",
                "name": name,
                "job_family": _JOB_FAMILY[name],
                "salary_multiplier": _DEPT_SALARY_MULT[name],
                "head_employee_id": None,
            })
        return pd.DataFrame(rows)

    def _build_teams(self, deps: pd.DataFrame) -> pd.DataFrame:
        weights = np.array(_DEPT_WEIGHTS)
        weights = weights / weights.sum()
        headcounts = self.rng.multinomial(self.config.headcount, weights)
        rows: list[dict] = []
        team_counter = 0
        for (_, dept), hc in zip(deps.iterrows(), headcounts, strict=True):
            remaining = int(hc)
            per_team = 7  # target size
            while remaining > 0:
                size = max(2, int(self.rng.normal(per_team, 2.0)))
                size = min(size, remaining)
                rows.append({
                    "team_id": f"team_{team_counter:04d}",
                    "name": f"{dept['name']} Team {team_counter + 1}",
                    "department_id": dept["department_id"],
                    "planned_size": size,
                    "manager_employee_id": None,
                })
                team_counter += 1
                remaining -= size
        return pd.DataFrame(rows)

    def _build_employees(self, deps: pd.DataFrame, teams: pd.DataFrame) -> pd.DataFrame:
        # Expand teams into per-employee assignments up-front so everything
        # else can be vectorized.
        assignments: list[tuple[str, str]] = []
        for _, t in teams.iterrows():
            assignments.extend([(t["team_id"], t["department_id"])] * int(t["planned_size"]))
        n = len(assignments)

        # Levels, roles, and departments-derived fields.
        levels = self.rng.choice(_LEVELS, size=n, p=_LEVEL_WEIGHTS)
        team_ids = np.array([a[0] for a in assignments])
        dept_ids = np.array([a[1] for a in assignments])
        dept_name_by_id = dict(zip(deps["department_id"], deps["name"]))
        dept_names = np.array([dept_name_by_id[d] for d in dept_ids])

        roles = np.array([
            self.rng.choice(_ROLES_BY_DEPT[dn]) for dn in dept_names
        ])

        # Names, emails, phones.
        first_names = [self.faker.first_name() for _ in range(n)]
        last_names = [self.faker.last_name() for _ in range(n)]
        full_names = [f"{f} {l}" for f, l in zip(first_names, last_names)]
        email_domain = self.config.org_name.lower().replace(" ", "") + ".example"
        emails = [
            f"{f.lower()}.{l.lower()}@{email_domain}"
            for f, l in zip(first_names, last_names)
        ]
        phones = [self.faker.msisdn() for _ in range(n)]

        # Locations.
        loc_idx = self.rng.choice(
            len(_LOCATIONS), size=n,
            p=np.array([loc[4] for loc in _LOCATIONS]) / sum(loc[4] for loc in _LOCATIONS),
        )
        cities = np.array([_LOCATIONS[i][0] for i in loc_idx])
        states = np.array([_LOCATIONS[i][1] for i in loc_idx])
        countries = np.array([_LOCATIONS[i][2] for i in loc_idx])
        timezones = np.array([_LOCATIONS[i][3] for i in loc_idx])
        col_mults = np.array([_LOCATIONS[i][5] for i in loc_idx])
        work_modes = self.rng.choice(_WORK_MODES, size=n, p=_WORK_MODE_WEIGHTS)

        # Demographics.
        genders = self.rng.choice(_GENDERS, size=n, p=_GENDER_WEIGHTS)
        diversity = self.rng.choice(_DIVERSITY_BUCKETS, size=n, p=_DIVERSITY_WEIGHTS)

        # Hire dates and tenure.
        # Level nudges tenure up: senior folks have been around longer.
        seniority_bonus = np.array([_LEVEL_SENIORITY[l] for l in levels]) * 3.0
        tenure_months = np.clip(
            self.rng.exponential(scale=24, size=n) + seniority_bonus
            + self.rng.normal(0, 4, size=n),
            0, 240,
        ).astype(int)
        ref = self.config.reference_date
        hire_dates = np.array([
            (ref - timedelta(days=int(t * 30.44))) for t in tenure_months
        ])

        # Age — base 22 + tenure + level nudge, plus noise.
        level_age_bump = np.array([_LEVEL_SENIORITY[l] for l in levels]) * 1.5
        ages = np.clip(
            22 + tenure_months / 12 + level_age_bump + self.rng.normal(0, 4, size=n),
            22, 66,
        ).astype(int)
        birth_dates = np.array([
            ref - timedelta(days=int(a * 365.25 + self.rng.integers(0, 365)))
            for a in ages
        ])

        # Compensation — level midpoint × dept mult × col mult × noise.
        level_mids = np.array([_LEVEL_SALARY_MID[l] for l in levels])
        dept_mults = deps.set_index("department_id")["salary_multiplier"].to_dict()
        dept_mult_arr = np.array([dept_mults[d] for d in dept_ids])
        salary_noise = self.rng.normal(1.0, 0.08, size=n)
        base_salary = np.maximum(30_000, level_mids * dept_mult_arr * col_mults * salary_noise)

        bonus_pct = np.array([_LEVEL_BONUS_PCT[l] for l in levels])
        bonus_target = base_salary * bonus_pct
        equity_mid = np.array([_LEVEL_EQUITY_MID[l] for l in levels])
        equity_value = np.maximum(0, equity_mid * self.rng.normal(1.0, 0.20, size=n))
        total_comp = base_salary + bonus_target + equity_value

        # Behavioral latents — the same distributions the sim uses.
        productivity = self.rng.beta(6, 3, size=n)
        collab_alpha = np.array([7 if l in ("M1", "M2", "M3", "VP", "CXO") else 5 for l in levels])
        collaboration = np.array([self.rng.beta(a, 3) for a in collab_alpha])
        engagement_raw = self.rng.beta(5, 3, size=n)
        engagement = np.where(tenure_months < 6, engagement_raw * 0.85, engagement_raw).clip(0, 1)
        turnover_risk = np.clip(
            0.8 - 0.6 * engagement + np.where(tenure_months < 12, 0.15, 0.0)
            + self.rng.normal(0, 0.05, size=n),
            0, 1,
        )
        # Bonus tied to productivity — high performers actually earn their target.
        performance_multiplier = 0.5 + productivity  # roughly 0.5x–1.5x of target
        bonus_earned_last = bonus_target * performance_multiplier

        promotions_count = np.clip(
            (tenure_months / 24 * (0.4 + productivity)).round().astype(int),
            0, 6,
        )

        return pd.DataFrame({
            "employee_id": [f"emp_{i:06d}" for i in range(n)],
            "first_name": first_names,
            "last_name": last_names,
            "full_name": full_names,
            "email": emails,
            "phone": phones,
            "birth_date": birth_dates,
            "age": ages,
            "gender": genders,
            "diversity_bucket": diversity,
            "city": cities,
            "state": states,
            "country": countries,
            "timezone": timezones,
            "work_mode": work_modes,
            "department_id": dept_ids,
            "team_id": team_ids,
            "level": levels,
            "role": roles,
            "job_family": [_JOB_FAMILY[dept_name_by_id[d]] for d in dept_ids],
            "hire_date": hire_dates,
            "tenure_months": tenure_months,
            "hire_source": self.rng.choice(_HIRE_SOURCES, size=n, p=_HIRE_SOURCE_WEIGHTS),
            "manager_employee_id": [None] * n,  # filled in _assign_managers
            "base_salary": np.round(base_salary, 2),
            "bonus_target_pct": np.round(bonus_pct, 3),
            "bonus_target": np.round(bonus_target, 2),
            "bonus_earned_last": np.round(bonus_earned_last, 2),
            "equity_value": np.round(equity_value, 2),
            "total_comp": np.round(total_comp, 2),
            "promotions_count": promotions_count,
            "productivity": np.round(productivity, 4),
            "engagement": np.round(engagement, 4),
            "collaboration": np.round(collaboration, 4),
            "turnover_risk": np.round(turnover_risk, 4),
        })

    def _finalize_teams(self, teams: pd.DataFrame, emps: pd.DataFrame) -> pd.DataFrame:
        actual = emps.groupby("team_id").size().rename("actual_size")
        teams = teams.merge(actual, left_on="team_id", right_index=True, how="left")
        teams["actual_size"] = teams["actual_size"].fillna(0).astype(int)
        return teams

    def _assign_managers(
        self, emps: pd.DataFrame, teams: pd.DataFrame, deps: pd.DataFrame,
    ) -> pd.DataFrame:
        emps = emps.copy()
        emps["_seniority"] = emps["level"].map(_LEVEL_SENIORITY)
        manager_col: dict[str, str | None] = {e: None for e in emps["employee_id"]}

        # Team manager: highest level in the team, prefer a true M1-M3.
        for team_id, group in emps.groupby("team_id"):
            managers = group[group["level"].isin(["M1", "M2", "M3"])]
            pick = managers if not managers.empty else group
            leader = pick.sort_values("_seniority", ascending=False).iloc[0]
            leader_id = str(leader["employee_id"])
            for eid in group["employee_id"]:
                if eid != leader_id:
                    manager_col[eid] = leader_id
            teams.loc[teams["team_id"] == team_id, "manager_employee_id"] = leader_id

        # Department head: most senior team manager in the dept.
        for _, dept in deps.iterrows():
            dept_teams = teams[teams["department_id"] == dept["department_id"]]
            head_candidates = emps[emps["employee_id"].isin(dept_teams["manager_employee_id"])]
            if head_candidates.empty:
                continue
            head = head_candidates.sort_values("_seniority", ascending=False).iloc[0]
            head_id = str(head["employee_id"])
            for tm_id in dept_teams["manager_employee_id"]:
                if tm_id and tm_id != head_id:
                    manager_col[tm_id] = head_id
            # Head reports to the CEO or nobody (assigned below).

        # CEO / top of chart: single highest-level person in the whole org.
        top = emps.sort_values("_seniority", ascending=False).iloc[0]
        top_id = str(top["employee_id"])
        # All department heads report to the CEO.
        for dept_id in deps["department_id"]:
            dept_teams = teams[teams["department_id"] == dept_id]
            head_candidates = emps[
                emps["employee_id"].isin(dept_teams["manager_employee_id"])
            ]
            if head_candidates.empty:
                continue
            head = head_candidates.sort_values("_seniority", ascending=False).iloc[0]
            head_id = str(head["employee_id"])
            if head_id != top_id:
                manager_col[head_id] = top_id
        manager_col[top_id] = None

        emps["manager_employee_id"] = emps["employee_id"].map(manager_col)
        return emps.drop(columns=["_seniority"])

    def _assign_dept_heads(self, deps: pd.DataFrame, emps: pd.DataFrame) -> pd.DataFrame:
        # A dept head is defined as the manager to whom the dept's team
        # managers report; equivalently, the manager of team managers within
        # the dept whose own manager is *not* a dept team manager.
        team_managers = set(emps.loc[emps["employee_id"].isin(
            emps["manager_employee_id"].dropna()
        ), "employee_id"])
        deps = deps.copy()
        heads: list[str | None] = []
        for _, dept in deps.iterrows():
            dept_emps = emps[emps["department_id"] == dept["department_id"]]
            candidates = dept_emps[dept_emps["employee_id"].isin(team_managers)]
            if candidates.empty:
                heads.append(None)
                continue
            candidates = candidates.assign(_s=candidates["level"].map(_LEVEL_SENIORITY))
            head = candidates.sort_values("_s", ascending=False).iloc[0]
            heads.append(str(head["employee_id"]))
        deps["head_employee_id"] = heads
        return deps

    def _reporting_edges(self, emps: pd.DataFrame) -> pd.DataFrame:
        edges = emps[["employee_id", "manager_employee_id"]].dropna(subset=["manager_employee_id"])
        return edges.rename(columns={
            "employee_id": "report_employee_id",
            "manager_employee_id": "manager_employee_id",
        }).reset_index(drop=True)

    def _performance_history(self, emps: pd.DataFrame) -> pd.DataFrame:
        """Quarterly 1–5 ratings for the last N quarters of tenure."""
        ref = self.config.reference_date
        rows: list[dict] = []
        # Base quarter mean is 3.0; productivity latent shifts the mean.
        # tenure gates how many quarters we actually have data for.
        productivity = emps["productivity"].to_numpy()
        tenure = emps["tenure_months"].to_numpy()
        for i, emp_id in enumerate(emps["employee_id"].to_numpy()):
            max_q = int(min(self.config.perf_quarters, tenure[i] // 3))
            if max_q <= 0:
                continue
            mean = 2.5 + 2.0 * productivity[i]  # 2.5–4.5 range
            for q_back in range(1, max_q + 1):
                q_end = ref - timedelta(days=q_back * 90)
                rating = float(np.clip(
                    self.rng.normal(mean, 0.35), 1.0, 5.0,
                ))
                rows.append({
                    "employee_id": emp_id,
                    "quarter_end": q_end,
                    "rating": round(rating, 2),
                })
        return pd.DataFrame(rows)

    def _compensation_history(self, emps: pd.DataFrame) -> pd.DataFrame:
        """Base salary snapshots, one per compensation event.

        Newest snapshot = current base_salary; earlier snapshots reflect
        a rough merit-cycle growth path.
        """
        ref = self.config.reference_date
        rows: list[dict] = []
        n_events = self.config.comp_history_events
        base = emps["base_salary"].to_numpy()
        bonus_pct = emps["bonus_target_pct"].to_numpy()
        equity = emps["equity_value"].to_numpy()
        tenure = emps["tenure_months"].to_numpy()
        hire_date = emps["hire_date"].to_numpy()
        emp_ids = emps["employee_id"].to_numpy()
        for i in range(len(emps)):
            events = min(n_events, max(1, int(tenure[i] // 12)))
            for k in range(events):
                # k=0 is current, k=events-1 is starting comp.
                years_back = k
                growth = 1.0 / (1.0 + 0.06) ** years_back  # ~6% annual merit
                effective = ref - timedelta(days=int(years_back * 365))
                if effective < hire_date[i]:
                    effective = hire_date[i]
                rows.append({
                    "employee_id": emp_ids[i],
                    "effective_date": effective,
                    "base_salary": round(float(base[i] * growth), 2),
                    "bonus_target_pct": round(float(bonus_pct[i]), 3),
                    "equity_value": round(float(equity[i] * growth), 2),
                })
        return pd.DataFrame(rows)

    def _hire_events(self, emps: pd.DataFrame) -> pd.DataFrame:
        return emps[["employee_id", "hire_date", "hire_source"]].reset_index(drop=True)


# ---- Public façade ----------------------------------------------------------


DATASET_SIZES: dict[str, DatasetConfig] = {
    "small":  DatasetConfig(name="small",  headcount=500,    seed=42),
    "medium": DatasetConfig(name="medium", headcount=5_000,  seed=43),
    "large":  DatasetConfig(name="large",  headcount=25_000, seed=44),
}


def build_and_save(config: DatasetConfig, out_root: Path) -> DatasetBundle:
    builder = DatasetBuilder(config)
    tables = builder.build()
    return builder.save(tables, out_root / config.name)


def to_organization(tables: dict[str, pd.DataFrame], *, org_name: str = "Acme Corp") -> "Organization":
    """Bridge the rich :class:`DatasetBuilder` tables into a sim-runnable
    :class:`Organization`.

    ``DatasetBuilder`` and :class:`~companysim.data.generators.WorkforceGenerator`
    are independent generators — the former produces wide, export-friendly
    DataFrames (compensation history, demographics, ...); the latter produces
    the minimal pydantic records :class:`OrganizationModel` runs on. This
    function is the adapter that lets the *rich* dataset (the one paired with
    ``human_factors``) be forward-simulated directly, which is what the
    turnover-label pipeline needs: labels have to come from simulating the
    exact same population the features describe.

    Only a straight column rename/subset — no re-derivation of values.
    """
    from companysim.data.schemas import Department, Employee, Organization, Team  # noqa: PLC0415

    emps = tables["employees"]
    teams = tables["teams"]
    deps = tables["departments"]

    member_ids = emps.groupby("team_id")["employee_id"].apply(list).to_dict()

    departments = [
        Department(
            id=row["department_id"],
            name=row["name"],
            head_id=row["head_employee_id"] if pd.notna(row["head_employee_id"]) else None,
        )
        for _, row in deps.iterrows()
    ]
    team_objs = [
        Team(
            id=row["team_id"],
            name=row["name"],
            department_id=row["department_id"],
            manager_id=row["manager_employee_id"] if pd.notna(row["manager_employee_id"]) else None,
            member_ids=member_ids.get(row["team_id"], []),
        )
        for _, row in teams.iterrows()
    ]
    employees = [
        Employee(
            id=row["employee_id"],
            name=row["full_name"],
            email=row["email"],
            department_id=row["department_id"],
            team_id=row["team_id"],
            manager_id=row["manager_employee_id"] if pd.notna(row["manager_employee_id"]) else None,
            level=row["level"],
            role=row["role"],
            tenure_months=int(row["tenure_months"]),
            salary=float(row["base_salary"]),
            productivity=float(row["productivity"]),
            engagement=float(row["engagement"]),
            collaboration=float(row["collaboration"]),
            turnover_risk=float(row["turnover_risk"]),
        )
        for _, row in emps.iterrows()
    ]
    return Organization(name=org_name, departments=departments, teams=team_objs, employees=employees)


# ---- json helpers -----------------------------------------------------------


def _json_dumps(obj: object) -> str:
    import json  # noqa: PLC0415
    return json.dumps(obj, indent=2, sort_keys=True, default=str)
