"""
Image preprocessing.

Goals, in priority order:
  1. Speed  - cap oversized images so OCR stays within the latency budget.
  2. Legibility - recover text from imperfect photos (low light, soft focus,
     mild blur) so a label with correct information still reads.

Two strengths are provided:
  - gentle (default): a single light sharpening pass. Best for normal, noisy, or
    glare-affected photos -- strong sharpening would amplify their grain.
  - aggressive: double sharpening, which rescues genuinely blurry / soft-focus
    photos. The OCR layer escalates to this only when the gentle pass comes back
    low-confidence, so clean images are never over-processed.

Pillow-only. Heavier corrections (perspective de-warp / deskew for steeply
angled photos) are noted as future work in the README.
"""

from PIL import Image, ImageOps, ImageFilter

MAX_EDGE = 2200       # cap longest edge for speed
MIN_EDGE = 1600       # upscale anything smaller so fine print has enough pixels
TARGET_SMALL = 1800


def _base(image: Image.Image) -> Image.Image:
    """Orientation, sizing, grayscale, and adaptive contrast (shared by both)."""
    image = ImageOps.exif_transpose(image)

    longest = max(image.size)
    if longest > MAX_EDGE:
        scale = MAX_EDGE / longest
        image = image.resize(
            (round(image.width * scale), round(image.height * scale)), Image.LANCZOS
        )

    gray = ImageOps.grayscale(image)

    longest = max(gray.size)
    if longest < MIN_EDGE:
        scale = TARGET_SMALL / longest
        gray = gray.resize(
            (int(gray.width * scale), int(gray.height * scale)), Image.LANCZOS
        )

    # Adaptive contrast: brightens dark photos, leaves normal ones alone.
    return ImageOps.autocontrast(gray, cutoff=1)


def preprocess(image: Image.Image, aggressive: bool = False) -> Image.Image:
    """Return a cleaned-up grayscale image ready for OCR."""
    gray = _base(image)
    if aggressive:
        # Double sharpening to counteract real blur (escalation path).
        gray = gray.filter(ImageFilter.UnsharpMask(radius=3, percent=220, threshold=1))
        gray = gray.filter(ImageFilter.UnsharpMask(radius=3, percent=220, threshold=1))
    else:
        # Single light pass: helps focus without amplifying noise/grain.
        gray = gray.filter(ImageFilter.UnsharpMask(radius=3, percent=180, threshold=1))
    return gray
