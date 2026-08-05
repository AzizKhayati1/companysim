"""Diff extracted rows against current org state → proposed changes.

Pure and DB-agnostic on purpose (no Session import, plain dicts in, plain
dataclasses out) — the same separation ``ml/gate.py`` keeps by only ever
receiving an already-built DataFrame. That's what lets the diff logic be
unit-tested with literal dicts while ``api/routers/ingest.py`` owns all
the SQLAlchemy on either side of it.

Only value *differences* become changes: re-uploading a roster that
matches the org exactly proposes nothing, so the review queue stays a
list of actual decisions rather than a re-confirmation of everything.
"""
from __future__ import annotations

from dataclasses import dataclass

from companysim.ingest.schemas import RosterRow

# RosterRow fields that map 1:1 onto EmployeeRecord columns.
RECONCILED_FIELDS: tuple[str, ...] = (
    "full_name", "level", "role", "tenure_months", "base_salary", "promotions_count",
)

# Fields the roster states as a *name* while EmployeeRecord holds an
# integer FK. Reconciled by comparing names on both sides — the caller
# passes id->name maps so this module still never touches a Session, and
# the staged fact carries the human-readable name (which is what a
# reviewer should see anyway). Resolving name -> id is the apply step's
# job; an unresolvable name surfaces there as a refusal rather than being
# silently dropped here.
NAME_REFERENCE_FIELDS: tuple[str, ...] = ("department_name", "team_name")

# NAME_REFERENCE_FIELDS -> (EmployeeRecord FK column, existing-dict key)
NAME_FIELD_TO_FK: dict[str, str] = {
    "department_name": "department_id",
    "team_name": "team_id",
}

# Sentinel field_name for a roster row with no matching employee — kept a
# reviewable fact (someone real is missing from the org) but never
# auto-applied; Phase 2's apply endpoint refuses to create employees.
NEW_HIRE_FIELD = "new_hire"


@dataclass
class ProposedChange:
    target_employee_id: int | None
    field_name: str
    proposed_value: str
    current_value: str | None
    confidence: float
    evidence_span: str


def _values_differ(field: str, proposed: object, current: object) -> bool:
    if current is None:
        return proposed is not None
    if field in ("tenure_months", "promotions_count", "base_salary"):
        return float(proposed) != float(current)  # type: ignore[arg-type]
    return str(proposed) != str(current)


def reconcile_roster(
    rows: list[RosterRow],
    existing: list[dict],
    *,
    department_names: dict[int, str] | None = None,
    team_names: dict[int, str] | None = None,
) -> list[ProposedChange]:
    """``existing`` dicts carry ``id``, ``email``, current values for
    :data:`RECONCILED_FIELDS`, and (for name-reference reconciliation)
    ``department_id``/``team_id``. ``department_names``/``team_names`` are
    id -> name maps the caller reads from the DB; omit them to skip
    name-reference fields entirely.

    Emails are matched case-insensitively — HRIS exports disagree on
    casing more often than on the address. Confidence is always 1.0 here:
    the rules parser read an exact cell, not an interpretation (the LLM
    path is the one that gets to say 0.7).

    A roster row whose email matches nobody becomes a single
    :data:`NEW_HIRE_FIELD` fact whose ``proposed_value`` is the row as
    JSON. That's the one place this staging table's string column carries
    structure rather than a scalar, and it's deliberate: creating an
    employee needs the whole row at once, and re-deriving it at apply time
    would mean re-parsing the document and hoping it still says the same
    thing.
    """
    by_email = {str(e["email"]).strip().lower(): e for e in existing}
    changes: list[ProposedChange] = []

    for row in rows:
        email = row.email.strip().lower()
        employee = by_email.get(email)
        if employee is None:
            changes.append(ProposedChange(
                target_employee_id=None,
                field_name=NEW_HIRE_FIELD,
                proposed_value=row.model_dump_json(),
                current_value=None,
                confidence=1.0,
                evidence_span=f"roster row for {row.email} matched no existing employee",
            ))
            continue

        for field in RECONCILED_FIELDS:
            proposed = getattr(row, field)
            if proposed is None:
                continue  # column absent/blank in the export — no opinion
            current = employee.get(field)
            if not _values_differ(field, proposed, current):
                continue
            changes.append(ProposedChange(
                target_employee_id=int(employee["id"]),
                field_name=field,
                proposed_value=str(proposed),
                current_value=None if current is None else str(current),
                confidence=1.0,
                evidence_span=f"roster row for {row.email}: {field}={proposed}",
            ))

        name_maps = {"department_name": department_names, "team_name": team_names}
        for field in NAME_REFERENCE_FIELDS:
            proposed = getattr(row, field)
            names = name_maps[field]
            if proposed is None or names is None:
                continue
            current_id = employee.get(NAME_FIELD_TO_FK[field])
            current = names.get(current_id) if current_id is not None else None
            if current is not None and str(proposed) == str(current):
                continue
            changes.append(ProposedChange(
                target_employee_id=int(employee["id"]),
                field_name=field,
                proposed_value=str(proposed),
                current_value=current,
                confidence=1.0,
                evidence_span=f"roster row for {row.email}: {field}={proposed}",
            ))
    return changes
