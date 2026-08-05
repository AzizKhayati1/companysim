"""Deterministic roster-CSV parsing — no LLM, no key, runs in CI.

Structured exports don't need a language model: a roster CSV has named
columns, and the only "understanding" required is mapping header variants
("Base Salary", "base_salary", "salary") onto ``RosterRow`` fields. Doing
that with a lookup table keeps this path fully deterministic and testable
offline — the same reason ``ml/exit_notes.py`` keeps its template
generator as the default under the optional LLM one. The LLM parser
(later phase) is only for free text, where no such table can exist.
"""
from __future__ import annotations

import csv
import io
import re

from companysim.ingest.schemas import RosterRow

# Canonical field -> accepted header variants, all compared in normalized
# form (lowercased, non-alphanumerics stripped) so "Base Salary",
# "base_salary" and "base-salary" all land in one entry.
_HEADER_VARIANTS: dict[str, tuple[str, ...]] = {
    "email": ("email", "emailaddress", "workemail", "mail"),
    "full_name": ("fullname", "name", "employeename"),
    "level": ("level", "grade", "band", "joblevel"),
    "role": ("role", "title", "jobtitle", "position"),
    "department_name": ("departmentname", "department", "dept", "org"),
    "team_name": ("teamname", "team", "squad"),
    "tenure_months": ("tenuremonths", "tenure", "monthsemployed"),
    "base_salary": ("basesalary", "salary", "annualsalary", "compensation"),
    "promotions_count": ("promotionscount", "promotions", "npromotions"),
}

_INT_FIELDS = {"tenure_months", "promotions_count"}
_FLOAT_FIELDS = {"base_salary"}

_NORMALIZE_RE = re.compile(r"[^a-z0-9]")


def _normalize(header: str) -> str:
    return _NORMALIZE_RE.sub("", header.lower())


def _map_headers(headers: list[str]) -> dict[str, str]:
    """Original header name -> RosterRow field, for headers we recognize."""
    variant_to_field = {
        variant: field for field, variants in _HEADER_VARIANTS.items() for variant in variants
    }
    mapped: dict[str, str] = {}
    for header in headers:
        field = variant_to_field.get(_normalize(header))
        if field is not None and field not in mapped.values():
            mapped[header] = field
    return mapped


def _coerce(field: str, raw: str) -> str | int | float | None:
    value = raw.strip()
    if not value:
        return None
    if field in _INT_FIELDS:
        # "3.0" and "$85,000"-style noise both appear in real exports.
        return int(float(value.replace(",", "")))
    if field in _FLOAT_FIELDS:
        return float(value.replace(",", "").replace("$", ""))
    return value


def parse_roster_csv(raw_text: str) -> list[RosterRow]:
    """``RosterRow`` per data line. Rows without a usable email are
    skipped (there's nothing to match them against), and a CSV with no
    recognizable email column at all raises — that's a wrong-document
    error the uploader should see, not an empty success.
    """
    reader = csv.DictReader(io.StringIO(raw_text))
    if not reader.fieldnames:
        raise ValueError("Empty CSV — no header row found.")
    header_map = _map_headers(list(reader.fieldnames))
    if "email" not in header_map.values():
        raise ValueError(
            "No email column recognized in CSV headers "
            f"{reader.fieldnames} — email is the roster match key."
        )

    rows: list[RosterRow] = []
    for raw_row in reader:
        values: dict[str, str | int | float | None] = {}
        for header, field in header_map.items():
            raw_value = raw_row.get(header)
            if raw_value is not None:
                values[field] = _coerce(field, raw_value)
        email = values.get("email")
        if not email:
            continue
        rows.append(RosterRow(**values))  # type: ignore[arg-type]
    return rows
