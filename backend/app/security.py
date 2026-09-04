import hashlib
import mimetypes
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, UploadFile

ALLOWED_DOCUMENT_TYPES = {"application/pdf", "image/png", "image/jpeg"}
MAGIC_BYTES = {"application/pdf": b"%PDF-", "image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}


def opaque_document_path(workspace_id: UUID, supplier_id: UUID | None, document_id: UUID, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return f"workspace/{workspace_id}/supplier/{supplier_id or 'transaction'}/document/{document_id}{suffix}"


async def validate_upload(upload: UploadFile, max_size_mb: int) -> tuple[bytes, str, str]:
    filename = Path(upload.filename or "upload").name
    content = await upload.read()
    if not content or len(content) > max_size_mb * 1024 * 1024:
        raise HTTPException(413, "File is empty or exceeds the configured size limit")
    detected = next((mime for mime, magic in MAGIC_BYTES.items() if content.startswith(magic)), None)
    guessed = mimetypes.guess_type(filename)[0]
    if detected not in ALLOWED_DOCUMENT_TYPES or (guessed and guessed != detected):
        raise HTTPException(415, "Only validated PDF, PNG, and JPEG documents are accepted")
    return content, filename, detected


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
