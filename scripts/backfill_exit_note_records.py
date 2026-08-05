"""Backfill ExitNoteRecord rows from historical diagnose runs' saved responses.

Individual exit-note text/theme/sentiment was never persisted before the
``exit_note_records`` table existed — only an aggregated per-report
summary (``NotesSummaryOut``) survived, serialized inside
``RunRecord.response_json``. This script recovers what it can: the up-to-2
sample quotes each historical diagnose run happened to save, re-analyzed
with the same sentiment/theme logic used for real-time notes
(``ml.exit_notes.analyze_note``), inserted as rows flagged
``is_backfilled=True``.

This is explicitly PARTIAL:

- Only the up-to-2 sampled quotes per report are recovered, not every note
  ever generated — ``analyze_notes()`` itself discards the rest.
- ``employee_id`` is unrecoverable — ``sample_quotes`` in the stored JSON
  has no employee linkage — so backfilled rows always have
  ``employee_id=None``.
- ``is_llm_generated`` is an approximation: ``True`` only when the
  report's stored ``n_llm_generated == n_notes`` (every note in that
  report was provably LLM-written); ``False`` otherwise, since claiming
  "LLM-written" under ambiguity is a stronger claim than the safe default.

Idempotent: a run whose id already has any ``is_backfilled=True`` rows is
skipped, so re-running this script after new diagnose runs have happened
only backfills the newly-added ones.

Usage:

    python scripts/backfill_exit_note_records.py
"""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy.orm import Session

from companysim.api.database import SessionLocal
from companysim.api.db_models import ExitNoteRecord, RunRecord
from companysim.ml.exit_notes import analyze_note


def backfill_exit_notes(db: Session) -> dict[str, int]:
    already_backfilled_run_ids = {
        run_id for (run_id,) in
        db.query(ExitNoteRecord.run_id).filter(ExitNoteRecord.is_backfilled.is_(True)).distinct()
    }

    runs_processed = 0
    new_rows: list[ExitNoteRecord] = []
    for run in db.query(RunRecord).filter(RunRecord.run_type == "diagnose").all():
        if run.id in already_backfilled_run_ids:
            continue
        response = json.loads(run.response_json)
        run_had_quotes = False
        for report in response.get("reports", []):
            notes_summary = report.get("notes_summary")
            if not notes_summary:
                continue
            quotes = notes_summary.get("sample_quotes", [])
            if not quotes:
                continue
            run_had_quotes = True
            n_notes = notes_summary.get("n_notes", 0)
            n_llm = notes_summary.get("n_llm_generated", 0)
            # Only claim "LLM-written" when it's provably true for every
            # note in the report — we can't tell which specific sampled
            # quotes were LLM vs. template when it's a mix.
            is_llm_generated = n_notes > 0 and n_llm == n_notes
            for text in quotes:
                sentiment, themes = analyze_note(text)
                new_rows.append(ExitNoteRecord(
                    org_id=run.org_id, run_id=run.id, employee_id=None,
                    text=text, sentiment=sentiment, themes=",".join(themes),
                    is_llm_generated=is_llm_generated, is_backfilled=True,
                ))
        if run_had_quotes:
            runs_processed += 1

    if new_rows:
        db.add_all(new_rows)
        db.commit()

    return {"runs_processed": runs_processed, "rows_inserted": len(new_rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    db = SessionLocal()
    try:
        stats = backfill_exit_notes(db)
    finally:
        db.close()

    print(
        f"Backfilled {stats['rows_inserted']} exit-note row(s) "
        f"from {stats['runs_processed']} historical diagnose run(s).",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
