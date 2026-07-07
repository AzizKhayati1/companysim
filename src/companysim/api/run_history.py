"""Persist a simulate/diagnose call so it can be reopened later.

Called from `routers/simulate.py` and `routers/diagnose.py` right after
each builds its response — every run auto-saves, no opt-in "save" step.
"""
from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.orm import Session

from companysim.api.db_models import RunRecord


def save_run(
    db: Session, org_id: int, run_type: str, summary: str,
    request: BaseModel, response: BaseModel,
) -> RunRecord:
    record = RunRecord(
        org_id=org_id, run_type=run_type, summary=summary,
        request_json=request.model_dump_json(),
        response_json=response.model_dump_json(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
