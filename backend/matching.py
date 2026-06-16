"""
Matching engine: compare an application's filed values against what OCR found
on the label, and produce a per-field result plus an overall verdict.

Matching philosophy (grounded in the discovery interviews):

  - The government warning is matched EXACTLY (see warning.py). People game it
    with title-case headings and altered wording, so near-misses are flagged.

  - Brand name, class/type, etc. are matched with NORMALIZED FUZZY logic.
    Dave's example: "STONE'S THROW" on the label vs "Stone's Throw" in the
    application is obviously the same product. Normalizing case/punctuation and
    allowing high-similarity matches handles this, while still catching genuine
    differences.

  - The tool never silently auto-approves. Confident matches pass; anything
    ambiguous is surfaced for a human ("review"). Agents keep the judgment.
"""

from typing import List, Optional

from .fuzzy import token_set_ratio
from .locations import expand_locations
from .extract import (
    normalize,
    extract_abv,
    extract_proof,
    parse_abv_value,
    parse_net_contents,
)
from .warning import check_warning

# Similarity thresholds for fuzzy text fields (0..100).
STRONG_MATCH = 90  # at/above -> pass
WEAK_MATCH = 70    # at/above (but below strong) -> review; below -> mismatch


def _present_in(value: str, ocr_text: str) -> int:
    """
    Best similarity of `value` against the OCR text, using token-set ratio so
    word order and extra surrounding words on the label don't hurt the score.
    """
    return int(token_set_ratio(normalize(value), normalize(ocr_text)))


def _fuzzy_field(field: str, expected: Optional[str], ocr_text: str) -> Optional[dict]:
    if not expected:
        return None
    score = _present_in(expected, ocr_text)
    if score >= STRONG_MATCH:
        status, reason = "match", f"Found on label (text match {score}%)."
    elif score >= WEAK_MATCH:
        status, reason = (
            "review",
            f"Possible match ({score}%). The label text is similar but not a "
            "clean match \u2014 please confirm.",
        )
    else:
        status, reason = (
            "mismatch",
            f"Not clearly found on the label (best match {score}%).",
        )
    return {
        "field": field,
        "status": status,
        "reason": reason,
        "expected": expected,
        "found": None,
        "details": {"similarity": score},
    }


def _location_field(field: str, expected: Optional[str], ocr_text: str) -> Optional[dict]:
    """
    Like _fuzzy_field, but expands US state abbreviations on both sides first,
    so "CA" and "California" match either direction.
    """
    if not expected:
        return None
    score = token_set_ratio(
        normalize(expand_locations(expected, strict_abbr=False)),
        normalize(expand_locations(ocr_text, strict_abbr=True)),
    )
    if score >= STRONG_MATCH:
        status, reason = "match", f"Found on label (text match {score}%)."
    elif score >= WEAK_MATCH:
        status, reason = (
            "review",
            f"Possible match ({score}%). Similar but not a clean match \u2014 "
            "please confirm.",
        )
    else:
        status, reason = (
            "mismatch",
            f"Not clearly found on the label (best match {score}%).",
        )
    return {
        "field": field, "status": status, "reason": reason,
        "expected": expected, "found": None, "details": {"similarity": score},
    }


def _check_abv(expected: Optional[str], ocr_text: str) -> Optional[dict]:
    if not expected:
        return None
    want = parse_abv_value(expected)
    found_abv, snippet = extract_abv(ocr_text)
    field = "Alcohol content"

    if found_abv is None:
        return {
            "field": field, "status": "missing",
            "reason": "No alcohol content (ABV) was found on the label.",
            "expected": expected, "found": None,
        }
    if want is None:
        return {
            "field": field, "status": "review",
            "reason": f"Label shows {found_abv}% but the filed value couldn't be parsed.",
            "expected": expected, "found": snippet,
        }

    if abs(found_abv - want) < 0.05:
        # Consistency bonus: if the label states proof, it should equal 2 x ABV.
        proof = extract_proof(ocr_text)
        detail = {"abv": found_abv}
        if proof is not None:
            detail["proof"] = proof
            if abs(proof - found_abv * 2) > 0.5:
                return {
                    "field": field, "status": "review",
                    "reason": (
                        f"ABV matches ({found_abv}%), but the stated proof "
                        f"({proof}) is not 2\u00d7 the ABV. Please check."
                    ),
                    "expected": expected, "found": snippet, "details": detail,
                }
        return {
            "field": field, "status": "match",
            "reason": f"ABV matches ({found_abv}%).",
            "expected": expected, "found": snippet, "details": detail,
        }

    return {
        "field": field, "status": "mismatch",
        "reason": f"Label shows {found_abv}% but the application filed {want}%.",
        "expected": expected, "found": snippet, "details": {"abv": found_abv, "filed": want},
    }


def _check_net_contents(expected: Optional[str], ocr_text: str) -> Optional[dict]:
    if not expected:
        return None
    field = "Net contents"
    want = parse_net_contents(expected)
    got = parse_net_contents(ocr_text)

    if got is None:
        return {
            "field": field, "status": "missing",
            "reason": "No net contents were found on the label.",
            "expected": expected, "found": None,
        }
    if want is None:
        return {
            "field": field, "status": "review",
            "reason": f"Label shows {got[0]:g} {got[1]} but the filed value couldn't be parsed.",
            "expected": expected, "found": got[2],
        }

    if abs(got[0] - want[0]) < 0.001 and got[1] == want[1]:
        return {
            "field": field, "status": "match",
            "reason": f"Net contents match ({got[2]}).",
            "expected": expected, "found": got[2],
        }
    return {
        "field": field, "status": "mismatch",
        "reason": f"Label shows {got[0]:g} {got[1]} but the application filed {want[0]:g} {want[1]}.",
        "expected": expected, "found": got[2],
    }


# Ranking so we can roll field statuses up into one verdict (worst wins).
_SEVERITY = {"match": 0, "not_checked": 0, "review": 1, "missing": 2, "mismatch": 2}


def _get(app: dict, *keys):
    """Return the first non-empty value among the given keys (key aliases)."""
    for k in keys:
        v = app.get(k)
        if v:
            return v
    return None


def verify_fields(app: dict, ocr_text: str, words=None, image=None) -> List[dict]:
    """
    Run every applicable check and return a list of field-result dicts.

    Accepts the form/CSV field names (brand_name, class_type, name_address,
    country_of_origin, ...) and also tolerates COLA-native aliases
    (class_type_desc, origin_desc) so either source works. Only fields the
    agent actually supplies are checked.

    `words` and `image` (from OCR) enable pixel-level bold detection on the
    government warning heading; without them, bold is reported as unconfirmed.
    """
    results: List[dict] = []

    brand = _fuzzy_field("Brand name", _get(app, "brand_name"), ocr_text)
    if brand:
        results.append(brand)

    fanciful = _fuzzy_field("Fanciful name", _get(app, "fanciful_name"), ocr_text)
    if fanciful:
        results.append(fanciful)

    cls = _fuzzy_field("Class / type", _get(app, "class_type", "class_type_desc"), ocr_text)
    if cls:
        results.append(cls)

    abv = _check_abv(_get(app, "alcohol_content"), ocr_text)
    if abv:
        results.append(abv)

    net = _check_net_contents(_get(app, "net_contents"), ocr_text)
    if net:
        results.append(net)

    origin = _location_field(
        "Origin",
        _get(app, "origin", "name_address", "country_of_origin", "origin_desc"),
        ocr_text,
    )
    if origin:
        results.append(origin)

    # The government warning is mandatory on every label, always checked.
    results.append(check_warning(ocr_text, words=words, image=image))

    return results


def overall_verdict(field_results: List[dict]) -> tuple:
    """Roll field statuses into (verdict, label, summary)."""
    worst = max((_SEVERITY.get(f["status"], 0) for f in field_results), default=0)
    n_attention = sum(1 for f in field_results if f["status"] in ("mismatch", "missing"))
    n_review = sum(1 for f in field_results if f["status"] == "review")

    if worst >= 2:
        return (
            "attention",
            "Needs attention",
            f"{n_attention} field(s) need attention"
            + (f", {n_review} to review" if n_review else "") + ".",
        )
    if worst == 1:
        return ("review", "Review recommended", f"{n_review} field(s) to review.")
    return ("pass", "All checks passed", "Every checked field matches the application.")
