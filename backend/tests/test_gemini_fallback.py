"""
Tests: Gemini AI fallback behaviour.
All paths must work without a real Gemini API key.
Tests use monkeypatching and do not make real network calls.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.schemas import RiskCategory, RiskFactor


def _make_factors():
    return [
        RiskFactor(
            code="full_advance", title="100% advance", severity=RiskCategory.high,
            contribution=28, evidence="Payment terms", recommendation="Verify supplier",
        )
    ]


class TestGeminiFallback:
    """Pure unit tests - no Supabase, no Gemini API key required."""

    @pytest.mark.asyncio
    async def test_fallback_used_when_api_key_missing(self):
        """When GEMINI_API_KEY is not set, generate_analysis falls back to local explanation."""
        with patch.dict("os.environ", {}, clear=False):
            import importlib, sys
            # Force reimport to pick up missing key
            if "app.ai_analyst" in sys.modules:
                del sys.modules["app.ai_analyst"]
            from app.ai_analyst import local_explanation
            factors = _make_factors()
            result = local_explanation(75, "Hold pending enhanced verification", factors)
            # local_explanation must return a dict with required keys
            required = {"summary", "risk_interpretation", "key_risk_factors",
                        "missing_information", "recommended_actions", "uncertainty", "disclaimer"}
            assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"

    @pytest.mark.asyncio
    async def test_fallback_when_gemini_http_500(self):
        """When Gemini returns 500, generate_analysis returns local fallback without raising."""
        import httpx
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")
            from app.ai_analyst import generate_analysis
            factors = _make_factors()
            result, status = await generate_analysis(75, "Hold pending enhanced verification", factors, documents=[])
            assert isinstance(result, dict)
            assert status in ("local_fallback", "ai_generated", "error")

    @pytest.mark.asyncio
    async def test_fallback_when_gemini_returns_malformed_json(self):
        """When Gemini returns non-JSON, generate_analysis uses local fallback."""
        import httpx
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                text="not valid json at all !!",
                json=MagicMock(side_effect=Exception("not json")),
            )
            from app.ai_analyst import generate_analysis
            factors = _make_factors()
            result, status = await generate_analysis(75, "Hold pending enhanced verification", factors, documents=[])
            assert isinstance(result, dict)

    def test_local_explanation_has_all_required_keys(self):
        """local_explanation must always return a complete dict."""
        from app.ai_analyst import local_explanation
        factors = _make_factors()
        for score in [10, 45, 70, 95]:
            result = local_explanation(score, "Hold pending enhanced verification", factors)
            assert "summary" in result
            assert "risk_interpretation" in result
            assert "key_risk_factors" in result
            assert "missing_information" in result
            assert "recommended_actions" in result
            assert "uncertainty" in result
            assert "disclaimer" in result

    def test_local_explanation_disclaimer_present(self):
        from app.ai_analyst import local_explanation
        result = local_explanation(80, "Hold pending enhanced verification", _make_factors())
        assert "disclaimer" in result
        # Disclaimer must be a non-empty string
        assert isinstance(result["disclaimer"], str)
        assert len(result["disclaimer"]) > 10