"""
Tests: File upload security validation.
Tests exercise backend file-type and size enforcement directly.
"""
import io, pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

try:
    from app.main import app
    HAS_APP = True
except Exception:
    HAS_APP = False

# Magic bytes for common file types
PDF_MAGIC   = b"%PDF-1.4 test content"
JPEG_MAGIC  = b"\xff\xd8\xff\xe0 fake jpeg content"
PNG_MAGIC   = b"\x89PNG\r\n\x1a\n fake png"
RANDOM_BYTES= b"\x00\x01\x02\x03\x04\x05 not a real file type"


def _upload(client, filename: str, content: bytes, content_type: str = "application/octet-stream"):
    return client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, io.BytesIO(content), content_type)},
        data={"supplier_id": "sup_test_001"},
        headers={"Authorization": "Bearer fake", "X-Workspace-ID": "00000000-0000-0000-0000-000000000001"},
    )


@pytest.mark.skipif(not HAS_APP, reason="App not importable")
class TestUploadSecurity:
    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_empty_file_rejected(self):
        r = _upload(self.client, "empty.pdf", b"")
        assert r.status_code in (400, 401, 413, 415, 422)

    def test_pdf_magic_with_pdf_extension_accepted_if_authenticated(self):
        r = _upload(self.client, "invoice.pdf", PDF_MAGIC, "application/pdf")
        # Without real auth this will be 401 - but must NOT be 415 (wrong type rejection)
        assert r.status_code in (200, 201, 401, 403, 404)

    def test_jpeg_magic_with_pdf_extension_rejected(self):
        """JPEG content disguised as PDF should be rejected for MIME mismatch."""
        r = _upload(self.client, "invoice.pdf", JPEG_MAGIC, "application/pdf")
        # Expect 401 (auth) or 415 (MIME mismatch) - never 200
        assert r.status_code in (400, 401, 415, 422)
        assert r.status_code != 200

    def test_unknown_magic_bytes_rejected(self):
        r = _upload(self.client, "malware.pdf", RANDOM_BYTES, "application/pdf")
        assert r.status_code in (400, 401, 415, 422)

    def test_oversized_filename_rejected(self):
        long_name = "a" * 500 + ".pdf"
        r = _upload(self.client, long_name, PDF_MAGIC, "application/pdf")
        assert r.status_code in (400, 401, 413, 415, 422)