"""Turn ingested documents into *labeled cohorts* — never loose examples.

This module exists because of one specific way document-derived training
data destroys a model, and it's worth stating plainly: **you only ever
receive a resignation letter from someone who quit.** Feeding those in as
individual ``quit_within_horizon=True`` rows hands
``ml.gate.run_training_gate`` a 100%-positive sample, and since it
concatenates whatever DataFrame it's given onto the synthetic cohort
before training, the blended base rate shifts and the classifier learns
that everybody leaves.

The fix is structural: a document batch may only contribute examples if
it establishes a **denominator**. That means all three of

1. a roster naming everyone employed as of ``window_start``,
2. an outcome window ``window_start -> window_end``,
3. the resignations that fall inside it,

so that positives are the resignations and *negatives are everyone else on
the roster*. A batch that can't produce a denominator raises
:class:`CohortValidationError` and contributes nothing — refusing to emit
is the honest failure, exactly as ``ingest/llm_parser.py`` refuses to
guess at a half-read document.

This is the same reasoning §5.4 of ``docs/project_overview.md`` applies to
targeted interventions (company-wide totals are the wrong denominator for
a targeted program), pointed at training data instead of at an
intervention's effect size.

DB-agnostic like the rest of ``companysim.ingest``: plain dates, ids and
dicts in, a DataFrame out. ``api.ingest_records`` does the querying.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from companysim.ml.turnover_features import FEATURE_COLUMNS, assert_no_temporal_leakage

# A cohort whose positives are this common is almost certainly a
# resignation-letter pile with a roster that only covers leavers, not a
# real population. The synthetic cohorts this blends into run a base rate
# well under 0.2, so anything above this is a denominator failure wearing
# a denominator's clothes.
MAX_PLAUSIBLE_BASE_RATE = 0.5

# Below this, a cohort is too small for its positives to be anything but
# noise once concatenated onto thousands of synthetic rows — and small
# enough that one mis-parsed letter meaningfully moves it.
MIN_COHORT_SIZE = 10


class CohortValidationError(Exception):
    """A document batch that cannot honestly produce labeled examples."""


@dataclass
class DocumentCohort:
    """Feature rows + organic-quit labels derived from real documents.

    ``frame`` is ``FEATURE_COLUMNS`` + ``quit_within_horizon``, ready to
    concatenate onto ``ml.gate.run_training_gate``'s synthetic cohort —
    the same contract ``api.training_examples.load_collected_examples``
    already satisfies for webapp-run examples.
    """

    frame: pd.DataFrame
    window_start: date
    window_end: date
    n_positives: int
    n_negatives: int
    # Resignations naming someone absent from the roster: real exits we
    # cannot use, because without a roster row they have no features and
    # no denominator. Counted and surfaced rather than silently dropped.
    n_unmatched_resignations: int

    @property
    def base_rate(self) -> float:
        total = self.n_positives + self.n_negatives
        return self.n_positives / total if total else 0.0


def build_document_cohort(
    *,
    roster_employee_ids: list[int],
    feature_rows: list[dict],
    resignations: dict[int, date],
    window_start: date,
    window_end: date,
    feature_source_dates: dict[str, date],
) -> DocumentCohort:
    """Assemble one validated cohort.

    ``feature_rows`` are ``FEATURE_COLUMNS``-shaped dicts carrying an
    ``employee_id`` (i.e. ``api.scoring_frame.build_scoring_frame`` output
    as records). ``resignations`` maps employee id -> effective date, from
    ingested resignation letters. ``feature_source_dates`` maps each
    contributing document's label to its as-of date and is checked against
    ``window_start`` before anything else — a leaked feature invalidates
    the cohort no matter how good its denominator is.
    """
    if window_end <= window_start:
        raise CohortValidationError(
            f"Outcome window end {window_end} must be after start {window_start}."
        )

    # Leakage first: a cohort built from post-window features is wrong
    # even when its denominator is perfect.
    try:
        assert_no_temporal_leakage(feature_source_dates, window_start)
    except ValueError as exc:
        raise CohortValidationError(str(exc)) from None

    roster = list(dict.fromkeys(roster_employee_ids))
    if not roster:
        raise CohortValidationError(
            "No roster for the window — resignation letters alone have no denominator. "
            "Upload a roster dated on or before the window start first."
        )

    by_id = {int(r["employee_id"]): r for r in feature_rows}
    usable = [eid for eid in roster if eid in by_id]
    if len(usable) < MIN_COHORT_SIZE:
        raise CohortValidationError(
            f"Only {len(usable)} roster member(s) have features; "
            f"need at least {MIN_COHORT_SIZE} for a usable cohort."
        )

    in_window = {
        eid: eff for eid, eff in resignations.items()
        if window_start <= eff <= window_end
    }
    n_unmatched = sum(1 for eid in in_window if eid not in by_id)
    positives = {eid for eid in in_window if eid in by_id}

    n_positives = len(positives)
    n_negatives = len(usable) - n_positives
    base_rate = n_positives / len(usable)
    if base_rate > MAX_PLAUSIBLE_BASE_RATE:
        raise CohortValidationError(
            f"Implausible base rate {base_rate:.0%} ({n_positives}/{len(usable)}) — "
            "the roster looks like it only covers people who left, which is a "
            "positive-only sample, not a cohort."
        )

    records = []
    for eid in usable:
        row = {col: by_id[eid][col] for col in FEATURE_COLUMNS}
        row["quit_within_horizon"] = eid in positives
        records.append(row)

    frame = pd.DataFrame(records, columns=[*FEATURE_COLUMNS, "quit_within_horizon"])
    return DocumentCohort(
        frame=frame, window_start=window_start, window_end=window_end,
        n_positives=n_positives, n_negatives=n_negatives,
        n_unmatched_resignations=n_unmatched,
    )
