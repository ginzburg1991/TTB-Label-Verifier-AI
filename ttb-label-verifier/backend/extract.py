"""
Extractors that pull specific structured values out of raw OCR text.

These are deliberately small and explicit. Each returns the parsed value plus
the raw snippet it came from, so the UI can show an agent exactly what the tool
saw on the label.
"""

import re
from typing import Optional, Tuple


def normalize(text: str) -> str:
    """Uppercase, drop punctuation, collapse whitespace. For fuzzy comparisons."""
    text = text.upper()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# --- Alcohol content -------------------------------------------------------

# Preferred: a percentage sitting right next to an alcohol keyword, in either
# order ("40% Alc./Vol." or "ALC 40% BY VOL"). The (?<!\d) guards against
# pulling "00" out of "100%" (e.g. "100% de Agave").
_ABV_AFTER_RE = re.compile(
    r"(?<!\d)(\d{1,2}(?:\.\d{1,2})?)\s*%\s*(?:alc|abv|alcohol)", re.IGNORECASE
)
_ABV_BEFORE_RE = re.compile(
    r"(?:alc|abv|alcohol)[^\d%]{0,12}(?<!\d)(\d{1,2}(?:\.\d{1,2})?)\s*%", re.IGNORECASE
)
# Fallback: any plausible "NN%" not embedded in a larger number.
_ABV_GENERIC_RE = re.compile(r"(?<!\d)(\d{1,2}(?:\.\d{1,2})?)\s*%")
_PROOF_RE = re.compile(r"(\d{1,3}(?:\.\d)?)\s*proof", re.IGNORECASE)

# Plausible ABV range for a beverage: above 0, up to ~95% for high-proof spirits.
_ABV_MIN, _ABV_MAX = 0.0, 95.0


def _plausible(value: float) -> bool:
    return _ABV_MIN < value <= _ABV_MAX


def extract_abv(text: str) -> Tuple[Optional[float], Optional[str]]:
    """Return (abv_percent, raw_snippet) found in the text, or (None, None)."""
    # 1) Percentage adjacent to an alcohol keyword (most reliable).
    for rx in (_ABV_AFTER_RE, _ABV_BEFORE_RE):
        m = rx.search(text)
        if m:
            try:
                v = float(m.group(1))
                if _plausible(v):
                    return v, m.group(0).strip()
            except ValueError:
                pass
    # 2) Fallback: first plausible standalone percentage (skips "100%" etc.).
    for m in _ABV_GENERIC_RE.finditer(text):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if _plausible(v):
            return v, m.group(0).strip()
    return None, None


def extract_proof(text: str) -> Optional[float]:
    m = _PROOF_RE.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def parse_abv_value(text: str) -> Optional[float]:
    """Parse an ABV number out of an application's free-text field."""
    if not text:
        return None
    abv, _ = extract_abv(text)
    if abv is not None:
        return abv
    m = re.search(r"(\d{1,2}(?:\.\d{1,2})?)", text)
    return float(m.group(1)) if m else None


# --- Net contents ----------------------------------------------------------

_NET_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ml|milliliters?|l|liters?|litres?|fl\.?\s*oz|oz)\b",
    re.IGNORECASE,
)

# Normalize unit spellings to a canonical token for comparison.
_UNIT_CANON = {
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "floz": "floz", "fl oz": "floz", "oz": "floz",
}


def parse_net_contents(text: str) -> Optional[Tuple[float, str, str]]:
    """Return (amount, canonical_unit, raw_snippet) or None."""
    if not text:
        return None
    m = _NET_RE.search(text)
    if not m:
        return None
    try:
        amount = float(m.group(1))
    except ValueError:
        return None
    unit_raw = re.sub(r"[.\s]+", " ", m.group(2).lower()).strip()
    unit = _UNIT_CANON.get(unit_raw.replace(" ", ""), _UNIT_CANON.get(unit_raw, unit_raw))
    return amount, unit, m.group(0).strip()
