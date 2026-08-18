"""Format stress corpus — descriptive filenames, one behaviour per file.

Volume was covered by the earlier 106-document run. This corpus varies the
*shape* of the input instead: delimiters, encodings, locales, rating
scales, date orders, page layout and file type. Each filename states what
it tests, so a results table reads without a legend.
"""
from __future__ import annotations

import collections
import json
import sqlite3
import sys
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    sys.exit('fpdf2 is required: pip install -e ".[api]"')

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample-docs" / "format-tests"
DB = ROOT / "data" / "app.db"
ORG_ID = 9


def _employees() -> list[dict]:
    """Real employees from the seeded demo org, so email matching in the
    generated files actually exercises reconciliation rather than always
    falling through to the new-hire path.

    Duplicate addresses are filtered out: org 9 contains six, and a file
    targeting one would confound the format behaviour under test with the
    known duplicate-match defect.
    """
    if not DB.exists():
        sys.exit(f"{DB} not found - this generator reads the seeded demo org.")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "select full_name, email from employees where org_id = ? order by id", (ORG_ID,))]
    seen = collections.Counter(r["email"].lower() for r in rows)
    uniq = [r for r in rows if seen[r["email"].lower()] == 1]
    if len(uniq) < 20:
        sys.exit(f"only {len(uniq)} unique-email employees in org {ORG_ID}; expected many more.")
    return uniq


E = _employees()

manifest: list[dict] = []


def add(kind: str, name: str, tests: str, expect: str, data: bytes, as_of="2026-01-01") -> None:
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    manifest.append({"kind": kind, "name": name, "path": str(p),
                     "tests": tests, "expect": expect, "as_of": as_of})


def txt(kind, name, tests, expect, body, *, encoding="utf-8", as_of="2026-01-01"):
    add(kind, name, tests, expect, body.encode(encoding), as_of)


def pdf(kind, name, tests, expect, lines, *, columns=False, as_of="2026-01-01"):
    doc = FPDF()
    doc.add_page()
    doc.set_font("Helvetica", size=10)
    if columns:
        # Two-column layout: PDF text extraction reads by content stream
        # order, not visual columns, so this interleaves the two columns.
        left, right = lines
        doc.set_xy(15, 20)
        for ln in left:
            doc.set_x(15)
            doc.multi_cell(80, 5, ln)
        doc.set_xy(105, 20)
        for ln in right:
            doc.set_x(105)
            doc.multi_cell(80, 5, ln)
    else:
        for ln in lines:
            if ln == "%%PAGEBREAK%%":
                doc.add_page()
                continue
            # x must be reset explicitly: multi_cell leaves the cursor at
            # the end of the last line, so a width-0 (full-width) call
            # afterwards has no room left and raises.
            doc.set_x(doc.l_margin)
            if not ln.strip():
                doc.ln(5)
            else:
                doc.multi_cell(0, 5, ln)
    add(kind, name, tests, expect, bytes(doc.output()), as_of)


# =====================================================================
# CSV — delimiters, encodings, locales, layout
# =====================================================================

a, b, c, d = E[0], E[1], E[2], E[3]

txt("roster", "roster-semicolon-delimited-french-excel.csv",
    "`;` separator — the default of Excel on a French/European locale",
    "REFUSED: no email column (DictReader assumes comma)",
    f"email;full_name;base_salary\n{a['email']};{a['full_name']};85000\n")

txt("roster", "roster-tab-delimited-export.csv",
    "Tab separator, common from database exports",
    "REFUSED: no email column",
    f"email\tfull_name\tbase_salary\n{a['email']}\t{a['full_name']}\t85000\n")

txt("roster", "roster-european-decimal-comma-salary.csv",
    "Salary written 85000,50 — decimal comma, French/German convention",
    "SILENT CORRUPTION: comma stripped -> 8500050",
    f"email,full_name,base_salary\n{a['email']},{a['full_name']},\"85000,50\"\n")

txt("roster", "roster-german-thousands-dot-decimal-comma.csv",
    "Salary written 85.000,50 — dot thousands + comma decimal",
    "SILENT CORRUPTION: -> 85.0005",
    f"email,full_name,base_salary\n{a['email']},{a['full_name']},\"85.000,50\"\n")

txt("roster", "roster-space-thousands-separator.csv",
    "Salary written '85 000' — the official French thousands separator",
    "REFUSED or row skipped: float() rejects the space",
    f"email,full_name,base_salary\n{a['email']},{a['full_name']},\"85 000\"\n")

txt("roster", "roster-salary-with-currency-suffix-eur.csv",
    "Salary written '85000 EUR' rather than a bare number",
    "REJECTED: only '$' is stripped",
    f"email,full_name,base_salary\n{a['email']},{a['full_name']},85000 EUR\n")

txt("roster", "roster-salary-in-tunisian-dinar.csv",
    "Non-USD currency with a three-decimal minor unit (TND)",
    "Parsed as a plain number; currency is silently lost",
    f"email,full_name,base_salary\n{a['email']},{a['full_name']},\"48500,000\"\n")

txt("roster", "roster-utf8-bom-excel-export.csv",
    "UTF-8 byte-order mark before the header, as Excel writes it",
    "OK: utf-8-sig decode strips the BOM",
    f"email,full_name,level\n{a['email']},{a['full_name']},IC4\n",
    encoding="utf-8-sig")

txt("roster", "roster-latin1-encoded-accented-names.csv",
    "Latin-1 encoding with accented French names",
    "OK: falls back to latin-1 after UTF-8 fails",
    f"email,full_name,role\n{a['email']},Hélène Lefèvre,Ingénieur Système\n",
    encoding="latin-1")

txt("roster", "roster-title-rows-above-header.csv",
    "Two report/title lines before the real header, as Excel exports do",
    "REFUSED: line 1 is read as the header",
    "Meridian Analytics - Headcount Report\nGenerated 2026-01-05\n"
    f"email,full_name,level\n{a['email']},{a['full_name']},IC3\n")

txt("roster", "roster-trailing-total-and-blank-rows.csv",
    "A TOTAL row and blank padding after the data, as spreadsheets add",
    "Data rows OK; the TOTAL row should be skipped (no email)",
    f"email,full_name,base_salary\n{a['email']},{a['full_name']},91000\n"
    f"{b['email']},{b['full_name']},77000\n"
    ",TOTAL,168000\n,,\n,,\n")

txt("roster", "roster-quoted-fields-containing-commas.csv",
    "Quoted values containing commas (job title with a comma)",
    "OK: csv module handles quoting",
    f'email,full_name,role\n{a["email"]},"{a["full_name"]}","Engineer, Platform"\n')

txt("roster", "roster-same-employee-listed-twice-conflicting.csv",
    "One employee on two rows with different salaries",
    "OPEN DEFECT: last row silently wins, no conflict raised",
    f"email,full_name,base_salary\n{a['email']},{a['full_name']},90000\n"
    f"{a['email']},{a['full_name']},120000\n")

txt("roster", "roster-single-data-row-minimal-columns.csv",
    "Smallest valid roster: email column only",
    "OK: one row, nothing to propose",
    f"email\n{a['email']}\n")

# =====================================================================
# Markdown
# =====================================================================

txt("performance_review", "performance-review-markdown-with-rating-table.md",
    "Markdown with the rating inside a pipe table",
    "Should extract 4.0 from the table",
    f"""# Performance Review — {b['full_name']}

**Employee:** {b['full_name']}
**Email:** `{b['email']}`
**Period:** 1 Jan 2025 – 31 Dec 2025

## Scorecard

| Dimension        | Weight | Score |
|------------------|--------|-------|
| Delivery         | 40%    | 4     |
| Collaboration    | 30%    | 5     |
| Technical craft  | 30%    | 3     |
| **Overall**      | —      | **4** |

## Narrative

Strong year. Took ownership of the reconciliation rewrite and delivered it
two sprints early.
""", as_of="2025-12-31")

txt("resignation_letter", "resignation-letter-markdown-formatted.md",
    "Markdown resignation with headings and a bullet list",
    "Should extract normally; markup must not leak into note_text",
    f"""## Notice of Resignation

**From:** {c['full_name']} <{c['email']}>
**Effective:** 2026-03-31

Dear team,

I am resigning from my position. My reasons, briefly:

- The workload has not returned to a sustainable level since the reorg.
- I raised this twice and was told to wait for the next planning cycle.
- I am not willing to spend another year waiting.

Regards,
{c['full_name']}
""", as_of="2026-03-31")

# =====================================================================
# PDF
# =====================================================================

pdf("performance_review", "performance-review-single-page-formal.pdf",
    "Straightforward one-page PDF",
    "Should extract 4.5",
    ["MERIDIAN ANALYTICS - PERFORMANCE REVIEW",
     "",
     f"Employee: {d['full_name']}",
     f"Email:    {d['email']}",
     "Period:   1 January 2025 - 31 December 2025",
     "",
     "OVERALL RATING: 4.5 / 5",
     "",
     "Consistently exceeded expectations across the year, with particular",
     "strength in incident response and mentoring."],
    as_of="2025-12-31")

pdf("resignation_letter", "resignation-letter-two-page-pdf.pdf",
    "Content split across two PDF pages",
    "Both pages must be concatenated before extraction",
    [f"{E[4]['full_name']}",
     f"{E[4]['email']}",
     "",
     "Dear Alison,",
     "",
     "I am writing to give notice of my resignation. My final working day",
     "will be 30 April 2026.",
     "",
     "The reasons are set out overleaf.",
     "%%PAGEBREAK%%",
     "Page 2 - reasons",
     "",
     "The commute change added three hours to my day. I understand the",
     "reasoning behind the policy; it simply does not work for my household.",
     "",
     "I will hand over cleanly.",
     "",
     f"{E[4]['full_name']}"],
    as_of="2026-04-30")

pdf("cv", "cv-two-column-layout-interleaves-on-extract.pdf",
    "Two visual columns — PDF text order follows the content stream, not the eye",
    "Text likely interleaves; extraction may still recover email + name",
    ([f"{E[5]['full_name'].upper()}",
      "aicha.benali@example.com",
      "Tunis, Tunisia",
      "",
      "PROFILE",
      "Data engineer with nine years",
      "building ingestion pipelines",
      "for financial services.",
      "",
      "SKILLS",
      "Python, Spark, dbt, Airflow"],
     ["EXPERIENCE",
      "",
      "Senior Data Engineer",
      "Carthage Analytics, 2020-present",
      "- Rebuilt the nightly ETL",
      "- Cut runtime 6h to 40min",
      "",
      "Data Engineer",
      "Sahel Systems, 2017-2020",
      "",
      "EDUCATION",
      "Ing. INSAT, 2017"]),
    columns=True, as_of="2026-04-01")

pdf("offer_letter", "offer-letter-pdf-with-letterhead-and-footer.pdf",
    "Letterhead and footer noise around the substantive terms",
    "Should extract department + base salary, ignoring footer",
    ["MERIDIAN ANALYTICS",
     "120 Fenchurch Street, London EC3M 5BA",
     "Registered in England and Wales No. 00000000",
     "",
     "18 August 2026",
     "",
     "Ms Ines Trabelsi",
     "ines.trabelsi@meridiananalytics.example",
     "",
     "OFFER OF EMPLOYMENT",
     "",
     "Position:    Data Scientist",
     "Level:       IC3",
     "Department:  Product",
     "Start date:  1 October 2026",
     "Base salary: GBP 96,000 per annum",
     "Bonus:       up to 10%",
     "",
     "This letter is confidential. Meridian Analytics is an equal",
     "opportunities employer. Registered office as above.",
     "VAT GB000000000. Page 1 of 1."],
    as_of="2026-10-01")

# =====================================================================
# Language and locale
# =====================================================================

txt("resignation_letter", "resignation-letter-written-in-french.txt",
    "Entirely French prose — the working language of many Sopra HR clients",
    "Should extract; note_text will be French",
    f"""{E[6]['full_name']}
{E[6]['email']}

Le 18 août 2026

Madame, Monsieur,

Par la présente, je vous informe de ma décision de démissionner de mon
poste. Mon dernier jour de travail sera le 30 septembre 2026, conformément
au préavis prévu par mon contrat.

Cette décision n'a pas été facile. La charge de travail est devenue
intenable depuis dix-huit mois et mes alertes répétées sont restées sans
réponse. Je pars sans amertume, mais avec le sentiment de ne pas avoir été
entendu.

Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations
distinguées.

{E[6]['full_name']}
""", as_of="2026-09-30")

txt("performance_review", "performance-review-written-in-french.txt",
    "French review with the rating expressed as 'Note globale : 4/5'",
    "Should extract 4.0",
    f"""ENTRETIEN ANNUEL D'ÉVALUATION

Collaborateur : {E[7]['full_name']}
Courriel      : {E[7]['email']}
Période       : du 1er janvier 2025 au 31 décembre 2025
Évaluateur    : Sophie Lindgren

Note globale : 4/5

Points forts
  - Excellente maîtrise technique, reconnue par ses pairs.
  - A repris la gestion des incidents sans qu'on le lui demande.

Axes de progrès
  - La communication écrite reste en retrait par rapport à la qualité
    de la réflexion.
""", as_of="2025-12-31")

txt("resignation_letter", "resignation-letter-mixed-french-and-english.txt",
    "Code-switching between French and English mid-document",
    "Should still extract email + date",
    f"""From: {E[8]['full_name']} <{E[8]['email']}>
Subject: Démission / Resignation

Bonjour Marco,

Je t'écris pour t'annoncer ma démission. Last working day will be
15 May 2026.

Honestly the reason is simple: j'ai reçu une offre que je ne pouvais pas
refuser, and the growth path here was never clarified despite three
conversations about it.

Merci pour tout,
{E[8]['full_name']}
""", as_of="2026-05-15")

# =====================================================================
# Rating scales
# =====================================================================

txt("performance_review", "performance-review-letter-grade-scale-a-to-f.txt",
    "Rating given as a letter grade with no numeric scale stated",
    "Ambiguous: A on an A-F scale should map to 5.0",
    f"""ANNUAL REVIEW

Employee: {E[9]['full_name']} ({E[9]['email']})
Period ending: 31 December 2025

Overall grade: A

Grading scale: A (outstanding) through F (unsatisfactory).

An exceptional year by any measure.
""", as_of="2025-12-31")

txt("performance_review", "performance-review-percentage-score-82.txt",
    "Score as a percentage rather than a scale point",
    "82% should map to roughly 4.1 on 1-5",
    f"""PERFORMANCE SUMMARY 2025

{E[10]['full_name']} <{E[10]['email']}>
Review period ends 31 December 2025

Composite score: 82%

Weighted across delivery (40%), quality (30%) and collaboration (30%).
""", as_of="2025-12-31")

txt("performance_review", "performance-review-star-rating-four-of-five.txt",
    "Rating drawn as star glyphs",
    "Should read 4.0 from the glyphs",
    f"""Review — {E[11]['full_name']}
{E[11]['email']}
Period end: 2025-12-31

Overall:  ★★★★☆   (4 of 5)

Reliable, low-drama, and the person everyone asks when the build breaks.
""", as_of="2025-12-31")

txt("performance_review", "performance-review-inverted-scale-1-is-best.txt",
    "German-style scale where 1 is BEST and 5 is worst",
    "TRAP: naive reading gives 1.0 when the true 1-5-higher-better value is 5.0",
    f"""LEISTUNGSBEURTEILUNG / PERFORMANCE APPRAISAL

Mitarbeiter / Employee: {E[12]['full_name']}
E-Mail: {E[12]['email']}
Zeitraum / Period: 01.01.2025 - 31.12.2025

Gesamtnote / Overall grade: 1

Notenskala / Grading scale:
  1 = sehr gut (excellent)
  2 = gut (good)
  3 = befriedigend (satisfactory)
  4 = ausreichend (sufficient)
  5 = mangelhaft (poor)

Hervorragende Leistung im gesamten Zeitraum.
""", as_of="2025-12-31")

# =====================================================================
# Dates
# =====================================================================

txt("resignation_letter", "resignation-letter-ambiguous-date-03-04-2026.txt",
    "Date written 03/04/2026 with no locale cue",
    "AMBIGUOUS: 3 April (EU) or 4 March (US) — no way to disambiguate",
    f"""{E[13]['full_name']}
{E[13]['email']}

I am resigning with effect from 03/04/2026.

The role has changed beyond what I signed up for and I would rather leave
on good terms than keep pretending otherwise.

{E[13]['full_name']}
""", as_of="2026-04-03")

txt("performance_review", "performance-review-fiscal-year-ends-in-june.txt",
    "Review period is a fiscal year (Jul-Jun), not a calendar year",
    "review_period_end must be 2025-06-30, not 2025-12-31",
    f"""PERFORMANCE REVIEW — FY2025

Employee: {E[14]['full_name']}
Email:    {E[14]['email']}
Fiscal year FY2025 runs 1 July 2024 to 30 June 2025.

Rating: 3.5 / 5

Solid contribution across the fiscal year.
""", as_of="2025-06-30")

# =====================================================================
# Structural edge cases
# =====================================================================

txt("performance_review", "performance-review-two-employees-in-one-file.txt",
    "Two complete reviews concatenated into one upload",
    "Schema holds one employee — the second must not be silently dropped",
    f"""REVIEW 1

Employee: {E[15]['full_name']} ({E[15]['email']})
Period end: 2025-12-31
Rating: 4 / 5
Strong year.

------------------------------------------------------------

REVIEW 2

Employee: {E[16]['full_name']} ({E[16]['email']})
Period end: 2025-12-31
Rating: 2 / 5
Struggled with delivery consistency.
""", as_of="2025-12-31")

txt("resignation_letter", "resignation-letter-empty-file.txt",
    "Zero-byte upload",
    "Must refuse cleanly, not crash",
    "")

txt("resignation_letter", "resignation-letter-whitespace-only.txt",
    "Whitespace only — looks non-empty by size",
    "Must refuse cleanly",
    "\n\n   \t\n   \n")

txt("resignation_letter", "resignation-letter-email-thread-with-quoted-replies.txt",
    "Forwarded thread where the resignation is buried under quoted replies",
    "Must attribute to the resigning employee, not the last sender",
    f"""From: Alison Pike <alison.pike@meridiananalytics.example>
Sent: 18 August 2026 09:14
To: People Operations
Subject: FW: Notice

Please process. — A

> From: Marco Duarte <marco.duarte@meridiananalytics.example>
> Sent: 18 August 2026 08:52
> Subject: FW: Notice
>
> Forwarding for the file.
>
> > From: {E[17]['full_name']} <{E[17]['email']}>
> > Sent: 17 August 2026 18:03
> > Subject: Notice
> >
> > Hi Marco,
> >
> > This is my formal notice. Last day 30 September 2026.
> >
> > I have accepted a role closer to home. Nothing dramatic —
> > the commute finally won.
> >
> > {E[17]['full_name']}
""", as_of="2026-09-30")

_noise = ("The quarterly business review covered pipeline health, regional "
          "performance, and the ongoing platform migration in considerable "
          "detail across every function represented. ")
txt("performance_review", "performance-review-very-long-15kb-buried-rating.txt",
    "~15 KB of filler with the rating in the final paragraph",
    "Tests context handling — rating must survive the length",
    f"""ANNUAL PERFORMANCE REVIEW

Employee: {E[18]['full_name']}
Email: {E[18]['email']}
Period ending 31 December 2025

BACKGROUND

{_noise * 120}

ASSESSMENT

After weighing the full year of evidence, the overall rating for this
period is 2.5 / 5.
""", as_of="2025-12-31")

txt("performance_review", "performance-review-ocr-garbled-characters.txt",
    "Simulated OCR damage: rn->m, l->1, O->0 confusions",
    "Should still recover email and rating, or refuse honestly",
    f"""PERF0RMANCE REVIEVV

Emp1oyee: {E[19]['full_name']}
Emai1: {E[19]['email']}
Peri0d ending: 31 Decernber 2025

0vera11 rating: 3 / 5

Meets expectati0ns. S0me inc0nsistency in de1ivery timing but a re1iab1e
c0ntribut0r 0vera11.
""", as_of="2025-12-31")

txt("offer_letter", "offer-letter-salary-in-tunisian-dinar.txt",
    "Compensation in TND with a local formatting convention",
    "base_salary should be the number; currency is not modelled",
    """MERIDIAN ANALYTICS TUNISIE

Candidate:   Youssef Gharbi
Email:       youssef.gharbi@meridiananalytics.example
Position:    Backend Engineer
Level:       IC2
Department:  Engineering
Start date:  1 October 2026
Salaire brut annuel: 78 000,000 TND

Signed, People Operations
""", as_of="2026-10-01")

add("roster", "roster-excel-workbook-unsupported-type.xlsx",
    "A real .xlsx binary signature — an unsupported file type",
    "Must refuse with the supported-types message, not crash",
    b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00" + b"\x00" * 64)

# =====================================================================

(OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
print(f"{len(manifest)} documents -> {OUT}")
for k, v in sorted(collections.Counter(m["kind"] for m in manifest).items()):
    print(f"  {k:<20} {v}")
