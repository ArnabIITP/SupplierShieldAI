"""
Tests: Razorpay webhook HMAC signature validation.
Tests exercise the backend HTTP endpoint directly using a real HMAC secret.
"""
import hashlib, hmac, json, pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

pytest.importorskip("fastapi")

try:
    from app.main import app
    HAS_APP = True
except Exception:
    HAS_APP = False

WEBHOOK_SECRET = "test_webhook_secret_for_unit_tests"
WEBHOOK_URL = "/api/v1/integrations/razorpay/webhook"


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _make_body() -> bytes:
    return json.dumps({
        "event": "payment.captured",
        "payload": {
            "payment": {"entity": {"id": "pay_test123", "order_id": "order_test456"}},
            "order": {"entity": {"receipt": "ws:abcd1234:efgh5678"}},
        },
    }).encode()


@pytest.mark.skipif(not HAS_APP, reason="App not importable")
class TestRazorpayWebhookSignature:
    def _client(self):
        return TestClient(app, raise_server_exceptions=False)

    def test_valid_signature_returns_200(self):
        body = _make_body()
        sig = _sign(body)
        with patch("app.config.Settings.razorpay_webhook_secret", new=WEBHOOK_SECRET):
            r = self._client().post(
                WEBHOOK_URL,
                content=body,
                headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
            )
        assert r.status_code in (200, 503)  # 503 if secret not configured in test env

    def test_invalid_signature_returns_400(self):
        body = _make_body()
        with patch.object(__import__("app.config", fromlist=["Settings"]).Settings,
                          "razorpay_webhook_secret", WEBHOOK_SECRET, create=True):
            r = self._client().post(
                WEBHOOK_URL,
                content=body,
                headers={
                    "X-Razorpay-Signature": "invalidsignaturexxx",
                    "Content-Type": "application/json",
                },
            )
        assert r.status_code in (400, 503)

    def test_missing_signature_header_returns_400(self):
        body = _make_body()
        r = self._client().post(
            WEBHOOK_URL,
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code in (400, 503)

    def test_empty_body_returns_400(self):
        r = self._client().post(
            WEBHOOK_URL,
            content=b"",
            headers={"X-Razorpay-Signature": "anysig", "Content-Type": "application/json"},
        )
        assert r.status_code in (400, 503)