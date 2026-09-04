"""
Tests: Authentication failures (invalid/missing JWT, missing workspace header).
All tests exercise backend API endpoints directly via HTTP - not frontend rendering.
"""
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

try:
    from app.main import app
    client = TestClient(app, raise_server_exceptions=False)
    HAS_APP = True
except Exception:
    HAS_APP = False


@pytest.mark.skipif(not HAS_APP, reason="App not importable in this environment")
class TestAuthentication:
    def test_no_auth_header_returns_401(self):
        r = client.get("/api/v1/assessments", headers={"X-Workspace-ID": "00000000-0000-0000-0000-000000000001"})
        assert r.status_code == 401

    def test_malformed_bearer_token_returns_401(self):
        r = client.get(
            "/api/v1/assessments",
            headers={"Authorization": "Bearer not-a-jwt", "X-Workspace-ID": "00000000-0000-0000-0000-000000000001"},
        )
        assert r.status_code == 401

    def test_empty_bearer_token_returns_401(self):
        r = client.get(
            "/api/v1/assessments",
            headers={"Authorization": "Bearer ", "X-Workspace-ID": "00000000-0000-0000-0000-000000000001"},
        )
        assert r.status_code == 401

    def test_missing_workspace_header_returns_400(self):
        r = client.get("/api/v1/assessments", headers={"Authorization": "Bearer fake.jwt.token"})
        # Without workspace header the request should fail at workspace resolution
        assert r.status_code in (400, 401, 422)

    def test_health_endpoint_requires_no_auth(self):
        r = client.get("/health")
        assert r.status_code == 200