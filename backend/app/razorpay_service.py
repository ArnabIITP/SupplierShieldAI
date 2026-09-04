"""Optional Razorpay Test-mode adapter.

SupplierShield does not initiate or block payments. This service only creates
test orders and normalizes read-only/test integration results.
"""
import base64

import httpx
from fastapi import HTTPException

from .config import get_settings


class RazorpayService:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.razorpay_mode == "test" and bool(self.settings.razorpay_key_id and self.settings.razorpay_key_secret)

    def _headers(self) -> dict[str, str]:
        credentials = f"{self.settings.razorpay_key_id}:{self.settings.razorpay_key_secret}".encode()
        return {"Authorization": f"Basic {base64.b64encode(credentials).decode()}", "Content-Type": "application/json"}

    async def create_test_order(self, amount_inr: float, receipt: str) -> dict:
        if not self.enabled:
            raise HTTPException(status_code=503, detail="Razorpay Test mode is not configured")
        payload = {"amount": round(amount_inr * 100), "currency": "INR", "receipt": receipt[:40]}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post("https://api.razorpay.com/v1/orders", json=payload, headers=self._headers())
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Razorpay Test request failed")
        data = response.json()
        return {"id": data["id"], "amount": data["amount"] / 100, "currency": data["currency"], "status": data["status"], "mode": "test"}
