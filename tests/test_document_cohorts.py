"""Tests for the two guards that stand between real documents and the model:

- ``ml.turnover_features.assert_no_temporal_leakage`` — a feature source
  dated on or after the outcome window start is rejected, including the
  exact-tie case (the conservative reading, per its docstring).
- ``ingest.cohorts.build_document_cohort`` — the denominator rule. A pile
  of resignation letters is not a training set: without a roster there is
  no denominator, and a roster covering only leavers is a positive-only
  sample wearing a cohort's clothes.

Both are pure functions here — no DB, no API — because that's the point of
keeping ``companysim.ingest`` DB-agnostic.
"""
from __future__ import annotations

from datetime import date

import pytest

from companysim.ingest.cohorts import (
    MAX_PLAUSIBLE_BASE_RATE,
    MIN_COHORT_SIZE,
    CohortValidationError,
    build_document_cohort,
)
from companysim.ml.turnover_features import FEATURE_COLUMNS, assert_no_temporal_leakage

WINDOW_START = date(2026, 1, 1)
WINDOW_END = date(2026, 4, 1)


def _feature_row(employee_id: int) -> dict:
    """A FEATURE_COLUMNS-shaped row with plausible neutral values."""
    row: dict = {"employee_id": employee_id}
    for col in FEATURE_COLUMNS:
        if col in ("level", "department_id", "role"):
            row[col] = "IC2" if col == "level" else f"{col}_a"
        elif col.startswith("rating"):
            row[col] = 3.0
        else:
            row[col] = 0.5
    return row


def _rows(n: int, start: int = 1) -> list[dict]:
    return [_feature_row(i) for i in range(start, start + n)]


# ---- temporal leakage guard --------------------------------------------


def test_temporal_leakage_allows_sources_strictly_before_window():
    assert_no_temporal_leakage(
        {"review#1": date(2025, 12, 31), "review#2": date(2025, 6, 1)}, WINDOW_START,
    )


def test_temporal_leakage_rejects_source_dated_after_window_start():
    with pytest.raises(ValueError, match="Temporal leakage"):
        assert_no_temporal_leakage({"review#1": date(2026, 2, 1)}, WINDOW_START)


def test_temporal_leakage_rejects_exact_boundary_tie():
    """A source dated exactly on the window start can't be proven to
    predate the outcome, so the tie is rejected."""
    with pytest.raises(ValueError, match="on or after"):
        assert_no_temporal_leakage({"review#1": WINDOW_START}, WINDOW_START)


def test_temporal_leakage_message_names_every_offender():
    with pytest.raises(ValueError) as exc:
        assert_no_temporal_leakage(
            {"good": date(2025, 1, 1), "bad_a": date(2026, 3, 1), "bad_b": date(2026, 5, 1)},
            WINDOW_START,
        )
    message = str(exc.value)
    assert "bad_a" in message and "bad_b" in message
    assert "good" not in message


def test_empty_feature_dates_is_vacuously_fine():
    assert_no_temporal_leakage({}, WINDOW_START)


# ---- cohort denominator rule -------------------------------------------


def test_cohort_labels_roster_non_resigners_as_negatives():
    rows = _rows(20)
    cohort = build_document_cohort(
        roster_employee_ids=[r["employee_id"] for r in rows],
        feature_rows=rows,
        resignations={1: date(2026, 2, 1), 2: date(2026, 3, 1)},
        window_start=WINDOW_START, window_end=WINDOW_END,
        feature_source_dates={},
    )
    assert cohort.n_positives == 2
    assert cohort.n_negatives == 18
    assert len(cohort.frame) == 20
    assert cohort.frame["quit_within_horizon"].sum() == 2
    assert list(cohort.frame.columns) == [*FEATURE_COLUMNS, "quit_within_horizon"]
    assert cohort.base_rate == pytest.approx(0.1)


def test_cohort_without_roster_is_refused():
    """The headline failure mode: resignation letters alone."""
    with pytest.raises(CohortValidationError, match="no denominator"):
        build_document_cohort(
            roster_employee_ids=[],
            feature_rows=_rows(20),
            resignations={1: date(2026, 2, 1)},
            window_start=WINDOW_START, window_end=WINDOW_END,
            feature_source_dates={},
        )


def test_cohort_of_only_leavers_is_refused_as_positive_only():
    rows = _rows(20)
    all_resigned = {r["employee_id"]: date(2026, 2, 1) for r in rows}
    with pytest.raises(CohortValidationError, match="Implausible base rate"):
        build_document_cohort(
            roster_employee_ids=[r["employee_id"] for r in rows],
            feature_rows=rows,
            resignations=all_resigned,
            window_start=WINDOW_START, window_end=WINDOW_END,
            feature_source_dates={},
        )


def test_cohort_base_rate_just_under_threshold_is_allowed():
    rows = _rows(20)
    n_positive = int(MAX_PLAUSIBLE_BASE_RATE * 20)  # exactly at the threshold
    resignations = {r["employee_id"]: date(2026, 2, 1) for r in rows[:n_positive]}
    cohort = build_document_cohort(
        roster_employee_ids=[r["employee_id"] for r in rows],
        feature_rows=rows, resignations=resignations,
        window_start=WINDOW_START, window_end=WINDOW_END,
        feature_source_dates={},
    )
    assert cohort.base_rate == pytest.approx(MAX_PLAUSIBLE_BASE_RATE)


def test_cohort_too_small_is_refused():
    rows = _rows(MIN_COHORT_SIZE - 1)
    with pytest.raises(CohortValidationError, match="at least"):
        build_document_cohort(
            roster_employee_ids=[r["employee_id"] for r in rows],
            feature_rows=rows, resignations={},
            window_start=WINDOW_START, window_end=WINDOW_END,
            feature_source_dates={},
        )


def test_resignations_outside_the_window_are_not_positives():
    rows = _rows(20)
    cohort = build_document_cohort(
        roster_employee_ids=[r["employee_id"] for r in rows],
        feature_rows=rows,
        resignations={
            1: date(2025, 6, 1),    # before the window
            2: date(2026, 9, 1),    # after the window
            3: date(2026, 2, 1),    # inside
        },
        window_start=WINDOW_START, window_end=WINDOW_END,
        feature_source_dates={},
    )
    assert cohort.n_positives == 1
    quit_ids = set(cohort.frame.index[cohort.frame["quit_within_horizon"]])
    assert len(quit_ids) == 1


def test_resignation_for_someone_off_the_roster_is_counted_not_dropped():
    rows = _rows(20)
    cohort = build_document_cohort(
        roster_employee_ids=[r["employee_id"] for r in rows],
        feature_rows=rows,
        resignations={1: date(2026, 2, 1), 999: date(2026, 2, 1)},
        window_start=WINDOW_START, window_end=WINDOW_END,
        feature_source_dates={},
    )
    assert cohort.n_positives == 1
    assert cohort.n_unmatched_resignations == 1


def test_cohort_rejects_leaked_feature_source_even_with_good_denominator():
    rows = _rows(20)
    with pytest.raises(CohortValidationError, match="Temporal leakage"):
        build_document_cohort(
            roster_employee_ids=[r["employee_id"] for r in rows],
            feature_rows=rows,
            resignations={1: date(2026, 2, 1)},
            window_start=WINDOW_START, window_end=WINDOW_END,
            feature_source_dates={"review#1": date(2026, 3, 1)},
        )


def test_cohort_rejects_inverted_window():
    rows = _rows(20)
    with pytest.raises(CohortValidationError, match="must be after"):
        build_document_cohort(
            roster_employee_ids=[r["employee_id"] for r in rows],
            feature_rows=rows, resignations={},
            window_start=WINDOW_END, window_end=WINDOW_START,
            feature_source_dates={},
        )
