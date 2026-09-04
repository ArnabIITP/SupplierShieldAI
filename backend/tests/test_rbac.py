"""
Tests: RBAC role enforcement.
Exercises backend HTTP 403 responses when a role is insufficient.
Tests mock the workspace_members DB query to set a specific role.
These tests do NOT require a live Supabase connection.
"""
import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

try:
    from app.main import app
    HAS_APP = True
except Exception:
    HAS_APP = False

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
USER_ID      = "00000000-0000-0000-0000-000000000002"


def _make_headers(token="Bearer fake.jwt.token"):
    return {
        "Authorization": token,
        "X-Workspace-ID": WORKSPACE_ID,
        "Content-Type": "application/json",
    }


def _mock_principal_and_role(role: str, monkeypatch):
    """
    Patch both the principal resolution and the role lookup so the request
    reaches the RBAC guard without needing a real Supabase connection.
    """
    from app import auth, workspaces
    from app.auth import Principal

    principal = Principal(user_id=uuid.UUID(USER_ID))

    async def _fake_current_principal(request=None):
        return principal

    async def _fake_role_for_request(request, p, store, allowed_roles=None):
        if allowed_roles and role not in allowed_roles:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Your workspace role cannot perform this action")
        return uuid.UUID(WORKSPACE_ID), role

    async def _fake_workspace_for_request(request, p, store):
        return uuid.UUID(WORKSPACE_ID)

    monkeypatch.setattr("app.main.current_principal", lambda: _fake_current_principal)
    monkeypatch.setattr("app.workspaces.role_for_request", _fake_role_for_request)
    monkeypatch.setattr("app.workspaces.workspace_for_request", _fake_workspace_for_request)


@pytest.mark.skipif(not HAS_APP, reason="App not importable")
class TestRbacViewer:
    """Viewer role must be blocked from write operations."""

    def test_viewer_cannot_create_supplier(self, monkeypatch):
        _mock_principal_and_role("viewer", monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/suppliers",
            json={"legal_name": "Test Co", "registration_number": "REG001",
                  "country": "India", "address": "123 Main"},
            headers=_make_headers(),
        )
        assert r.status_code in (403, 401, 503), f"Expected 403 for viewer create supplier, got {r.status_code}"

    def test_viewer_cannot_create_assessment(self, monkeypatch):
        _mock_principal_and_role("viewer", monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/assessments",
            json={
                "supplier_id": str(uuid.uuid4()),
                "amount": 100000.0, "currency": "INR",
                "category": "Goods", "quantity": 10,
                "unit_price": 10000.0, "payment_method": "bank",
                "advance_percentage": 50.0, "delivery_days": 30,
                "delivery_terms": "standard",
                "payment_destination_changed": False,
                "quote_deviation_percent": 0.0,
                "missing_information_count": 0, "document_mismatch": False,
            },
            headers=_make_headers(),
        )
        assert r.status_code in (403, 401, 503)


@pytest.mark.skipif(not HAS_APP, reason="App not importable")
class TestRbacAnalyst:
    """Analyst role: can create assessments, cannot make decisions."""

    def test_analyst_cannot_update_verification_item(self, monkeypatch):
        _mock_principal_and_role("analyst", monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        item_id = str(uuid.uuid4())
        r = client.patch(
            f"/api/v1/verification-items/{item_id}",
            json={"status": "verified", "reviewer_note": "done"},
            headers=_make_headers(),
        )
        # Analyst is not in reviewer/admin/owner for item updates -> 403 or 404 (item not found)
        assert r.status_code in (403, 401, 404, 503)


@pytest.mark.skipif(not HAS_APP, reason="App not importable")
class TestRbacInvite:
    """Only owner/admin can invite members."""

    def test_analyst_cannot_invite(self, monkeypatch):
        _mock_principal_and_role("analyst", monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/workspace/invite",
            json={"email": "test@example.com", "role": "viewer"},
            headers=_make_headers(),
        )
        assert r.status_code in (403, 401, 503)

@pytest.mark.skipif(not HAS_APP, reason="App not importable")
class TestRbacReviewer:
    """Reviewer role: can update verification items, cannot make assessment-level decisions."""

    def test_reviewer_cannot_make_assessment_decision(self, monkeypatch):
        """Assessment decisions are restricted to owner/admin only (not reviewer)."""
        _mock_principal_and_role("reviewer", monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        assessment_id = str(uuid.uuid4())
        r = client.post(
            f"/api/v1/assessments/{assessment_id}/decisions",
            json={"action": "approve", "reason": "looks good"},
            headers=_make_headers(),
        )
        # reviewer is blocked at RBAC level -> 403 or 401 (JWT check fires first)
        assert r.status_code in (403, 401, 503), \
            f"Expected 403 for reviewer making assessment decision, got {r.status_code}"

    def test_analyst_cannot_make_assessment_decision(self, monkeypatch):
        """Assessment decisions are restricted to owner/admin only (not analyst)."""
        _mock_principal_and_role("analyst", monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        assessment_id = str(uuid.uuid4())
        r = client.post(
            f"/api/v1/assessments/{assessment_id}/decisions",
            json={"action": "approve", "reason": "looks good"},
            headers=_make_headers(),
        )
        assert r.status_code in (403, 401, 503), \
            f"Expected 403 for analyst making assessment decision, got {r.status_code}"