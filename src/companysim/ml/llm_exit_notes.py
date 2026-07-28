"""Optional real-LLM exit-note generation — Groq, behind a flag.

``exit_notes.py``'s template generator is fast, deterministic, and needs
no external service; that stays the default everywhere in this project,
including the test suite and CI. This module is the "clean, contained
upgrade" that module's docstring anticipates: when explicitly enabled
(``COMPANYSIM_LLM_EXIT_NOTES=1``) and a ``GROQ_API_KEY`` is present,
exit notes for employees who actually quit during a run are instead
written by Groq — grounded in the exact same top-driver signal
(``exit_notes._rank_bad_drivers``) so the LLM's note is honestly tied to
the same underlying state as the template path, never independently
invented.

Any failure — flag off, package not installed, no key, network error,
empty response — falls back to the template generator for that employee,
so a live API hiccup never breaks a diagnosis run.
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd

from companysim.ml.exit_notes import _PHRASE_BANK, _rank_bad_drivers, generate_note

_FLAG_VAR = "COMPANYSIM_LLM_EXIT_NOTES"
_MODEL = "llama-3.3-70b-versatile"
_MAX_OUTPUT_TOKENS = 200

_FEATURE_LABELS: dict[str, str] = {
    "workload_perceived": "workload",
    "burnout_exhaustion": "burnout/exhaustion",
    "stress_level": "day-to-day stress",
    "manager_support_score": "lack of manager support",
    "psychological_safety_perceived": "low psychological safety",
    "financial_security_score": "financial/compensation concerns",
    "meaning_at_work_score": "lack of meaning in the work",
    "sleep_quality": "poor sleep quality",
    "mood": "low mood",
    "life_satisfaction": "low life satisfaction",
}


def is_llm_enabled() -> bool:
    """True only when the flag is on, a key is present, and the optional
    ``groq`` package (the ``llm`` extra) is actually installed."""
    if os.environ.get(_FLAG_VAR, "").strip().lower() not in {"1", "true", "yes"}:
        return False
    if not os.environ.get("GROQ_API_KEY"):
        return False
    try:
        import groq  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def _build_prompt(driver_values: dict[str, float]) -> str | None:
    worst = _rank_bad_drivers(driver_values)
    if not worst:
        return None
    labels = [_FEATURE_LABELS.get(f, f) for f in worst]
    return (
        "You are simulating a short, first-person exit-interview note for a fictional "
        "employee in an organizational simulation model. No real person is involved. "
        f"Their most elevated risk factors, in order, were: {', '.join(labels)}. "
        "Write 2-4 sentences in a candid but professional first-person voice explaining "
        "why they're leaving, grounded in those factors. Don't mention numeric scores, "
        "and don't use the words 'simulation' or 'synthetic'. Optionally end with one "
        "brief positive aside about the team. Return only the note text, no preamble."
    )


def generate_note_via_llm(driver_values: dict[str, float]) -> str | None:
    """A Groq-generated note, or ``None`` on any failure — the caller
    should fall back to :func:`exit_notes.generate_note` when this
    returns ``None``."""
    prompt = _build_prompt(driver_values)
    if prompt is None:
        return None
    try:
        from groq import Groq  # noqa: PLC0415

        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_MAX_OUTPUT_TOKENS,
            temperature=0.9,
        )
        text = (response.choices[0].message.content or "").strip()
        return text or None
    except Exception:
        return None


def generate_notes_for_employees_mixed(
    driver_frame: pd.DataFrame, employee_ids: list[Any], rng: np.random.Generator,
) -> tuple[dict[Any, str], int]:
    """Same contract as ``exit_notes.generate_notes_for_employees``, but
    tries Groq first for each employee and falls back to the template
    generator on any failure. Returns ``(notes, n_llm_generated)``."""
    columns = [c for c in _PHRASE_BANK if c in driver_frame.columns]
    indexed = driver_frame.set_index("employee_id")
    notes: dict[Any, str] = {}
    n_llm = 0
    for eid in employee_ids:
        if eid not in indexed.index:
            continue
        row = indexed.loc[eid]
        values = {c: float(row[c]) for c in columns}
        llm_note = generate_note_via_llm(values)
        if llm_note:
            notes[eid] = llm_note
            n_llm += 1
        else:
            notes[eid] = generate_note(values, rng)
    return notes, n_llm
