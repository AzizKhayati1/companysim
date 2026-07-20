from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.db_models import (
    EmployeeRecord,
    EmployeeRiskSnapshot,
    EmployeeWellbeingRecord,
    OrgRecord,
)
from companysim.api.scoring_frame import build_driver_frame, load_production_bundle
from companysim.api.schemas import DriverOut, EmployeeIn, EmployeeOut, RiskHistoryPointOut
from companysim.ml.diagnostics import explain_employee

router = APIRouter(prefix="/orgs/{org_id}/employees", tags=["employees"])

# Neutral midpoint defaults for a freshly-added employee's wellbeing row —
# every field HumanProfile.from_row needs, even though only a handful are
# exposed as editable via EmployeeIn.
_DEFAULT_WELLBEING = dict(
    openness=0.5, conscientiousness=0.5, extraversion=0.5, agreeableness=0.5, neuroticism=0.5,
    education_level="Bachelor", first_gen_professional=0, childhood_ses_quintile=3,
    ace_score=0, attachment_style="secure", financial_security_score=0.55,
    caregiving_load=0.2, commute_burden_minutes=30, hours_slept_typical=7.0,
    physical_health_score=0.65, recent_life_event="none", months_since_life_event=-1,
    social_support_score=0.55, mood=0.55, stress_level=0.4, sleep_quality=0.55,
    energy_level=0.55, anxiety_symptom_score=0.3, depression_symptom_score=0.25,
    life_satisfaction=0.55, burnout_exhaustion=0.35, burnout_cynicism=0.3,
    burnout_efficacy=0.6, workload_perceived=0.45, autonomy_score=0.55,
    psychological_safety_perceived=0.6, manager_support_score=0.6, peer_support_score=0.6,
    meaning_at_work_score=0.55, growth_opportunity_score=0.5, recognition_score=0.5,
    role_clarity_score=0.6, effort_reward_imbalance=0.4, eap_utilization_last_year=0,
    mental_health_engagement="none", wellness_program_participation=0.3,
)


def _get_org_or_404(db: Session, org_id: int) -> OrgRecord:
    org = db.get(OrgRecord, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    return org


def _get_emp_or_404(db: Session, org_id: int, emp_id: int) -> EmployeeRecord:
    emp = db.query(EmployeeRecord).filter_by(org_id=org_id, id=emp_id).first()
    if emp is None:
        raise HTTPException(404, "employee not found")
    return emp


def _to_out(emp: EmployeeRecord) -> EmployeeOut:
    w = emp.wellbeing
    return EmployeeOut(
        id=emp.id, full_name=emp.full_name, email=emp.email,
        department_id=emp.department_id, team_id=emp.team_id, manager_id=emp.manager_id,
        level=emp.level, role=emp.role, tenure_months=emp.tenure_months,
        base_salary=emp.base_salary, work_mode=emp.work_mode,
        promotions_count=emp.promotions_count,
        workload_perceived=w.workload_perceived,
        manager_support_score=w.manager_support_score,
        psychological_safety_perceived=w.psychological_safety_perceived,
        financial_security_score=w.financial_security_score,
    )


@router.get("", response_model=list[EmployeeOut])
def list_employees(org_id: int, db: Session = Depends(get_db)):
    _get_org_or_404(db, org_id)
    emps = db.query(EmployeeRecord).filter_by(org_id=org_id).all()
    return [_to_out(e) for e in emps]


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(org_id: int, body: EmployeeIn, db: Session = Depends(get_db)):
    _get_org_or_404(db, org_id)
    if not body.full_name or body.department_id is None or body.team_id is None:
        raise HTTPException(400, "full_name, department_id and team_id are required")

    local = body.full_name.lower().replace(" ", ".")
    emp = EmployeeRecord(
        org_id=org_id, department_id=body.department_id, team_id=body.team_id,
        manager_id=body.manager_id, full_name=body.full_name,
        email=f"{local}@newhire.example",
        level=body.level or "IC1", role=body.role or "Individual Contributor",
        tenure_months=body.tenure_months if body.tenure_months is not None else 0,
        base_salary=body.base_salary if body.base_salary is not None else 70_000.0,
        work_mode=body.work_mode or "hybrid",
        productivity=0.5, engagement=0.5, collaboration=0.5, turnover_risk=0.4,
    )
    db.add(emp)
    db.flush()

    wellbeing_kwargs = dict(_DEFAULT_WELLBEING)
    if body.workload_perceived is not None:
        wellbeing_kwargs["workload_perceived"] = body.workload_perceived
    if body.manager_support_score is not None:
        wellbeing_kwargs["manager_support_score"] = body.manager_support_score
    if body.psychological_safety_perceived is not None:
        wellbeing_kwargs["psychological_safety_perceived"] = body.psychological_safety_perceived
    if body.financial_security_score is not None:
        wellbeing_kwargs["financial_security_score"] = body.financial_security_score
    db.add(EmployeeWellbeingRecord(employee_id=emp.id, **wellbeing_kwargs))

    db.commit()
    db.refresh(emp)
    return _to_out(emp)


@router.patch("/{emp_id}", response_model=EmployeeOut)
def update_employee(org_id: int, emp_id: int, body: EmployeeIn, db: Session = Depends(get_db)):
    emp = _get_emp_or_404(db, org_id, emp_id)

    field_map = {
        "full_name": "full_name", "department_id": "department_id", "team_id": "team_id",
        "manager_id": "manager_id", "level": "level", "role": "role",
        "tenure_months": "tenure_months", "base_salary": "base_salary", "work_mode": "work_mode",
    }
    for api_field, model_field in field_map.items():
        value = getattr(body, api_field)
        if value is not None:
            setattr(emp, model_field, value)

    wellbeing_fields = (
        "workload_perceived", "manager_support_score",
        "psychological_safety_perceived", "financial_security_score",
    )
    for field in wellbeing_fields:
        value = getattr(body, field)
        if value is not None:
            setattr(emp.wellbeing, field, value)

    db.commit()
    db.refresh(emp)
    return _to_out(emp)


@router.delete("/{emp_id}", status_code=204)
def delete_employee(org_id: int, emp_id: int, db: Session = Depends(get_db)):
    emp = _get_emp_or_404(db, org_id, emp_id)
    db.delete(emp)
    db.commit()


@router.get("/{emp_id}/risk-history", response_model=list[RiskHistoryPointOut])
def get_risk_history(org_id: int, emp_id: int, db: Session = Depends(get_db)):
    _get_emp_or_404(db, org_id, emp_id)
    rows = (
        db.query(EmployeeRiskSnapshot)
        .filter_by(org_id=org_id, employee_id=emp_id)
        .order_by(EmployeeRiskSnapshot.computed_at)
        .all()
    )
    return [
        RiskHistoryPointOut(
            run_id=r.run_id, computed_at=r.computed_at.isoformat(),
            turnover_probability=r.turnover_probability, risk_tier=r.risk_tier,
            model_available=r.model_available,
        )
        for r in rows
    ]


@router.get("/{emp_id}/risk-drivers", response_model=list[DriverOut])
def get_risk_drivers(org_id: int, emp_id: int, db: Session = Depends(get_db)):
    """Why *this* employee is at risk — the same importance-weighted,
    deviation-from-org-mean attribution ``/diagnose`` uses for a
    department/team, applied to one person. See
    ``ml.diagnostics.explain_employee``.
    """
    _get_emp_or_404(db, org_id, emp_id)
    driver_frame = build_driver_frame(db, org_id)
    bundle = load_production_bundle()
    contributions = explain_employee(emp_id, driver_frame, turnover_bundle=bundle)
    return [
        DriverOut(
            segment_type=c.segment_type, segment_id=c.segment_id, feature=c.feature,
            segment_mean=c.segment_mean, org_mean=c.org_mean,
            deviation=c.deviation, score=c.score,
        )
        for c in contributions
    ]
