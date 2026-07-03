from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.db_models import DepartmentRecord, EmployeeRecord, OrgRecord, TeamRecord
from companysim.api.schemas import DepartmentIn, DepartmentOut

router = APIRouter(prefix="/orgs/{org_id}/departments", tags=["departments"])


def _get_org_or_404(db: Session, org_id: int) -> OrgRecord:
    org = db.get(OrgRecord, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    return org


def _get_dept_or_404(db: Session, org_id: int, dept_id: int) -> DepartmentRecord:
    dept = db.query(DepartmentRecord).filter_by(org_id=org_id, id=dept_id).first()
    if dept is None:
        raise HTTPException(404, "department not found")
    return dept


@router.get("", response_model=list[DepartmentOut])
def list_departments(org_id: int, db: Session = Depends(get_db)):
    _get_org_or_404(db, org_id)
    return db.query(DepartmentRecord).filter_by(org_id=org_id).all()


@router.post("", response_model=DepartmentOut, status_code=201)
def create_department(org_id: int, body: DepartmentIn, db: Session = Depends(get_db)):
    _get_org_or_404(db, org_id)
    if not body.name:
        raise HTTPException(400, "name is required")
    dept = DepartmentRecord(
        org_id=org_id, name=body.name,
        salary_multiplier=body.salary_multiplier if body.salary_multiplier is not None else 1.0,
    )
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept


@router.patch("/{dept_id}", response_model=DepartmentOut)
def update_department(org_id: int, dept_id: int, body: DepartmentIn, db: Session = Depends(get_db)):
    dept = _get_dept_or_404(db, org_id, dept_id)
    if body.name is not None:
        dept.name = body.name
    if body.salary_multiplier is not None:
        dept.salary_multiplier = body.salary_multiplier
    db.commit()
    db.refresh(dept)
    return dept


@router.delete("/{dept_id}", status_code=204)
def delete_department(org_id: int, dept_id: int, db: Session = Depends(get_db)):
    dept = _get_dept_or_404(db, org_id, dept_id)
    if db.query(TeamRecord).filter_by(department_id=dept_id).count() > 0:
        raise HTTPException(400, "department still has teams — move or delete them first")
    if db.query(EmployeeRecord).filter_by(department_id=dept_id).count() > 0:
        raise HTTPException(400, "department still has employees — move or delete them first")
    db.delete(dept)
    db.commit()
