"""Generate photograph-like images of paper documents for OCR testing.

Renders each page onto an off-white sheet and then degrades it the way a
phone camera does: a slight rotation, uneven lighting across the page, and
sensor noise. A crisp screenshot of text is not a useful OCR fixture —
every backend reads one perfectly, so it would prove nothing about the
cases that actually fail.

The last file is pushed to the edge of legibility on purpose. The
interesting failure there is not a refusal — that would be correct —
but a confident misreading of a date or a salary digit, which nothing
downstream can catch because the result is still a valid value.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
except ImportError:
    sys.exit('Pillow is required: pip install pillow')

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample-docs" / "paper-scans"
W, H = 1240, 1754  # A4 at ~150 dpi


def _font(size: int):
    for name in ("georgia.ttf", "times.ttf", "DejaVuSerif.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _sheet(lines: list[tuple[str, int]]) -> Image.Image:
    img = Image.new("RGB", (W, H), (250, 249, 245))
    draw = ImageDraw.Draw(img)
    y = 150
    for text, size in lines:
        if not text:
            y += size
            continue
        draw.text((120, y), text, font=_font(size), fill=(28, 28, 32))
        y += int(size * 1.55)
    return img


def _photograph(img: Image.Image, rng: random.Random, *, severity: float = 1.0) -> Image.Image:
    """Make a clean render look like it was photographed on a desk."""
    img = img.rotate(rng.uniform(-1.6, 1.6) * severity,
                     resample=Image.BICUBIC, fillcolor=(250, 249, 245))

    # Uneven lighting: a soft gradient across the page, as from a window.
    shade = Image.new("L", img.size, 0)
    sd = ImageDraw.Draw(shade)
    for x in range(0, W, 8):
        sd.rectangle([x, 0, x + 8, H], fill=int(28 * severity * (x / W)))
    img = Image.composite(img, Image.new("RGB", img.size, (214, 212, 206)),
                          shade.point(lambda v: 255 - v))

    img = img.filter(ImageFilter.GaussianBlur(0.6 * severity))
    img = ImageEnhance.Contrast(img).enhance(1 - 0.18 * severity)

    noise = Image.effect_noise(img.size, 14 * severity).convert("L")
    return Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.05 * severity)


def write(name: str, lines: list[tuple[str, int]], *, severity: float, seed: int) -> None:
    rng = random.Random(seed)
    img = _photograph(_sheet(lines), rng, severity=severity)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    img.save(path, quality=82, optimize=True)
    print(f"  {name}  ({path.stat().st_size / 1024:.0f} KB)")


RESIGNATION = [
    ("MERIDIAN ANALYTICS", 30), ("", 10),
    ("Anna Daniels", 26),
    ("anna.daniels@meridiananalytics.example", 22), ("", 14),
    ("18 August 2026", 22), ("", 20),
    ("Dear Alison,", 24), ("", 10),
    ("I am writing to give formal notice of my resignation", 22),
    ("from the position of Senior Analyst. My last working", 22),
    ("day will be 30 September 2026.", 22), ("", 12),
    ("The workload has not returned to a sustainable level", 22),
    ("since the reorganisation in March. I raised this twice", 22),
    ("and was asked both times to wait for the next planning", 22),
    ("cycle. I am not willing to spend another year waiting.", 22), ("", 12),
    ("I will do everything I can to hand over cleanly.", 22), ("", 20),
    ("Regards,", 22), ("", 16),
    ("Anna Daniels", 24),
]

REVIEW = [
    ("PERFORMANCE REVIEW", 30),
    ("Meridian Analytics - Confidential", 20), ("", 22),
    ("Employee:   Carla Clark", 23),
    ("Email:      carla.clark@meridiananalytics.example", 21),
    ("Department: Engineering", 23),
    ("Period:     1 January 2025 - 31 December 2025", 23), ("", 20),
    ("OVERALL RATING:  4 / 5", 28), ("", 20),
    ("Strengths", 24),
    ("- Rebuilt the on-call escalation pipeline; median", 21),
    ("  time-to-acknowledge fell from 14 minutes to 3.", 21),
    ("- Mentored two graduates through first deploys.", 21), ("", 14),
    ("Development areas", 24),
    ("- Estimates remain optimistic; three of five", 21),
    ("  commitments slipped during the period.", 21), ("", 20),
    ("Reviewer: A. Pike", 22),
]

OFFER = [
    ("MERIDIAN ANALYTICS", 30),
    ("120 Fenchurch Street, London EC3M 5BA", 19), ("", 22),
    ("OFFER OF EMPLOYMENT", 27), ("", 18),
    ("Candidate:    Nadia Osei", 23),
    ("Email:        nadia.osei@meridiananalytics.example", 20),
    ("Position:     Backend Engineer", 23),
    ("Level:        IC3", 23),
    ("Department:   Engineering", 23),
    ("Start date:   1 October 2026", 23),
    ("Base salary:  GBP 128,000 per annum", 23),
    ("Bonus:        up to 10% of base, discretionary", 21), ("", 20),
    ("This offer is conditional on satisfactory references", 21),
    ("and your right to work in the United Kingdom.", 21), ("", 18),
    ("People Operations", 22),
]


def main() -> None:
    print(f"writing to {OUT}")
    write("resignation-letter-photographed-clean.jpg", RESIGNATION, severity=0.5, seed=1)
    write("performance-review-photographed-angled.jpg", REVIEW, severity=1.0, seed=2)
    write("offer-letter-photographed-poor-lighting.jpg", OFFER, severity=1.6, seed=3)
    # Washed out almost to the paper colour. The body text survives just
    # well enough that a strong model may still read it, which is the
    # point: the failure to watch for is not a refusal but a confident
    # wrong reading of a digit or a date.
    write("resignation-letter-photographed-very-faint.jpg", RESIGNATION, severity=3.4, seed=4)
    print("\ndone")


if __name__ == "__main__":
    main()
