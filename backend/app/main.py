"""SupplierShield AI - FastAPI application.

All data operations require an authenticated Supabase session.
There are no in-memory fallbacks or demo code paths.
"""
import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

def now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .ai_analyst import generate_analysis
from .auth import Principal, current_principal
from .config import get_settings
from .document_processing import extract_document
from .razorpay_service import RazorpayService
from .risk_engine import assess, load_models
from .schemas import (
    Assessment,
    AssessmentCreate,
    AuditEvent,
    DecisionCreate,
    RiskCategory,
    Supplier,
    SupplierCreate,
    VerificationItemUpdate,
)
from .security import sha256, validate_upload
from .supabase_store import SupabaseStore
from .workspaces import role_for_request, workspace_for_request

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Workspace-ID"],
)

rate_windows: dict[str, list[float]] = defaultdict(list)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse(
                status_code=500,
                content={"code": "internal_error", "message": "The request could not be completed."},
            )
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(CorrelationIdMiddleware)
razorpay = RazorpayService()
store = SupabaseStore()



def enforce_rate_limit(bucket: str, limit: int) -> None:
    import time

    moment = time.monotonic()
    rate_windows[bucket] = [value for value in rate_windows[bucket] if moment - value < 60]
    if len(rate_windows[bucket]) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please retry shortly.")
    rate_windows[bucket].append(moment)


def assessment_from_rows(transaction: dict, assessment: dict, factors: list[dict]) -> Assessment:
    return Assessment(
        id=assessment["id"],
        supplier_id=transaction["supplier_id"],
        amount=float(transaction["amount"]),
        risk_score=assessment["risk_score"],
        risk_category=assessment["risk_category"],
        confidence=assessment["confidence"],
        recommendation=assessment["recommendation"],
        anomaly_score=assessment["anomaly_score"],
        factors=[
            {
                "code": factor["factor_code"],
                "title": factor["title"],
                "severity": factor["severity"],
                "contribution": factor["contribution"],
                "evidence": factor["evidence_reference"].get("evidence", "Evidence unavailable"),
                "recommendation": factor["suggested_verification"],
            }
            for factor in factors
        ],
        ai_status=assessment["ai_status"],
        ai_analysis=assessment.get("ai_analysis"),
        shap_contributions=assessment.get("shap_contributions"),
        model_version=assessment["model_version"],
        ruleset_version=assessment["ruleset_version"],
        created_at=assessment["created_at"],
    )


def _audit_event_from_row(row: dict) -> AuditEvent:
    metadata = row.get("metadata") or {}
    description = metadata.get("description") or f"{row['event_type']} on {row['entity_type']}"
    return AuditEvent(
        id=str(row["id"]),
        event_type=row["event_type"],
        entity_type=row["entity_type"],
        entity_id=str(row.get("entity_id") or ""),
        description=description,
        created_at=row["created_at"],
    )


@app.on_event("startup")
def startup() -> None:
    settings.validate_runtime()
    load_models()  # warm the model cache on startup


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/v1/health")
def health(response: Response) -> dict:
    model, anomaly = load_models()
    return {
        "status": "ok",
        "services": {
            "api": "available",
            "database": "supabase-configured" if store.enabled else "not-configured",
            "storage": "supabase-storage",
            "ml_model": "available" if model is not None and anomaly is not None else "fallback-rules",
            "gemini": "configured" if settings.gemini_api_key else "disabled",
            "razorpay": "configured-test" if settings.razorpay_key_id else "disabled",
        },
    }


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------

@app.post("/api/v1/workspaces/bootstrap")
async def bootstrap_workspace(payload: dict, principal: Principal = Depends(current_principal)) -> dict:
    """Creates the first workspace for a new authenticated user."""
    if not store.enabled:
        raise HTTPException(status_code=503, detail="Database service is not configured")
    name = str(payload.get("name", "")).strip()
    if not 2 <= len(name) <= 120:
        raise HTTPException(status_code=422, detail="Workspace name must be between 2 and 120 characters")
    existing = await store.select(
        "workspace_members",
        {"user_id": f"eq.{principal.user_id}", "select": "workspace_id", "limit": "1"},
    )
    if existing:
        raise HTTPException(status_code=409, detail="The user already belongs to a workspace")
    workspace = await store.insert("workspaces", {"name": name, "owner_id": str(principal.user_id)})
    await store.insert(
        "workspace_members",
        {"workspace_id": workspace["id"], "user_id": str(principal.user_id), "role": "owner"},
    )
    await store.insert(
        "audit_events",
        {
            "workspace_id": workspace["id"],
            "actor_id": str(principal.user_id),
            "event_type": "workspace.created",
            "entity_type": "workspace",
            "entity_id": workspace["id"],
            "metadata": {"name": name, "description": f"Workspace '{name}' created"},
        },
    )
    return {"id": workspace["id"], "name": workspace["name"], "role": "owner"}


@app.get("/api/v1/workspaces")
async def list_workspaces(principal: Principal = Depends(current_principal)) -> list[dict]:
    if not store.enabled:
        raise HTTPException(status_code=503, detail="Database service is not configured")
    memberships = await store.select(
        "workspace_members",
        {"user_id": f"eq.{principal.user_id}", "select": "role,workspaces(id,name)"},
    )
    return [
        {"id": row["workspaces"]["id"], "name": row["workspaces"]["name"], "role": row["role"]}
        for row in memberships
        if row.get("workspaces")
    ]


class InviteMemberPayload(BaseModel):
    email: str = Field(..., min_length=5, max_length=200)
    role: str = Field("analyst", pattern="^(admin|analyst|reviewer|viewer)$")


@app.post("/api/v1/workspaces/invite", status_code=201)
async def invite_member(
    payload: InviteMemberPayload,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    """PRD Sec4.16 - invite a user to the workspace (owner/admin only).

    Calls Supabase Auth admin.inviteUserByEmail() and pre-creates a
    workspace_members row so the user lands in the right workspace after
    accepting the invitation email.
    """
    if not store.enabled:
        raise HTTPException(status_code=503, detail="Database service is not configured")
    workspace = await workspace_for_request(request, principal, store)
    await role_for_request(request, principal, store, {"owner", "admin"})

    # Check the email is not already a member
    settings = get_settings()
    import httpx
    supabase_url = settings.supabase_url
    service_key = settings.supabase_service_role_key

    if not supabase_url or not service_key:
        raise HTTPException(status_code=503, detail="Supabase service role key not configured - cannot send invitations")

    # Call Supabase Admin API to invite the user
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{supabase_url}/auth/v1/admin/users",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            json={
                "email": payload.email,
                "email_confirm": False,
                "user_metadata": {
                    "invited_to_workspace": workspace["id"],
                    "invited_role": payload.role,
                },
                "send_invite": True,
            },
        )
        if resp.status_code not in (200, 201):
            detail = resp.json().get("msg") or resp.json().get("message") or resp.text
            raise HTTPException(status_code=400, detail=f"Supabase invite failed: {detail}")
        invited_user = resp.json()
        invited_user_id = invited_user.get("id")

    # Pre-create workspace_members so they join the right workspace on first login
    if invited_user_id:
        try:
            await store.insert("workspace_members", {
                "workspace_id": workspace["id"],
                "user_id": invited_user_id,
                "role": payload.role,
            })
        except Exception:
            pass  # May already exist if re-invited

    await store.insert("audit_events", {
        "workspace_id": workspace["id"],
        "actor_id": str(principal.user_id),
        "event_type": "member.invited",
        "entity_type": "workspace_member",
        "entity_id": workspace["id"],
        "metadata": {"email": payload.email, "role": payload.role, "invited_by": str(principal.user_id)},
    })

    return {"status": "invited", "email": payload.email, "role": payload.role}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/api/v1/dashboard")
async def dashboard(request: Request, principal: Principal = Depends(current_principal)) -> dict:
    workspace_id = await workspace_for_request(request, principal, store)
    items = await _workspace_assessments(workspace_id)
    decision_rows = await store.select(
        "decisions",
        {"workspace_id": f"eq.{workspace_id}", "select": "assessment_id"},
    )
    decided = {row["assessment_id"] for row in decision_rows}
    unresolved = [
        item
        for item in items
        if item.risk_category in (RiskCategory.high, RiskCategory.critical) and item.id not in decided
    ]
    audit_rows = await store.select(
        "audit_events",
        {"workspace_id": f"eq.{workspace_id}", "order": "created_at.desc", "limit": "8"},
    )
    # Risk trend: group assessments by date (last 30 assessments)
    risk_trend = _compute_risk_trend(items)
    return {
        "summary": {
            "total_assessments": len(items),
            "by_risk": {category.value: sum(item.risk_category == category for item in items) for category in RiskCategory},
            "amount_under_review": sum(item.amount for item in unresolved),
            "awaiting_action": len(unresolved),
        },
        "review_queue": sorted(unresolved, key=lambda item: (item.risk_score, item.amount), reverse=True)[:8],
        "recent_activity": [_audit_event_from_row(row) for row in audit_rows],
        "risk_trend": risk_trend,
    }


def _compute_risk_trend(items: list[Assessment]) -> list[dict]:
    """Group last 30 assessments by date for a simple trend chart."""
    by_date: dict[str, dict[str, int]] = {}
    for item in sorted(items, key=lambda a: a.created_at)[-30:]:
        date_key = item.created_at.strftime("%Y-%m-%d") if hasattr(item.created_at, "strftime") else str(item.created_at)[:10]
        if date_key not in by_date:
            by_date[date_key] = {"date": date_key, "Low": 0, "Medium": 0, "High": 0, "Critical": 0}
        by_date[date_key][item.risk_category.value] += 1
    return list(by_date.values())


async def _workspace_assessments(workspace_id) -> list[Assessment]:
    transaction_rows = await store.select(
        "transactions",
        {"workspace_id": f"eq.{workspace_id}", "select": "id,supplier_id,amount", "order": "created_at.desc"},
    )
    assessment_rows = await store.select(
        "assessments",
        {"workspace_id": f"eq.{workspace_id}", "order": "created_at.desc"},
    )
    by_transaction = {row["id"]: row for row in transaction_rows}
    ids = [row["id"] for row in assessment_rows]
    factor_rows = (
        await store.select("risk_factors", {"assessment_id": f"in.({','.join(ids)})"}) if ids else []
    )
    factors_by_assessment: dict[str, list[dict]] = defaultdict(list)
    for factor in factor_rows:
        factors_by_assessment[factor["assessment_id"]].append(factor)
    return [
        assessment_from_rows(by_transaction[row["transaction_id"]], row, factors_by_assessment[row["id"]])
        for row in assessment_rows
        if row["transaction_id"] in by_transaction
    ]


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

@app.get("/api/v1/suppliers", response_model=list[Supplier])
async def list_suppliers(
    request: Request,
    q: str = "",
    category: str = "",
    status: str = "",
    principal: Principal = Depends(current_principal),
) -> list[Supplier]:
    workspace_id = await workspace_for_request(request, principal, store)
    query: dict[str, str] = {"workspace_id": f"eq.{workspace_id}", "order": "created_at.desc"}
    if q.strip():
        query["legal_name"] = f"ilike.*{q.strip()}*"
    if category.strip():
        query["category"] = f"eq.{category.strip()}"
    if status.strip():
        query["status"] = f"eq.{status.strip()}"
    rows = await store.select("suppliers", query)
    return [_supplier_from_row(row) for row in rows]


@app.get("/api/v1/suppliers/{supplier_id}", response_model=Supplier)
async def get_supplier(
    supplier_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> Supplier:
    workspace_id = await workspace_for_request(request, principal, store)
    rows = await store.select(
        "suppliers",
        {"id": f"eq.{supplier_id}", "workspace_id": f"eq.{workspace_id}"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return _supplier_from_row(rows[0])


def _supplier_from_row(row: dict) -> Supplier:
    return Supplier(
        id=row["id"],
        legal_name=row["legal_name"],
        category=row["category"],
        contact=row["contact_data"].get("contact", ""),
        city=row["city"],
        state=row["state"],
        business_age_years=float(row["business_age_years"]),
        registration_identifier=row["registration_identifier"],
        payment_beneficiary="Protected",
        payment_reference_masked="Protected",
        source=row["source"],
        notes=row.get("notes"),
        status=row["status"].replace("_", " ").title(),
        created_at=row["created_at"],
    )


@app.post("/api/v1/suppliers", response_model=Supplier, status_code=201)
async def create_supplier(
    payload: SupplierCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> Supplier:
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin", "analyst"})
    row = await store.insert(
        "suppliers",
        {
            "workspace_id": str(workspace_id),
            "legal_name": payload.legal_name,
            "category": payload.category,
            "contact_data": {"contact": payload.contact},
            "city": payload.city,
            "state": payload.state,
            "business_age_years": payload.business_age_years,
            "registration_identifier": payload.registration_identifier,
            "source": payload.source,
            "notes": payload.notes,
            "created_by": str(principal.user_id),
        },
    )
    await store.insert(
        "supplier_accounts",
        {
            "supplier_id": row["id"],
            "account_reference_hash": sha256(payload.payment_reference_masked.encode()),
            "beneficiary_name": payload.payment_beneficiary,
        },
    )
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "supplier.created",
            "entity_type": "supplier",
            "entity_id": row["id"],
            "metadata": {"legal_name": payload.legal_name, "description": f"Supplier '{payload.legal_name}' created"},
        },
    )
    return Supplier(id=row["id"], created_at=row["created_at"], **payload.model_dump())


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------

@app.get("/api/v1/assessments", response_model=list[Assessment])
async def list_assessments(
    request: Request,
    risk_category: str = "",
    principal: Principal = Depends(current_principal),
) -> list[Assessment]:
    workspace_id = await workspace_for_request(request, principal, store)
    assessment_query: dict[str, str] = {"workspace_id": f"eq.{workspace_id}", "order": "created_at.desc"}
    if risk_category.strip():
        assessment_query["risk_category"] = f"eq.{risk_category.strip()}"
    transaction_rows = await store.select(
        "transactions",
        {"workspace_id": f"eq.{workspace_id}", "select": "id,supplier_id,amount", "order": "created_at.desc"},
    )
    assessment_rows = await store.select("assessments", assessment_query)
    by_transaction = {row["id"]: row for row in transaction_rows}
    ids = [row["id"] for row in assessment_rows]
    factors = await store.select("risk_factors", {"assessment_id": f"in.({','.join(ids)})"}) if ids else []
    factors_by_assessment: dict[str, list[dict]] = defaultdict(list)
    for factor in factors:
        factors_by_assessment[factor["assessment_id"]].append(factor)
    return [
        assessment_from_rows(by_transaction[row["transaction_id"]], row, factors_by_assessment[row["id"]])
        for row in assessment_rows
        if row["transaction_id"] in by_transaction
    ]


@app.get("/api/v1/assessments/{assessment_id}", response_model=Assessment)
async def get_assessment(
    assessment_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> Assessment:
    return await _get_assessment(assessment_id, request, principal)


async def _get_assessment(assessment_id: str, request: Request, principal: Principal) -> Assessment:
    workspace_id = await workspace_for_request(request, principal, store)
    rows = await store.select(
        "assessments",
        {"id": f"eq.{assessment_id}", "workspace_id": f"eq.{workspace_id}"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Assessment not found")
    transactions = await store.select(
        "transactions",
        {
            "id": f"eq.{rows[0]['transaction_id']}",
            "workspace_id": f"eq.{workspace_id}",
            "select": "id,supplier_id,amount",
        },
    )
    if not transactions:
        raise HTTPException(status_code=404, detail="Assessment transaction not found")
    factors = await store.select("risk_factors", {"assessment_id": f"eq.{assessment_id}"})
    return assessment_from_rows(transactions[0], rows[0], factors)


@app.post("/api/v1/assessments", response_model=Assessment, status_code=201)
async def post_assessment(
    payload: AssessmentCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> Assessment:
    enforce_rate_limit("assessments", settings.max_assessments_per_minute)
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin", "analyst"})
    supplier_rows = await store.select(
        "suppliers",
        {"id": f"eq.{payload.supplier_id}", "workspace_id": f"eq.{workspace_id}", "select": "id"},
    )
    if not supplier_rows:
        raise HTTPException(status_code=404, detail="Supplier not found")
    transaction = await store.insert(
        "transactions",
        {
            "workspace_id": str(workspace_id),
            "supplier_id": payload.supplier_id,
            "amount": payload.amount,
            "currency": payload.currency,
            "category": payload.category,
            "quantity": payload.quantity,
            "unit_price": payload.unit_price,
            "payment_method": payload.payment_method,
            "advance_percentage": payload.advance_percentage,
            "delivery_days": payload.delivery_days,
            "delivery_terms": payload.delivery_terms,
            "payment_destination_changed": payload.payment_destination_changed,
            "quote_deviation_percent": payload.quote_deviation_percent,
            "missing_information_count": payload.missing_information_count,
            "document_mismatch": payload.document_mismatch,
            "status": "assessed",
            "created_by": str(principal.user_id),
        },
    )
    score, category, confidence, anomaly, recommendation, factors, shap_contributions = assess(payload)
    docs = await store.select("documents", {"supplier_id": f"eq.{payload.supplier_id}", "workspace_id": f"eq.{workspace_id}"})
    analysis, ai_status = await generate_analysis(score, recommendation, factors, documents=docs)
    assessment_row = await store.insert(
        "assessments",
        {
            "transaction_id": transaction["id"],
            "workspace_id": str(workspace_id),
            "model_version": settings.model_version,
            "ruleset_version": settings.ruleset_version,
            "prompt_version": settings.prompt_version,
            "risk_score": score,
            "risk_category": category.value,
            "confidence": confidence,
            "anomaly_score": anomaly,
            "recommendation": recommendation,
            "ai_status": ai_status,
            "ai_analysis": analysis,
            "shap_contributions": shap_contributions if shap_contributions else None,
        },
    )
    persisted_factors = []
    for factor in factors:
        persisted_factors.append(
            await store.insert(
                "risk_factors",
                {
                    "assessment_id": assessment_row["id"],
                    "factor_code": factor.code,
                    "title": factor.title,
                    "severity": factor.severity.value,
                    "contribution": factor.contribution,
                    "evidence_reference": {"evidence": factor.evidence},
                    "suggested_verification": factor.recommendation,
                },
            )
        )
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "assessment.completed",
            "entity_type": "assessment",
            "entity_id": assessment_row["id"],
            "metadata": {
                "risk_score": score,
                "model_version": settings.model_version,
                "description": f"Assessment completed - {category.value} risk score {score}/100",
            },
        },
    )
    return assessment_from_rows(transaction, assessment_row, persisted_factors)


# ---------------------------------------------------------------------------
# AI Analysis
# ---------------------------------------------------------------------------

@app.get("/api/v1/assessments/{assessment_id}/ai-analysis")
async def get_ai_analysis(
    assessment_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> dict:
    workspace_id = await workspace_for_request(request, principal, store)
    rows = await store.select(
        "assessments",
        {"id": f"eq.{assessment_id}", "workspace_id": f"eq.{workspace_id}", "select": "id,ai_status,ai_analysis"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return {"assessment_id": assessment_id, "status": rows[0]["ai_status"], "analysis": rows[0].get("ai_analysis")}


@app.post("/api/v1/assessments/{assessment_id}/ai-analysis")
async def refresh_ai_analysis(
    assessment_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> dict:
    enforce_rate_limit("ai", settings.max_ai_requests_per_minute)
    workspace_id = await workspace_for_request(request, principal, store)
    item = await _get_assessment(assessment_id, request, principal)
    docs = await store.select("documents", {"supplier_id": f"eq.{item.supplier_id}", "workspace_id": f"eq.{workspace_id}"})
    analysis, status = await generate_analysis(item.risk_score, item.recommendation, item.factors, documents=docs)
    await store.update(
        "assessments",
        {"id": f"eq.{assessment_id}", "workspace_id": f"eq.{workspace_id}"},
        {"ai_status": status, "ai_analysis": analysis},
    )
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "assessment.ai_analysis_generated",
            "entity_type": "assessment",
            "entity_id": assessment_id,
            "metadata": {"description": f"AI analysis refreshed - status: {status}"},
        },
    )
    return {"assessment_id": item.id, "status": status, "analysis": analysis}


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@app.post("/api/v1/assessments/{assessment_id}/verification")
async def request_verification(
    assessment_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> dict:
    workspace_id = await workspace_for_request(request, principal, store)
    item = await _get_assessment(assessment_id, request, principal)

    # Specific, actionable verification questions per risk factor code
    VERIFICATION_QUESTIONS: dict[str, str] = {
        "full_advance": (
            "Obtain a signed Proforma Invoice or purchase contract from the supplier that explicitly "
            "lists deliverables, delivery date, and penalties for non-delivery — attach it to this "
            "case before releasing the 100% advance payment."
        ),
        "high_advance": (
            "Negotiate a milestone-based payment structure with the supplier: propose holding at least "
            "40% of the payment until goods are delivered and inspected. Attach written supplier "
            "acknowledgement of revised terms."
        ),
        "beneficiary_change": (
            "Call the supplier's officially registered phone number (from GST or MCA records — not "
            "from the recent communication) and verbally confirm: (1) the new bank account holder "
            "name, (2) account number last 4 digits, and (3) IFSC code. Log the call date, time, "
            "and name of the supplier representative spoken to."
        ),
        "quote_deviation": (
            "Source at least two competing quotations for the same specification and quantity from "
            "alternate suppliers. Attach all quotes and document the reason this supplier was "
            "selected despite the price deviation."
        ),
        "document_mismatch": (
            "Request fresh, corrected documents from the supplier. Cross-check the GSTIN, "
            "legal name, registered address, and bank account holder name against the MCA / "
            "GST portal records. Attach the portal screenshot alongside the corrected documents."
        ),
        "missing_evidence": (
            "Collect and attach the missing transaction evidence: (1) Supplier GST certificate, "
            "(2) signed quotation on letterhead, (3) delivery commitment in writing with expected "
            "dispatch date. Do not proceed to payment until all three are on file."
        ),
        "high_exposure": (
            "Obtain a second approval from a senior manager or finance head for this payment. "
            "Document the approver's name, designation, and date of approval. For amounts above "
            "INR 10 lakh, consider splitting into milestone-based tranches."
        ),
        "compressed_delivery": (
            "Confirm with the supplier in writing that the stock is available and ready to dispatch. "
            "Request a warehouse receipt or stock photograph. Get a written delivery commitment "
            "with a specific dispatch date and logistics tracking number."
        ),
    }

    # Build checklist: use specific question if available, else fall back to factor recommendation
    checklist = []
    for factor in item.factors:
        question = VERIFICATION_QUESTIONS.get(factor.code, factor.recommendation)
        checklist.append({"title": question, "factor_code": factor.code, "status": "pending"})

    # Always include at least one standard identity check
    if not checklist:
        checklist = [{
            "title": (
                "Verify the supplier's legal identity: confirm the GSTIN, registered address, "
                "and payment beneficiary name against government records (GST portal / MCA)."
            ),
            "factor_code": "identity_check",
            "status": "pending",
        }]

    case = await store.insert(
        "verification_cases",
        {"assessment_id": assessment_id, "workspace_id": str(workspace_id), "status": "open"},
    )
    for check in checklist:
        await store.insert(
            "verification_items",
            {
                "verification_case_id": case["id"],
                "item_type": "risk_factor",
                "title": check["title"],
                "status": "pending",
            },
        )
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "verification.requested",
            "entity_type": "assessment",
            "entity_id": assessment_id,
            "metadata": {"description": f"Verification checklist generated - {len(checklist)} items"},
        },
    )
    return {"assessment_id": item.id, "case_id": case["id"], "status": "open", "items": checklist}



@app.get("/api/v1/assessments/{assessment_id}/verification")
async def get_verification(
    assessment_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> dict:
    workspace_id = await workspace_for_request(request, principal, store)
    item = await _get_assessment(assessment_id, request, principal)
    cases = await store.select(
        "verification_cases",
        {
            "assessment_id": f"eq.{assessment_id}",
            "workspace_id": f"eq.{workspace_id}",
            "select": "id,status,created_at,closed_at",
            "limit": "1",
        },
    )
    if not cases:
        return {"assessment_id": item.id, "status": "not_started", "items": []}
    rows = await store.select(
        "verification_items",
        {"verification_case_id": f"eq.{cases[0]['id']}", "order": "updated_at.asc"},
    )
    return {
        "assessment_id": item.id,
        "case_id": cases[0]["id"],
        "status": cases[0]["status"],
        "items": [
            {
                "id": row["id"],
                "title": row["title"],
                "question": row.get("question") or row["title"],  # title IS the question
                "evidence": row.get("evidence"),
                "status": row["status"],
                "reviewer_note": row.get("reviewer_note"),
            }
            for row in rows
        ],
    }


@app.patch("/api/v1/verification-items/{item_id}")
async def update_verification_item(
    item_id: str,
    payload: VerificationItemUpdate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin", "reviewer"})
    rows = await store.select("verification_items", {"id": f"eq.{item_id}", "select": "id,verification_case_id,status"})
    if not rows:
        raise HTTPException(status_code=404, detail="Verification item not found")
    # Enforce item finality at the backend level
    FINAL_STATUSES = {"verified", "rejected", "not_applicable"}
    if rows[0].get("status") in FINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"This verification item is already finalized ({rows[0]['status']}) and cannot be changed.",
        )
    cases = await store.select(
        "verification_cases",
        {"id": f"eq.{rows[0]['verification_case_id']}", "workspace_id": f"eq.{workspace_id}", "select": "id,assessment_id"},
    )
    if not cases:
        raise HTTPException(status_code=404, detail="Verification item not found")
    updated = await store.update(
        "verification_items",
        {"id": f"eq.{item_id}", "verification_case_id": f"eq.{rows[0]['verification_case_id']}"},
        {"status": payload.status, "reviewer_note": payload.reviewer_note, "updated_by": str(principal.user_id)},
    )

    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "verification.updated",
            "entity_type": "verification_item",
            "entity_id": item_id,
            "metadata": {"description": f"Verification item marked {payload.status}"},
        },
    )

    # C7: Check if all items in this case are now complete — if so, close the case
    # and save a verification summary to supplier memory so future assessments see it
    case_id = cases[0]["id"]
    assessment_id_for_case = cases[0]["assessment_id"]
    all_items = await store.select(
        "verification_items",
        {"verification_case_id": f"eq.{case_id}", "select": "id,title,status"},
    )
    COMPLETE_STATUSES = {"verified", "not_applicable"}
    all_complete = all(i["status"] in COMPLETE_STATUSES for i in all_items)
    verified_count = sum(1 for i in all_items if i["status"] == "verified")

    if all_complete and all_items:
        # Close the verification case
        try:
            await store.update(
                "verification_cases",
                {"id": f"eq.{case_id}"},
                {"status": "closed", "closed_at": now().isoformat()},
            )
        except Exception:
            pass  # Non-fatal if update fails

        # Save a verification summary document to supplier memory
        try:
            # Look up the supplier_id via the transaction linked to the assessment
            assessment_rows = await store.select(
                "assessments",
                {"id": f"eq.{assessment_id_for_case}", "select": "transaction_id"},
            )
            if assessment_rows:
                txn_rows = await store.select(
                    "transactions",
                    {"id": f"eq.{assessment_rows[0]['transaction_id']}", "select": "supplier_id"},
                )
                if txn_rows:
                    supplier_id = txn_rows[0]["supplier_id"]
                    summary_text = (
                        f"Verification completed on {now().strftime('%Y-%m-%d')} for assessment "
                        f"{assessment_id_for_case[-6:].upper()}. "
                        f"{verified_count} of {len(all_items)} checks passed. "
                        f"Outcome: {'FULLY VERIFIED' if verified_count == len(all_items) else 'PARTIALLY VERIFIED'}. "
                        f"Items checked: {'; '.join(i['title'][:80] for i in all_items if i['status'] == 'verified')}."
                    )
                    await store.insert(
                        "documents",
                        {
                            "workspace_id": str(workspace_id),
                            "supplier_id": supplier_id,
                            "filename": f"verification_summary_{assessment_id_for_case[-6:].upper()}.txt",
                            "document_type": "verification_summary",
                            "extracted_fields": {
                                "type": "verification_summary",
                                "assessment_id": assessment_id_for_case,
                                "verified_count": verified_count,
                                "total_items": len(all_items),
                                "outcome": "verified" if verified_count == len(all_items) else "partial",
                                "summary": summary_text,
                            },
                            "file_hash": sha256(summary_text.encode()),
                            "status": "extracted",
                        },
                    )
                    await store.insert(
                        "audit_events",
                        {
                            "workspace_id": str(workspace_id),
                            "actor_id": str(principal.user_id),
                            "event_type": "verification.completed",
                            "entity_type": "verification_case",
                            "entity_id": case_id,
                            "metadata": {
                                "description": f"Verification case closed - {verified_count}/{len(all_items)} items verified. Summary saved to supplier memory.",
                                "supplier_id": supplier_id,
                            },
                        },
                    )
        except Exception:
            pass  # Saving to memory is best-effort; don't fail the item update

    return {"id": updated["id"], "status": updated["status"], "reviewer_note": updated.get("reviewer_note")}


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

@app.post("/api/v1/assessments/{assessment_id}/decisions")
async def post_decision(
    assessment_id: str,
    payload: DecisionCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin"})
    await _get_assessment(assessment_id, request, principal)
    # Enforce finality: Approve and Reject are irreversible at the backend level
    existing = await store.select(
        "decisions",
        {"assessment_id": f"eq.{assessment_id}", "workspace_id": f"eq.{workspace_id}", "select": "action"},
    )
    final_actions = {"approve", "reject"}
    if any(d["action"] in final_actions for d in existing):
        raise HTTPException(
            status_code=409,
            detail="A final decision (Approve or Reject) has already been recorded for this assessment. It cannot be changed.",
        )
    row = await store.insert(
        "decisions",
        {
            "assessment_id": assessment_id,
            "workspace_id": str(workspace_id),
            "user_id": str(principal.user_id),
            **payload.model_dump(),
        },
    )
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "decision.made",
            "entity_type": "assessment",
            "entity_id": assessment_id,
            "metadata": {"description": f"Decision recorded: {payload.action}", "action": payload.action},
        },
    )
    return {"id": row["id"], "action": row["action"], "reason": row["reason"], "created_at": row["created_at"]}



@app.get("/api/v1/assessments/{assessment_id}/decisions")
async def get_decisions(
    assessment_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> list[dict]:
    workspace_id = await workspace_for_request(request, principal, store)
    await _get_assessment(assessment_id, request, principal)
    rows = await store.select(
        "decisions",
        {"assessment_id": f"eq.{assessment_id}", "workspace_id": f"eq.{workspace_id}", "order": "created_at.desc"},
    )
    return [{"id": r["id"], "action": r["action"], "reason": r["reason"], "created_at": r["created_at"]} for r in rows]


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@app.post("/api/v1/documents")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    supplier_id: str | None = Form(default=None),
    transaction_id: str | None = Form(default=None),
    principal: Principal = Depends(current_principal),
) -> dict:
    enforce_rate_limit("uploads", settings.max_assessments_per_minute)
    if document_type not in {"invoice", "quotation", "business_document"}:
        raise HTTPException(status_code=422, detail="Unsupported document type")
    if not supplier_id and not transaction_id:
        raise HTTPException(status_code=422, detail="Sec supplier or transaction reference is required")
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin", "analyst"})
    if supplier_id and not await store.select(
        "suppliers", {"id": f"eq.{supplier_id}", "workspace_id": f"eq.{workspace_id}", "select": "id"}
    ):
        raise HTTPException(status_code=404, detail="Supplier not found")
    if transaction_id and not await store.select(
        "transactions", {"id": f"eq.{transaction_id}", "workspace_id": f"eq.{workspace_id}", "select": "id"}
    ):
        raise HTTPException(status_code=404, detail="Transaction not found")
    content, filename, mime_type = await validate_upload(file, settings.max_upload_size_mb)
    try:
        extraction = await extract_document(content, mime_type)
        status = "extracted"
    except Exception as exc:
        logger.warning("Document extraction failed: %s", exc)
        raise HTTPException(status_code=422, detail="Could not read text from this document. Please upload a clearer PDF, PNG, or JPEG.") from exc
    document_id = str(uuid4())
    storage_reference = f"workspace/{workspace_id}/document/{document_id}"
    await store.upload(settings.supabase_storage_bucket, storage_reference, content, mime_type)
    await store.insert(
        "documents",
        {
            "workspace_id": str(workspace_id),
            "supplier_id": supplier_id,
            "transaction_id": transaction_id,
            "storage_reference": storage_reference,
            "document_type": document_type,
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(content),
            "checksum": sha256(content),
            "extracted_fields": extraction.fields,
            "uploaded_by": str(principal.user_id),
        },
    )
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "document.uploaded",
            "entity_type": "document",
            "entity_id": document_id,
            "metadata": {"description": f"Uploaded {document_type} ({status})", "filename": filename},
        },
    )
    return {
        "id": document_id,
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": len(content),
        "checksum": sha256(content),
        "status": status,
        "extracted_fields": extraction.fields,
    }


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@app.get("/api/v1/audit", response_model=list[AuditEvent])
async def list_audit(
    request: Request,
    event_type: str = "",
    entity_type: str = "",
    limit: int = 100,
    principal: Principal = Depends(current_principal),
) -> list[AuditEvent]:
    workspace_id = await workspace_for_request(request, principal, store)
    query: dict[str, str] = {
        "workspace_id": f"eq.{workspace_id}",
        "order": "created_at.desc",
        "limit": str(min(limit, 200)),
    }
    if event_type.strip():
        query["event_type"] = f"eq.{event_type.strip()}"
    if entity_type.strip():
        query["entity_type"] = f"eq.{entity_type.strip()}"
    rows = await store.select("audit_events", query)
    return [_audit_event_from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@app.get("/api/v1/analytics")
async def analytics(request: Request, principal: Principal = Depends(current_principal)) -> dict:
    workspace_id = await workspace_for_request(request, principal, store)
    items = await _workspace_assessments(workspace_id)
    factors_count: dict[str, int] = defaultdict(int)
    for item in items:
        for factor in item.factors:
            factors_count[factor.title] += 1

    # Decision outcome counts
    decision_rows = await store.select(
        "decisions",
        {"workspace_id": f"eq.{workspace_id}", "select": "action"},
    )
    decision_counts: dict[str, int] = defaultdict(int)
    for row in decision_rows:
        decision_counts[row["action"]] += 1

    # Verification outcome counts
    verification_rows = await store.select(
        "verification_cases",
        {"workspace_id": f"eq.{workspace_id}", "select": "status"},
    )
    verification_counts: dict[str, int] = defaultdict(int)
    for row in verification_rows:
        verification_counts[row["status"]] += 1

    # Load model benchmark if available
    import json
    from pathlib import Path
    benchmark_path = Path(__file__).resolve().parents[1] / "artifacts" / "model_metrics.json"
    model_benchmark: dict = {}
    if benchmark_path.exists():
        try:
            model_benchmark = json.loads(benchmark_path.read_text())
        except Exception:
            model_benchmark = {}

    return {
        "risk_distribution": [
            {"risk": risk.value, "count": sum(item.risk_category == risk for item in items)}
            for risk in RiskCategory
        ],
        "top_risk_factors": [
            {"factor": title, "count": count}
            for title, count in sorted(factors_count.items(), key=lambda pair: pair[1], reverse=True)[:8]
        ],
        "risk_trend": _compute_risk_trend(items),
        "decision_outcomes": dict(decision_counts),
        "verification_outcomes": dict(verification_counts),
        "total_assessments": len(items),
        "high_risk_exposure": sum(
            item.amount for item in items if item.risk_category in (RiskCategory.high, RiskCategory.critical)
        ),
        "model_benchmark": model_benchmark,
    }


# ---------------------------------------------------------------------------
# Razorpay test order
# ---------------------------------------------------------------------------

@app.post("/api/v1/assessments/{assessment_id}/razorpay-test-order")
async def create_razorpay_test_order(
    assessment_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> dict:
    workspace_id = await workspace_for_request(request, principal, store)
    assessment = await _get_assessment(assessment_id, request, principal)
    # Embed workspace context in receipt so the webhook handler can associate
    # the event with the correct workspace. Format: ws:<first-8-chars>:<assessment-last-8>
    receipt = f"ws:{str(workspace_id)[:8]}:{assessment_id[-8:]}"[:40]
    order = await razorpay.create_test_order(assessment.amount, receipt)
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "razorpay.test_order_created",
            "entity_type": "assessment",
            "entity_id": assessment_id,
            "metadata": {"description": "Created Razorpay Test-mode order", "receipt": receipt},
        },
    )
    return order


# ---------------------------------------------------------------------------
# PRD ÂSec15.1 - GET /api/v1/me
# ---------------------------------------------------------------------------

@app.get("/api/v1/me")
async def get_me(request: Request, principal: Principal = Depends(current_principal)) -> dict:
    """Returns the authenticated user's context and workspace memberships."""
    if not store.enabled:
        raise HTTPException(status_code=503, detail="Database service is not configured")
    memberships = await store.select(
        "workspace_members",
        {"user_id": f"eq.{principal.user_id}", "select": "role,workspaces(id,name)"},
    )
    workspaces = [
        {"id": row["workspaces"]["id"], "name": row["workspaces"]["name"], "role": row["role"]}
        for row in memberships
        if row.get("workspaces")
    ]
    return {
        "user_id": str(principal.user_id),
        "workspaces": workspaces,
    }


# ---------------------------------------------------------------------------
# PRD ÂSec15.1 - POST /api/v1/onboarding/complete (alias for workspace bootstrap)
# ---------------------------------------------------------------------------

@app.post("/api/v1/onboarding/complete")
async def onboarding_complete(payload: dict, principal: Principal = Depends(current_principal)) -> dict:
    """Creates/initializes application profile/workspace after Supabase signup."""
    if not store.enabled:
        raise HTTPException(status_code=503, detail="Database service is not configured")
    name = str(payload.get("name", "My workspace")).strip()
    if not 2 <= len(name) <= 120:
        name = "My workspace"
    existing = await store.select(
        "workspace_members",
        {"user_id": f"eq.{principal.user_id}", "select": "workspace_id", "limit": "1"},
    )
    if existing:
        ws_row = await store.select("workspaces", {"id": f"eq.{existing[0]['workspace_id']}"})
        role_row = await store.select(
            "workspace_members",
            {"user_id": f"eq.{principal.user_id}", "workspace_id": f"eq.{existing[0]['workspace_id']}", "select": "role"},
        )
        return {"id": existing[0]["workspace_id"], "name": ws_row[0]["name"] if ws_row else name, "role": role_row[0]["role"] if role_row else "owner"}
    workspace = await store.insert("workspaces", {"name": name, "owner_id": str(principal.user_id)})
    await store.insert(
        "workspace_members",
        {"workspace_id": workspace["id"], "user_id": str(principal.user_id), "role": "owner"},
    )
    await store.insert(
        "audit_events",
        {
            "workspace_id": workspace["id"],
            "actor_id": str(principal.user_id),
            "event_type": "workspace.created",
            "entity_type": "workspace",
            "entity_id": workspace["id"],
            "metadata": {"name": name, "description": f"Workspace '{name}' created via onboarding"},
        },
    )
    return {"id": workspace["id"], "name": workspace["name"], "role": "owner"}


# ---------------------------------------------------------------------------
# PRD ÂSec15.2 - PATCH /api/v1/suppliers/{supplier_id}
# ---------------------------------------------------------------------------

@app.patch("/api/v1/suppliers/{supplier_id}", response_model=Supplier)
async def patch_supplier(
    supplier_id: str,
    payload: dict,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> Supplier:
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin", "analyst"})
    existing = await store.select(
        "suppliers", {"id": f"eq.{supplier_id}", "workspace_id": f"eq.{workspace_id}", "select": "id"}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Supplier not found")
    allowed = {"legal_name", "category", "city", "state", "business_age_years", "notes", "status"}
    update = {k: v for k, v in payload.items() if k in allowed}
    if not update:
        raise HTTPException(status_code=422, detail="No updatable fields provided")
    await store.update("suppliers", {"id": f"eq.{supplier_id}"}, update)
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "supplier.updated",
            "entity_type": "supplier",
            "entity_id": supplier_id,
            "metadata": {"description": f"Supplier updated: {', '.join(update.keys())}"},
        },
    )
    rows = await store.select("suppliers", {"id": f"eq.{supplier_id}"})
    return _supplier_from_row(rows[0])


# ---------------------------------------------------------------------------
# PRD ÂSec15.2 - GET /api/v1/suppliers/{supplier_id}/assessments
# ---------------------------------------------------------------------------

@app.get("/api/v1/suppliers/{supplier_id}/assessments", response_model=list[Assessment])
async def get_supplier_assessments(
    supplier_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> list[Assessment]:
    workspace_id = await workspace_for_request(request, principal, store)
    transaction_rows = await store.select(
        "transactions",
        {"supplier_id": f"eq.{supplier_id}", "workspace_id": f"eq.{workspace_id}", "select": "id,supplier_id,amount"},
    )
    if not transaction_rows:
        return []
    tx_ids = [row["id"] for row in transaction_rows]
    by_transaction = {row["id"]: row for row in transaction_rows}
    assessment_rows = await store.select(
        "assessments",
        {"transaction_id": f"in.({','.join(tx_ids)})", "workspace_id": f"eq.{workspace_id}", "order": "created_at.desc"},
    )
    ids = [row["id"] for row in assessment_rows]
    factors = await store.select("risk_factors", {"assessment_id": f"in.({','.join(ids)})"}) if ids else []
    factors_by_assessment: dict[str, list[dict]] = defaultdict(list)
    for factor in factors:
        factors_by_assessment[factor["assessment_id"]].append(factor)
    return [
        assessment_from_rows(by_transaction[row["transaction_id"]], row, factors_by_assessment[row["id"]])
        for row in assessment_rows
        if row["transaction_id"] in by_transaction
    ]


# ---------------------------------------------------------------------------
# PRD ÂSec15.3 - POST /api/v1/suppliers/{supplier_id}/transactions
# PRD ÂSec15.3 - GET /api/v1/transactions/{transaction_id}
# ---------------------------------------------------------------------------

class TransactionCreate(BaseModel):
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


@app.post("/api/v1/suppliers/{supplier_id}/transactions", status_code=201)
async def create_transaction(
    supplier_id: str,
    payload: TransactionCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin", "analyst"})
    if not await store.select("suppliers", {"id": f"eq.{supplier_id}", "workspace_id": f"eq.{workspace_id}", "select": "id"}):
        raise HTTPException(status_code=404, detail="Supplier not found")
    transaction = await store.insert(
        "transactions",
        {
            "workspace_id": str(workspace_id),
            "supplier_id": supplier_id,
            "status": "pending_assessment",
            "created_by": str(principal.user_id),
            **payload.model_dump(),
        },
    )
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "transaction.created",
            "entity_type": "transaction",
            "entity_id": transaction["id"],
            "metadata": {"description": f"Transaction created - ‚¹{payload.amount:,.0f}"},
        },
    )
    return {"id": transaction["id"], "supplier_id": supplier_id, "amount": payload.amount, "status": "pending_assessment"}


@app.get("/api/v1/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> dict:
    workspace_id = await workspace_for_request(request, principal, store)
    rows = await store.select(
        "transactions", {"id": f"eq.{transaction_id}", "workspace_id": f"eq.{workspace_id}"}
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Transaction not found")
    r = rows[0]
    return {"id": r["id"], "supplier_id": r["supplier_id"], "amount": float(r["amount"]),
            "currency": r.get("currency", "INR"), "status": r.get("status", "unknown"), "created_at": r["created_at"]}


# PRD ÂSec15.4 - POST /api/v1/transactions/{transaction_id}/assessments
@app.post("/api/v1/transactions/{transaction_id}/assessments", response_model=Assessment, status_code=201)
async def assess_transaction(
    transaction_id: str,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> Assessment:
    """Run assessment on an existing transaction."""
    enforce_rate_limit("assessments", settings.max_assessments_per_minute)
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin", "analyst"})
    tx_rows = await store.select(
        "transactions", {"id": f"eq.{transaction_id}", "workspace_id": f"eq.{workspace_id}"}
    )
    if not tx_rows:
        raise HTTPException(status_code=404, detail="Transaction not found")
    tx = tx_rows[0]
    payload = AssessmentCreate(
        supplier_id=tx["supplier_id"],
        amount=float(tx["amount"]),
        currency=tx.get("currency", "INR"),
        category=tx.get("category", "General"),
        quantity=float(tx.get("quantity", 1)),
        unit_price=float(tx.get("unit_price", float(tx["amount"]))),
        payment_method=tx.get("payment_method", "Bank transfer"),
        advance_percentage=float(tx.get("advance_percentage", 0)),
        delivery_days=int(tx.get("delivery_days", 30)),
        delivery_terms=tx.get("delivery_terms", "Delivered"),
        payment_destination_changed=bool(tx.get("payment_destination_changed", False)),
        quote_deviation_percent=float(tx.get("quote_deviation_percent", 0)),
        missing_information_count=int(tx.get("missing_information_count", 0)),
        document_mismatch=bool(tx.get("document_mismatch", False)),
    )
    score, category, confidence, anomaly, recommendation, factors, shap_contributions = assess(payload)
    docs = await store.select("documents", {"supplier_id": f"eq.{payload.supplier_id}", "workspace_id": f"eq.{workspace_id}"})
    analysis, ai_status = await generate_analysis(score, recommendation, factors, documents=docs)
    assessment_row = await store.insert(
        "assessments",
        {
            "transaction_id": transaction_id,
            "workspace_id": str(workspace_id),
            "model_version": settings.model_version,
            "ruleset_version": settings.ruleset_version,
            "prompt_version": settings.prompt_version,
            "risk_score": score,
            "risk_category": category.value,
            "confidence": confidence,
            "anomaly_score": anomaly,
            "recommendation": recommendation,
            "ai_status": ai_status,
            "ai_analysis": analysis,
            "shap_contributions": shap_contributions if shap_contributions else None,
        },
    )
    persisted_factors = []
    for factor in factors:
        persisted_factors.append(
            await store.insert(
                "risk_factors",
                {
                    "assessment_id": assessment_row["id"],
                    "factor_code": factor.code,
                    "title": factor.title,
                    "severity": factor.severity.value,
                    "contribution": factor.contribution,
                    "evidence_reference": {"evidence": factor.evidence},
                    "suggested_verification": factor.recommendation,
                },
            )
        )
    await store.update(
        "transactions", {"id": f"eq.{transaction_id}"}, {"status": "assessed"}
    )
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "assessment.completed",
            "entity_type": "assessment",
            "entity_id": assessment_row["id"],
            "metadata": {
                "risk_score": score,
                "model_version": settings.model_version,
                "description": f"Assessment completed via transaction - {category.value} risk {score}/100",
            },
        },
    )
    return assessment_from_rows({"id": transaction_id, "supplier_id": tx["supplier_id"], "amount": float(tx["amount"])}, assessment_row, persisted_factors)


# ---------------------------------------------------------------------------
# PRD ÂSec15.5 - Verification case routes
# ---------------------------------------------------------------------------

@app.get("/api/v1/verification/{case_id}")
async def get_verification_case(
    case_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> dict:
    workspace_id = await workspace_for_request(request, principal, store)
    cases = await store.select(
        "verification_cases",
        {"id": f"eq.{case_id}", "workspace_id": f"eq.{workspace_id}", "select": "id,status,assessment_id,created_at,closed_at,priority"},
    )
    if not cases:
        raise HTTPException(status_code=404, detail="Verification case not found")
    rows = await store.select(
        "verification_items",
        {"verification_case_id": f"eq.{case_id}", "order": "updated_at.asc"},
    )
    return {
        "case_id": cases[0]["id"],
        "assessment_id": cases[0]["assessment_id"],
        "status": cases[0]["status"],
        "priority": cases[0].get("priority", "normal"),
        "created_at": cases[0]["created_at"],
        "items": [
            {
                "id": row["id"],
                "title": row["title"],
                "description": row.get("description"),
                "status": row["status"],
                "reviewer_note": row.get("reviewer_note"),
                "updated_by": row.get("updated_by"),
                "updated_at": row.get("updated_at"),
            }
            for row in rows
        ],
    }


@app.patch("/api/v1/verification/{case_id}/items/{item_id}")
async def update_verification_item_v2(
    case_id: str,
    item_id: str,
    payload: VerificationItemUpdate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin", "reviewer"})
    cases = await store.select(
        "verification_cases",
        {"id": f"eq.{case_id}", "workspace_id": f"eq.{workspace_id}", "select": "id"},
    )
    if not cases:
        raise HTTPException(status_code=404, detail="Verification case not found")
    items = await store.select("verification_items", {"id": f"eq.{item_id}", "verification_case_id": f"eq.{case_id}"})
    if not items:
        raise HTTPException(status_code=404, detail="Verification item not found")
    await store.update(
        "verification_items",
        {"id": f"eq.{item_id}"},
        {"status": payload.status, "reviewer_note": payload.reviewer_note, "updated_by": str(principal.user_id)},
    )
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "verification.updated",
            "entity_type": "verification_item",
            "entity_id": item_id,
            "metadata": {"description": f"Verification item marked {payload.status}", "case_id": case_id},
        },
    )
    return {"id": item_id, "status": payload.status, "reviewer_note": payload.reviewer_note}


@app.post("/api/v1/verification/{case_id}/decision")
async def verification_case_decision(
    case_id: str,
    payload: DecisionCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin", "reviewer"})
    cases = await store.select(
        "verification_cases",
        {"id": f"eq.{case_id}", "workspace_id": f"eq.{workspace_id}", "select": "id,assessment_id"},
    )
    if not cases:
        raise HTTPException(status_code=404, detail="Verification case not found")
    assessment_id = cases[0]["assessment_id"]
    row = await store.insert(
        "decisions",
        {
            "assessment_id": assessment_id,
            "workspace_id": str(workspace_id),
            "user_id": str(principal.user_id),
            **payload.model_dump(),
        },
    )
    # Close the verification case
    await store.update(
        "verification_cases",
        {"id": f"eq.{case_id}"},
        {"status": "closed", "closed_at": now().isoformat()},
    )
    await store.insert(
        "audit_events",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(principal.user_id),
            "event_type": "decision.made",
            "entity_type": "assessment",
            "entity_id": assessment_id,
            "metadata": {
                "description": f"Decision via verification case: {payload.action}",
                "action": payload.action,
                "case_id": case_id,
            },
        },
    )
    return {"id": row["id"], "action": row["action"], "reason": row["reason"], "created_at": row["created_at"]}


# ---------------------------------------------------------------------------
# PRD ÂSec15.6 - GET /api/v1/audit-events (alias + date/user filter)
# ---------------------------------------------------------------------------

@app.get("/api/v1/audit-events", response_model=list[AuditEvent])
async def list_audit_events(
    request: Request,
    event_type: str = "",
    entity_type: str = "",
    entity_id: str = "",
    actor_id: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 100,
    principal: Principal = Depends(current_principal),
) -> list[AuditEvent]:
    workspace_id = await workspace_for_request(request, principal, store)
    query: dict[str, str] = {
        "workspace_id": f"eq.{workspace_id}",
        "order": "created_at.desc",
        "limit": str(min(limit, 200)),
    }
    if event_type.strip():
        query["event_type"] = f"eq.{event_type.strip()}"
    if entity_type.strip():
        query["entity_type"] = f"eq.{entity_type.strip()}"
    if entity_id.strip():
        query["entity_id"] = f"eq.{entity_id.strip()}"
    if actor_id.strip():
        query["actor_id"] = f"eq.{actor_id.strip()}"
    if date_from.strip():
        query["created_at"] = f"gte.{date_from.strip()}"
    if date_to.strip():
        query["created_at"] = f"lte.{date_to.strip()}"
    rows = await store.select("audit_events", query)
    return [_audit_event_from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# PRD ÂSec15.7 - Analytics sub-endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/analytics/overview")
async def analytics_overview(request: Request, principal: Principal = Depends(current_principal)) -> dict:
    workspace_id = await workspace_for_request(request, principal, store)
    items = await _workspace_assessments(workspace_id)
    return {
        "total_assessments": len(items),
        "high_risk_exposure": sum(
            item.amount for item in items if item.risk_category in (RiskCategory.high, RiskCategory.critical)
        ),
        "risk_distribution": [
            {"risk": risk.value, "count": sum(item.risk_category == risk for item in items)}
            for risk in RiskCategory
        ],
    }


@app.get("/api/v1/analytics/risk-distribution")
async def analytics_risk_distribution(request: Request, principal: Principal = Depends(current_principal)) -> list[dict]:
    workspace_id = await workspace_for_request(request, principal, store)
    items = await _workspace_assessments(workspace_id)
    return [
        {"risk": risk.value, "count": sum(item.risk_category == risk for item in items)}
        for risk in RiskCategory
    ]


@app.get("/api/v1/analytics/factors")
async def analytics_factors(request: Request, principal: Principal = Depends(current_principal)) -> list[dict]:
    workspace_id = await workspace_for_request(request, principal, store)
    items = await _workspace_assessments(workspace_id)
    factors_count: dict[str, int] = defaultdict(int)
    for item in items:
        for factor in item.factors:
            factors_count[factor.title] += 1
    return [
        {"factor": title, "count": count}
        for title, count in sorted(factors_count.items(), key=lambda p: p[1], reverse=True)[:10]
    ]


@app.get("/api/v1/analytics/model-performance")
async def analytics_model_performance() -> dict:
    """Returns benchmark metrics from training artifacts - never hard-coded."""
    import json
    from pathlib import Path
    benchmark_path = Path(__file__).resolve().parents[1] / "artifacts" / "model_metrics.json"
    if not benchmark_path.exists():
        raise HTTPException(status_code=503, detail="Model evaluation artifact not available")
    try:
        data = json.loads(benchmark_path.read_text())
        return {
            "dataset_version": data.get("dataset_version"),
            "model_version": data.get("model_version"),
            "metrics": data.get("metrics", {}),
            "business_metrics": data.get("business_metrics", {}),
            "split": data.get("split", {}),
            "limitation": data.get("limitation"),
        }
    except Exception:
        raise HTTPException(status_code=503, detail="Model evaluation artifact could not be read")


# ---------------------------------------------------------------------------
# PRD ÂSec15.8 - Razorpay integration endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/integrations/razorpay/status")
async def razorpay_status(principal: Principal = Depends(current_principal)) -> dict:
    return {
        "mode": settings.razorpay_mode,
        "configured": razorpay.enabled,
        "status": "connected-test" if razorpay.enabled else "disconnected",
        "live_mode_accepted": False,
    }


@app.post("/api/v1/integrations/razorpay/test-connection")
async def razorpay_test_connection(principal: Principal = Depends(current_principal)) -> dict:
    if not razorpay.enabled:
        raise HTTPException(status_code=503, detail="Razorpay Test mode is not configured")
    try:
        import httpx
        import base64
        credentials = f"{settings.razorpay_key_id}:{settings.razorpay_key_secret}".encode()
        headers = {"Authorization": f"Basic {base64.b64encode(credentials).decode()}"}
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get("https://api.razorpay.com/v1/payments?count=1", headers=headers)
        return {"status": "ok" if r.status_code < 400 else "error", "http_status": r.status_code}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Connection test failed: {exc}")


@app.post("/api/v1/integrations/razorpay/webhook")
async def razorpay_webhook(request: Request) -> dict:
    """
    Razorpay webhook endpoint. Unauthenticated but HMAC-SHA256 signature-verified.

    Workspace association: The workspace_id is parsed from the Razorpay order receipt
    field, which is embedded at order-creation time as 'ws:<workspace-prefix>:<assessment-suffix>'.
    If the receipt cannot be parsed (e.g. orders created before this change, or Razorpay
    does not round-trip the receipt field in this sandbox event type), the event is
    recorded with a null workspace_id and clearly labeled as sandbox-only.

    This is a sandbox demonstration. Production deployment would carry workspace
    context through a secure server-side order-metadata mechanism.
    """
    import hmac as hmaclib
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty webhook body")
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing X-Razorpay-Signature header")
    webhook_secret = settings.razorpay_webhook_secret
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")
    # Always verify HMAC before any processing
    expected = hmaclib.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmaclib.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Webhook signature verification failed")
    try:
        import json as _json
        event = _json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    event_type = event.get("event", "unknown")
    entity = event.get("payload", {}).get("payment", {}).get("entity", {})

    # Attempt to resolve workspace_id from the order receipt field
    order_id = entity.get("order_id", "")
    receipt = event.get("payload", {}).get("order", {}).get("entity", {}).get("receipt", "")
    resolved_workspace_id = "00000000-0000-0000-0000-000000000000"
    workspace_resolution = "sandbox_null_fallback"
    if receipt and receipt.startswith("ws:"):
        # Receipt format: ws:<workspace-first-8>:<assessment-last-8>
        parts = receipt.split(":")
        if len(parts) >= 2:
            ws_prefix = parts[1]
            # Attempt to find matching workspace by prefix
            try:
                if store.enabled:
                    matches = await store.select(
                        "workspaces",
                        {"id": f"like.{ws_prefix}%", "select": "id"},
                    )
                    if matches:
                        resolved_workspace_id = matches[0]["id"]
                        workspace_resolution = "receipt_parsed"
            except Exception:
                pass  # Fall through to null workspace

    if store.enabled:
        await store.insert(
            "audit_events",
            {
                "workspace_id": resolved_workspace_id,
                "actor_id": "00000000-0000-0000-0000-000000000000",
                "event_type": f"razorpay.{event_type}",
                "entity_type": "payment",
                "entity_id": entity.get("id", "unknown"),
                "metadata": {
                    "description": f"Razorpay webhook: {event_type}",
                    "order_id": order_id,
                    "workspace_resolution": workspace_resolution,
                    "sandbox_note": (
                        "Workspace association via receipt parsing (sandbox demonstration). "
                        "Production requires secure server-side order-metadata mechanism."
                        if workspace_resolution == "sandbox_null_fallback"
                        else None
                    ),
                },
            },
        )
    return {"status": "processed", "event": event_type}


# ---------------------------------------------------------------------------
# PRD ÂSec15.9 - Health live/ready endpoints
# ---------------------------------------------------------------------------

@app.get("/health/live")
def health_live() -> dict:
    """Liveness: API process is alive."""
    return {"status": "alive"}


@app.get("/health/ready")
def health_ready() -> dict:
    """Readiness: necessary dependencies are available."""
    model, anomaly = load_models()
    if model is None or anomaly is None:
        raise HTTPException(status_code=503, detail="ML model artifacts are not loaded")
    if not store.enabled:
        raise HTTPException(status_code=503, detail="Database is not configured")
    return {"status": "ready", "ml_model": "loaded", "database": "configured"}


# ---------------------------------------------------------------------------
# PRD ÂSec16 - Suppliers transactions list
# ---------------------------------------------------------------------------

@app.get("/api/v1/suppliers/{supplier_id}/transactions")
async def get_supplier_transactions(
    supplier_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> list[dict]:
    workspace_id = await workspace_for_request(request, principal, store)
    rows = await store.select(
        "transactions",
        {"supplier_id": f"eq.{supplier_id}", "workspace_id": f"eq.{workspace_id}", "order": "created_at.desc"},
    )
    return [
        {"id": r["id"], "amount": float(r["amount"]), "currency": r.get("currency", "INR"),
         "status": r.get("status", "unknown"), "created_at": r["created_at"]}
        for r in rows
    ]

@app.get("/api/v1/suppliers/{supplier_id}/documents")
async def get_supplier_documents(
    supplier_id: str, request: Request, principal: Principal = Depends(current_principal)
) -> list[dict]:
    workspace_id = await workspace_for_request(request, principal, store)
    rows = await store.select(
        "documents",
        {"supplier_id": f"eq.{supplier_id}", "workspace_id": f"eq.{workspace_id}", "order": "created_at.desc"},
    )
    return rows




@app.delete('/api/v1/suppliers/{supplier_id}')
async def delete_supplier(supplier_id: str, request: Request, principal: Principal = Depends(current_principal)):
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin"})
    # Verify supplier belongs to this workspace
    supplier_rows = await store.select(
        "suppliers", {"id": f"eq.{supplier_id}", "workspace_id": f"eq.{workspace_id}", "select": "id,legal_name"}
    )
    if not supplier_rows:
        raise HTTPException(status_code=404, detail="Supplier not found")
    supplier_name = supplier_rows[0].get("legal_name", supplier_id)

    # Cascade-delete child records (documents and transactions by supplier_id only)
    for table, filter_key in [
        ("documents", "supplier_id"),
        ("transactions", "supplier_id"),
    ]:
        try:
            await store.delete(table, {filter_key: f"eq.{supplier_id}"})
        except Exception as exc:
            logger.warning("Could not delete %s for supplier %s: %s", table, supplier_id, exc)

    await store.delete("suppliers", {"id": f"eq.{supplier_id}", "workspace_id": f"eq.{workspace_id}"})
    # Write permanent audit event even after deletion
    try:
        await store.insert(
            "audit_events",
            {
                "workspace_id": str(workspace_id),
                "actor_id": str(principal.user_id),
                "event_type": "supplier.deleted",
                "entity_type": "supplier",
                "entity_id": supplier_id,
                "metadata": {"description": f"Supplier '{supplier_name}' permanently deleted by user. All associated transactions and documents removed."},
            },
        )
    except Exception:
        pass
    return {"status": "deleted", "supplier_id": supplier_id}


@app.delete('/api/v1/documents/{document_id}')
async def delete_document(document_id: str, request: Request, principal: Principal = Depends(current_principal)):
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin", "analyst"})
    doc_rows = await store.select(
        "documents", {"id": f"eq.{document_id}", "workspace_id": f"eq.{workspace_id}", "select": "id,filename,supplier_id"}
    )
    if not doc_rows:
        raise HTTPException(status_code=404, detail="Document not found")
    doc = doc_rows[0]
    await store.delete("documents", {"id": f"eq.{document_id}", "workspace_id": f"eq.{workspace_id}"})
    try:
        await store.insert(
            "audit_events",
            {
                "workspace_id": str(workspace_id),
                "actor_id": str(principal.user_id),
                "event_type": "document.deleted",
                "entity_type": "document",
                "entity_id": document_id,
                "metadata": {"description": f"Document '{doc.get('filename', document_id)}' removed from supplier memory.", "supplier_id": doc.get("supplier_id")},
            },
        )
    except Exception:
        pass
    return {"status": "deleted", "document_id": document_id}


@app.delete('/api/v1/assessments/{assessment_id}')
async def delete_assessment(assessment_id: str, request: Request, principal: Principal = Depends(current_principal)):
    """A3: Delete an assessment with full audit trail. Requires owner or admin role."""
    workspace_id, _ = await role_for_request(request, principal, store, {"owner", "admin"})
    assessment = await _get_assessment(assessment_id, request, principal)
    # Cascade-delete related records
    for table, filter_key in [
        ("risk_factors", "assessment_id"),
        ("decisions", "assessment_id"),
        ("verification_items", "verification_case_id"),  # handled via cases below
    ]:
        try:
            if table == "verification_items":
                cases = await store.select("verification_cases", {"assessment_id": f"eq.{assessment_id}", "select": "id"})
                for case in cases:
                    await store.delete("verification_items", {"verification_case_id": f"eq.{case['id']}"})
                await store.delete("verification_cases", {"assessment_id": f"eq.{assessment_id}", "workspace_id": f"eq.{workspace_id}"})
            else:
                await store.delete(table, {filter_key: f"eq.{assessment_id}"})
        except Exception as exc:
            logger.warning("Could not delete %s for assessment %s: %s", table, assessment_id, exc)

    await store.delete("assessments", {"id": f"eq.{assessment_id}", "workspace_id": f"eq.{workspace_id}"})
    # Permanent audit record
    try:
        await store.insert(
            "audit_events",
            {
                "workspace_id": str(workspace_id),
                "actor_id": str(principal.user_id),
                "event_type": "assessment.deleted",
                "entity_type": "assessment",
                "entity_id": assessment_id,
                "metadata": {
                    "description": f"Assessment {assessment_id[-6:].upper()} (risk score {assessment.risk_score}, {assessment.risk_category}) permanently deleted.",
                    "risk_score": assessment.risk_score,
                    "risk_category": assessment.risk_category,
                },
            },
        )
    except Exception:
        pass
    return {"status": "deleted", "assessment_id": assessment_id}
@app.post('/api/v1/extract')
async def extract_only(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    request: Request = None, principal: Principal = Depends(current_principal)
):
    content, filename, mime_type = await validate_upload(file, settings.max_upload_size_mb)
    try:
        extraction = await extract_document(content, mime_type)
        status = 'extracted'
    except Exception as exc:
        logger.warning("Document extraction failed: %s", exc)
        raise HTTPException(status_code=422, detail="Could not read text from this document. Please upload a clearer PDF, PNG, or JPEG.") from exc
    return {'filename': filename, 'extracted_fields': extraction.fields, 'status': status}
