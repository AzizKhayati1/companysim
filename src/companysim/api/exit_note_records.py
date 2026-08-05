"""Persist and query individual exit-interview notes across runs.

Unlike ``risk_snapshots.py`` (record-only, aggregation lives in
``scoring_frame.py``), this module also hosts the aggregation queries —
there's no existing shared adapter module for exit notes to slot into, and
the queries are small enough not to warrant one. Powers the Exit Notes
Insights page's theme-frequency, sentiment-trend, and recent-quotes views.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from companysim.api.db_models import ExitNoteRecord


@dataclass
class PendingNoteRecord:
    employee_id: int
    text: str
    sentiment: float
    themes: list[str]
    is_llm_generated: bool


def record_exit_notes(
    db: Session, org_id: int, run_id: int, records: list[PendingNoteRecord],
) -> None:
    if not records:
        return
    db.add_all(
        ExitNoteRecord(
            org_id=org_id,
            run_id=run_id,
            employee_id=r.employee_id,
            text=r.text,
            sentiment=r.sentiment,
            themes=",".join(r.themes),
            is_llm_generated=r.is_llm_generated,
            is_backfilled=False,
        )
        for r in records
    )
    db.commit()


def theme_frequency_rows(db: Session, org_id: int) -> list[dict[str, Any]]:
    """Count of notes mentioning each theme, descending. Themes are stored
    comma-joined (a note can match 0-7), so this counts in Python rather
    than via SQL GROUP BY.
    """
    theme_lists = (
        db.query(ExitNoteRecord.themes)
        .filter(ExitNoteRecord.org_id == org_id, ExitNoteRecord.themes != "")
        .all()
    )
    counts: dict[str, int] = {}
    for (themes,) in theme_lists:
        for theme in themes.split(","):
            counts[theme] = counts.get(theme, 0) + 1
    return [
        {"theme": theme, "count": count}
        for theme, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    ]


def sentiment_trend_rows(db: Session, org_id: int) -> list[dict[str, Any]]:
    """Mean sentiment per run that has notes, oldest first — mirrors
    ``scoring_frame.risk_trend_rows``'s per-run group-by shape."""
    rows = (
        db.query(
            ExitNoteRecord.run_id,
            func.min(ExitNoteRecord.generated_at).label("generated_at"),
            func.avg(ExitNoteRecord.sentiment).label("mean_sentiment"),
            func.count(ExitNoteRecord.id).label("n_notes"),
        )
        .filter(ExitNoteRecord.org_id == org_id)
        .group_by(ExitNoteRecord.run_id)
        .order_by(func.min(ExitNoteRecord.generated_at))
        .all()
    )
    return [
        {
            "run_id": r.run_id,
            "generated_at": r.generated_at.isoformat(),
            "mean_sentiment": float(r.mean_sentiment),
            "n_notes": int(r.n_notes),
        }
        for r in rows
    ]


def recent_quote_rows(db: Session, org_id: int, limit: int = 20) -> list[dict[str, Any]]:
    rows = (
        db.query(ExitNoteRecord)
        .filter(ExitNoteRecord.org_id == org_id)
        .order_by(ExitNoteRecord.generated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "run_id": r.run_id,
            "employee_id": r.employee_id,
            "text": r.text,
            "sentiment": r.sentiment,
            "themes": [t for t in r.themes.split(",") if t],
            "is_llm_generated": r.is_llm_generated,
            "is_backfilled": r.is_backfilled,
            "generated_at": r.generated_at.isoformat(),
        }
        for r in rows
    ]


def notes_totals(db: Session, org_id: int) -> dict[str, Any]:
    row = (
        db.query(
            func.count(ExitNoteRecord.id).label("n_notes_total"),
            func.avg(ExitNoteRecord.sentiment).label("mean_sentiment_overall"),
        )
        .filter(ExitNoteRecord.org_id == org_id)
        .first()
    )
    n_notes_total = int(row.n_notes_total or 0)
    mean_sentiment_overall = float(row.mean_sentiment_overall or 0.0)
    n_llm_generated_total = (
        db.query(func.count(ExitNoteRecord.id))
        .filter(ExitNoteRecord.org_id == org_id, ExitNoteRecord.is_llm_generated.is_(True))
        .scalar() or 0
    )
    n_backfilled_total = (
        db.query(func.count(ExitNoteRecord.id))
        .filter(ExitNoteRecord.org_id == org_id, ExitNoteRecord.is_backfilled.is_(True))
        .scalar() or 0
    )
    return {
        "n_notes_total": n_notes_total,
        "mean_sentiment_overall": mean_sentiment_overall,
        "n_llm_generated_total": int(n_llm_generated_total),
        "n_backfilled_total": int(n_backfilled_total),
    }
