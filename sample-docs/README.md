# Sample documents

Test fixtures for the **Document Ingestion** page (`/orgs/:id/documents`).

Generated against **org 9 "Meridian Analytics"** (400 employees, seed 2026).
Every file that names an internal person uses a real employee's email from
that org, so matching actually succeeds. Against any other org those rows
become *new hires* or `needs_review` — which is a legitimate thing to test,
just not the one the filename describes.

Every file here has been run through the live API and behaves as listed.

## Rosters — deterministic, no API key needed

| File | Exercises | Expected |
|---|---|---|
| `01-updates-existing.csv` | field reconciliation | 4 facts staged (one row is byte-identical and must propose nothing) |
| `02-new-hires.csv` | **the hiring document** — 5 outsiders, real departments | 5 `new_hire` facts → Apply creates 5 employees |
| `03-mixed-updates-and-hires.csv` | updates + outsiders in one file | mix of field facts and `new_hire` facts |
| `04-new-hire-unknown-department.csv` | refusal path | 1 fact; Apply **rejects** it — departments are never auto-created |
| `05-messy-headers.csv` | tolerant parsing | header variants (`Work Email`, `Annual Salary`), `$1,42,000`, uppercase email still matches, blank-email row skipped |
| `06-no-email-column.csv` | hard parser error | `needs_review` — email is the match key, so this is a wrong-document error, not an empty success |

A roster row whose email matches nobody becomes a `new_hire` fact, and
approving it creates the `EmployeeRecord` plus its wellbeing row. That's why
`02-new-hires.csv` carries a `Department` column — creation needs somewhere
to put them, and an unknown department name is refused rather than invented.

## Offer letters — needs `COMPANYSIM_LLM_INGEST=1` + `GROQ_API_KEY`

The hiring document proper. Resolves to the **same** `new_hire` proposal a
roster row produces, so approving one creates the employee through one code
path rather than a parallel one.

| File | Exercises | Verified result |
|---|---|---|
| `01-engineering-ic3.txt` | full formal letter | staged: Nadia Osei, IC3 Backend Engineer, Engineering, 128000 — start date becomes the doc's as-of date |
| `02-design-ic2.txt` | informal email-style offer | staged; base salary read without the bonus/equity noise |
| `03-manager-with-team.txt` | names a specific team | staged with `team_name` |
| `04-no-department-stated.txt` | **refusal** | `needs_review` — names what it read *and* the departments that exist |
| `05-already-an-employee.txt` | wrong-document error | `needs_review` — a hiring document describes someone *new* |

Salary is annual **base** only; bonus, equity and sign-on are excluded by
the prompt and `01`/`03` both include those to prove it.

## CVs / résumés — same flag + key

Deliberately weaker than an offer letter. A CV says what a candidate has
done, not what you are hiring them into — department and salary are the
org's decision, made in an offer. So `CvExtract` has **no salary field at
all**, and a CV without a department stages a candidate that Apply then
refuses. That refusal is the intended outcome, not a gap.

| File | Exercises | Verified result |
|---|---|---|
| `01-senior-engineer.txt` | standard CV, no target dept | staged; Apply **refuses** — "names no department" |
| `02-graduate-no-target-role.txt` | graduate CV, sparse | staged; Apply refuses the same way |
| `03-with-target-department.txt` | states "APPLYING FOR: … Product" | staged **with** the department → Apply creates the employee |
| `04-no-email.txt` | no contact email | `needs_review` — email is the match key |

Confidence reflects authority: **1.0** for a CSV cell, **0.85** for an offer
letter, **0.6** for a CV. A CV is the candidate's own account of themselves,
and the fields it fills are the ones it's least authoritative about.

## Performance reviews — needs `COMPANYSIM_LLM_INGEST=1` + `GROQ_API_KEY`

| File | Exercises | Verified result |
|---|---|---|
| `01-strong-performer.txt` | happy path, 5/5 | `extracted`, period 2025-12-31 |
| `02-decline-h1.txt` | first of two periods, 4/5 | `extracted`, period 2025-06-30 |
| `03-decline-h2.txt` | **same employee**, later period, 2/5 | together these give a real `rating_delta = -2` |
| `04-outsider-not-in-org.txt` | contractor, email matches nobody | `needs_review`, nothing written |
| `05-ten-point-scale.txt` | scale conversion (7/10) | `extracted` as **3.5** on the 1–5 scale |
| `06-no-rating-stated.txt` | refusal, not invention | `needs_review` — the model reports the missing field rather than guessing |

`02` + `03` are the pair worth uploading together: they're the only way to
see `rating_last` / `rating_prev` / `rating_delta` all differ, which is the
whole point of ingesting reviews (they replace a hardcoded 3.0/3.0/0.0).

## Resignation letters — needs the same flag + key

| File | Exercises | Verified result |
|---|---|---|
| `01-burnout-workload.txt` | workload + unheard escalation | `extracted`, sentiment **−1.00**, themes `manager_support,workload` |
| `02-compensation.txt` | pay as the driver | `extracted`, theme `compensation` |
| `03-growth-and-meaning.txt` | stalled growth | `extracted`, theme `meaning` |
| `04-relocation-positive.txt` | leaving for non-work reasons | `extracted`, no negative theme — the honest "not the company's fault" case |
| `05-layoff-involuntary.txt` | **§5.6 boundary** | `needs_review` — an employer-initiated exit is refused as a quit label |
| `06-outsider-not-in-org.txt` | consultant, email matches nobody | `needs_review`, nothing written |
| `07-no-reason-given.txt` | valid label, no prose | `extracted` (contributes the date) but writes **no** exit note — there is nothing to analyze |

A letter contributes the quit **label** and its date, never a feature. It's
written at the moment of the outcome, so anything it says about workload or
morale would be temporal leakage — which is why
`ResignationLetterExtract` has no feature fields at all.

## Pulse export

`pulse/01-weekly-pulse-export.csv` — a plausible weekly pulse export.
There is **no parser for this kind yet**, so it uploads and parks as
`needs_review` with that reason. It's here to test the honest-refusal path,
and as the fixture for whoever closes the `*_pulse_trend` placeholders.

## Suggested run-through

1. Upload `rosters/02-new-hires.csv` with an as-of date of **2026-01-01**,
   Extract, approve all → 5 employees created.
2. Upload `performance-reviews/02` and `03`, Extract both → check
   **Where this lands**; `rating_delta` is now −2 for that employee.
3. Upload `resignation-letters/01`–`04`, Extract → notes appear on
   **Exit Notes Insights**.
4. Upload `05-layoff-involuntary.txt` → refused, and nothing is written.
5. The **Training cohort** panel should now be usable: the roster supplies
   the denominator, the letters supply the positives.

## Prompting is not a guarantee — one worked example

`offer-letters/04-no-department-stated.txt` is worth understanding. The
prompt tells the model to return `{"error": …}` when a required field is
missing. On this letter it instead returned
`department_name: "no department stated"` — a perfectly valid string that
passed schema validation and staged a plausible-looking hire.

The fix was not a better prompt. `routers/ingest.py` now **resolves the
department against ones that actually exist** before staging anything, the
same way the performance-review path resolves the employee email. Structural
checks catch a class of failure; prompt wording catches one phrasing of it.

## Known limitation you will see

Sentiment is a small hand-built lexicon (`ml/exit_notes.py`) tuned on the
template-generated notes. Real prose often scores **0.00** even when the
theme matches — `02-compensation.txt` reads as clearly unhappy but contains
few lexicon words. Themes are the more reliable signal on real documents.

Org 9 also contains 6 duplicate emails across 400 employees (the generator
reuses names). Every file here deliberately targets a unique-email employee;
a duplicate would match the *last* one silently.
