"""
US state / territory abbreviation handling.

Lets "CA" match "California" (and vice versa) when comparing a filed
name/address or origin against what's on the label. We expand a piece of text
so it contains BOTH forms, then the normal fuzzy comparison finds the overlap
regardless of which side used the abbreviation.
"""

import re

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico", "VI": "Virgin Islands", "GU": "Guam",
}

# Longer names first so "WEST VIRGINIA" is matched before "VIRGINIA".
_NAME_TO_ABBR = sorted(
    ((name.upper(), abbr) for abbr, name in STATES.items()),
    key=lambda kv: -len(kv[0]),
)


def expand_locations(text: str, strict_abbr: bool = False) -> str:
    """
    Return `text` (uppercased) augmented with both the abbreviation and the full
    name for any US state it mentions, so abbreviated and spelled-out forms match.

    strict_abbr=True is used for the noisy label/OCR side: it only treats a
    2-letter token as a state abbreviation when it is genuinely uppercase in the
    original text (so the word "or" in the warning body isn't read as Oregon,
    and "in" isn't read as Indiana), and it ignores "FL" in "FL OZ".

    strict_abbr=False is used for the short, deliberate filed value, where any
    state name or abbreviation should expand.
    """
    if not text:
        return ""
    upper = text.upper()
    extras = []

    # Full state name present -> add its abbreviation (and keep the name).
    for name, abbr in _NAME_TO_ABBR:
        if re.search(r"\b" + re.escape(name) + r"\b", upper):
            extras.append(abbr)
            extras.append(name)

    # Standalone abbreviation present -> add its full name.
    if strict_abbr:
        # Only uppercase tokens in the ORIGINAL text; skip "FL" in "FL OZ".
        tokens = re.findall(r"\b[A-Z]{2}\b(?!\s*OZ)", text)
    else:
        tokens = re.findall(r"\b[A-Z]{2}\b", upper)
    for tok in tokens:
        if tok in STATES:
            extras.append(STATES[tok].upper())
            extras.append(tok)

    return upper + (" " + " ".join(extras) if extras else "")
