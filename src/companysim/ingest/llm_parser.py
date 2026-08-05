"""Optional real-LLM document extraction — Groq, behind a flag.

The third Groq integration in this codebase, after ``ml/llm_exit_notes.py``
and ``api/org_chat.py``, and it follows the same opt-in shape: off by
default, needs both ``COMPANYSIM_LLM_INGEST=1`` and a ``GROQ_API_KEY``,
and the whole test suite plus CI runs without either.

Where it *differs* from those two is the fallback policy, and the
difference is deliberate. Exit notes fall back to a template generator;
chat falls back to an honest "unavailable" message. Free-text extraction
falls back to **nothing at all** — every function here returns ``None`` on
any failure and the caller parks the document as ``needs_review``. A
half-parsed performance review is worse than an unparsed one: it would
write a wrong rating into a model feature under the appearance of real
data. ``ingest/rules_parser.py`` stays the default for anything
structured enough not to need a model.

Structured output is enforced twice: Groq's JSON mode constrains the
response to valid JSON, then the pydantic schema in ``ingest/schemas.py``
validates the fields. Anything that fails either check is a ``None``, not
a guess — and because ``ResignationLetterExtract`` has no feature fields,
even a maximally confused model cannot introduce temporal leakage through
this path.
"""
from __future__ import annotations

import json
import os
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from companysim.ingest.schemas import (
    CvExtract,
    OfferLetterExtract,
    PerformanceReviewExtract,
    ResignationLetterExtract,
)
from companysim.llm.usage import FEATURE_INGEST, record_response

_FLAG_VAR = "COMPANYSIM_LLM_INGEST"
MODEL = "llama-3.3-70b-versatile"
_MAX_OUTPUT_TOKENS = 600
# Extraction is a reading task, not a writing one — unlike exit-note
# *generation* (temperature 0.9 for variety), we want the most likely
# reading of the document every time.
_TEMPERATURE = 0.0

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)

_PERFORMANCE_REVIEW_PROMPT = """\
Extract structured fields from this performance review document.

Return ONLY a JSON object with exactly these keys:
  "employee_email":     string  - the reviewed employee's email address
  "review_period_end":  string  - ISO date (YYYY-MM-DD) the review period ENDS
  "rating":             number  - overall rating on a 1-5 scale
  "summary_text":       string  - one or two sentences summarizing the review

Rules:
- Convert any other rating scale to 1-5 proportionally (e.g. 7/10 -> 3.5,
  "Exceeds Expectations" on a 4-point scale -> 4.0).
- If the document does not state a value for a required key, return
  {"error": "<what is missing>"} instead of guessing.
- Do not infer an email address from a name.

Document:
---
%s
---
"""

_RESIGNATION_LETTER_PROMPT = """\
Extract structured fields from this resignation letter.

Return ONLY a JSON object with exactly these keys:
  "employee_email":  string   - the departing employee's email address
  "effective_date":  string   - ISO date (YYYY-MM-DD) their departure takes effect
  "is_voluntary":    boolean  - false if this describes a layoff, termination or
                                other employer-initiated exit; true otherwise
  "note_text":       string   - the letter's own words about WHY they are leaving,
                                verbatim or lightly condensed. Empty string if it
                                gives no reason.

Rules:
- Do NOT rate, score, or quantify anything (no workload/morale/burnout scores).
  Only the fields listed above are wanted.
- If the document does not state a value for a required key, return
  {"error": "<what is missing>"} instead of guessing.
- Do not infer an email address from a name.

Document:
---
%s
---
"""


def is_ingest_llm_enabled() -> bool:
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


def _complete_json(prompt: str) -> dict | None:
    try:
        from groq import Groq  # noqa: PLC0415

        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_MAX_OUTPUT_TOKENS,
            temperature=_TEMPERATURE,
            response_format={"type": "json_object"},
        )
        # Recorded before the response is inspected: a call that returned
        # unparseable JSON still burned tokens and still has to be billed.
        record_response(response, feature=FEATURE_INGEST, model=MODEL)
        text = (response.choices[0].message.content or "").strip()
        if not text:
            return None
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _extract(prompt_template: str, text: str, schema: type[_SchemaT]) -> _SchemaT | None:
    payload = _complete_json(prompt_template % text)
    if payload is None or "error" in payload:
        # The model reporting a missing field is a successful refusal, not
        # a crash — either way the caller parks the document for review.
        return None
    try:
        return schema.model_validate(payload)
    except ValidationError:
        return None


_OFFER_LETTER_PROMPT = """\
Extract structured fields from this employment offer letter.

Return ONLY a JSON object with exactly these keys:
  "candidate_email":  string  - the candidate's email address
  "candidate_name":   string  - the candidate's full name
  "department_name":  string  - the department/team org unit they will join
  "level":            string or null - job level/band if stated (e.g. IC3, M1)
  "role":             string or null - job title
  "team_name":        string or null - specific team, if named separately
  "base_salary":      number or null - annual base salary as a plain number
  "start_date":       string or null - ISO date (YYYY-MM-DD) they start

Rules:
- base_salary is the ANNUAL BASE only. Exclude bonus, equity and sign-on.
  Strip currency symbols and separators ("$128,000" -> 128000).
- department_name is required. If the letter does not say which department
  or org unit they are joining, return {"error": "no department stated"}.
- If any other required key is missing, return {"error": "<what is missing>"}.
- Do not infer an email address from a name.

Document:
---
%s
---
"""

_CV_PROMPT = """\
Extract structured fields from this candidate CV / resume.

Return ONLY a JSON object with exactly these keys:
  "candidate_email":    string - the candidate's email address
  "candidate_name":     string - the candidate's full name
  "most_recent_title":  string or null - their current/most recent job title
  "years_experience":   number or null - total years of professional experience
  "department_name":    string or null - the department they are applying to,
                        ONLY if the CV explicitly states a target department
  "level":              string or null - a job level ONLY if explicitly stated

Rules:
- Do NOT guess department_name or level from the job history. A CV states
  what someone has done, not what they are being hired into; that is the
  offer's job. Return null rather than inferring.
- Do NOT return a salary. A CV does not set compensation.
- years_experience: total professional years. Estimate from the earliest
  professional role if not stated outright, and use null if unclear.
- If candidate_email or candidate_name is missing, return
  {"error": "<what is missing>"}.

Document:
---
%s
---
"""


def extract_performance_review(text: str) -> PerformanceReviewExtract | None:
    return _extract(_PERFORMANCE_REVIEW_PROMPT, text, PerformanceReviewExtract)


def extract_offer_letter(text: str) -> OfferLetterExtract | None:
    return _extract(_OFFER_LETTER_PROMPT, text, OfferLetterExtract)


def extract_cv(text: str) -> CvExtract | None:
    return _extract(_CV_PROMPT, text, CvExtract)


def extract_resignation_letter(text: str) -> ResignationLetterExtract | None:
    return _extract(_RESIGNATION_LETTER_PROMPT, text, ResignationLetterExtract)
