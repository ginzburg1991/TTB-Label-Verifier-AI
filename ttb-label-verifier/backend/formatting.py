"""
Detect whether the "GOVERNMENT WARNING" heading is in BOLD type.

Plain OCR text can't see font weight, so we look at the pixels. Bold glyphs have
measurably thicker strokes than regular ones at the same size. We:

  1. Binarize the label into an ink mask.
  2. Estimate each word's mean stroke width (ink area vs. boundary length),
     normalized by the word's height so it's size-independent.
  3. Compare the heading words ("GOVERNMENT", "WARNING") against the warning's
     body words (same size, known to be non-bold per regulation).

If the heading's relative stroke width is clearly larger than the body's, it's
bold. This is a heuristic, not a font parser, so a narrow middle band returns
"uncertain" rather than guessing.

Requires numpy (a light, common dependency). If numpy is unavailable the caller
falls back to "uncertain".
"""

from __future__ import annotations

from typing import List, Optional

try:
    import numpy as np
    _HAVE_NUMPY = True
except Exception:  # pragma: no cover
    _HAVE_NUMPY = False

# Tuned on the preprocessed images: non-bold headings land near ~1.07, bold
# headings at ~1.35 and up. Thresholds sit in the gap with margin.
BOLD_RATIO = 1.30        # heading/body stroke ratio at/above this -> bold
NOT_BOLD_RATIO = 1.18    # at/below this -> not bold; between -> uncertain


def _otsu_threshold(gray) -> int:
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    total = gray.size
    sum_all = float(np.dot(np.arange(256), hist))
    w_b = 0.0
    sum_b = 0.0
    max_var = -1.0
    thr = 127
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > max_var:
            max_var = var
            thr = t
    return thr


def _stroke_rel(ink, box) -> Optional[float]:
    """Mean stroke width of a word region, normalized by its height."""
    l, t, w, h = box
    crop = ink[t:t + h, l:l + w]
    area = int(crop.sum())
    if area < 12 or h < 5:
        return None
    # Interior = ink pixels whose 4-neighbors are all ink; boundary = the rest.
    up = np.zeros_like(crop); up[1:, :] = crop[:-1, :]
    dn = np.zeros_like(crop); dn[:-1, :] = crop[1:, :]
    lf = np.zeros_like(crop); lf[:, 1:] = crop[:, :-1]
    rt = np.zeros_like(crop); rt[:, :-1] = crop[:, 1:]
    interior = crop & up & dn & lf & rt
    boundary = area - int(interior.sum())
    if boundary <= 0:
        return None
    stroke_width = 2.0 * area / boundary
    return stroke_width / h


def analyze_heading_weight(image, words: List[dict]) -> dict:
    """
    image: a grayscale PIL image of the label (the preprocessed OCR image).
    words: list of {text, left, top, width, height} from OCR.

    Returns {"bold": True|False|None, "ratio": float|None, "reason": str}.
    `bold` is None when it can't be determined.
    """
    unknown = {"bold": None, "ratio": None,
               "reason": "Could not measure stroke weight."}
    if not _HAVE_NUMPY or image is None or not words:
        return unknown

    gray = np.asarray(image.convert("L"))
    if gray.ndim != 2:
        return unknown
    thr = _otsu_threshold(gray)
    ink = gray < thr

    heights = [w["height"] for w in words if w.get("height")]
    if not heights:
        return unknown
    median_h = float(np.median(heights))

    head_rel, body_rel = [], []
    saw_heading = False
    for w in words:
        key = w["text"].upper().strip(":.,()")
        box = (w["left"], w["top"], w["width"], w["height"])
        rel = _stroke_rel(ink, box)
        if rel is None:
            continue
        if key in ("GOVERNMENT", "WARNING"):
            head_rel.append(rel)
            saw_heading = True
        elif 0.7 * median_h <= w["height"] <= 1.4 * median_h:
            # Body baseline: words the same size as the heading (excludes the
            # large bold brand name, which would otherwise skew the baseline).
            body_rel.append(rel)

    if not saw_heading or len(head_rel) == 0 or len(body_rel) < 3:
        return unknown

    h_med = float(np.median(head_rel))
    b_med = float(np.median(body_rel))
    if b_med <= 0:
        return unknown
    ratio = h_med / b_med

    if ratio >= BOLD_RATIO:
        return {"bold": True, "ratio": round(ratio, 2),
                "reason": "Heading strokes are clearly heavier than the body text."}
    if ratio <= NOT_BOLD_RATIO:
        return {"bold": False, "ratio": round(ratio, 2),
                "reason": "Heading strokes are about the same weight as the body text."}
    return {"bold": None, "ratio": round(ratio, 2),
            "reason": "Heading weight is borderline; please confirm by eye."}
