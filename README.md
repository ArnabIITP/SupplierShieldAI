# SupplierShield AI

> **Razorpay AI Buildathon 2026 — Track 02: AI Risk Manager**

SupplierShield is a supplier procurement risk platform for Indian SMEs. It solves one specific problem: businesses pay large advances to unverified suppliers with no structured way to assess risk first.

The product scores each proposed transaction using a three-component risk model (deterministic rules + XGBoost + IsolationForest), surfaces the evidence behind every flag, runs a verification checklist, and produces an append-only audit trail of every decision.

---

## Table of Contents

1. [Problem Being Solved](#1-problem-being-solved)
2. [Buildathon Track 02 Compliance](#2-buildathon-track-02-compliance)
3. [Benchmark Results](#3-benchmark-results)
4. [Architecture](#4-architecture)
5. [Risk Scoring — How It Works](#5-risk-scoring--how-it-works)
6. [Every Page and Feature](#6-every-page-and-feature)
7. [Every API Endpoint](#7-every-api-endpoint)
8. [Security and Access Control](#8-security-and-access-control)
9. [RBAC Permission Matrix](#9-rbac-permission-matrix)
10. [Reproducible Training Pipeline](#10-reproducible-training-pipeline)
11. [Local Setup](#11-local-setup)
12. [Environment Variables](#12-environment-variables)
13. [Razorpay Integration](#13-razorpay-integration)
14. [CI Pipeline](#14-ci-pipeline)
15. [Test Suite](#15-test-suite)
16. [What Was Changed](#16-what-was-changed)
17. [Known Limitations](#17-known-limitations)

---

## 1. Problem Being Solved

Indian SMEs routinely make large upfront payments to suppliers they have never transacted with. Common fraud patterns:
- **Payment destination change** — attacker changes the bank account before payment is released
- **Full advance demand** — fraudulent supplier requests 100% upfront before any delivery
- **Document forgery** — fake GST certificates, PAN cards, delivery confirmations
- **Inflated pricing** — price deviates significantly from reference
- **Unverifiable identity** — business registration details cannot be confirmed

SupplierShield provides a structured workflow that forces the purchaser to collect, review, and record verification evidence before any payment decision. It does not integrate with external APIs (GST portal, MCA, bank APIs).

---

## 2. Buildathon Track 02 Compliance

| Requirement | Implementation |
|---|---|
| Working detector for one class of loss | XGBoost classifier for elevated supplier-payment and procurement risk |
| Measured precision/recall on held-out test set | P=0.732, R=0.772, F1=0.752, ROC-AUC=0.893 |
| Honest metrics including false-positive cost | FP cost = INR 300 + 0.08% of amount (synthetic assumption) |
| Strictly defense-only | Risk flags escalate transactions for human review and hold. The system never executes, captures, or autonomously routes payments. All decisions require human authorization. |
| Reproducible | train.py is fully deterministic from seed |

---

## 3. Benchmark Results

> **SYNTHETIC BENCHMARK DISCLAIMER**
> All metrics are from a synthetic generated dataset. They are NOT real-world fraud detection performance. Cost figures are illustrative estimates — not Indian SME industry data, not Razorpay data, not empirical fraud losses.

### Standard Metrics (held-out test set, single evaluation after all decisions frozen)

| Metric | Value |
|---|---|
| Precision | **0.732** |
| Recall | **0.772** |
| F1 | **0.752** |
| ROC-AUC | **0.893** |
| PR-AUC | **0.825** |
| False Positive Rate | 0.104 |
| False Negative Rate | 0.228 |
| Confusion Matrix | TN=2942, FP=343, FN=277, TP=938 |

### Business Cost Comparison (synthetic assumptions)

| Policy | Total Expected Cost (INR) | Review Rate |
|---|---|---|
| Pass All (Baseline A) | ~78,700,000 | 0% |
| **SupplierShield** | **~13,200,000** | 28.5% |
| Flag All (Baseline B) | ~1,248,000 | 100% |

Cost saved vs Pass-All: **INR 65,574,677** (synthetic assumptions).

### Cost Model (synthetic assumptions)
- FP cost: INR 300 (review labor) + 0.08% of amount (delay opportunity cost)
- FN cost: 35% of transaction amount (expected loss rate)

### Leakage-Prone Baseline v1
Original training used rule-engine-derived labels. ROC-AUC was 0.955 — inflated because the model was copying the rule engine. Retained in `leakage_baseline_metrics.json` as a methodological warning.

---

## 4. Architecture

```
frontend/
  src/pages/            One file per page
  src/types.ts          TypeScript interfaces
  src/styles.css        Primary stylesheet

backend/
  app/
    main.py             FastAPI — 47 routes
    risk_engine.py      Composite scoring pipeline
    schemas.py          Pydantic models
    auth.py             Supabase JWT introspection
    workspaces.py       Workspace resolution + RBAC
    supabase_store.py   httpx Supabase adapter (no ORM)
    ai_analyst.py       Gemini narrative + local fallback
    razorpay.py         Sandbox order creation
    config.py           Pydantic settings

  train.py              Reproducible training pipeline
  artifacts/
    risk_model.joblib       XGBoost (122 KB)
    anomaly_model.joblib    IsolationForest (1.3 MB)
    scaler.joblib           StandardScaler for LogReg baseline
    calibrator.joblib       Isotonic regression calibrator
    train_config.json       All frozen hyperparameter decisions
    model_metrics.json      Final held-out metrics + cost model
    leakage_baseline_metrics.json

  tests/                10 test files (9 in standard run + 1 integration); 33 unit tests pass
.github/workflows/ci.yml
```

---

## 5. Risk Scoring — How It Works

### Component 1: Deterministic Rule Score (max 88 pts)

| Rule | Trigger | Points |
|---|---|---|
| `full_advance` | advance >= 100% | 28 |
| `beneficiary_change` | payment destination changed | 22 |
| `document_mismatch` | document fields inconsistent | 20 |
| `high_advance` | advance >= 60% | 16 |
| `missing_evidence` | missing_count >= 2 | min(18, count×5) |
| `quote_deviation` | \|deviation\| >= 30% | 15 |
| `high_exposure` | amount >= INR 500,000 | 12 |
| `compressed_delivery` | delivery <= 3 days AND amount >= INR 100,000 | 8 |

### Component 2: XGBoost ML Probability

Features: `[amount_log, advance_pct, quote_dev, dest_changed, doc_mismatch, missing_count, delivery_days]`

Isotonic calibration applied (ECE: 0.087 → 0.023).

### Component 3: IsolationForest Anomaly Signal (0–100)

```
raw   = -IsolationForest.score_samples(features)
t     = 80th percentile of raw on training data (0.5225)
s     = 95th − 80th percentile (0.0605)
anomaly = clip((raw − t) / s × 100, 0, 100)
```

t and s loaded from `train_config.json` — not hardcoded.

### Composite Formula

```
score = max(8, min(100, round(rule × 0.45 + ml_prob × 100 × 0.45 + anomaly × 0.10)))
score = max(8, score − min(8, prior_verified_count × 3))
```

Weights selected by minimum validation expected cost. Loaded from `train_config.json`.

### Risk Bands

| Band | Score | Recommendation |
|---|---|---|
| Low | 0–29 | Proceed with standard controls |
| Medium | 30–59 | Request verification |
| High | 60–79 | Hold pending enhanced verification |
| Critical | 80–100 | Hold pending enhanced verification |


The classification threshold (score >= 25 = flagged) is independent of these display bands. Scores in the 25-29 range are presented as Low band but are still flagged for review; the threshold governs the flag decision, the band governs the UI label.

### SHAP

SHAP TreeExplainer runs on XGBoost. Results:
- Shown in UI as bar chart (annotates rule factor evidence strings with ML signal context)
- Returned as `shap_contributions: dict[str, float]` in the API response
- **Never added to the risk score** (shap_score_bonus removed)

### Evidence Coverage

`confidence = min(94, 55 + len(factors) × 7 + (8 if doc_mismatch))` — a heuristic count of evaluated risk signals, **not a calibrated probability**. Previously mislabelled "Confidence" — corrected.

---

## 6. Every Page and Feature

### Dashboard Page

Loaded from live API — no hardcoded values.
- **Assessments summary** — total count, breakdown by risk category
- **Recent activity** — last 10 audit events
- **AI status distribution** — ai_generated / local_fallback / error / pending (human-readable labels, fixed from raw enum)
- **Quick actions** — "New supplier", "New assessment" navigation buttons

### Suppliers Page

- **Supplier list** — search (name/registration/country), risk badge from latest assessment
- **New Supplier** button — modal form: Legal Name, Registration Number, Country, Address, Contact Name, Email, Phone, GST, PAN, MSME
- **Supplier detail** — Overview tab, Documents tab, Assessments tab
  - **Documents** — upload (PDF/JPEG/PNG ≤10 MB, magic bytes validated), delete (with confirmation, loading state, error handling)
  - **Delete supplier** — owner/admin only, with confirmation

### Assessments Page

- **Filter** — by risk category chips
- **Sort** — date, risk score, evidence coverage
- **Assessment detail**:
  - Risk score dial (0–100, colour-coded by band)
  - Risk category badge
  - **Evidence Coverage (heuristic) N%** — hover tooltip explaining it is not a probability
  - Anomaly signal
  - Recommendation
  - **Risk factors** — each shows: title, severity, evidence text (with SHAP ML annotation), verification step, points
  - **Model explanation (XGBoost)** — SHAP bar chart, top 6 features by absolute value, disclaimer
  - **How this score is calculated** — collapsible showing formula and weights
  - **AI risk analysis** — Gemini narrative (Summary, Risk Interpretation, Key Risk Factors, Missing Information, Recommended Actions, Uncertainty, Disclaimer). Refresh button (rate-limited).
  - **Request Verification** — analyst/admin/owner. Disabled if case exists or decision made.
  - **Decision panel** — Approve/Reject (owner/admin). HTTP 409 enforced on server if already decided.

### Verification Page

- **Case list** — all open and closed cases
- **Case detail**:
  - Linked assessment and supplier
  - **Verification items** — each: title, status (pending/verified/rejected/not_applicable), reviewer note, timestamp
  - **Update item status** — reviewer/admin/owner. HTTP 409 on server if item already finalised.
  - **Case decision** — approve/reject/maintain_hold (owner/admin)

### Analytics Page

- Overview stats, risk distribution, factor frequency, model performance
- All data from live API. `model_metrics.json` read at runtime — no frontend hardcoding.
- Model performance panel includes cost model disclaimer on every render.

### Audit Page

Complete append-only event log. Every write operation creates an audit event automatically.

### Integrations Page

- Razorpay connection status and key prefix
- **Test connection** button — live API call
- **Create test order (sandbox)** — from assessment detail (previously mislabelled "Razorpay section")

---

## 7. Every API Endpoint

All routes require `Authorization: Bearer <jwt>` and `X-Workspace-ID: <uuid>` unless noted.

### Workspace / Auth
| Method | Path | Auth Required | Role |
|---|---|---|---|
| GET | `/api/v1/health` | No | — |
| GET | `/health/live` | No | — |
| GET | `/health/ready` | No | — |
| GET | `/api/v1/me` | Yes | any |
| POST | `/api/v1/workspaces/bootstrap` | Yes | — |
| GET | `/api/v1/workspaces` | Yes | any |
| POST | `/api/v1/workspaces/invite` | Yes | owner/admin |
| POST | `/api/v1/onboarding/complete` | Yes | any |

### Suppliers
| Method | Path | Role |
|---|---|---|
| GET | `/api/v1/suppliers` | any |
| GET | `/api/v1/suppliers/{id}` | any |
| POST | `/api/v1/suppliers` | analyst+ |
| PATCH | `/api/v1/suppliers/{id}` | analyst+ |
| DELETE | `/api/v1/suppliers/{id}` | owner/admin |
| GET | `/api/v1/suppliers/{id}/assessments` | any |
| GET | `/api/v1/suppliers/{id}/transactions` | any |
| GET | `/api/v1/suppliers/{id}/documents` | any |

### Assessments
| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/api/v1/assessments` | any | |
| GET | `/api/v1/assessments/{id}` | any | includes shap_contributions |
| POST | `/api/v1/assessments` | analyst+ | runs full risk engine |
| DELETE | `/api/v1/assessments/{id}` | owner/admin | |
| GET | `/api/v1/assessments/{id}/ai-analysis` | any | |
| POST | `/api/v1/assessments/{id}/ai-analysis` | any | rate-limited |
| POST | `/api/v1/assessments/{id}/verification` | analyst+ | |
| GET | `/api/v1/assessments/{id}/verification` | any | |
| POST | `/api/v1/assessments/{id}/decisions` | owner/admin | HTTP 409 if decision exists |
| GET | `/api/v1/assessments/{id}/decisions` | any | |
| POST | `/api/v1/assessments/{id}/razorpay-test-order` | analyst+ | |

### Verification
| Method | Path | Role | Notes |
|---|---|---|---|
| PATCH | `/api/v1/verification-items/{id}` | reviewer+ | HTTP 409 if already finalised |
| GET | `/api/v1/verification/{case_id}` | any | |
| PATCH | `/api/v1/verification/{case_id}/items/{item_id}` | reviewer+ | |
| POST | `/api/v1/verification/{case_id}/decision` | owner/admin | |

### Transactions
| Method | Path | Role |
|---|---|---|
| POST | `/api/v1/suppliers/{id}/transactions` | analyst+ |
| GET | `/api/v1/transactions/{id}` | any |
| POST | `/api/v1/transactions/{id}/assessments` | analyst+ |

### Documents
| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/documents` | Multipart; validates magic bytes |
| DELETE | `/api/v1/documents/{id}` | |

### Analytics / Audit
| Method | Path |
|---|---|
| GET | `/api/v1/analytics` |
| GET | `/api/v1/analytics/overview` |
| GET | `/api/v1/analytics/risk-distribution` |
| GET | `/api/v1/analytics/factors` |
| GET | `/api/v1/analytics/model-performance` |
| GET | `/api/v1/audit` |
| GET | `/api/v1/audit-events` |

### Integrations
| Method | Path | Auth |
|---|---|---|
| GET | `/api/v1/integrations/razorpay/status` | JWT |
| POST | `/api/v1/integrations/razorpay/test-connection` | JWT |
| POST | `/api/v1/integrations/razorpay/webhook` | None (HMAC verified) |

### Utility
| Method | Path |
|---|---|
| POST | `/api/v1/extract` |

---

## 8. Security and Access Control

**Authentication** — every request hits `current_principal()` which calls Supabase Auth live. Invalid/expired tokens → HTTP 401.

**Workspace Isolation** — `workspace_for_request()`:
1. Reads `X-Workspace-ID` header — HTTP 400 if missing, HTTP 422 if malformed
2. Queries `workspace_members` — HTTP 403 if user is not a member
All DB queries include `workspace_id` filter. Supabase RLS provides a second layer.

**Role Enforcement** — `role_for_request(allowed_roles)` returns HTTP 403 if role is insufficient. Role is read from the DB on every request — no caching.

**Decision locks** — server-enforced HTTP 409:
- `POST /decisions` if approve/reject already exists
- `PATCH /verification-items/{id}` if status is already finalised

**Document uploads** — backend validates content-type header, file size, and magic bytes.

**Webhook** — HMAC-SHA256 verification before any processing. Empty body, missing header, or invalid signature → HTTP 400.

**Rate limiting** — in-process sliding window on Gemini AI calls.

---

## 9. RBAC Permission Matrix

| Action | owner | admin | analyst | reviewer | viewer |
|---|:---:|:---:|:---:|:---:|:---:|
| View data | ✓ | ✓ | ✓ | ✓ | ✓ |
| Create supplier / assessment | ✓ | ✓ | ✓ | ✗ | ✗ |
| Edit supplier | ✓ | ✓ | ✓ | ✗ | ✗ |
| Request verification | ✓ | ✓ | ✓ | ✗ | ✗ |
| Upload document | ✓ | ✓ | ✓ | ✗ | ✗ |
| Update verification item | ✓ | ✓ | ✗ | ✓ | ✗ |
| Make case decision | ✓ | ✓ | ✗ | ✓ | ✗ |
| Make assessment decision | ✓ | ✓ | ✗ | ✗ | ✗ |
| Invite members | ✓ | ✓ | ✗ | ✗ | ✗ |
| Delete supplier / assessment | ✓ | ✓ | ✗ | ✗ | ✗ |

---

## 10. Reproducible Training Pipeline

```bash
cd backend && python train.py
```

Steps (all decisions use only train + validation data):
1. Generate 30k-record latent-variable synthetic dataset (seed=42)
2. Generate leakage-prone baseline (v1, comparison only)
3. 70/15/15 stratified split
4. Tune Logistic Regression on validation (C candidates)
5. Tune XGBoost on validation (grid search)
6. Select IsolationForest contamination from [0.05,0.10,0.15,0.20] by validation cost
7. Select weight configuration from 4 candidates by validation cost
8. Select classification threshold (25–70, step 5) by validation cost
9. Optional calibration (60/40 validation split for fit/eval — ECE 0.087→0.023, **applied**)
10. Save `train_config.json` — all decisions frozen
11. Run **single** held-out evaluation
12. Save `model_metrics.json`

The held-out test set is never used to tune any decision. Modifying train.py and re-running to improve test metrics invalidates the held-out guarantee.

---

## 11. Local Setup

```bash
# Backend
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python train.py              # optional — artifacts included
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Tests (no Supabase needed)
python -m pytest tests/ -v -m "not integration"

# Frontend
cd frontend && npm install && npm run dev
```

---

## 12. Environment Variables

```bash
# backend/.env
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
GEMINI_API_KEY=              # optional
GEMINI_MODEL=gemini-3.6-flash
RAZORPAY_KEY_ID=             # optional
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=

# frontend/.env.local
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_API_URL=http://127.0.0.1:8000
```

---

## 13. Razorpay Integration

**What is implemented (sandbox only):**
- Test-mode order creation from any assessment
- Order receipt embeds workspace prefix: `ws:<ws-8chars>:<assessment-8chars>`
- Webhook receives payment events — HMAC-SHA256 verified before processing
- Webhook parses workspace from receipt field; falls back to null UUID with documentation
- Live connectivity test endpoint

**What is NOT implemented:**
- Live payment processing
- Automated payment blocking based on risk score
- Production-grade workspace association

---

## 14. CI Pipeline

`.github/workflows/ci.yml` — runs on push/PR to main:
1. Python 3.11 → install deps → `ruff check backend/app`
2. `pytest tests/ -m "not integration"` (no Supabase)
3. Node 22 → `npm ci` → `npm run build` (must exit 0)

---

## 15. Test Suite

**33 passed, 28 skipped, 3 deselected, 0 failed**

Skipped tests require a live Supabase connection (integration tests). Deselected = integration-marked tests excluded by `-m "not integration"`.

Run command: `python -m pytest tests/ -m "not integration" -q`

| File | Coverage |
|---|---|
| `test_risk_engine.py` | Every rule boundary, score floor/cap, bands, SHAP return |
| `test_auth.py` | 401 on bad tokens, 400 on missing workspace |
| `test_rbac.py` | 403 on insufficient role; reviewer/analyst blocked from assessment decisions |
| `test_tenancy.py` | 400/422/403 on workspace violations |
| `test_decision_lock.py` | HTTP 409 on duplicate decision |
| `test_verification_lock.py` | HTTP 409 on finalised item update |
| `test_gemini_fallback.py` | local_explanation structure and completeness |
| `test_razorpay_webhook.py` | HMAC validation paths |
| `test_upload_security.py` | Magic bytes, empty file, long filename |

---

## 16. What Was Changed

### New Files Added

| File | Description |
|---|---|
| `backend/train.py` | Reproducible training pipeline |
| `backend/artifacts/train_config.json` | Frozen hyperparameter decisions |
| `backend/artifacts/model_metrics.json` | Final metrics + cost model |
| `backend/artifacts/scaler.joblib` | StandardScaler (LogReg baseline) |
| `backend/artifacts/calibrator.joblib` | Isotonic regression calibrator |
| `backend/artifacts/leakage_baseline_metrics.json` | v1 leakage baseline |
| `backend/tests/conftest.py` | pytest integration marker |
| `backend/tests/test_auth.py` | Auth failure tests |
| `backend/tests/test_rbac.py` | RBAC role tests |
| `backend/tests/test_tenancy.py` | Workspace isolation tests |
| `backend/tests/test_risk_engine.py` | 31 risk engine tests |
| `backend/tests/test_decision_lock.py` | HTTP 409 decision lock |
| `backend/tests/test_verification_lock.py` | HTTP 409 item lock |
| `backend/tests/test_gemini_fallback.py` | Gemini fallback tests |
| `backend/tests/test_razorpay_webhook.py` | Webhook HMAC tests |
| `backend/tests/test_upload_security.py` | Upload security tests |
| `.github/workflows/ci.yml` | GitHub Actions CI |

### Modified Files

| File | Change |
|---|---|
| `backend/artifacts/risk_model.joblib` | Retrained on latent-variable v2 dataset |
| `backend/artifacts/anomaly_model.joblib` | Retrained with new contamination selection |
| `backend/app/risk_engine.py` | Removed SHAP score bonus; weights from train_config.json; anomaly params from train_config.json; returns 7-tuple with shap_contributions |
| `backend/app/schemas.py` | Added `shap_contributions: dict[str,float] | None` to Assessment |
| `backend/app/main.py` | Both assess() calls unpack 7-tuple + persist shap_contributions; assessment_from_rows passes shap_contributions; Razorpay order receipt embeds workspace; webhook parses workspace from receipt + validates empty body/missing header |
| `frontend/src/types.ts` | Added `shap_contributions?: Record<string,number> | null` |
| `frontend/src/pages/AssessmentsPage.tsx` | "Confidence" → "Evidence Coverage (heuristic)" with tooltip; SHAP bar chart panel; score formula collapsible |
| `frontend/src/styles.css` | SHAP bar CSS + score formula CSS |
| `README.md` | Complete rewrite |

### Security Fixes (previous session, preserved)

| Change | Effect |
|---|---|
| `POST /decisions` — HTTP 409 if final decision exists | Decision lock enforced at API layer |
| `PATCH /verification-items/{id}` — HTTP 409 if finalised | Item lock enforced at API layer |

---

## 17. Known Limitations

1. **Synthetic benchmark.** Labels come from generated data. Real-world performance unknown.
2. **Cost model is illustrative.** Figures are synthetic assumptions, not industry data.
3. **Evidence Coverage is a heuristic.** Not a calibrated probability.
4. **SHAP explains XGBoost only.** Does not explain rule score, anomaly, or composite score.
5. **No external verification APIs.** No GST portal, MCA, or bank API integration.
6. **Gemini is optional.** Local fallback fires on any error.
7. **Razorpay webhook workspace association is sandbox-grade.**
8. **Rate limiting is in-process.** Resets on server restart; not distributed.
9. **Auth is live on every request.** No token caching.
10. **Audit trail is not cryptographically sealed.** Append-only at application layer only.
