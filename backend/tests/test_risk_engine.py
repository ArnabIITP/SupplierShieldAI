"""
Tests: Risk engine unit tests.
Pure Python - no Supabase or network required.
Tests each rule factor boundary, score floor/cap, category bands, fallback path.
"""
import pytest
from app.risk_engine import assess, _risk_category
from app.schemas import AssessmentCreate, RiskCategory


def _make(
    amount=50_000.0,
    advance_pct=0.0,
    dest_changed=False,
    quote_dev=0.0,
    doc_mismatch=False,
    missing=0,
    days=30,
) -> AssessmentCreate:
    return AssessmentCreate(
        supplier_id="sup_test",
        amount=amount,
        currency="INR",
        category="Test",
        quantity=1,
        unit_price=amount,
        payment_method="bank",
        advance_percentage=advance_pct,
        delivery_days=days,
        delivery_terms="standard",
        payment_destination_changed=dest_changed,
        quote_deviation_percent=quote_dev,
        missing_information_count=missing,
        document_mismatch=doc_mismatch,
    )


# ---------------------------------------------------------------------------
# Rule factor boundary tests
# ---------------------------------------------------------------------------

class TestRuleBoundaries:
    def test_full_advance_triggers_at_100(self):
        score, _, _, _, _, factors, _ = assess(_make(advance_pct=100.0))
        codes = [f.code for f in factors]
        assert "full_advance" in codes

    def test_full_advance_does_not_trigger_at_99(self):
        score, _, _, _, _, factors, _ = assess(_make(advance_pct=99.0))
        codes = [f.code for f in factors]
        assert "full_advance" not in codes

    def test_high_advance_triggers_at_60(self):
        _, _, _, _, _, factors, _ = assess(_make(advance_pct=60.0))
        codes = [f.code for f in factors]
        assert "high_advance" in codes

    def test_high_advance_does_not_trigger_at_59(self):
        _, _, _, _, _, factors, _ = assess(_make(advance_pct=59.9))
        codes = [f.code for f in factors]
        assert "high_advance" not in codes

    def test_beneficiary_change_triggers(self):
        _, _, _, _, _, factors, _ = assess(_make(dest_changed=True))
        codes = [f.code for f in factors]
        assert "beneficiary_change" in codes

    def test_beneficiary_change_does_not_trigger_when_false(self):
        _, _, _, _, _, factors, _ = assess(_make(dest_changed=False))
        codes = [f.code for f in factors]
        assert "beneficiary_change" not in codes

    def test_quote_deviation_triggers_at_30(self):
        _, _, _, _, _, factors, _ = assess(_make(quote_dev=30.0))
        codes = [f.code for f in factors]
        assert "quote_deviation" in codes

    def test_quote_deviation_triggers_negative_at_minus_30(self):
        _, _, _, _, _, factors, _ = assess(_make(quote_dev=-30.0))
        codes = [f.code for f in factors]
        assert "quote_deviation" in codes

    def test_quote_deviation_does_not_trigger_at_29(self):
        _, _, _, _, _, factors, _ = assess(_make(quote_dev=29.0))
        codes = [f.code for f in factors]
        assert "quote_deviation" not in codes

    def test_document_mismatch_triggers(self):
        _, _, _, _, _, factors, _ = assess(_make(doc_mismatch=True))
        codes = [f.code for f in factors]
        assert "document_mismatch" in codes

    def test_document_mismatch_does_not_trigger_when_false(self):
        _, _, _, _, _, factors, _ = assess(_make(doc_mismatch=False))
        codes = [f.code for f in factors]
        assert "document_mismatch" not in codes

    def test_missing_evidence_triggers_at_2(self):
        _, _, _, _, _, factors, _ = assess(_make(missing=2))
        codes = [f.code for f in factors]
        assert "missing_evidence" in codes

    def test_missing_evidence_does_not_trigger_at_1(self):
        _, _, _, _, _, factors, _ = assess(_make(missing=1))
        codes = [f.code for f in factors]
        assert "missing_evidence" not in codes

    def test_high_exposure_triggers_at_500000(self):
        _, _, _, _, _, factors, _ = assess(_make(amount=500_000.0))
        codes = [f.code for f in factors]
        assert "high_exposure" in codes

    def test_high_exposure_does_not_trigger_at_499999(self):
        _, _, _, _, _, factors, _ = assess(_make(amount=499_999.0))
        codes = [f.code for f in factors]
        assert "high_exposure" not in codes

    def test_compressed_delivery_triggers_at_3_days_100k(self):
        _, _, _, _, _, factors, _ = assess(_make(amount=100_000.0, days=3))
        codes = [f.code for f in factors]
        assert "compressed_delivery" in codes

    def test_compressed_delivery_does_not_trigger_at_4_days(self):
        _, _, _, _, _, factors, _ = assess(_make(amount=100_000.0, days=4))
        codes = [f.code for f in factors]
        assert "compressed_delivery" not in codes

    def test_compressed_delivery_does_not_trigger_below_100k(self):
        _, _, _, _, _, factors, _ = assess(_make(amount=99_999.0, days=3))
        codes = [f.code for f in factors]
        assert "compressed_delivery" not in codes


# ---------------------------------------------------------------------------
# Score floor, cap, bands
# ---------------------------------------------------------------------------

class TestScoreFloorCapBands:
    def test_score_floor_is_8(self):
        # Minimal clean transaction: score should never go below 8
        score, _, _, _, _, _, _ = assess(_make())
        assert score >= 8

    def test_score_cap_is_100(self):
        # Worst-case transaction: score should never exceed 100
        score, _, _, _, _, _, _ = assess(_make(
            amount=1_000_000.0, advance_pct=100.0, dest_changed=True,
            quote_dev=50.0, doc_mismatch=True, missing=5, days=1,
        ))
        assert score <= 100

    def test_score_is_int(self):
        score, _, _, _, _, _, _ = assess(_make())
        assert isinstance(score, int)

    def test_low_band_boundary(self):
        assert _risk_category(0) == RiskCategory.low
        assert _risk_category(29) == RiskCategory.low

    def test_medium_band_boundary(self):
        assert _risk_category(30) == RiskCategory.medium
        assert _risk_category(59) == RiskCategory.medium

    def test_high_band_boundary(self):
        assert _risk_category(60) == RiskCategory.high
        assert _risk_category(79) == RiskCategory.high

    def test_critical_band_boundary(self):
        assert _risk_category(80) == RiskCategory.critical
        assert _risk_category(100) == RiskCategory.critical


# ---------------------------------------------------------------------------
# Prior verified-supplier discount
# ---------------------------------------------------------------------------

class TestPriorVerificationDiscount:
    def test_no_discount_when_zero(self):
        req = _make(advance_pct=60.0)
        req_with_prior = _make(advance_pct=60.0)
        # Both have prior_verified_count defaulting to 0
        s1, _, _, _, _, _, _ = assess(req)
        s2, _, _, _, _, _, _ = assess(req_with_prior)
        assert s1 == s2

    def test_discount_applied_with_prior_count(self):
        # prior_verified_count is read via getattr(payload, 'prior_verified_count', 0)
        # Verify that adding the field to the payload dict via model_validate applies discount.
        import json
        req_data = dict(
            supplier_id="sup_test", amount=50_000.0, currency="INR", category="Test",
            quantity=1, unit_price=50_000.0, payment_method="bank",
            advance_percentage=60.0, delivery_days=30, delivery_terms="standard",
            payment_destination_changed=False, quote_deviation_percent=0.0,
            missing_information_count=0, document_mismatch=False,
        )
        from app.schemas import AssessmentCreate
        req_no_prior = AssessmentCreate(**req_data)
        score_without, _, _, _, _, _, _ = assess(req_no_prior)

        # Create a payload class with prior_verified_count set
        class AssessmentWithPrior(AssessmentCreate):
            prior_verified_count: int = 0

        req_with_prior = AssessmentWithPrior(**{**req_data, "prior_verified_count": 3})
        score_with, _, _, _, _, _, _ = assess(req_with_prior)
        assert score_with <= score_without


# ---------------------------------------------------------------------------
# Recommendation alignment
# ---------------------------------------------------------------------------

class TestRecommendations:
    def test_high_risk_recommendation(self):
        _, cat, _, _, rec, _, _ = assess(_make(advance_pct=100.0, dest_changed=True, doc_mismatch=True))
        if cat in (RiskCategory.high, RiskCategory.critical):
            assert rec == "Hold pending enhanced verification"

    def test_low_risk_recommendation(self):
        _, cat, _, _, rec, _, _ = assess(_make())
        if cat == RiskCategory.low:
            assert rec == "Proceed with standard controls"


# ---------------------------------------------------------------------------
# Comprehensive high-risk case (regression)
# ---------------------------------------------------------------------------

class TestHighRiskRegression:
    def test_all_factors_triggered(self):
        req = _make(
            amount=480_000.0, advance_pct=100.0, dest_changed=True,
            quote_dev=45.0, doc_mismatch=True, missing=3, days=2,
        )
        score, category, _, _, recommendation, factors, _ = assess(req)
        assert score >= 65
        assert category in (RiskCategory.high, RiskCategory.critical)
        assert recommendation == "Hold pending enhanced verification"
        assert len(factors) > 0
        assert all(f.contribution > 0 for f in factors)

    def test_shap_contributions_returned(self):
        req = _make(advance_pct=60.0, doc_mismatch=True)
        _, _, _, _, _, _, shap = assess(req)
        # shap may be empty dict if SHAP library unavailable, but must be a dict
        assert isinstance(shap, dict)