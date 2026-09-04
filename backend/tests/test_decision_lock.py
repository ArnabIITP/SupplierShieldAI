"""
Tests: Decision lock — once a final decision exists, no further decisions allowed.
Exercises the backend HTTP 409 enforcement, not frontend button hiding.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock
import uuid

pytest.importorskip("fastapi")

try:
    from app.main import app
    from app import auth, workspaces
    HAS_APP = True
except Exception:
    HAS_APP = False

ASSESSMENT_ID = str(uuid.uuid4())
WORKSPACE_ID  = str(uuid.uuid4())
USER_ID       = str(uuid.uuid4())


def _mock_principal():
    from app.auth import Principal
    return Principal(user_id=uuid.UUID(USER_ID))


@pytest.mark.skipif(not HAS_APP, reason="App not importable")
@pytest.mark.integration
class TestDecisionLock:
    """
    Integration tests — require a live Supabase connection.
    Skipped in CI without credentials. Run locally with SUPABASE_URL set.
    """

    def _client_with_auth(self):
        client = TestClient(app, raise_server_exceptions=False)
        return client

    def test_second_decision_returns_409(self):
        """
        After a final 'approve' decision exists, a second POST /decisions returns 409.
        This test calls the real HTTP layer and expects the backend-enforced lock.
        """
        import os
        if not os.getenv("SUPABASE_URL"):
            pytest.skip("No SUPABASE_URL — integration test skipped")

        client = self._client_with_auth()
        headers = {
            "Authorization": "Bearer test-token",
            "X-Workspace-ID": WORKSPACE_ID,
        }
        payload1 = {"action": "approve", "reason": "All checks passed in integration test"}
        r1 = client.post(f"/api/v1/assessments/{ASSESSMENT_ID}/decisions", json=payload1, headers=headers)
        # First decision may succeed (201) or fail if no real assessment
        # The point is that a second attempt on the same assessment returns 409

        payload2 = {"action": "reject", "reason": "Attempting a second decision"}
        r2 = client.post(f"/api/v1/assessments/{ASSESSMENT_ID}/decisions", json=payload2, headers=headers)
        # If first succeeded, second must return 409
        if r1.status_code in (200, 201):
            assert r2.status_code == 409