"""Create a new persisted org from the existing synthetic-data pipeline.

Reuses `DatasetBuilder` (which already calls `generate_human_factors`
internally) exactly as-is — this module's only job is inserting that
output into SQLite instead of returning it as DataFrames. Two-pass
employee insert: employees first (so they get DB ids), then a second pass
wires up manager/head-of-department references now that every id exists.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from companysim.api.db_models import (
    WELLBEING_COLUMNS,
    DepartmentRecord,
    EmployeeRecord,
    EmployeeWellbeingRecord,
    OrgRecord,
    TeamRecord,
)
from companysim.data.datasets import DatasetBuilder, DatasetConfig


def create_org(db: Session, *, name: str, headcount: int, seed: int) -> OrgRecord:
    cfg = DatasetConfig(name=name, headcount=headcount, seed=seed, org_name=name)
    tables = DatasetBuilder(cfg).build()
    emps_df = tables["employees"]
    deps_df = tables["departments"]
    teams_df = tables["teams"]
    hf_df = tables["human_factors"].set_index("employee_id")

    org = OrgRecord(name=name, seed=seed)
    db.add(org)
    db.flush()  # assign org.id

    dept_by_str_id: dict[str, DepartmentRecord] = {}
    for _, row in deps_df.iterrows():
        dept = DepartmentRecord(
            org_id=org.id, name=row["name"],
            salary_multiplier=float(row["salary_multiplier"]),
        )
        db.add(dept)
        dept_by_str_id[row["department_id"]] = dept
    db.flush()  # assign department ids

    team_by_str_id: dict[str, TeamRecord] = {}
    for _, row in teams_df.iterrows():
        team = TeamRecord(
            org_id=org.id,
            department_id=dept_by_str_id[row["department_id"]].id,
            name=row["name"],
        )
        db.add(team)
        team_by_str_id[row["team_id"]] = team
    db.flush()  # assign team ids

    # Pass 1: insert employees without manager references.
    emp_by_str_id: dict[str, EmployeeRecord] = {}
    for _, row in emps_df.iterrows():
        emp = EmployeeRecord(
            org_id=org.id,
            department_id=dept_by_str_id[row["department_id"]].id,
            team_id=team_by_str_id[row["team_id"]].id,
            full_name=row["full_name"],
            email=row["email"],
            level=row["level"],
            role=row["role"],
            tenure_months=int(row["tenure_months"]),
            base_salary=float(row["base_salary"]),
            work_mode=row["work_mode"],
            promotions_count=int(row["promotions_count"]),
            productivity=float(row["productivity"]),
            engagement=float(row["engagement"]),
            collaboration=float(row["collaboration"]),
            turnover_risk=float(row["turnover_risk"]),
        )
        db.add(emp)
        emp_by_str_id[row["employee_id"]] = emp
    db.flush()  # assign employee ids

    # Pass 2: manager / department-head references, now that every
    # employee has a DB id.
    for _, row in emps_df.iterrows():
        mgr_str_id = row["manager_employee_id"]
        if mgr_str_id and mgr_str_id in emp_by_str_id:
            emp_by_str_id[row["employee_id"]].manager_id = emp_by_str_id[mgr_str_id].id

    for _, row in teams_df.iterrows():
        mgr_str_id = row["manager_employee_id"]
        if mgr_str_id and mgr_str_id in emp_by_str_id:
            team_by_str_id[row["team_id"]].manager_employee_id = emp_by_str_id[mgr_str_id].id

    for _, row in deps_df.iterrows():
        head_str_id = row["head_employee_id"]
        if head_str_id and head_str_id in emp_by_str_id:
            dept_by_str_id[row["department_id"]].head_employee_id = emp_by_str_id[head_str_id].id

    # Wellbeing rows, 1:1 with employees.
    for str_id, emp in emp_by_str_id.items():
        row = hf_df.loc[str_id]
        kwargs = {col: row[col] for col in WELLBEING_COLUMNS}
        kwargs["first_gen_professional"] = int(row["first_gen_professional"])
        kwargs["eap_utilization_last_year"] = int(row["eap_utilization_last_year"])
        kwargs["childhood_ses_quintile"] = int(row["childhood_ses_quintile"])
        kwargs["ace_score"] = int(row["ace_score"])
        kwargs["commute_burden_minutes"] = int(row["commute_burden_minutes"])
        kwargs["months_since_life_event"] = int(row["months_since_life_event"])
        db.add(EmployeeWellbeingRecord(employee_id=emp.id, **kwargs))

    db.commit()
    db.refresh(org)
    return org
