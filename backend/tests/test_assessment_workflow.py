from fastapi.testclient import TestClient

from app.main import app


def test_assessment_verification_and_decision_workflow():
    client = TestClient(app)
    supplier = client.get("/api/v1/suppliers").json()[0]
    payload = {
        "supplier_id": supplier["id"],
        "amount": 480000,
        "category": "Industrial supplies",
        "quantity": 800,
        "unit_price": 600,
        "payment_method": "Bank transfer",
        "advance_percentage": 100,
        "delivery_days": 3,
        "delivery_terms": "Advance dispatch",
        "payment_destination_changed": True,
        "quote_deviation_percent": 44,
        "missing_information_count": 3,
        "document_mismatch": True,
    }

    assessment = client.post("/api/v1/assessments", json=payload)
    assert assessment.status_code == 201
    assessment_id = assessment.json()["id"]

    verification = client.post(f"/api/v1/assessments/{assessment_id}/verification")
    assert verification.status_code == 200
    assert verification.json()["items"]
    item_id = verification.json()["items"][0]["id"]
    verification_item = client.patch(f"/api/v1/verification-items/{item_id}", json={"status": "verified", "reviewer_note": "Beneficiary confirmed independently."})
    assert verification_item.status_code == 200
    assert verification_item.json()["status"] == "verified"

    decision = client.post(
        f"/api/v1/assessments/{assessment_id}/decisions",
        json={"action": "maintain_hold", "reason": "Enhanced verification is still required."},
    )
    assert decision.status_code == 200
    assert decision.json()["action"] == "maintain_hold"
