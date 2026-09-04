from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RiskCategory(StrEnum):
    low = "Low"
    medium = "Medium"
    high = "High"
    critical = "Critical"


class SupplierCreate(BaseModel):
    legal_name: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=80)
    contact: str = Field(min_length=3, max_length=160)
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=80)
    business_age_years: float = Field(ge=0, le=100)
    registration_identifier: str = Field(min_length=3, max_length=80)
    payment_beneficiary: str = Field(min_length=2, max_length=160)
    payment_reference_masked: str = Field(min_length=4, max_length=80)
    source: str = Field(min_length=2, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)


class Supplier(SupplierCreate):
    id: str
    status: str = "Active"
    created_at: datetime


class AssessmentCreate(BaseModel):
    supplier_id: str
    amount: float = Field(gt=0, le=100_000_000)
    currency: str = Field(default="INR", pattern="^[A-Z]{3}$")
    category: str = Field(min_length=2, max_length=80)
    quantity: float = Field(gt=0)
    unit_price: float = Field(gt=0)
    payment_method: str = Field(min_length=2, max_length=50)
    advance_percentage: float = Field(ge=0, le=100)
    delivery_days: int = Field(ge=0, le=3650)
    delivery_terms: str = Field(min_length=2, max_length=200)
    payment_destination_changed: bool = False
    quote_deviation_percent: float = Field(default=0, ge=-100, le=1000)
    missing_information_count: int = Field(default=0, ge=0, le=20)
    document_mismatch: bool = False


class RiskFactor(BaseModel):
    code: str
    title: str
    severity: RiskCategory
    contribution: int = Field(ge=0, le=100)
    evidence: str
    recommendation: str


class Assessment(BaseModel):
    id: str
    supplier_id: str
    amount: float
    risk_score: int
    risk_category: RiskCategory
    confidence: int
    recommendation: str
    anomaly_score: int
    factors: list[RiskFactor]
    ai_status: str
    ai_analysis: dict[str, Any] | None = None
    # SHAP contributions for the XGBoost model ONLY.
    # These explain the ML model probability — NOT the rule score, anomaly, or composite score.
    shap_contributions: dict[str, float] | None = None
    model_version: str
    ruleset_version: str
    created_at: datetime


class DecisionCreate(BaseModel):
    action: str = Field(pattern="^(approve|request_information|maintain_hold|reject)$")
    reason: str = Field(min_length=5, max_length=1000)


class VerificationItemUpdate(BaseModel):
    status: str = Field(pattern="^(pending|verified|rejected|not_applicable)$")
    reviewer_note: str | None = Field(default=None, max_length=1000)


class AuditEvent(BaseModel):
    id: str
    event_type: str
    entity_type: str
    entity_id: str
    description: str
    created_at: datetime
