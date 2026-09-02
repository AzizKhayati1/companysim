# Demo clips

Ten short MP4s, one per capability, each recorded against the running app
with a real model call. Nothing is staged, mocked or sped up — the pauses
you see are the extractor actually working.

Regenerate with `python scripts/record_demos.py` (needs the servers up;
see below).

| # | File | Shows | Length |
|---|---|---|---|
| 1 | `01-roster-csv-deterministic-parsing.mp4` | A roster CSV parsed with no model involved; only fields that differ are staged | 0:25 |
| 2 | `02-resignation-letter-llm-extraction.mp4` | Free prose read by the LLM — the letter contributes a label and a date, never a feature | 0:30 |
| 3 | `03-photographed-paper-ocr.mp4` | A photographed review transcribed on upload, marked OCR, then extracted through the same route | 0:32 |
| 4 | `04-honest-refusal-of-an-involuntary-exit.mp4` | A redundancy notice refused as a quit label, with the reason stored | 0:32 |
| 5 | `05-review-queue-filter-and-evidence.mp4` | Filtering 142 documents to the ones needing a decision, then the split review view | 0:22 |
| 6 | `06-scenario-simulator-forecast.mp4` | Building a scenario from a template and forecasting it | 0:33 |
| 7 | `07-diagnosis-report-modal.mp4` | The diagnosis opening over the page rather than below it | 0:36 |
| 8 | `08-retention-risk-ranking.mp4` | Who the model ranks highest, and the drivers behind each score | 0:18 |
| 9 | `09-turnover-model-and-promotion-gate.mp4` | The model, its metrics and the promotion audit log | 0:19 |
| 10 | `10-token-usage-meter.mp4` | Total / today / week, split by feature so OCR is separable from extraction | 0:15 |

Each clip carries a caption bar naming what is being shown, so it stands on
its own in a slide with no narration. Clips 1–4 pair with slide 07 of
`reading-the-paperwork.pptx`, which is the demo placeholder.

## Regenerating

```bash
.\scripts\start-dev.ps1                # both servers must be up
pip install playwright imageio-ffmpeg
python -m playwright install chromium
python scripts/record_demos.py
```

Two details in the recorder worth knowing before you edit it.

**Demo files are generated with a run-stamp.** The sample documents are
already uploaded to org 9, and upload rejects a duplicate content hash, so
a fixed fixture would fail on the second run. The recorder writes fresh
ones referencing real org-9 employees.

**It writes to `data/app.db`.** Each run adds four documents to org 9.
Restore afterwards with `git checkout -- data/app.db` unless you want to
keep them.

Videos are recorded as WebM by Playwright and converted to MP4 with the
ffmpeg binary that ships inside `imageio-ffmpeg` — PowerPoint will not
reliably play WebM, and this avoids a system ffmpeg install.

## What recording them found

Driving the real UI exposed a layout bug that no screenshot had: opening
the inspector takes 5 of 12 columns away from the list, and the fixed
column widths did not adapt. 616px of fixed cells left the filename
nothing, so names wrapped to three lines, the upload date collided with the
document type, and the Delete button was clipped. The list now drops the
*type* and *as-of* columns while the inspector is open — those are what a
reviewer can lose there; the filename and the status are what a row is
picked by.

That is the argument for recording flows rather than capturing screens: a
screenshot of the same page looked fine, because nothing was selected.
