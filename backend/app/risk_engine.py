"""SupplierShield AI - Risk Engine.

PRD Sec10: XGBoost + Isolation Forest + SHAP explainability.
Risk thresholds: Low 0-29, Medium 30-59, High 60-79, Critical 80-100.

Composite score formula (weights loaded from train_config.json):
  raw = rule_score * W_rule + ml_probability * 100 * W_ml + anomaly * W_anomaly
  score = max(8, min(100, round(raw))) - prior_verified_discount

SHAP is used ONLY to explain the XGBoost model probability.
SHAP is NEVER added to the risk score (shap_score_bonus has been removed).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np

from .schemas import AssessmentCreate, RiskCategory, RiskFactor

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"

THRESHOLDS = {
    "low_max": 29,
    "medium_max": 59,
    "high_max": 79,
}

# Fallback weights used ONLY when train_config.json is unavailable.
_FALLBACK_WEIGHTS = {"W_rule": 0.50, "W_ml": 0.40, "W_anomaly": 0.10}
_FALLBACK_THRESHOLD = 50


@lru_cache(maxsize=1)
def _load_train_config() -> dict:
    """Load frozen training configuration from artifacts. Falls back to documented defaults."""
    cfg_path = ARTIFACTS / "train_config.json"
    if not cfg_path.exists():
        import logging
        logging.getLogger(__name__).warning(
            "train_config.json not found. Using fallback weights %s. "
            "Run backend/train.py to generate the configuration.",
            _FALLBACK_WEIGHTS,
        )
        return {}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_weights() -> dict:
    cfg = _load_train_config()
    cs = cfg.get("composite_score", {})
    if cs.get("W_rule") is not None:
        return {
            "W_rule": float(cs["W_rule"]),
            "W_ml": float(cs["W_ml"]),
            "W_anomaly": float(cs["W_anomaly"]),
        }
    return _FALLBACK_WEIGHTS


def _get_anomaly_params() -> tuple[float, float]:
    """Return (t, s) for percentile-based anomaly normalisation."""
    cfg = _load_train_config()
    if_cfg = cfg.get("isolation_forest", {})
    t = float(if_cfg.get("t_param", 0.35))
    s = float(if_cfg.get("s_param", 0.01))
    return t, s


@lru_cache(maxsize=1)
def load_models():
    model_path = ARTIFACTS / "risk_model.joblib"
    anomaly_path = ARTIFACTS / "anomaly_model.joblib"
    if not model_path.exists() or not anomaly_path.exists():
        return None, None
    return joblib.load(model_path), joblib.load(anomaly_path)


@lru_cache(maxsize=1)
def _load_calibrator():
    """Load isotonic calibrator if present. Returns None if not applied during training."""
    cal_path = ARTIFACTS / "calibrator.joblib"
    if not cal_path.exists():
        return None
    try:
        return joblib.load(cal_path)
    except Exception:
        return None


def _risk_category(score: int) -> RiskCategory:
    if score >= 80:
        return RiskCategory.critical
    if score >= 60:
        return RiskCategory.high
    if score >= 30:
        return RiskCategory.medium
    return RiskCategory.low


def feature_vector(payload: AssessmentCreate) -> np.ndarray:
    return np.array([[
        np.log1p(payload.amount),
        payload.advance_percentage,
        payload.quote_deviation_percent,
        int(payload.payment_destination_changed),
        int(payload.document_mismatch),
        payload.missing_information_count,
        payload.delivery_days,
    ]])


FEATURE_NAMES = [
    "amount_log", "advance_pct", "quote_dev", "dest_changed",
    "doc_mismatch", "missing_count", "delivery_days",
]


def assess(
    payload: AssessmentCreate,
) -> tuple[int, RiskCategory, int, int, str, list[RiskFactor], dict[str, float]]:
    """
    Run the full risk assessment pipeline.

    Returns
    -------
    score          : int         final composite score 0-100
    category       : RiskCategory
    confidence     : int         evidence coverage indicator (heuristic, not calibrated probability)
    anomaly        : int         IsolationForest anomaly score 0-100
    recommendation : str
    factors        : list[RiskFactor]
    shap_contributions : dict[str, float]
        SHAP values for the XGBoost model ONLY. These explain the XGBoost
        probability estimate. They do NOT explain the rule score, the anomaly
        signal, or the final composite score.
    """
    factors: list[RiskFactor] = []

    def add(code: str, title: str, severity: RiskCategory, points: int,
            evidence: str, recommendation: str) -> None:
        factors.append(RiskFactor(
            code=code, title=title, severity=severity,
            contribution=points, evidence=evidence, recommendation=recommendation,
        ))

    # Deterministic rule factors
    if payload.advance_percentage >= 100:
        add("full_advance", "100% advance requested", RiskCategory.high, 28,
            "Transaction payment terms",
            "Verify the supplier and payment beneficiary independently before releasing funds.")
    elif payload.advance_percentage >= 60:
        add("high_advance", "High advance requested", RiskCategory.medium, 16,
            "Transaction payment terms",
            "Negotiate milestone-based payment or request additional evidence.")

    if payload.payment_destination_changed:
        add("beneficiary_change", "Payment destination recently changed", RiskCategory.high, 22,
            "Payment destination field",
            "Confirm beneficiary details using an independently sourced contact channel.")

    if abs(payload.quote_deviation_percent) >= 30:
        add("quote_deviation", "Quoted price is outside the reference range", RiskCategory.medium, 15,
            f"Quote deviation: {payload.quote_deviation_percent:.0f}%",
            "Obtain comparable quotes and validate quantity and unit price.")

    if payload.document_mismatch:
        add("document_mismatch", "Supplier information is inconsistent", RiskCategory.high, 20,
            "Supplier and document fields do not match",
            "Request corrected documents and verify registration details.")

    if payload.missing_information_count >= 2:
        add("missing_evidence", "Critical evidence is incomplete", RiskCategory.medium,
            min(18, payload.missing_information_count * 5),
            f"{payload.missing_information_count} required fields are incomplete",
            "Collect the missing business and transaction evidence before payment.")

    if payload.amount >= 500_000:
        add("high_exposure", "Material financial exposure", RiskCategory.medium, 12,
            f"Proposed amount: INR {payload.amount:,.0f}",
            "Escalate the payment for a second review.")

    if payload.delivery_days <= 3 and payload.amount >= 100_000:
        add("compressed_delivery", "Compressed delivery commitment", RiskCategory.medium, 8,
            "Delivery timeline relative to transaction value",
            "Confirm stock availability and delivery terms in writing.")

    rule_score = min(88, sum(item.contribution for item in factors))

    model, anomaly_model = load_models()
    calibrator = _load_calibrator()
    weights = _get_weights()
    t_param, s_param = _get_anomaly_params()
    shap_contributions: dict[str, float] = {}

    if model is not None and anomaly_model is not None:
        vector = feature_vector(payload)
        raw_ml_probability = float(model.predict_proba(vector)[0, 1])
        # Apply isotonic calibrator if it was produced during training (train_config.json
        # records calibration.status). Using calibrated probability matches the training
        # evaluation in train.py and ensures the composite score is consistent.
        if calibrator is not None:
            ml_probability = float(np.clip(calibrator.predict([raw_ml_probability])[0], 0.0, 1.0))
        else:
            ml_probability = raw_ml_probability

        raw_anomaly = float(-anomaly_model.score_samples(vector)[0])
        anomaly = int(np.clip((raw_anomaly - t_param) / s_param * 100, 0, 100))

        # SHAP: explains XGBoost model probability ONLY.
        # SHAP values are NOT added to the final risk score.
        # They annotate rule factor evidence strings and are returned for UI display.
        try:
            import shap
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(vector)
            shap_contributions = {
                name: float(shap_values[0][i])
                for i, name in enumerate(FEATURE_NAMES)
            }
            # Annotate rule factor evidence strings with SHAP signal context
            _SHAP_FACTOR_MAP = {
                "advance_pct": ("full_advance", "high_advance"),
                "dest_changed": ("beneficiary_change",),
                "quote_dev": ("quote_deviation",),
                "doc_mismatch": ("document_mismatch",),
                "missing_count": ("missing_evidence",),
                "amount_log": ("high_exposure",),
                "delivery_days": ("compressed_delivery",),
            }
            for fname, fval in shap_contributions.items():
                codes = _SHAP_FACTOR_MAP.get(fname, ())
                for factor in factors:
                    if factor.code in codes and abs(fval) > 0.1:
                        signal = (
                            "ML model also flags this as a strong risk signal."
                            if fval > 0 else
                            "ML model considers this a moderate concern in context."
                        )
                        factor.evidence = f"{factor.evidence} {signal}"
        except Exception:
            shap_contributions = {}

        # Composite score — SHAP bonus removed; weights from train_config.json
        score = min(100, round(
            rule_score * weights["W_rule"]
            + ml_probability * 100 * weights["W_ml"]
            + anomaly * weights["W_anomaly"]
        ))
    else:
        # Fallback: no ML model available
        anomaly = min(95, int(
            payload.advance_percentage * .3
            + max(0, abs(payload.quote_deviation_percent) - 10) * .35
            + (22 if payload.payment_destination_changed else 0)
        ))
        score = min(100, round(rule_score * .78 + anomaly * .22))

    score = max(8, score)

    # Prior verified-supplier discount (max -8 points)
    prior_verified_count: int = getattr(payload, "prior_verified_count", 0)
    if prior_verified_count > 0:
        score = max(8, score - min(8, prior_verified_count * 3))

    category = _risk_category(score)

    recommendation = (
        "Hold pending enhanced verification"
        if category in (RiskCategory.high, RiskCategory.critical)
        else "Request verification"
        if category == RiskCategory.medium
        else "Proceed with standard controls"
    )

    # Evidence coverage indicator — heuristic based on available risk signals.
    # This is NOT a calibrated probability.
    confidence = min(94, 55 + len(factors) * 7 + (8 if payload.document_mismatch else 0))

    return (
        score, category, confidence, anomaly, recommendation,
        sorted(factors, key=lambda f: f.contribution, reverse=True),
        shap_contributions,
    )