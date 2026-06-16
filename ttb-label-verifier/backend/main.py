"""
TTB Label Verification API.

Endpoints:
  GET  /api/health              -> service + OCR engine status
  POST /api/verify              -> verify one label image against filed data
  POST /api/verify-batch        -> verify many labels from a CSV manifest + images
  GET  /                        -> the web app (static frontend)

Run:
  uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from .matching import verify_fields, overall_verdict
from .models import VerificationResult
from .ocr import get_provider, OcrProvider

app = FastAPI(title="TTB Label Verification", version="1.0.0")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# OCR confidence below this gets an image-quality warning for the agent.
LOW_CONFIDENCE = 60.0

# Lazily-initialised provider so the app can boot and report a helpful error
# (e.g. "install Tesseract") instead of crashing on import.
_provider: Optional[OcrProvider] = None
_provider_error: Optional[str] = None


def provider() -> OcrProvider:
    global _provider, _provider_error
    if _provider is None and _provider_error is None:
        try:
            _provider = get_provider()
        except Exception as exc:  # surfaced to the client as a clear message
            _provider_error = str(exc)
    if _provider is None:
        raise HTTPException(status_code=503, detail=_provider_error or "OCR unavailable")
    return _provider


def _load_image(raw: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError):
        raise HTTPException(
            status_code=400,
            detail="That file could not be read as an image. Use JPG or PNG.",
        )


def _verify_one(app_data: dict, image: Image.Image, label_id: Optional[str],
                reference: Optional[dict] = None) -> dict:
    start = time.perf_counter()
    ocr = provider().read(image)
    fields = verify_fields(app_data, ocr.text, words=ocr.words, image=ocr.image)
    verdict, verdict_label, summary = overall_verdict(fields)

    quality_note = None
    if ocr.low_quality or (0 <= ocr.confidence < LOW_CONFIDENCE):
        quality_note = (
            "Image quality looks low \u2014 this photo needed heavy enhancement to "
            "read"
            + (f" (OCR confidence {ocr.confidence:.0f}%)" if ocr.confidence >= 0 else "")
            + ". Some fields may be misread, so review the label yourself and "
            "confirm if it's actually correct. A clearer, straight-on photo will help."
        )

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return VerificationResult(
        label_id=label_id,
        verdict=verdict,
        verdict_label=verdict_label,
        summary=summary,
        fields=fields,
        reference={k: v for k, v in (reference or {}).items() if v} or None,
        ocr_confidence=ocr.confidence if ocr.confidence >= 0 else None,
        image_quality_note=quality_note,
        elapsed_ms=elapsed_ms,
        ocr_provider=ocr.provider,
        ocr_text=ocr.text.strip(),
    ).model_dump()


@app.get("/api/health")
def health():
    status = {"status": "ok", "service": "ttb-label-verification"}
    try:
        status["ocr_provider"] = provider().name
        status["ocr_ready"] = True
    except HTTPException as exc:
        status["ocr_ready"] = False
        status["ocr_error"] = exc.detail
    return status


@app.post("/api/verify")
async def verify(
    image: UploadFile = File(...),
    brand_name: str = Form(...),
    class_type: Optional[str] = Form(None),
    alcohol_content: Optional[str] = Form(None),
    net_contents: Optional[str] = Form(None),
    origin: Optional[str] = Form(None),
):
    app_data = {
        "brand_name": brand_name,
        "class_type": class_type,
        "alcohol_content": alcohol_content,
        "net_contents": net_contents,
        "origin": origin,
    }
    img = _load_image(await image.read())
    return _verify_one(app_data, img, label_id=image.filename)


@app.post("/api/verify-batch")
async def verify_batch(
    manifest: UploadFile = File(..., description="CSV with one row per label"),
    images: List[UploadFile] = File(..., description="Label image files"),
):
    """
    Batch mode for importers that submit hundreds of labels at once.

    The manifest CSV must have a header row including at least:
      image_filename, brand_name
    Optional columns: label_id, class_type, alcohol_content, net_contents,
    origin (a US state or a country of origin).
    Each row is matched to an uploaded image by `image_filename`.
    """
    # Index uploaded images by filename.
    raw_images = {}
    for up in images:
        raw_images[Path(up.filename).name] = await up.read()

    text = (await manifest.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "image_filename" not in reader.fieldnames:
        raise HTTPException(
            status_code=400,
            detail="Manifest must be a CSV with an 'image_filename' column.",
        )

    results = []
    for row in reader:
        fname = (row.get("image_filename") or "").strip()
        label_id = (row.get("label_id") or fname or "").strip()
        app_data = {
            "brand_name": (row.get("brand_name") or "").strip(),
            "class_type": (row.get("class_type") or "").strip() or None,
            "alcohol_content": (row.get("alcohol_content") or "").strip() or None,
            "net_contents": (row.get("net_contents") or "").strip() or None,
            # Single origin column; tolerate older name_address/country_of_origin.
            "origin": (row.get("origin") or row.get("name_address")
                       or row.get("country_of_origin") or "").strip() or None,
        }

        if fname not in raw_images:
            results.append({
                "label_id": label_id, "verdict": "attention",
                "verdict_label": "Image missing",
                "summary": f"No uploaded image named '{fname}'.",
                "fields": [], "elapsed_ms": 0,
                "ocr_provider": "n/a", "ocr_text": None,
            })
            continue

        try:
            img = _load_image(raw_images[fname])
            results.append(_verify_one(app_data, img, label_id=label_id))
        except HTTPException as exc:
            results.append({
                "label_id": label_id, "verdict": "attention",
                "verdict_label": "Error", "summary": str(exc.detail),
                "fields": [], "elapsed_ms": 0,
                "ocr_provider": "n/a", "ocr_text": None,
            })

    # Surface problems first: attention, then review, then passes.
    order = {"attention": 0, "review": 1, "pass": 2}
    results.sort(key=lambda r: order.get(r["verdict"], 0))

    counts = {"pass": 0, "review": 0, "attention": 0}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    return JSONResponse({"counts": counts, "total": len(results), "results": results})


# Serve the web app. Mounted last so it doesn't shadow /api routes.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
