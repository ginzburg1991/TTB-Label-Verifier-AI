"""
OCR providers.

Design note (this is the most important architectural decision in the project):

During discovery, IT (Marcus) was explicit that the agency's network blocks
outbound traffic to many domains, and that the previous vendor's cloud ML
endpoints were firewalled, breaking half their features. So the DEFAULT engine
here is local Tesseract: it runs entirely on-prem with zero outbound calls,
which is what a real TTB deployment would require.

OCR is hidden behind a small interface so a more capable engine (e.g. a
self-hosted vision model, or a cloud vision API for environments that allow it)
can be swapped in without touching the extraction or matching logic. A cloud
vision stub is included but disabled by default and clearly marked as
firewall-incompatible for TTB's environment.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from PIL import Image

from .preprocess import preprocess

# If the gentle OCR pass comes back below this mean confidence, retry with
# aggressive sharpening (the image is probably blurry / soft focus).
ESCALATE_THRESHOLD = 78.0


@dataclass
class OcrOutput:
    text: str
    confidence: float  # mean word confidence, 0..100; -1 if unknown
    provider: str
    words: List[dict] = field(default_factory=list)  # {text,left,top,width,height}
    image: Optional[Image.Image] = None  # preprocessed grayscale, for pixel analysis
    low_quality: bool = False  # photo read poorly even after enhancement / needed escalation


class OcrProvider(Protocol):
    name: str

    def read(self, image: Image.Image) -> OcrOutput: ...


class TesseractProvider:
    """Local OCR via the Tesseract engine (no network)."""

    name = "tesseract (local, on-prem)"

    def __init__(self) -> None:
        # Import here so the app can start and explain itself even if the
        # python binding isn't installed yet.
        import pytesseract  # noqa: F401

        self._pytesseract = pytesseract

        cmd = self._resolve_tesseract_cmd()
        if cmd is None:
            raise RuntimeError(
                "The Tesseract OCR engine could not be found. Either add it to "
                "your PATH, or set the TESSERACT_CMD environment variable to the "
                "full path of the executable. Install it from:\n"
                "  macOS:   brew install tesseract\n"
                "  Ubuntu:  sudo apt-get install tesseract-ocr\n"
                "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
                "Example (Windows PowerShell):\n"
                '  $env:TESSERACT_CMD = "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"'
            )

        # Point pytesseract at the resolved executable.
        pytesseract.pytesseract.tesseract_cmd = cmd

    @staticmethod
    def _resolve_tesseract_cmd():
        """
        Find the Tesseract executable, in priority order:
          1. TESSERACT_CMD env var (explicit override)
          2. on the system PATH
          3. common default install locations (Windows / macOS / Linux)
        Returns the path, or None if nothing is found.
        """
        env = os.environ.get("TESSERACT_CMD")
        if env and os.path.exists(env):
            return env

        on_path = shutil.which("tesseract")
        if on_path:
            return on_path

        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/usr/bin/tesseract",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return None

    def _summarize(self, data) -> tuple:
        """Build the word list and mean confidence from image_to_data output."""
        confs, words = [], []
        for i, word in enumerate(data["text"]):
            if not word.strip():
                continue
            words.append({
                "text": word,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "width": int(data["width"][i]),
                "height": int(data["height"][i]),
            })
            try:
                c = float(data["conf"][i])
                if c >= 0:
                    confs.append(c)
            except (TypeError, ValueError):
                pass
        mean_conf = round(sum(confs) / len(confs), 1) if confs else -1.0
        return mean_conf, words

    def read(self, image: Image.Image) -> OcrOutput:
        pt = self._pytesseract

        # Pass 1: gentle preprocessing (good for normal / noisy / glare photos).
        clean = preprocess(image, aggressive=False)
        data = pt.image_to_data(clean, output_type=pt.Output.DICT)
        conf, words = self._summarize(data)

        # Escalate to aggressive sharpening only if the gentle pass read poorly
        # (likely a blurry / soft-focus photo). Keep whichever reads better.
        # A poor gentle pass is itself the "this is a low-quality photo" signal:
        # clean / noisy / glare photos read fine gently (~90%+), while genuinely
        # blurry or dark ones drop below the escalation threshold.
        low_quality = 0 <= conf < ESCALATE_THRESHOLD
        if low_quality:
            clean2 = preprocess(image, aggressive=True)
            data2 = pt.image_to_data(clean2, output_type=pt.Output.DICT)
            conf2, words2 = self._summarize(data2)
            if conf2 > conf:
                clean, conf, words = clean2, conf2, words2

        text = pt.image_to_string(clean)
        return OcrOutput(text=text, confidence=conf, provider=self.name,
                         words=words, image=clean, low_quality=low_quality)


class CloudVisionProvider:
    """
    Placeholder for a cloud vision model (e.g. an LLM with image input).

    NOT used by default. In TTB's environment outbound calls to ML endpoints
    are firewalled, so this would fail there exactly as the previous vendor's
    product did. It exists to show the interface is engine-agnostic: a
    self-hosted vision model could implement this same `read()` contract and
    drop straight in. Implementation is intentionally left as a stub.
    """

    name = "cloud-vision (disabled \u2014 firewall-incompatible for TTB)"

    def read(self, image: Image.Image) -> OcrOutput:  # pragma: no cover
        raise NotImplementedError(
            "Cloud vision provider is a stub. The default on-prem Tesseract "
            "provider is used so the tool works behind the agency firewall."
        )


def get_provider() -> OcrProvider:
    """Select the OCR provider from the OCR_PROVIDER env var (default tesseract)."""
    choice = os.environ.get("OCR_PROVIDER", "tesseract").lower()
    if choice == "cloud":
        return CloudVisionProvider()
    return TesseractProvider()
