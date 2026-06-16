"""Data models shared across the API."""

from typing import List, Optional
from pydantic import BaseModel, Field


class ApplicationData(BaseModel):
    """
    The 'truth' an agent filed, that the label image is checked against.

    Field names match the web form and the batch CSV columns. Only brand_name
    is required; every other field is checked only when supplied.
    """

    brand_name: str = Field(..., description="Brand name as filed, e.g. 'OLD TOM DISTILLERY'")
    class_type: Optional[str] = Field(None, description="Class/type, e.g. 'Kentucky Straight Bourbon Whiskey'")
    alcohol_content: Optional[str] = Field(None, description="ABV as filed, e.g. '45% Alc./Vol.'")
    net_contents: Optional[str] = Field(None, description="Net contents, e.g. '750 mL'")
    origin: Optional[str] = Field(None, description="Origin: a US state (e.g. 'Kentucky') or a country (e.g. 'Product of Mexico')")


class FieldResult(BaseModel):
    field: str
    status: str  # match | review | mismatch | missing | not_checked
    reason: str
    expected: Optional[str] = None
    found: Optional[str] = None
    details: Optional[dict] = None


class VerificationResult(BaseModel):
    label_id: Optional[str] = None
    verdict: str  # pass | review | attention
    verdict_label: str
    summary: str
    fields: List[FieldResult]
    reference: Optional[dict] = None  # COLA metadata shown but not matched
    ocr_confidence: Optional[float] = None
    image_quality_note: Optional[str] = None
    elapsed_ms: int
    ocr_provider: str
    ocr_text: Optional[str] = None  # raw text, useful for agents to eyeball
