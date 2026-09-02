"""Record one video per major capability, driving the real app.

Each clip is a real interaction against a running server and a real model
call — nothing is faked or sped up. A caption banner is injected so a
viewer knows what is being demonstrated without narration, which is what
makes these usable as standalone slides.

Demo files are generated fresh with a run-stamp: the sample documents are
already uploaded to org 9, and the content hash would reject a duplicate.
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "docs" / "demos" / ".work"
FILES = HERE / "demo_files"
RAW = HERE / "demo_raw"
OUT = ROOT / "docs" / "demos"
BASE = "http://localhost:5173"
ORG = 9
STAMP = datetime.now().strftime("%H%M%S")

for d in (FILES, RAW, OUT):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- fixtures
con = sqlite3.connect(ROOT / "data" / "app.db")
emps = [r for r in con.execute(
    "select full_name, email from employees where org_id=? limit 400", (ORG,))]
seen: dict[str, int] = {}
for _, e in emps:
    seen[e.lower()] = seen.get(e.lower(), 0) + 1
uniq = [(n, e) for n, e in emps if seen[e.lower()] == 1]
A, B, C = uniq[10], uniq[11], uniq[12]

(FILES / "roster-update.csv").write_text(
    "email,full_name,level,base_salary\n"
    f"{A[1]},{A[0]},IC5,132500\n"
    f"{B[1]},{B[0]},M1,151000\n", encoding="utf-8")

(FILES / "resignation-letter.txt").write_text(
    f"""{C[0]}
{C[1]}

18 August 2026

Dear Alison,

I am writing to give formal notice of my resignation. My last working day
will be 30 September 2026.

The workload has not come back down since the reorg in March. I raised it
twice and was told each time that it would settle after the next release.
It did not settle. I am tired in a way a holiday does not fix.

I will hand over cleanly — the runbooks are current.

Regards,
{C[0]}
(ref {STAMP})
""", encoding="utf-8")

(FILES / "redundancy-notice.txt").write_text(
    f"""NOTICE OF TERMINATION OF EMPLOYMENT

To:       {A[0]} ({A[1]})
Date:     18 August 2026

Following the restructure announced on 2 August 2026, your role has been
identified as redundant. Your employment will end on 30 September 2026.

This is an employer-initiated termination. You will receive statutory
redundancy pay plus an enhanced package.

People Operations  (ref {STAMP})
""", encoding="utf-8")

# A photographed page, drawn rather than sourced so it can be regenerated.
from PIL import Image, ImageDraw  # noqa: E402

img = Image.new("RGB", (940, 470), "white")
d = ImageDraw.Draw(img)
y = 30
for line in ["MERIDIAN ANALYTICS", "",
             f"Employee: {B[0]}", f"Email: {B[1]}", "",
             "PERFORMANCE REVIEW", "Period ending: 31 December 2025", "",
             "Overall rating: 4 out of 5", "",
             f"Signed, A. Pike   (ref {STAMP})"]:
    d.text((40, y), line, fill="black")
    y += 38
img.save(FILES / "scanned-review.png")

print(f"fixtures: {A[0]}, {B[0]}, {C[0]}")

# ---------------------------------------------------------------- helpers
CAPTION_JS = """
(text) => {
  let el = document.getElementById('__demo_caption');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_caption';
    el.style.cssText = [
      'position:fixed','left:0','right:0','bottom:0','z-index:99999',
      'padding:14px 24px','background:rgba(8,12,12,0.94)',
      'color:#f2f5f4','font:600 17px/1.4 "Segoe UI",system-ui,sans-serif',
      'borderTop:2px solid #a79bff','letter-spacing:.01em',
      'box-shadow:0 -8px 24px rgba(0,0,0,.4)'
    ].join(';');
    el.style.borderTop = '2px solid #a79bff';
    document.body.appendChild(el);
  }
  el.textContent = text;
}
"""


def caption(page, text, hold=2.2):
    page.evaluate(CAPTION_JS, text)
    time.sleep(hold)


def convert(src: Path, dest: Path) -> None:
    """webm -> mp4. PowerPoint will not reliably play webm."""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [ff, "-y", "-loglevel", "error", "-i", str(src),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
         "-vf", "scale=1440:-2", str(dest)],
        check=True)


RESULTS: list[tuple[str, str]] = []


def demo(name: str, title: str):
    """Decorator: one recorded context per capability."""
    def wrap(fn):
        def run(browser):
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900},
                record_video_dir=str(RAW),
                record_video_size={"width": 1440, "height": 900},
            )
            page = ctx.new_page()
            page.set_default_timeout(45_000)
            try:
                fn(page)
                time.sleep(1.4)
                status = "ok"
            except Exception as exc:  # keep the batch going
                status = f"FAILED: {type(exc).__name__}: {str(exc)[:120]}"
            vid = page.video.path() if page.video else None
            ctx.close()
            if vid:
                dest = OUT / f"{name}.mp4"
                convert(Path(vid), dest)
            RESULTS.append((name, status))
            print(f"  {name:52} {status}")
        run.__name__ = fn.__name__
        return run
    return wrap


def goto_documents(page):
    page.goto(f"{BASE}/orgs/{ORG}/documents", wait_until="networkidle")
    time.sleep(1.2)


def upload(page, kind_label: str, filename: str, as_of: str | None = None):
    page.locator("select").first.select_option(label=kind_label)
    if as_of:
        page.locator('input[type="date"]').first.fill(as_of)
    page.locator('input[type="file"]').set_input_files(str(FILES / filename))
    time.sleep(0.7)
    page.get_by_role("button", name="Upload", exact=True).click()
    page.wait_for_timeout(2500)


# ---------------------------------------------------------------- demos
@demo("01-roster-csv-deterministic-parsing", "Roster CSV")
def d01(page):
    goto_documents(page)
    caption(page, "1 — Roster CSV: parsed deterministically, no model involved", 2.6)
    upload(page, "Roster export", "roster-update.csv", "2026-01-01")
    caption(page, "Uploaded. Extract compares each row against the current roster.", 2.4)
    page.get_by_role("button", name="Extract", exact=True).first.click()
    page.wait_for_timeout(3500)
    caption(page, "Only fields that actually differ are staged — nothing is written yet.", 3.4)
    page.mouse.wheel(0, 500)
    time.sleep(2.4)


@demo("02-resignation-letter-llm-extraction", "Resignation letter")
def d02(page):
    goto_documents(page)
    caption(page, "2 — A resignation letter: free prose, read by the language model", 2.6)
    upload(page, "Resignation letter", "resignation-letter.txt", "2026-09-30")
    caption(page, "Extracting… the letter contributes a LABEL and a date, never a feature.", 2.2)
    page.get_by_role("button", name="Extract", exact=True).first.click()
    page.wait_for_timeout(9000)
    caption(page, "Extracted. The schema has no feature fields, so it cannot leak one.", 3.6)
    page.mouse.wheel(0, 450)
    time.sleep(2.2)


@demo("03-photographed-paper-ocr", "OCR")
def d03(page):
    goto_documents(page)
    caption(page, "3 — Paper: a photographed performance review, read by OCR", 2.8)
    upload(page, "Performance review", "scanned-review.png", "2025-12-31")
    caption(page, "Transcribed on upload and marked OCR — paper is a front door, not a second pipeline.", 3.4)
    page.get_by_role("button", name="Extract", exact=True).first.click()
    page.wait_for_timeout(9000)
    caption(page, "Same route as a typed file. Facts from a photo are staged at 0.7x confidence.", 3.8)
    page.mouse.wheel(0, 450)
    time.sleep(2.2)


@demo("04-honest-refusal-of-an-involuntary-exit", "Refusal")
def d04(page):
    goto_documents(page)
    caption(page, "4 — Honest refusal: a redundancy notice is not a resignation", 3.0)
    upload(page, "Resignation letter", "redundancy-notice.txt", "2026-09-30")
    caption(page, "Extracting… a layoff must not become a voluntary-quit label.", 2.2)
    page.get_by_role("button", name="Extract", exact=True).first.click()
    page.wait_for_timeout(9000)
    caption(page, "Refused, with the reason stored. Nothing was written — that is the success case.", 4.0)
    page.mouse.wheel(0, 400)
    time.sleep(2.4)


@demo("05-review-queue-filter-and-evidence", "Review queue")
def d05(page):
    goto_documents(page)
    caption(page, "5 — The queue: 135 documents, and the handful that need a decision", 3.0)
    page.get_by_role("tab").nth(1).click()   # "Needs review N"
    page.wait_for_timeout(1500)
    caption(page, "Filtered to what is waiting on you, rather than scrolling to find it.", 2.8)
    page.get_by_role("button", name="Review", exact=True).first.click()
    page.wait_for_timeout(2000)
    caption(page, "List and inspector side by side — choosing and deciding are one glance.", 3.2)
    page.mouse.wheel(0, 300)
    time.sleep(2.6)


@demo("06-scenario-simulator-forecast", "Simulator")
def d06(page):
    page.goto(f"{BASE}/orgs/{ORG}/simulate", wait_until="networkidle")
    time.sleep(1.2)
    caption(page, "6 — Scenario simulator: model a change before you make it", 2.8)
    page.get_by_role("button", name="Layoff wave").click()
    page.wait_for_timeout(1200)
    caption(page, "A template drops events onto the timeline — position in time is real information.", 3.2)
    page.get_by_role("button", name="Run forecast").click()
    page.wait_for_timeout(11000)
    caption(page, "Baseline against the scenario, with the effect measured in the targeted cohort.", 3.4)
    page.mouse.wheel(0, 700)
    time.sleep(3.0)


@demo("07-diagnosis-report-modal", "Diagnosis")
def d07(page):
    page.goto(f"{BASE}/orgs/{ORG}/simulate", wait_until="networkidle")
    time.sleep(1.2)
    caption(page, "7 — Diagnose: the report opens over the page, not below it", 3.0)
    page.get_by_role("button", name="Diagnose").click()
    page.wait_for_timeout(14000)
    caption(page, "Top drivers, the affected cohort, and a recommendation you can apply.", 3.4)
    page.mouse.wheel(0, 400)
    time.sleep(2.6)
    caption(page, "Dismissing costs nothing — the scenario underneath keeps its state.", 2.8)


@demo("08-retention-risk-ranking", "Retention risk")
def d08(page):
    page.goto(f"{BASE}/orgs/{ORG}/at-risk", wait_until="networkidle")
    time.sleep(1.6)
    caption(page, "8 — Retention risk: who the model ranks highest, and why", 3.2)
    page.mouse.wheel(0, 450)
    time.sleep(2.8)
    caption(page, "Each score traces to drivers — the model never shows a number alone.", 3.2)


@demo("09-turnover-model-and-promotion-gate", "Model")
def d09(page):
    page.goto(f"{BASE}/model", wait_until="networkidle")
    time.sleep(1.6)
    caption(page, "9 — The turnover model and its promotion gate", 3.0)
    page.mouse.wheel(0, 400)
    time.sleep(2.6)
    caption(page, "A candidate is promoted only if AUC does not regress. Every decision is logged.", 3.6)


@demo("10-token-usage-meter", "Token meter")
def d10(page):
    goto_documents(page)
    caption(page, "10 — What it costs: every model call is metered", 2.8)
    page.get_by_role("button", name="LLM token usage").click()
    page.wait_for_timeout(1500)
    caption(page, "Total, today and this week — split by feature, so OCR is separable from extraction.", 3.8)
    time.sleep(1.6)


DEMOS = [d01, d02, d03, d04, d05, d06, d07, d08, d09, d10]

if __name__ == "__main__":
    print(f"recording {len(DEMOS)} demos -> {OUT}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for fn in DEMOS:
            fn(browser)
        browser.close()
    shutil.rmtree(RAW, ignore_errors=True)
    print("\n--- summary ---")
    for name, status in RESULTS:
        print(f"  {name:52} {status}")
