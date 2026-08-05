"""Synthetic exit-interview notes + real NLP extraction over them.

Two halves, deliberately separate concerns:

1. **Generation** — ``generate_note`` builds a short first-person note
   grounded in an employee's actual simulated driver values, using
   ``ml/diagnostics.py``'s ``BAD_DIRECTION`` (the same "which direction is
   bad" convention the structured diagnosis uses) so the note's content
   is honestly tied to the same underlying state, not independently
   invented.
2. **Extraction** — ``analyze_notes`` runs actual text analysis over a
   set of notes: TF-IDF keyword extraction (scikit-learn, already a
   project dependency), a small hand-built lexicon for sentiment, and a
   keyword→theme mapping that's independent of the structured diagnosis
   (so agreement between the two is a genuine corroboration, not the
   same computation twice).

This is classical, dependency-light NLP — bag-of-words + a lexicon — not
a transformer or an LLM call. That's a deliberate choice: there's no real
free-text corpus in this synthetic system to justify anything heavier,
and this way the whole pipeline stays deterministic, fast, and testable
with no API keys or external services. Swapping in a real LLM call for
more natural generation or deeper extraction is a clean, contained
upgrade later if wanted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from companysim.ml.diagnostics import BAD_DIRECTION

# ---- Generation --------------------------------------------------------

_PHRASE_BANK: dict[str, list[str]] = {
    "workload_perceived": [
        "The workload became unsustainable, and there was no real relief in sight.",
        "I was constantly buried under an unsustainable workload with barely any time to catch my breath.",
        "The workload was overwhelming and ultimately unmanageable for one person.",
    ],
    "burnout_exhaustion": [
        "I was completely burned out by the end.",
        "I felt emotionally drained most days, even before I got to work.",
        "The exhaustion built up over months until I had nothing left to give.",
    ],
    "stress_level": [
        "The day-to-day stress was hard to sustain long-term.",
        "I was constantly stressed trying to keep up with everything.",
    ],
    "manager_support_score": [
        "I felt largely unsupported by my manager when things got difficult.",
        "Feedback from leadership was rare, and I often felt neglected and unheard.",
        "My manager was frequently unavailable when I needed guidance.",
    ],
    "psychological_safety_perceived": [
        "The environment felt unsafe for raising concerns or admitting a mistake.",
        "Speaking up about problems felt risky, so I mostly kept quiet.",
    ],
    "financial_security_score": [
        "The compensation didn't reflect the effort I was putting in, and I felt underpaid.",
        "I was worried about my finances and needed something that paid better.",
        "Pay was a real source of stress for me here.",
    ],
    "meaning_at_work_score": [
        "My work started to feel pointless, and I struggled to see its impact.",
        "It became hard to see the impact of what I was doing, which felt pointless at times.",
    ],
    "sleep_quality": [
        "I wasn't sleeping well, and the stress from this job followed me home.",
        "The stress from work followed me home and affected my sleep.",
    ],
    "mood": [
        "Honestly, I had become unhappy here and it was hard to shake.",
        "My mood had been low for a while before I decided to leave.",
    ],
    "life_satisfaction": [
        "Overall, this role left me feeling low and unhappy outside of work too.",
        "I felt like something had to change for my own wellbeing.",
    ],
}

_POSITIVE_ASIDES: list[str] = [
    "That said, I did appreciate my teammates and will miss working with them.",
    "To be fair, there were parts of the role I genuinely enjoyed.",
    "I want to be clear this wasn't about any one person — the team was great.",
    "",
]

_CONNECTIVES: list[str] = ["Also, ", "On top of that, ", "Beyond that, ", ""]

_NEUTRAL_NOTE = (
    "Overall things were fine; leaving was more about a personal "
    "opportunity than any specific issue here."
)


def _rank_bad_drivers(driver_values: dict[str, float], top_n: int = 3) -> list[str]:
    """Worst drivers first, restricted to fields with phrasing available,
    scored against an assumed-neutral 0.5 baseline (all these fields are
    0..1 scores) and the shared BAD_DIRECTION sign convention.
    """
    scored = []
    for feature, value in driver_values.items():
        if feature not in _PHRASE_BANK or feature not in BAD_DIRECTION:
            continue
        badness = (value - 0.5) * BAD_DIRECTION[feature]
        if badness > 0.05:
            scored.append((badness, feature))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [feature for _, feature in scored[:top_n]]


def generate_note(driver_values: dict[str, float], rng: np.random.Generator) -> str:
    """A short, first-person synthetic exit-interview note grounded in
    ``driver_values`` (any subset of BAD_DIRECTION's keys, 0..1 scale).
    """
    worst = _rank_bad_drivers(driver_values)
    if not worst:
        return _NEUTRAL_NOTE

    sentences = []
    for i, feature in enumerate(worst):
        phrase = str(rng.choice(_PHRASE_BANK[feature]))
        connective = _CONNECTIVES[0] if i == 0 else str(rng.choice(_CONNECTIVES[1:]))
        sentences.append(f"{connective}{phrase}" if connective else phrase)

    aside = str(rng.choice(_POSITIVE_ASIDES))
    if aside:
        sentences.append(aside)
    return " ".join(s for s in sentences if s)


def generate_notes_for_employees(
    driver_frame: pd.DataFrame, employee_ids: list[Any], rng: np.random.Generator,
) -> dict[Any, str]:
    columns = [c for c in _PHRASE_BANK if c in driver_frame.columns]
    indexed = driver_frame.set_index("employee_id")
    notes: dict[Any, str] = {}
    for eid in employee_ids:
        if eid not in indexed.index:
            continue
        row = indexed.loc[eid]
        values = {c: float(row[c]) for c in columns}
        notes[eid] = generate_note(values, rng)
    return notes


# ---- Extraction — the actual NLP ---------------------------------------

_POSITIVE_WORDS: set[str] = {
    "great", "good", "enjoyed", "appreciate", "appreciated", "supportive", "happy",
    "positive", "growth", "opportunity", "fair", "clear", "safe", "valued", "recognized",
    "team", "collaborative", "flexible", "balance",
}
_NEGATIVE_WORDS: set[str] = {
    "burned", "burnout", "exhausted", "exhausting", "exhaustion", "drained", "stress", "stressed",
    "unsustainable", "overwhelmed", "overwhelming", "unmanageable", "overworked", "buried",
    "unsupported", "neglected", "unheard", "unavailable", "unsafe", "risky", "pointless",
    "worried", "worry", "low", "unhappy", "unfair", "unclear", "underpaid", "undervalued",
}

_THEME_KEYWORDS: dict[str, set[str]] = {
    "workload": {"workload", "buried", "tasks", "unsustainable", "overwhelming", "unmanageable"},
    "burnout": {"burned", "burnout", "exhausted", "exhausting", "exhaustion", "drained"},
    "manager_support": {
        "manager", "unsupported", "guidance", "feedback", "leadership",
        "neglected", "unheard", "unavailable",
    },
    "psychological_safety": {"unsafe", "speaking", "risky", "mistake", "quiet"},
    "compensation": {"compensation", "pay", "paid", "underpaid", "finances", "financial"},
    "meaning": {"pointless", "impact", "meaningful"},
    "sleep_wellbeing": {"sleep", "sleeping", "mood", "wellbeing"},
}

_WORD_RE = re.compile(r"[a-z']+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def score_sentiment(text: str) -> float:
    """Lexicon-based sentiment in [-1, 1]: (positive - negative) word
    hits, normalized by note length. Simple and fully inspectable —
    every score traces back to which words fired, not a hidden model.
    """
    tokens = _tokenize(text)
    if not tokens:
        return 0.0
    pos = sum(1 for t in tokens if t in _POSITIVE_WORDS)
    neg = sum(1 for t in tokens if t in _NEGATIVE_WORDS)
    if pos == 0 and neg == 0:
        return 0.0
    return float(np.clip((pos - neg) / len(tokens) * 10, -1.0, 1.0))


def _match_themes(text: str) -> set[str]:
    tokens = set(_tokenize(text))
    return {theme for theme, keywords in _THEME_KEYWORDS.items() if tokens & keywords}


def analyze_note(text: str) -> tuple[float, list[str]]:
    """Per-note sentiment + matched themes — the same building blocks
    ``analyze_notes`` aggregates over a batch, exposed individually so a
    single note can be persisted with its own scores (see
    ``api.exit_note_records``) instead of only surviving inside a
    discarded batch aggregate.
    """
    return score_sentiment(text), sorted(_match_themes(text))


@dataclass
class NotesAnalysis:
    n_notes: int
    mean_sentiment: float
    theme_counts: dict[str, int] = field(default_factory=dict)
    top_terms: list[str] = field(default_factory=list)
    sample_quotes: list[str] = field(default_factory=list)
    n_llm_generated: int = 0


def analyze_notes(
    notes: dict[Any, str], *, max_quotes: int = 2, max_terms: int = 8, n_llm_generated: int = 0,
) -> NotesAnalysis:
    texts = list(notes.values())
    if not texts:
        return NotesAnalysis(n_notes=0, mean_sentiment=0.0)

    mean_sentiment = float(np.mean([score_sentiment(t) for t in texts]))

    theme_counts: dict[str, int] = {}
    for t in texts:
        for theme in _match_themes(t):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

    top_terms: list[str] = []
    if len(texts) >= 2:
        try:
            vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=50)
            matrix = vectorizer.fit_transform(texts)
            scores = matrix.sum(axis=0).A1
            terms = vectorizer.get_feature_names_out()
            ranked = sorted(zip(scores, terms), key=lambda t: t[0], reverse=True)
            top_terms = [term for _, term in ranked[:max_terms]]
        except ValueError:
            top_terms = []
    elif len(texts) == 1:
        top_terms = _tokenize(texts[0])[:max_terms]

    return NotesAnalysis(
        n_notes=len(texts), mean_sentiment=mean_sentiment,
        theme_counts=theme_counts, top_terms=top_terms, sample_quotes=texts[:max_quotes],
        n_llm_generated=n_llm_generated,
    )


def augment_explanation_with_notes(
    base_explanation: str, notes_analysis: NotesAnalysis | None,
) -> str:
    """Append a qualitative paragraph drawn from actual exit notes, when
    any exist — or an honest note that this diagnosis is structural-only
    when nobody in the segment actually left during this run.
    """
    if notes_analysis is None or notes_analysis.n_notes == 0:
        return (
            base_explanation
            + " No employees in this segment actually left during this run — "
              "this diagnosis is based on structural risk factors alone, not exit feedback."
        )

    themes = sorted(notes_analysis.theme_counts.items(), key=lambda kv: kv[1], reverse=True)
    theme_str = (
        ", ".join(f"{name} ({count})" for name, count in themes[:3])
        if themes else "no single recurring theme"
    )
    sentiment_word = (
        "negative" if notes_analysis.mean_sentiment < -0.15
        else "positive" if notes_analysis.mean_sentiment > 0.15
        else "mixed"
    )
    parts = [
        base_explanation,
        f"{notes_analysis.n_notes} employee(s) in this segment actually left during this run; "
        f"their exit notes skew {sentiment_word} (score {notes_analysis.mean_sentiment:+.2f}) "
        f"and most frequently mention: {theme_str}.",
    ]
    if notes_analysis.sample_quotes:
        parts.append(f'Representative note: "{notes_analysis.sample_quotes[0]}"')
    return " ".join(parts)
