import asyncio
import base64
import json
import logging
import re
import shutil
from dataclasses import dataclass
from io import BytesIO

import fitz
import httpx
import pytesseract
from PIL import Image, ImageOps

from .config import get_settings

logger = logging.getLogger(__name__)

# Use whatever tesseract binary is on PATH (works in the production Docker
# image and in local dev). Falls back to the bare 'tesseract' command name.
tesseract_path = shutil.which('tesseract') or 'tesseract'
pytesseract.pytesseract.tesseract_cmd = tesseract_path


@dataclass(frozen=True)
class Extraction:
    text: str
    fields: dict[str, str]


class DocumentExtractionError(ValueError):
    """Raised when a document cannot yield usable text."""


async def extract_document(data: bytes, mime_type: str) -> Extraction:
    # 1. Extract raw text using PyMuPDF (PDFs) or Tesseract (Images)
    if mime_type == "application/pdf":
        def read_pdf():
            with fitz.open(stream=data, filetype="pdf") as document:
                page_text: list[str] = []
                for page in document:
                    text = page.get_text().strip()
                    # A PDF can contain both digital and scanned pages.  OCR each
                    # page without usable embedded text instead of only page one.
                    if len(text) < 20:
                        pix = page.get_pixmap(dpi=300, alpha=False)
                        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                        text = _ocr_image(image)
                    page_text.append(text)
                return "\n".join(page_text)[:50_000]
        text = await asyncio.to_thread(read_pdf)
    else:
        def read_img():
            with Image.open(BytesIO(data)) as image:
                return _ocr_image(image)[:50_000]
        text = await asyncio.to_thread(read_img)

    if not text.strip():
        raise DocumentExtractionError("No readable text was found in the uploaded document")

    fields: dict[str, str] = {}
    
    # 2. Ask Gemini to inspect the source document as well as the local OCR text.
    # Vision is especially helpful for tables, stamps, unusual layouts, and text
    # that traditional OCR reads imperfectly.
    settings = get_settings()
    if settings.gemini_api_key and settings.gemini_model:
        try:
            fields = await _parse_fields_with_gemini(data, mime_type, text, settings.gemini_api_key, settings.gemini_model)
        except Exception:
            logger.warning("Gemini document parsing failed; using local extraction", exc_info=True)
            fields = {}
    
    # 3. Fallback to Regex if Gemini is disabled or fails
    if not fields:
        patterns = {
            "invoice_number": r"(?:invoice|quotation|bill)\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9/-]{3,})",
            "gstin": r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d][A-Z\d]\b",
            "amount": r"(?:INR |INR|Rs\.?|Total|Amount|Bill Amount)[\s:$]*([\d,]+(?:\.\d{1,2})?)",
            "supplier": r"(?:M/s|Supplier|Vendor|From|Billed By|Client Information)\s*[:.-]?\s*([A-Za-z0-9\s.,&-]{3,40})",
            "city": r"(?:City|Location|Place of Supply|Address)\s*[:.-]?\s*(?:.*,)?\s*([A-Za-z\s]{3,30})(?:,|$)",
            "contact": r"(?:Email|Phone|Call|Contact|Ph|Tel)\s*[:.-]?\s*([A-Za-z0-9@+.-]{5,40})",
            "state": r"(?:State|Province)\s*[:.-]?\s*([A-Za-z\s]{3,30})(?:,|$)",
            "payment_beneficiary": r"(?:Beneficiary|Account Name|Pay To)\s*[:.-]?\s*([A-Za-z0-9\s.,&-]{3,40})",
            "payment_reference_masked": r"(?:A/C|Account|IBAN|Acc)\s*[:.-]?\s*[A-Za-z0-9\s-]*([0-9]{4})\b",
        }
        for label, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fields[label] = match.group(1).strip() if match.lastindex else match.group(0).strip()
                
    return Extraction(text=text, fields=fields)


def _ocr_image(image: Image.Image) -> str:
    """Prepare common phone/scanner image formats before passing them to Tesseract."""
    image = ImageOps.exif_transpose(image)
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image.convert("RGBA"))
        image = background.convert("RGB")
    else:
        image = image.convert("RGB")

    # Small camera images are routinely under-resolved for invoice text. Upscaling
    # them improves character recognition without needlessly inflating normal scans.
    if max(image.size) < 1800:
        image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(ImageOps.grayscale(image))

    # Invoices vary between sparse pages and dense tables. Try both Tesseract
    # layouts and retain the stronger result instead of assuming one layout fits all.
    candidates = [
        pytesseract.image_to_string(image, config="--oem 3 --psm 3"),
        pytesseract.image_to_string(image, config="--oem 3 --psm 6"),
    ]
    return max(candidates, key=_ocr_quality)


def _ocr_quality(text: str) -> tuple[int, int]:
    """Prefer useful, character-rich OCR output over whitespace or page noise."""
    useful = sum(character.isalnum() for character in text)
    return useful, len(text.strip())


async def _parse_fields_with_gemini(
    data: bytes, mime_type: str, text: str, api_key: str, model: str
) -> dict[str, str]:
    prompt = f"""You are a precise document-understanding system for Indian business documents.
Inspect the attached source document and compare it against the local OCR transcription below.
Extract only values actually present in the document. Prefer the visual document when OCR disagrees.
Return ONLY a JSON object; omit any unknown field. Never invent values.

Allowed keys: invoice_number, gstin, amount, supplier, city, state, contact,
payment_beneficiary, payment_reference_masked, category, source, notes,
business_age_years, quantity, unit_price, payment_method, delivery_days,
delivery_terms, advance_percentage, quote_deviation_percent, missing_information_count.

Rules: amount and unit_price must be numeric strings without currency symbols;
payment_reference_masked must contain only the final four digits when an account number is shown;
supplier is the issuing vendor, not the customer; preserve GSTIN/CIN/PAN exactly.

Local OCR transcription:
{text[:50_000]}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    source_part = {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(data).decode("ascii")}}
    try:
        return await _gemini_json(url, [{"text": prompt}, source_part])
    except Exception:
        # Some Gemini models/accounts do not accept a PDF as inline media. They
        # still get the high-quality local transcription rather than failing OCR.
        return await _gemini_json(url, [{"text": prompt}])


async def _gemini_json(url: str, parts: list[dict]) -> dict[str, str]:
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload)
    response.raise_for_status()
    content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    decoded = json.loads(content)
    if not isinstance(decoded, dict):
        raise ValueError("Gemini did not return a JSON object")
    allowed = {
        "invoice_number", "gstin", "amount", "supplier", "city", "state", "contact",
        "payment_beneficiary", "payment_reference_masked", "category", "source", "notes",
        "business_age_years", "quantity", "unit_price", "payment_method", "delivery_days",
        "delivery_terms", "advance_percentage", "quote_deviation_percent", "missing_information_count",
    }
    return {key: str(value).strip() for key, value in decoded.items() if key in allowed and value is not None and str(value).strip()}
