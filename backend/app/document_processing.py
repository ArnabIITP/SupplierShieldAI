import re
from dataclasses import dataclass
from io import BytesIO

import fitz
import pytesseract
from PIL import Image

import shutil
tesseract_path = shutil.which('tesseract') or r'C:\Users\arnab\scoop\apps\tesseract\current\tesseract.exe'
pytesseract.pytesseract.tesseract_cmd = tesseract_path


@dataclass(frozen=True)
class Extraction:
    text: str
    fields: dict[str, str]


import asyncio
import json
import httpx
from .config import get_settings

async def extract_document(data: bytes, mime_type: str) -> Extraction:
    # 1. Extract raw text using PyMuPDF (PDFs) or Tesseract (Images)
    if mime_type == "application/pdf":
        def read_pdf():
            with fitz.open(stream=data, filetype="pdf") as document:
                return "\n".join(page.get_text() for page in document)[:50_000]
        text = await asyncio.to_thread(read_pdf)
    else:
        def read_img():
            return pytesseract.image_to_string(Image.open(BytesIO(data)))[:50_000]
        text = await asyncio.to_thread(read_img)

    fields: dict[str, str] = {}
    
    # 2. Use Gemini to intelligently parse fields from the raw text
    settings = get_settings()
    if settings.gemini_api_key and settings.gemini_model:
        prompt = f"""
You are an expert AI parser. I will provide raw text extracted from a business document (invoice/quotation).
Extract the following fields and return ONLY a valid JSON object. No markdown, no backticks.
Keys to extract:
- "invoice_number": String
- "gstin": String (Tax ID, CIN, PAN, etc)
- "amount": String (Just the numeric amount, e.g. "9822.00")
- "supplier": String (Name of the vendor/client issuing the document)
- "city": String
- "state": String
- "contact": String (Email or Phone number)
- "payment_beneficiary": String (Who to pay)
- "payment_reference_masked": String (e.g. last 4 digits of account)
- "category": String (e.g. Electronic Components, Industrial supplies)
- "source": String (e.g. Source of supplier, like 'Tech Expo 2026')
- "notes": String (Any additional notes or context found)
- "business_age_years": Integer (Years in business if mentioned)
- "quantity": String (Total quantity of items if available)
- "unit_price": String (Unit price of primary item if available)
- "payment_method": String (e.g. Bank transfer, Credit Card, Net30)
- "delivery_days": String (e.g. 7, 30 if delivery timeline is mentioned)
- "delivery_terms": String (e.g. Delivered, FOB, CIF)
- "advance_percentage": String (Percentage of advance payment if mentioned, e.g. 100, 50, 0)
- "quote_deviation_percent": String (Percentage deviation from quote if mentioned)
- "missing_information_count": String (Count of missing information if explicitly stated)

If a field is completely missing, omit the key.

Raw Text:
{text}
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0}
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            fields = json.loads(content)
        except Exception as e:
            print(f"Gemini parsing failed, falling back to regex: {e}")
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
