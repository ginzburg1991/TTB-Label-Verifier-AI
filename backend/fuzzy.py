"""
Small, dependency-free fuzzy string matching.

We only need one function: a token-set similarity that ignores word order and
tolerates extra surrounding words (the label has lots of other text around the
brand name). This mirrors the idea behind RapidFuzz's token_set_ratio but uses
only the standard library, so there's nothing extra to install.
"""

from difflib import SequenceMatcher


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def token_set_ratio(a: str, b: str) -> int:
    """
    Return a 0..100 similarity score between two already-normalized strings,
    comparing the shared token set against each side's extra tokens.
    """
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0

    inter = sorted(ta & tb)
    diff_a = sorted(ta - tb)
    diff_b = sorted(tb - ta)

    sect = " ".join(inter)
    combined_a = (sect + " " + " ".join(diff_a)).strip()
    combined_b = (sect + " " + " ".join(diff_b)).strip()

    scores = [_ratio(combined_a, combined_b)]
    if sect:
        # If every query token is present (diff_a empty), these hit 1.0 even when
        # the other side has lots of extra label text.
        scores.append(_ratio(sect, combined_a))
        scores.append(_ratio(sect, combined_b))

    return int(round(100 * max(scores)))
