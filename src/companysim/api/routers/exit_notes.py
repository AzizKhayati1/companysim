"""Exit Notes Insights — cross-run trending over the individual exit-note
records collected by ``routers.diagnose`` (real-time) and
``scripts/backfill_exit_note_records.py`` (recovered from historical runs).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.exit_note_records import (
    notes_totals,
    recent_quote_rows,
    sentiment_trend_rows,
    theme_frequency_rows,
)
from companysim.api.schemas import (
    ExitNoteQuoteOut,
    ExitNoteSentimentPointOut,
    ExitNotesInsightsResponse,
    ThemeFrequencyOut,
)

router = APIRouter(prefix="/orgs/{org_id}/exit-notes", tags=["exit-notes"])


@router.get("/insights", response_model=ExitNotesInsightsResponse)
def get_exit_notes_insights(org_id: int, quote_limit: int = 20, db: Session = Depends(get_db)):
    totals = notes_totals(db, org_id)
    return ExitNotesInsightsResponse(
        **totals,
        theme_frequency=[ThemeFrequencyOut(**row) for row in theme_frequency_rows(db, org_id)],
        sentiment_trend=[
            ExitNoteSentimentPointOut(**row) for row in sentiment_trend_rows(db, org_id)
        ],
        recent_quotes=[
            ExitNoteQuoteOut(**row) for row in recent_quote_rows(db, org_id, quote_limit)
        ],
    )
