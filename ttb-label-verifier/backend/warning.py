"""
Government Health Warning verification.

The warning statement is the single highest-stakes check on a TTB label, so it
gets its own module. Per the Alcoholic Beverage Labeling Act of 1988 and
27 CFR 16.21 / 16.22:

  - The statement must appear word-for-word.
  - The first two words, "GOVERNMENT WARNING", must be in CAPITAL LETTERS
    and in bold type. The remainder must NOT be bold.
  - It must appear as a single continuous statement.

What we CAN verify from OCR text:
  - The exact wording (case-sensitive, after normalizing OCR whitespace noise).
  - That "GOVERNMENT WARNING" appears in all caps (Tesseract preserves case).

What we CANNOT verify from OCR text alone:
  - Bold type / font weight. Detecting bold requires layout/glyph analysis,
    not plain text. We flag this as a manual-review item rather than passing
    silently. See README "Known limitations".
"""

import re
from difflib import SequenceMatcher

from .formatting import analyze_heading_weight

# The exact, canonical statement (27 CFR 16.21). This is the source of truth.
CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should "
    "not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your "
    "ability to drive a car or operate machinery, and may cause health "
    "problems."
)

# The body text only (everything after "GOVERNMENT WARNING:"), used to compare
# wording independently of the heading's capitalization.
CANONICAL_BODY = CANONICAL_WARNING.split(":", 1)[1].strip()

# Matches the heading in any casing so we can locate the statement and then
# inspect how it was actually capitalized on the label.
_HEADING_RE = re.compile(r"government\s+warning", re.IGNORECASE)


def _collapse_ws(text: str) -> str:
    """Collapse all runs of whitespace (incl. OCR line breaks) to single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def _similarity(a: str, b: str) -> float:
    """0..1 similarity, tolerant of small OCR character errors."""
    return SequenceMatcher(None, a, b).ratio()


def check_warning(ocr_text: str, words=None, image=None) -> dict:
    """
    Inspect the full OCR text of a label for the government warning.

    If `words` (OCR boxes) and `image` (grayscale label) are supplied, the
    heading's bold type is verified from the pixels. Without them, bold is
    reported as unconfirmed ("review").

    Returns a dict describing the finding. `status` is one of:
      - "match"     : wording, capitalization, AND bold all confirmed
      - "review"    : wording/caps fine but bold couldn't be determined, or a
                      near-match within OCR tolerance
      - "mismatch"  : wording differs, heading not capitalized, or heading not bold
      - "missing"   : no warning statement found at all
    """
    flat = _collapse_ws(ocr_text)

    heading_match = _HEADING_RE.search(flat)
    if not heading_match:
        return {
            "field": "Government warning",
            "status": "missing",
            "reason": "No government warning statement was found on the label.",
            "found": None,
            "expected": CANONICAL_WARNING,
        }

    # Pull the statement from the heading to roughly the end of the canonical
    # length (plus slack) so we compare like-for-like even if other label text
    # follows the warning.
    start = heading_match.start()
    window = flat[start : start + len(CANONICAL_WARNING) + 60]

    # 1) Capitalization of the heading itself.
    raw_heading = window[: heading_match.end() - heading_match.start()]
    heading_is_caps = raw_heading.strip().startswith("GOVERNMENT WARNING")

    # 2) Compare the body wording, case-sensitive but whitespace-normalized.
    #    Split on the first colon in the located window.
    if ":" in window:
        found_body = window.split(":", 1)[1].strip()
    else:
        found_body = window[len("GOVERNMENT WARNING") :].strip()

    # Trim the found body to the canonical body length for a fair comparison;
    # trailing label text (e.g. "CONTAINS SULFITES") shouldn't fail the check.
    trimmed_body = found_body[: len(CANONICAL_BODY)]
    exact_body = trimmed_body == CANONICAL_BODY
    body_score = _similarity(trimmed_body, CANONICAL_BODY)

    found_display = window.strip()

    # Decision tree.
    if exact_body and heading_is_caps:
        weight = analyze_heading_weight(image, words or [])
        if weight["bold"] is True:
            return {
                "field": "Government warning",
                "status": "match",
                "reason": (
                    "Wording, all-caps heading, and bold type are all confirmed."
                ),
                "found": found_display,
                "expected": CANONICAL_WARNING,
                "details": {"wording": "exact", "heading_uppercase": True,
                            "heading_bold": True, "bold_ratio": weight["ratio"]},
            }
        if weight["bold"] is False:
            return {
                "field": "Government warning",
                "status": "mismatch",
                "reason": (
                    "Wording and capitalization are correct, but 'GOVERNMENT "
                    "WARNING' is not in bold type. The heading must be bold "
                    "(27 CFR 16.22)."
                ),
                "found": found_display,
                "expected": CANONICAL_WARNING,
                "details": {"wording": "exact", "heading_uppercase": True,
                            "heading_bold": False, "bold_ratio": weight["ratio"]},
            }
        # bold is None -> couldn't measure.
        return {
            "field": "Government warning",
            "status": "review",
            "reason": (
                "Wording and capitalization are correct. " + weight["reason"]
                + " Please verify 'GOVERNMENT WARNING' appears in bold."
            ),
            "found": found_display,
            "expected": CANONICAL_WARNING,
            "details": {"wording": "exact", "heading_uppercase": True,
                        "heading_bold": None, "bold_ratio": weight["ratio"]},
        }

    if not heading_is_caps and (exact_body or body_score >= 0.97):
        return {
            "field": "Government warning",
            "status": "mismatch",
            "reason": (
                "Wording is correct but 'GOVERNMENT WARNING' is not in all "
                "capital letters. The heading must be capitalized (27 CFR 16.22)."
            ),
            "found": found_display,
            "expected": CANONICAL_WARNING,
            "details": {
                "wording": "exact" if exact_body else "near",
                "heading_uppercase": False,
            },
        }

    if body_score >= 0.97:
        # Very close: likely OCR noise rather than a real wording change.
        return {
            "field": "Government warning",
            "status": "review",
            "reason": (
                "Wording is a very close match but not byte-for-byte identical "
                f"({body_score:.0%}). This is often OCR noise \u2014 please "
                "confirm the text reads exactly as required."
            ),
            "found": found_display,
            "expected": CANONICAL_WARNING,
            "details": {"wording": "near", "similarity": round(body_score, 3)},
        }

    return {
        "field": "Government warning",
        "status": "mismatch",
        "reason": (
            f"Warning wording differs from the required statement "
            f"({body_score:.0%} similar). The statement must appear "
            "word-for-word."
        ),
        "found": found_display,
        "expected": CANONICAL_WARNING,
        "details": {"wording": "different", "similarity": round(body_score, 3)},
    }
