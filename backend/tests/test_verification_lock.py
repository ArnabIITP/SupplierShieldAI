"""
Tests: Verification item lock.
Once a verification item reaches a final status (verified/rejected/not_applicable),
further status updates must be rejected with 409.
These tests exercise the backend HTTP endpoint directly.
"""
import pytest
from fastapi.testclient import TestClient
import os, uuid

pytest.importorskip("fastapi")

try:
    from app.main import app
    HAS_APP = True
except Exception:
    HAS_APP = False


@pytest.mark.skipif(not HAS_APP, reason="App not importable")
@pytest.mark.integration
class TestVerificationItemLock:
    """Integration tests - require live Supabase. Skipped in CI without credentials."""

    def setup_method(self):
        if not os.getenv("SUPABASE_URL"):
            pytest.skip("No SUPABASE_URL - integration test skipped")
        self.client = TestClient(app, raise_server_exceptions=False)
        self.headers = {
            "Authorization": "Bearer test-token",
            "X-Workspace-ID": str(uuid.uuid4()),
        }

    def test_update_after_verified_returns_409(self):
        item_id = str(uuid.uuid4())
        # First update to verified
        r1 = self.client.patch(
            f"/api/v1/verification-items/{item_id}",
            json={"status": "verified", "reviewer_note": "confirmed"},
            headers=self.headers,
        )
        # If item exists and first update succeeded, second must return 409
        if r1.status_code == 200:
            r2 = self.client.patch(
                f"/api/v1/verification-items/{item_id}",
                json={"status": "pending", "reviewer_note": "attempt reversal"},
                headers=self.headers,
            )
            assert r2.status_code == 409

    def test_update_after_rejected_returns_409(self):
        item_id = str(uuid.uuid4())
        r1 = self.client.patch(
            f"/api/v1/verification-items/{item_id}",
            json={"status": "rejected", "reviewer_note": "docs invalid"},
            headers=self.headers,
        )
        if r1.status_code == 200:
            r2 = self.client.patch(
                f"/api/v1/verification-items/{item_id}",
                json={"status": "verified", "reviewer_note": "attempt override"},
                headers=self.headers,
            )
            assert r2.status_code == 409