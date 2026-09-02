"""Build the 24-minute talk deck from the published outline.

Dark, because every screenshot in it is dark: a light deck wrapped around
dark product shots reads as two decks stapled together.

Slides that need a live demo or a photograph I cannot take headlessly are
emitted as clearly-marked placeholders rather than quietly skipped.
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "slide-screenshots"
OUT = ROOT / "docs" / "reading-the-paperwork.pptx"

# Regenerate the screenshots with the app running (see docs/talk-deck.md):
#   chrome --headless=new --force-device-scale-factor=2 --window-size=1560,980 #          --virtual-time-budget=14000 --screenshot=out.png <url>

# Product dark palette — the same values the app ships.
BG      = RGBColor(0x0B, 0x0F, 0x0E)
SURFACE = RGBColor(0x16, 0x1C, 0x1B)
TEXT    = RGBColor(0xF2, 0xF5, 0xF4)
MUTED   = RGBColor(0x98, 0xA3, 0xA1)
DIM     = RGBColor(0x6D, 0x78, 0x77)
ACCENT  = RGBColor(0xA7, 0x9B, 0xFF)
AMBER   = RGBColor(0xDE, 0x75, 0x29)
RULE    = RGBColor(0x2A, 0x33, 0x32)

W, H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.9)
CONTENT_W = W - 2 * MARGIN

prs = Presentation()
prs.slide_width, prs.slide_height = W, H
BLANK = prs.slide_layouts[6]


def new_slide(notes: str = "") -> "object":
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = BG
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def text(slide, left, top, width, height, runs, *, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    """runs: list of (string, size_pt, bold, colour, space_after_pt)."""
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, (s, size, bold, colour, after) in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = s
        p.alignment = align
        p.space_after = Pt(after)
        f = p.font
        f.size, f.bold, f.color.rgb = Pt(size), bold, colour
        f.name = "Segoe UI"
    return tb


def eyebrow_title(slide, eyebrow, title, sub=None):
    text(slide, MARGIN, Inches(0.62), CONTENT_W, Inches(0.3),
         [(eyebrow.upper(), 12, True, ACCENT, 0)])
    text(slide, MARGIN, Inches(1.0), CONTENT_W, Inches(1.1),
         [(title, 34, True, TEXT, 0)])
    if sub:
        text(slide, MARGIN, Inches(1.95), CONTENT_W, Inches(0.5),
             [(sub, 16, False, MUTED, 0)])


def rule(slide, top, width=None):
    ln = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, MARGIN, top, width or CONTENT_W, Emu(9525))
    ln.fill.solid(); ln.fill.fore_color.rgb = RULE
    ln.line.fill.background(); ln.shadow.inherit = False


def timing(slide, clock, dur, idx):
    text(slide, W - Inches(2.3), Inches(0.62), Inches(1.5), Inches(0.6),
         [(f"{clock}  ·  {dur}", 11, True, DIM, 0),
          (f"slide {idx}", 10, False, DIM, 0)], align=PP_ALIGN.RIGHT)


def bullets(slide, items, top=Inches(2.7), size=19, gap=14):
    runs = []
    for it in items:
        runs.append((f"—   {it}", size, False, TEXT, gap))
    text(slide, MARGIN, top, CONTENT_W * 0.92, Inches(4.2), runs)


def shot(slide, name, caption=None, top=Inches(2.4), height=Inches(4.35)):
    """Sized by HEIGHT, not width: the slide is 7.5in tall and the app
    screenshots are 1.59:1, so fitting to width pushes the bottom of the
    image off the slide — which PowerPoint will happily render."""
    path = SHOTS / f"{name}.png"
    if not path.exists():
        placeholder(slide, f"Screenshot missing: {name}.png", top=top)
        return
    from PIL import Image
    with Image.open(path) as im:
        ratio = im.width / im.height
    width = Emu(int(height * ratio))
    left = int((W - width) / 2)
    frame = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                   left - Inches(0.06), top - Inches(0.06),
                                   width + Inches(0.12), height + Inches(0.12))
    frame.fill.solid(); frame.fill.fore_color.rgb = SURFACE
    frame.line.color.rgb = RULE; frame.line.width = Pt(1)
    frame.shadow.inherit = False
    slide.shapes.add_picture(str(path), left, top, height=height)
    if caption:
        text(slide, MARGIN, top + height + Inches(0.22), CONTENT_W, Inches(0.45),
             [(caption, 13, False, DIM, 0)], align=PP_ALIGN.CENTER)


DEMOS = ROOT / "docs" / "demos"


def video(slide, name, left, top, width):
    """Embed a clip, with its poster frame ALSO laid in as a real picture
    underneath.

    Canva's .pptx import does not carry embedded media across. Relying on
    the poster that `add_movie` stores inside the media shape would mean
    relying on that shape surviving, which is the thing that does not.
    Adding the frame as an ordinary picture first costs a few MB and
    guarantees the slide still shows the right thing in the right place —
    so the deck degrades to a screenshot deck rather than to blank boxes,
    and the clip can be dropped back on top by hand.
    """
    clip = DEMOS / f"{name}.mp4"
    poster = DEMOS / "posters" / f"{name}.png"
    if not clip.exists():
        placeholder(slide, f"Missing clip: {name}.mp4", top=top)
        return
    height = Emu(int(width / 1.6))  # the recordings are 1440x900

    frame = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                   left - Inches(0.06), top - Inches(0.06),
                                   width + Inches(0.12), height + Inches(0.12))
    frame.fill.solid()
    frame.fill.fore_color.rgb = SURFACE
    frame.line.color.rgb = ACCENT
    frame.line.width = Pt(1.25)
    frame.shadow.inherit = False

    if poster.exists():
        slide.shapes.add_picture(str(poster), left, top, width, height)

    slide.shapes.add_movie(
        str(clip), left, top, width, height,
        poster_frame_image=str(poster) if poster.exists() else None,
        mime_type="video/mp4")


def demo_slide(name, eyebrow, title, points, clock=None, dur=None, idx=None, notes=""):
    """Title and what-to-watch-for on the left, the clip on the right."""
    s = new_slide(notes)
    eyebrow_title(s, eyebrow, title)
    if clock:
        timing(s, clock, dur, idx)
    runs = []
    for pt in points:
        runs.append((f"—   {pt}", 15, False, TEXT, 12))
    text(s, MARGIN, Inches(2.5), Inches(4.0), Inches(4.2), runs)
    video(s, name, Inches(5.25), Inches(2.45), Inches(7.15))
    return s


def placeholder(slide, instruction, detail=None, top=Inches(2.5), height=Inches(3.6)):
    """A slot the presenter fills. Deliberately loud — a placeholder that
    looks finished is one that ships to a jury unfilled."""
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                 MARGIN, top, CONTENT_W, height)
    box.fill.solid(); box.fill.fore_color.rgb = SURFACE
    box.line.color.rgb = AMBER; box.line.width = Pt(1.75)
    box.line.dash_style = 4  # dashed
    box.shadow.inherit = False
    runs = [("YOUR CONTENT HERE", 13, True, AMBER, 10), (instruction, 21, True, TEXT, 10)]
    if detail:
        runs.append((detail, 15, False, MUTED, 0))
    text(slide, MARGIN + Inches(0.6), top + Inches(0.55),
         CONTENT_W - Inches(1.2), height - Inches(1.0), runs)


def statement(slide, big, under, foot=None):
    text(slide, MARGIN, Inches(2.5), CONTENT_W, Inches(2.0),
         [(big, 88, True, ACCENT, 6)])
    text(slide, MARGIN, Inches(4.35), CONTENT_W * 0.85, Inches(1.2),
         [(under, 24, False, TEXT, 0)])
    if foot:
        text(slide, MARGIN, Inches(6.4), CONTENT_W, Inches(0.5),
             [(foot, 14, False, DIM, 0)])


# ══════════════════════════════════════════════════════════════════════
# 01 — Title
# ══════════════════════════════════════════════════════════════════════
s = new_slide("Name, team, one sentence on what the next 24 minutes are for. "
              "Do not narrate the agenda.")
bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, MARGIN, Inches(2.15), Inches(1.5), Pt(5))
bar.fill.solid(); bar.fill.fore_color.rgb = ACCENT
bar.line.fill.background(); bar.shadow.inherit = False
text(s, MARGIN, Inches(1.55), CONTENT_W, Inches(0.4),
     [("END-OF-STUDIES INTERNSHIP  ·  SOPRA HR SOFTWARE × ESPRIT", 13, True, ACCENT, 0)])
text(s, MARGIN, Inches(2.55), CONTENT_W, Inches(1.6),
     [("Reading the Paperwork", 60, True, TEXT, 0)])
text(s, MARGIN, Inches(4.0), Inches(8.6), Inches(1.4),
     [("Turning unstructured HR documents — including photographs of paper — "
       "into machine-learning features.", 20, False, MUTED, 0)])
text(s, MARGIN, Inches(6.2), CONTENT_W, Inches(0.9),
     [("[Your name]", 17, True, TEXT, 4),
      ("Supervisors: [company] · [academic]      [date]", 14, False, DIM, 0)])

# ══════════════════════════════════════════════════════════════════════
# 02 — The cost
# ══════════════════════════════════════════════════════════════════════
s = new_slide("One employee resigning costs recruitment, onboarding, lost productivity, and "
              "knowledge nobody wrote down. Turnover is expensive, consequential and partly "
              "predictable — which is why every HR platform wants a model for it.\n\n"
              "FIND A REAL, CITABLE FIGURE. An invented one is the first thing a jury challenges.")
eyebrow_title(s, "Act I · The problem worth money", "Start with the cost, not the technology")
timing(s, "0:20", "1:00", "02")
statement(s, "[ X ]× monthly salary",
          "The cost of replacing one departing employee.",
          "Replace with a sourced figure — SHRM, Gallup, or internal Sopra HR material.")

# ══════════════════════════════════════════════════════════════════════
# 03 — The unread archive
# ══════════════════════════════════════════════════════════════════════
s = new_slide("The obstacle is not modelling. Published turnover work runs on a handful of public "
              "datasets — the most-used has ~1,470 rows and is itself synthetic — while real "
              "organisations hold enormous archives that are prose, PDF and paper.\n\n"
              "Say the last line slowly. It is the thesis of the whole talk.")
eyebrow_title(s, "Act I", "The data exists. It just isn't readable.")
timing(s, "1:20", "1:20", "03")
bullets(s, ["Thousands of performance reviews",
            "Every resignation letter ever received",
            "Every offer letter, every CV",
            "A great deal of it never digitised at all"], top=Inches(2.6))
text(s, MARGIN, Inches(5.6), CONTENT_W * 0.8, Inches(1.0),
     [("“The data is not missing. It is unreadable.”", 26, True, ACCENT, 0)])

# ══════════════════════════════════════════════════════════════════════
# 04 — What existed
# ══════════════════════════════════════════════════════════════════════
s = new_slide("The platform simulates an organisation week by week, so employees actually resign "
              "inside the model. The classifier trains on real events rather than a risk score "
              "somebody assigned — the difference between learning something and restating an "
              "assumption.\n\nIt worked. Everything in it came from its own simulation.\n\n"
              "80 seconds. Resist explaining the simulation; it is context, not the contribution.")
eyebrow_title(s, "Act I", "What already existed: the Digital Workforce Twin")
timing(s, "2:40", "1:20", "04")
shot(s, "atrisk", "The platform before this internship — risk scoring, interventions, an MLOps gate.")

# ══════════════════════════════════════════════════════════════════════
# 05 — The gap
# ══════════════════════════════════════════════════════════════════════
s = new_slide("With no review history, the scoring layer supplied a neutral 3 out of 5 for "
              "everybody. Three of eighteen features were the same number for every employee — a "
              "tree never splits on them, so the effective feature count was fifteen.\n\n"
              "A declining rating is one of the more reliable early signals of resignation, so the "
              "missing signal was not arbitrary.\n\nTHIS IS THE PIVOT.")
eyebrow_title(s, "Act I", "The gap: three features were constants")
timing(s, "4:00", "1:20", "05")
box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, MARGIN, Inches(2.6), Inches(6.2), Inches(2.0))
box.fill.solid(); box.fill.fore_color.rgb = SURFACE
box.line.color.rgb = RULE; box.shadow.inherit = False
text(s, MARGIN + Inches(0.45), Inches(2.9), Inches(5.4), Inches(1.5),
     [("rating_last   =  3.0", 22, True, TEXT, 8),
      ("rating_prev   =  3.0", 22, True, TEXT, 8),
      ("rating_delta  =  0.0", 22, True, TEXT, 0)])
text(s, Inches(7.6), Inches(2.75), Inches(4.9), Inches(2.2),
     [("3 of 18", 46, True, AMBER, 6),
      ("numeric features carried no information at all", 17, False, TEXT, 0)])
text(s, MARGIN, Inches(5.15), CONTENT_W * 0.86, Inches(1.0),
     [("The application had no performance-review history to read — so it invented a "
       "neutral one for everybody.", 17, False, MUTED, 0)])

# ══════════════════════════════════════════════════════════════════════
# 06 — The pipeline
# ══════════════════════════════════════════════════════════════════════
s = new_slide("Documents arrive as CSV, PDF, free text or a photograph. Structured files parse "
              "deterministically — a roster needs no model and no API key. Prose goes to a "
              "language model. Both routes end in the same place: a staging table.\n\n"
              "There is no code path from extraction to a personnel record.\n\n"
              "You will point back at this slide three times.")
eyebrow_title(s, "Act II · What I built", "The pipeline, in one diagram")
timing(s, "5:20", "1:40", "06")

stages = [("Document\nCSV · PDF · text · PHOTO", SURFACE, TEXT, 2.10),
          ("Parse\nrules  or  LLM  or  OCR", SURFACE, TEXT, 2.10),
          ("STAGING\nnothing proceeds", ACCENT, BG, 2.45),
          ("HUMAN\napproves per field", SURFACE, TEXT, 2.10),
          ("Employees · reviews\nexit notes · cohort", SURFACE, TEXT, 2.15)]
x = MARGIN
for label, fill, fg, w_in in stages:
    w = Inches(w_in)
    b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, Inches(3.0), w, Inches(1.5))
    b.fill.solid(); b.fill.fore_color.rgb = fill
    b.line.color.rgb = ACCENT if fill == ACCENT else RULE
    b.line.width = Pt(1.5); b.shadow.inherit = False
    tf = b.text_frame; tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, line in enumerate(label.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line; p.alignment = PP_ALIGN.CENTER
        p.font.size = Pt(14 if i == 0 else 11)
        p.font.bold = i == 0
        p.font.color.rgb = fg
        p.font.name = "Segoe UI"
    x += w + Inches(0.12)
text(s, MARGIN, Inches(5.0), CONTENT_W, Inches(0.9),
     [("Both parsers write only to staging. The apply endpoint is the sole writer of employee "
       "data — so “no unreviewed write” is a property of the architecture, not a rule someone "
       "follows.", 16, False, MUTED, 0)])

# ══════════════════════════════════════════════════════════════════════
# 07 — Demo (a real recording of the running app)
# ══════════════════════════════════════════════════════════════════════
s = demo_slide(
    "03-photographed-paper-ocr", "Act II",
    "Demo — a photograph of paper, start to finish",
    ["Upload a photographed review — the row appears, marked OCR",
     "Transcribed once on upload, however often it is re-extracted",
     "Then the identical route a typed file takes: extract, stage, review",
     "Facts from a photo are staged at 0.7x confidence, automatically"],
    clock="7:00", dur="2:30", idx="07",
    notes="Narrate what is happening, not what you are clicking. The moment worth "
          "pausing on is that nothing downstream is special-cased for paper — only the "
          "confidence differs, and it differs at the one point every extraction path "
          "funnels through.\n\n"
          "This is a recording, not a live run: a call to a cloud model on conference "
          "wifi is a two-minute silence waiting to happen.\n\n"
          "Three more clips sit in the appendix if the room wants the roster, the "
          "letter or the refusal.")

# ══════════════════════════════════════════════════════════════════════
# 08 — Principle 1
# ══════════════════════════════════════════════════════════════════════
s = new_slide("A property of the architecture, not a rule someone follows. Both parsers write only "
              "to staging; the apply endpoint is the only writer of employee data and acts only on "
              "facts approved by identifier.\n\n"
              "For a vendor holding client personnel data under GDPR that is not a nice-to-have. "
              "Say the GDPR line looking at the business half of the room.")
eyebrow_title(s, "Act III · Why it can be trusted",
              "Principle 1 — nothing is written without a human")
timing(s, "9:30", "1:20", "08")
shot(s, "documents",
     "Every staged change carries its current value, its proposed value, a confidence and the "
     "source text it came from.")

# ══════════════════════════════════════════════════════════════════════
# 09 — Principle 2
# ══════════════════════════════════════════════════════════════════════
s = new_slide("A resignation letter says the author was exhausted and unsupported. Workload and "
              "manager support are legitimate features — so why not use them?\n\n"
              "Because the letter is written AT the moment of the outcome. A model trained on it "
              "learns that people who write about exhaustion in resignation letters resign. "
              "Excellent AUC, zero predictive value — at scoring time no such letter exists.\n\n"
              "So the schema has nowhere to put those values. TWO FULL MINUTES. If a jury "
              "remembers one thing, this is it.")
eyebrow_title(s, "Act III", "Principle 2 — make the wrong thing unrepresentable")
timing(s, "10:50", "2:00", "09")
box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, MARGIN, Inches(2.55), Inches(6.4), Inches(3.0))
box.fill.solid(); box.fill.fore_color.rgb = SURFACE
box.line.color.rgb = RULE; box.shadow.inherit = False
text(s, MARGIN + Inches(0.4), Inches(2.8), Inches(5.6), Inches(2.6),
     [("class ResignationLetterExtract:", 16, True, ACCENT, 10),
      ("    employee_email", 16, False, TEXT, 6),
      ("    effective_date", 16, False, TEXT, 6),
      ("    is_voluntary", 16, False, TEXT, 6),
      ("    note_text", 16, False, TEXT, 14),
      ("No workload field. No morale field.", 15, True, AMBER, 4),
      ("No feature fields at all.", 15, True, AMBER, 0)])
text(s, Inches(7.8), Inches(2.7), Inches(4.7), Inches(3.2),
     [("The letter is written at the moment of the outcome it describes.", 19, True, TEXT, 14),
      ("Anything it says about workload or morale is post-outcome information. "
       "Using it would be textbook temporal leakage — an excellent AUC that predicts nothing, "
       "because at scoring time the letter does not exist yet.", 16, False, MUTED, 14),
      ("A confused model cannot leak through this path. The field is not there.",
       16, True, ACCENT, 0)])

# ══════════════════════════════════════════════════════════════════════
# 10 — Principle 3
# ══════════════════════════════════════════════════════════════════════
s = new_slide("An organisation never receives a resignation letter from someone who stayed. A "
              "training set built from letters alone is 100% positive — the model learns that "
              "everybody leaves.\n\nSo cohort construction refuses to build a training set unless "
              "a roster establishes who did NOT leave, and refuses outright above a 50% base "
              "rate.\n\nThe most accessible idea in the talk. If you must cut slide 09, this "
              "survives.")
eyebrow_title(s, "Act III", "Principle 3 — you only get letters from people who left")
timing(s, "12:50", "1:20", "10")
for i, (title, sub, val, colour, lx) in enumerate([
        ("Letters only", "24 positives · 0 negatives", "100%", AMBER, 0.9),
        ("Letters + roster", "24 positives · 377 negatives", "5.99%", ACCENT, 7.1)]):
    b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(lx), Inches(2.7),
                           Inches(5.35), Inches(2.6))
    b.fill.solid(); b.fill.fore_color.rgb = SURFACE
    b.line.color.rgb = colour; b.line.width = Pt(1.5); b.shadow.inherit = False
    text(s, Inches(lx + 0.45), Inches(2.95), Inches(4.5), Inches(2.2),
         [(title, 17, True, TEXT, 4), (sub, 14, False, MUTED, 14),
          (val, 52, True, colour, 4),
          ("base rate", 13, False, DIM, 0)])
text(s, MARGIN, Inches(5.7), CONTENT_W * 0.9, Inches(0.9),
     [("The roster is not an optional enrichment of the cohort. It is what makes the labels "
       "mean anything at all.", 17, False, MUTED, 0)])

# ══════════════════════════════════════════════════════════════════════
# 11 — The model made something up
# ══════════════════════════════════════════════════════════════════════
s = new_slide("My favourite failure. I told the model to report a missing field. It complied "
              "semantically and failed structurally — it put the refusal INSIDE the field. Schema "
              "validation passed, because that is a perfectly valid string.\n\n"
              "The fix was not a better prompt. The department is now resolved against departments "
              "that actually exist. Prompt wording constrains one phrasing of a failure; a "
              "structural check constrains the whole class.\n\nTell it as an anecdote — the one "
              "place in the talk to sound amused.")
eyebrow_title(s, "Act III", "When the model made something up")
timing(s, "14:10", "1:20", "11")
text(s, MARGIN, Inches(2.6), CONTENT_W * 0.9, Inches(0.6),
     [("The prompt said: if the department is missing, return an error.", 18, False, MUTED, 0)])
box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, MARGIN, Inches(3.3), Inches(10.2), Inches(1.25))
box.fill.solid(); box.fill.fore_color.rgb = SURFACE
box.line.color.rgb = AMBER; box.line.width = Pt(1.5); box.shadow.inherit = False
text(s, MARGIN + Inches(0.45), Inches(3.55), Inches(9.4), Inches(0.9),
     [('department_name:  "no department stated"', 24, True, AMBER, 0)])
text(s, MARGIN, Inches(4.95), CONTENT_W * 0.9, Inches(1.4),
     [("A valid string. It passed schema validation and staged a plausible-looking hire.",
       19, True, TEXT, 12),
      ("Prompt wording constrains one phrasing of a failure. A structural check constrains "
       "the whole class of it.", 17, False, ACCENT, 0)])

# ══════════════════════════════════════════════════════════════════════
# 12 — Paper and portability
# ══════════════════════════════════════════════════════════════════════
s = new_slide("Plenty of HR records are still paper, so a photograph produces the same text a "
              "typed document would and travels the identical route. Paper is a front door, not a "
              "second pipeline.\n\nWhat differs is confidence, and it differs automatically. OCR "
              "can turn a three into an eight in a salary and nothing downstream would catch it — "
              "both are valid numbers. So the discount is applied at the one point every "
              "extraction path funnels through.\n\nAnd the model provider is a configuration "
              "setting: a client who requires everything inside their own AWS account gets that "
              "without a code change.")
eyebrow_title(s, "Act III", "Paper, and not being locked in")
timing(s, "15:30", "1:20", "12")
for lx, head, body, colour in [
        (0.9, "Paper",
         "Photo of a letter  →  transcription  →  the same pipeline.\n\n"
         "Facts staged at 0.7× confidence, marked text_source = ocr.\n\n"
         "A scanned PDF with no text layer takes the same route.", ACCENT),
        (7.1, "Portability",
         "Groq  ⇄  AWS Bedrock — one environment variable.\n\n"
         "Credentials resolve through boto3's chain, so an IAM role works in production "
         "with no key material on disk.\n\nRuns inside the client's own AWS account.", ACCENT)]:
    b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(lx), Inches(2.6),
                           Inches(5.35), Inches(3.2))
    b.fill.solid(); b.fill.fore_color.rgb = SURFACE
    b.line.color.rgb = RULE; b.shadow.inherit = False
    text(s, Inches(lx + 0.45), Inches(2.9), Inches(4.5), Inches(2.8),
         [(head, 20, True, colour, 12), (body, 15, False, TEXT, 0)])
text(s, MARGIN, Inches(6.1), CONTENT_W * 0.9, Inches(0.7),
     [("Two commercial objections, answered before they are asked: “our clients aren’t "
       "digitised” and “we can’t send data to a third party”.", 15, False, DIM, 0)])

# ══════════════════════════════════════════════════════════════════════
# 13 — Results
# ══════════════════════════════════════════════════════════════════════
s = new_slide("I generated documents across six types, and about one in six was built to be "
              "REFUSED — a review with no rating, a redundancy notice, a letter from someone who "
              "does not work here.\n\nA corpus of happy paths proves nothing about whether a "
              "parser invents data when a document is deficient. All seventeen refusals behaved "
              "correctly, with specific reasons rather than a generic failure.\n\n"
              "Say “designed to fail” out loud.")
eyebrow_title(s, "Act IV · What it produced", "Tested against documents built to fail")
timing(s, "16:50", "1:30", "13")
for i, (val, lab) in enumerate([("17/17", "designed refusals\nbehaved correctly"),
                                ("143", "documents across\ntwo corpora"),
                                ("343", "automated tests"),
                                ("541s", "for the full\n106-document run")]):
    lx = Inches(0.9 + i * 3.05)
    b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, lx, Inches(2.8), Inches(2.85), Inches(2.1))
    b.fill.solid(); b.fill.fore_color.rgb = SURFACE
    b.line.color.rgb = RULE; b.shadow.inherit = False
    text(s, lx + Inches(0.3), Inches(3.05), Inches(2.3), Inches(1.7),
         [(val, 40, True, ACCENT, 8), (lab, 14, False, MUTED, 0)])
text(s, MARGIN, Inches(5.4), CONTENT_W * 0.9, Inches(1.2),
     [("Three involuntary terminations were refused as quit labels: “an employer-initiated exit, "
       "not a voluntary resignation.”", 18, False, TEXT, 10),
      ("A redundancy notice is not a resignation — treating it as a positive label would teach "
       "the model that reorganisations are voluntary departures.", 16, False, MUTED, 0)])

# ══════════════════════════════════════════════════════════════════════
# 14 — The second corpus
# ══════════════════════════════════════════════════════════════════════
s = new_slide("The 106 documents all tested CONTENT. So I built a second corpus that tests the "
              "CONTAINER — delimiters, encodings, locales, scales, page layout.\n\n"
              "It found this before a single file was uploaded. The parser strips every comma as a "
              "thousands separator, so a French salary is read a hundred times too large — worse "
              "than a refusal, because the wrong number reaches a reviewer looking completely "
              "plausible.\n\nEvery one of my first 106 documents was UTF-8, comma-delimited and in "
              "English, because that is what you write when inventing plausible documents.\n\n"
              "Say plainly that it is still open.")
eyebrow_title(s, "Act IV", "Then a second corpus found the bug the first could not")
timing(s, "18:20", "1:20", "14")
box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, MARGIN, Inches(2.6), Inches(10.2), Inches(1.9))
box.fill.solid(); box.fill.fore_color.rgb = SURFACE
box.line.color.rgb = AMBER; box.line.width = Pt(1.5); box.shadow.inherit = False
text(s, MARGIN + Inches(0.5), Inches(2.85), Inches(9.2), Inches(1.5),
     [("1234,56        →        123456.0", 26, True, TEXT, 10),
      ("85.000,50      →        85.0005", 26, True, TEXT, 0)])
text(s, MARGIN, Inches(4.75), CONTENT_W * 0.92, Inches(1.6),
     [("A European decimal comma multiplies a salary by one hundred. Silently.",
       22, True, AMBER, 14),
      ("“A corpus that varies content cannot find a defect that lives in the container.”",
       18, False, ACCENT, 0)])

# ══════════════════════════════════════════════════════════════════════
# 15 — The gap closed
# ══════════════════════════════════════════════════════════════════════
s = new_slide("Twelve employees now have two-period histories with real deltas instead of a "
              "hard-coded zero. The promotion gate records document-sourced examples separately, "
              "so a change in AUC can be attributed to a source — while the fixed synthetic "
              "evaluation cohort never sees ingested data, so documents can improve the model or "
              "do nothing, but cannot quietly degrade production.\n\n"
              "CALL BACK TO SLIDE 05 EXPLICITLY: “those three constants”.")
eyebrow_title(s, "Act IV", "The gap from slide 5, closed")
timing(s, "19:40", "1:20", "15")
rows = [("Informative numeric features", "15 of 18", "18 of 18"),
        ("Performance reviews in the database", "0", "38"),
        ("Employees with a real rating history", "0", "26"),
        ("…of those, with two periods (a real delta)", "0", "12")]
top = 2.75
for label, before, after in rows:
    text(s, MARGIN, Inches(top), Inches(6.6), Inches(0.5), [(label, 17, False, TEXT, 0)])
    text(s, Inches(8.0), Inches(top), Inches(1.6), Inches(0.5),
         [(before, 17, False, DIM, 0)], align=PP_ALIGN.RIGHT)
    text(s, Inches(9.9), Inches(top), Inches(0.6), Inches(0.5),
         [("→", 17, False, DIM, 0)], align=PP_ALIGN.CENTER)
    text(s, Inches(10.6), Inches(top), Inches(1.8), Inches(0.5),
         [(after, 17, True, ACCENT, 0)], align=PP_ALIGN.RIGHT)
    rule(s, Inches(top + 0.52))
    top += 0.72
text(s, MARGIN, Inches(5.9), CONTENT_W * 0.9, Inches(0.8),
     [("The three constants from slide 5 are now measured values — for the employees a document "
       "covers.", 17, False, MUTED, 0)])

# ══════════════════════════════════════════════════════════════════════
# 16 — What doesn't work
# ══════════════════════════════════════════════════════════════════════
s = new_slide("Three things I would not claim. The sentiment analysis is a small hand-built "
              "lexicon and it fails on real prose — a letter saying the author was “tired in a way "
              "a holiday does not fix” scores zero. At 24 documents that is most of them.\n\n"
              "And I have not shown an improvement in predicting real turnover. That needs a real "
              "organisation's documents and a real outcome window.\n\n"
              "DO NOT SKIP THIS SLIDE. Naming your own limits before a jury does is the cheapest "
              "credibility you will buy all talk.")
eyebrow_title(s, "Act IV", "What doesn't work yet")
timing(s, "21:00", "1:00", "16")
bullets(s, ["83% of ingested exit notes yield no theme — the lexicon was tuned on simulated text",
            "A European decimal comma still corrupts salaries — it has a fixture, not a fix",
            "Duplicate email addresses can attach a review to the wrong person",
            "Validation used generated documents, not a real archive"], top=Inches(2.75), size=18)
text(s, MARGIN, Inches(5.9), CONTENT_W * 0.9, Inches(0.9),
     [("No improvement in predicting real turnover is claimed. That needs a real organisation’s "
       "documents and a prospective outcome window — neither was available.", 17, True, AMBER, 0)])

# ══════════════════════════════════════════════════════════════════════
# 17 — Commercial
# ══════════════════════════════════════════════════════════════════════
s = new_slide("The pitch in one line: this turns an archive a client is already paying to store "
              "into something their analytics can use, with an audit trail that survives a "
              "data-protection review.\n\nAnd because the cost per document is measured rather "
              "than estimated, a client can be quoted before a pilot rather than after it.\n\n"
              "Four claims, no more — each answers a question a buyer actually asks.")
eyebrow_title(s, "Act V · Where it goes", "Why this is worth money to a client")
timing(s, "22:00", "1:20", "17")
claims = [("Dormant asset", "Archives every client already owns become model inputs"),
          ("Auditable by construction", "Every value traces to a document and a sentence; nothing is auto-written"),
          ("Their infrastructure", "Runs inside the client's own AWS account"),
          ("Known unit cost", "~460 tokens and ~5 seconds per document")]
for i, (head, body) in enumerate(claims):
    lx = Inches(0.9 + (i % 2) * 6.2)
    ty = Inches(2.75 + (i // 2) * 1.75)
    b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, lx, ty, Inches(5.5), Inches(1.45))
    b.fill.solid(); b.fill.fore_color.rgb = SURFACE
    b.line.color.rgb = RULE; b.shadow.inherit = False
    text(s, lx + Inches(0.4), ty + Inches(0.22), Inches(4.7), Inches(1.1),
         [(head, 17, True, ACCENT, 6), (body, 14, False, MUTED, 0)])
text(s, MARGIN, Inches(6.4), CONTENT_W * 0.9, Inches(0.6),
     [("An archive they already pay to store, made usable — with a trail that survives a "
       "data-protection review.", 16, False, TEXT, 0)])

# ══════════════════════════════════════════════════════════════════════
# 18 — Close
# ══════════════════════════════════════════════════════════════════════
s = new_slide("The highest-return next step is the sentiment model, because 83% of what we ingest "
              "currently produces no signal.\n\nAnd if you take one idea away: every safety "
              "property in this pipeline is structural. A letter cannot leak a feature because the "
              "schema has no feature fields. A batch of letters cannot become a training set "
              "because the base rate is checked. Each could have been a rule in a document — and "
              "each would eventually have been forgotten.\n\n"
              "STOP TALKING AFTER THAT SENTENCE. Leave the line up; let the silence be the "
              "invitation.")
eyebrow_title(s, "Act V", "Next, and close")
timing(s, "23:20", "0:40", "18")
text(s, MARGIN, Inches(2.6), CONTENT_W * 0.9, Inches(1.0),
     [("Next  —  replace the exit-note lexicon  ·  fix the decimal comma  ·  "
       "resolve duplicate identities  ·  validate on a real, redacted archive",
       17, False, MUTED, 0)])
bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, MARGIN, Inches(3.9), Inches(2.2), Pt(4))
bar.fill.solid(); bar.fill.fore_color.rgb = ACCENT
bar.line.fill.background(); bar.shadow.inherit = False
text(s, MARGIN, Inches(4.35), CONTENT_W * 0.88, Inches(2.0),
     [("Make the wrong thing unrepresentable,", 40, True, TEXT, 4),
      ("rather than detectable.", 40, True, ACCENT, 0)])

# ══════════════════════════════════════════════════════════════════════
# Appendix — one clip per capability, not part of the 24-minute run
# ══════════════════════════════════════════════════════════════════════
CLIPS = [
    ("01-roster-csv-deterministic-parsing", "Roster CSV — deterministic parsing",
     ["No model involved; a roster needs no API key at all",
      "Each row compared against the current roster",
      "Only fields that actually differ are staged",
      "A byte-identical row proposes nothing"]),
    ("02-resignation-letter-llm-extraction", "Resignation letter — LLM extraction",
     ["Free prose, read by the language model",
      "Contributes the quit label and its date",
      "Never a feature — the schema has no field for one",
      "The note text flows on to exit-note analysis"]),
    ("04-honest-refusal-of-an-involuntary-exit", "Honest refusal — a redundancy notice",
     ["An employer-initiated exit is not a resignation",
      "Refused as a quit label, with the reason stored",
      "Nothing was written — that is the success case",
      "Accepting it would teach the model that reorgs are voluntary"]),
    ("05-review-queue-filter-and-evidence", "The review queue",
     ["142 documents, and the handful needing a decision",
      "A segmented filter rather than scrolling to find them",
      "List and inspector side by side",
      "Every proposal carries the sentence it came from"]),
    ("06-scenario-simulator-forecast", "Scenario simulator",
     ["A template drops events onto the timeline",
      "Position in time is real information, so it is drawn",
      "Baseline against the scenario",
      "Effect measured within the targeted cohort"]),
    ("07-diagnosis-report-modal", "Diagnosis report",
     ["Opens over the page, not below it",
      "Top drivers and the affected cohort",
      "A recommendation that can be applied to the scenario",
      "Dismissing costs nothing — the scenario keeps its state"]),
    ("08-retention-risk-ranking", "Retention risk",
     ["Who the model ranks highest",
      "Each score traces to its drivers",
      "Never a number on its own"]),
    ("09-turnover-model-and-promotion-gate", "Turnover model and promotion gate",
     ["Promoted only if AUC does not regress",
      "Every decision appended to an audit log",
      "Document-sourced examples counted separately"]),
    ("10-token-usage-meter", "Token usage meter",
     ["Total, today and this week",
      "Split by feature, so OCR is separable from extraction",
      "The model that actually served each call"]),
]

for _name, _title, _points in CLIPS:
    demo_slide(_name, "Backup · not in the main flow", _title, _points,
               notes="Backup clip — not part of the 24-minute run. Use only if asked.")

# The two screens no clip covers.
for _name, _title, _cap in [
        ("dashboard", "Appendix — Dashboard", "Organisation overview and headline risk."),
        ("exitnotes", "Appendix — Exit Notes Insights",
         "Where ingested resignation letters land — and where the lexicon limitation shows.")]:
    _s = new_slide("Backup slide — not in the 24-minute run. Use only if asked.")
    eyebrow_title(_s, "Backup · not in the main flow", _title)
    shot(_s, _name, _cap)


prs.save(OUT)
print(f"wrote {OUT}")
print(f"  {len(prs.slides.__iter__.__self__._sldIdLst)} slides")
