"""Render a ``DiagnoseResponse`` into a shareable PDF via fpdf2.

Pure-Python PDF generation — no system-level dependencies (unlike
``weasyprint``, which needs Cairo/Pango). Kept deliberately simple: one
pass over the already-built report, no HTML/CSS templating layer, since
the content is a short, fixed structure (title, then one block per
detected problem).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fpdf import FPDF

from companysim.api.schemas import DiagnoseResponse, DiagnosisReportOut

_MARGIN = 15
_LATIN1_FALLBACKS = {
    "’": "'", "‘": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...",
}


def _safe_text(text: str) -> str:
    """fpdf2's built-in fonts are Latin-1 only; swap common smart-quote/dash
    unicode punctuation for plain ASCII rather than crashing on encode.
    """
    for src, dst in _LATIN1_FALLBACKS.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


class _DiagnosisPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _add_problem_block(pdf: _DiagnosisPDF, index: int, report: DiagnosisReportOut) -> None:
    problem = report.problem
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(
        0, 8, _safe_text(f"{index}. {problem.metric} (week {problem.tick})"),
        new_x="LMARGIN", new_y="NEXT",
    )

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(
        0, 6, _safe_text(f"{problem.description} Severity: {problem.severity:.2f}."),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(2)

    if report.drivers:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(0, 6, "Top drivers:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for d in report.drivers:
            direction = "above" if d.deviation > 0 else "below"
            line = (
                f"  - {d.segment_type} {d.segment_id}: {d.feature} "
                f"{abs(d.deviation):.2f} {direction} org average (score {d.score:.3f})"
            )
            pdf.multi_cell(0, 5.5, _safe_text(line), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Recommendation:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    rec = report.recommendation
    target = ""
    if rec.target_department is not None:
        target = f" (department {rec.target_department})"
    elif rec.target_team is not None:
        target = f" (team {rec.target_team})"
    pdf.multi_cell(
        0, 5.5, _safe_text(f"  {rec.event_type.replace('_', ' ').title()}{target} — {rec.rationale}"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(1)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Explanation:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5.5, _safe_text(report.explanation), new_x="LMARGIN", new_y="NEXT")

    if report.notes_summary and report.notes_summary.sample_quotes:
        pdf.ln(1)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(90, 90, 90)
        for quote in report.notes_summary.sample_quotes:
            pdf.set_x(pdf.l_margin + 5)
            pdf.multi_cell(0, 5, _safe_text(f'"{quote}"'), new_x="LMARGIN", new_y="NEXT")
        if report.notes_summary.n_llm_generated > 0:
            pdf.set_x(pdf.l_margin + 5)
            pdf.multi_cell(
                0, 5,
                _safe_text(
                    f"{report.notes_summary.n_llm_generated} of {report.notes_summary.n_notes} "
                    "note(s) above were AI-generated, grounded in this employee's own "
                    "risk-driver values."
                ),
                new_x="LMARGIN", new_y="NEXT",
            )

    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)
    pdf.set_draw_color(210, 210, 210)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)


def render_diagnosis_pdf(org_name: str, report: DiagnoseResponse) -> bytes:
    pdf = _DiagnosisPDF(format="A4")
    pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    pdf.set_auto_page_break(auto=True, margin=_MARGIN)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _safe_text("Diagnosis Report"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(90, 90, 90)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pdf.cell(0, 7, _safe_text(f"{org_name} — generated {generated_at}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    if not report.reports:
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, "No problems were detected during this run.", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, f"{report.problems_detected} problem(s) detected.", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        for i, r in enumerate(report.reports, start=1):
            _add_problem_block(pdf, i, r)

    output = pdf.output()
    return bytes(output)
