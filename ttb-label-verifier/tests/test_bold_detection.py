"""
Bold-detection tests.

Unlike test_matching.py, these need the OCR engine (to locate the heading words
by bounding box). They skip cleanly if Tesseract isn't installed, so they don't
break environments without it.

Run:  pytest -q
"""

from PIL import Image, ImageDraw

from backend.formatting import analyze_heading_weight


def _tesseract_available():
    try:
        from backend.ocr import TesseractProvider
        TesseractProvider()
        return True
    except Exception:
        return False


def _render(heading_bold):
    """A minimal label: a heading (bold or not) above regular body text."""
    from scripts.generate_test_labels import font  # reuse the font resolver
    img = Image.new("RGB", (900, 480), "#ffffff")
    d = ImageDraw.Draw(img)
    d.text((40, 40), "GOVERNMENT WARNING:", font=font(24, bold=heading_bold), fill="#000")
    body = ("According to the Surgeon General women should not drink alcoholic\n"
            "beverages during pregnancy because of the risk of birth defects and\n"
            "consumption impairs your ability to drive a car or operate machinery")
    d.text((40, 95), body, font=font(24, bold=False), fill="#000")
    return img


def _analyze(heading_bold):
    from backend.ocr import TesseractProvider
    ocr = TesseractProvider().read(_render(heading_bold))
    return analyze_heading_weight(ocr.image, ocr.words)


def test_bold_heading_detected_as_bold():
    if not _tesseract_available():
        return  # skip without OCR
    result = _analyze(heading_bold=True)
    assert result["bold"] is True, result


def test_regular_heading_detected_as_not_bold():
    if not _tesseract_available():
        return  # skip without OCR
    result = _analyze(heading_bold=False)
    assert result["bold"] is False, result


def test_analyze_returns_unknown_without_inputs():
    # No image / no words -> can't determine -> None (never a false positive).
    assert analyze_heading_weight(None, [])["bold"] is None
