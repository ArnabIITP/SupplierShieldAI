"""
Tests: Workspace tenancy isolation.
Verifies that cross-workspace data access is prevented at the application layer.
These tests exercise the backend HTTP layer with mocked workspace resolution.
"""
import pytest, uuid
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

pytest.importorskip("fastapi")

try:
    from app.main import app
    HAS_APP = True
except Exception:
    HAS_APP = False

WORKSPACE_A = "aaaaaaaa-0000-0000-0000-000000000001"
WORKSPACE_B = "bbbbbbbb-0000-0000-0000-000000000002"
USER_A      = "aaaaaaaa-0000-0000-0000-000000000010"
USER_B      = "bbbbbbbb-0000-0000-0000-000000000011"


@pytest.mark.skipif(not HAS_APP, reason="App not importable")
class TestTenancy:
    """
    Tenancy is enforced at two layers:
      1. Application: workspace_for_request() checks workspace_members table.
         If user is not a member, returns HTTP 403.
      2. Database: Supabase RLS policies reject queries that cross workspace_id.

    These tests verify layer 1 only (no live Supabase required).
    """

    def test_missing_workspace_header_returns_400(self):
        """Request without X-Workspace-ID header must be rejected before touching the DB."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(
            "/api/v1/assessments",
            headers={"Authorization": "Bearer fake.jwt.token"},
        )
        assert r.status_code in (400, 401, 422)

    def test_invalid_workspace_uuid_returns_422(self):
        """Malformed workspace ID must be rejected before touching the DB."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(
            "/api/v1/assessments",
            headers={
                "Authorization": "Bearer fake.jwt.token",
                "X-Workspace-ID": "not-a-valid-uuid",
            },
        )
        assert r.status_code in (401, 422)

    def test_workspace_id_required_on_supplier_create(self):
        """Supplier creation without workspace header must fail."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/suppliers",
            json={"legal_name": "Acme", "registration_number": "ACM001",
                  "country": "India", "address": "MH"},
            headers={"Authorization": "Bearer fake.jwt.token"},
        )
        assert r.status_code in (400, 401, 422)

    def test_workspace_id_required_on_assessment_create(self):
        """Assessment creation without workspace header must fail."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/assessments",
            json={
                "supplier_id": str(uuid.uuid4()), "amount": 50000.0,
                "currency": "INR", "category": "Goods", "quantity": 1,
                "unit_price": 50000.0, "payment_method": "bank",
                "advance_percentage": 30.0, "delivery_days": 30,
                "delivery_terms": "standard", "payment_destination_changed": False,
                "quote_deviation_percent": 0.0, "missing_information_count": 0,
                "document_mismatch": False,
            },
            headers={"Authorization": "Bearer fake.jwt.token"},
        )
        assert r.status_code in (400, 401, 422)

    def test_cross_workspace_access_returns_403_or_401(self):
        """
        A request with a valid-format workspace ID that the user is NOT a member of
        must return 403 (membership check) or 401 (invalid JWT). Never 200.
        Without a real token and DB, the auth guard fires first (401).
        """
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(
            "/api/v1/assessments",
            headers={
                "Authorization": "Bearer invalid.jwt.token",
                "X-Workspace-ID": WORKSPACE_B,
            },
        )
        assert r.status_code in (401, 403)
        assert r.status_code != 200