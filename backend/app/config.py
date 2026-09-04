from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    app_name: str = "SupplierShield"
    app_url: str = "http://localhost:5173"
    api_url: str = "http://localhost:8000"
    cors_allowed_origins: str = "http://localhost:5173"
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_secret_key: str | None = None
    supabase_db_url: str | None = None
    supabase_jwks_url: str | None = None
    supabase_storage_bucket: str = "supplier-documents"
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    razorpay_mode: str = "test"
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None  # PRD Sec14.4 - webhook signature verification
    feature_version: str = "features-v1"  # PRD Sec26 - versioned feature set label
    model_version: str = "supplier-risk-v1"
    ruleset_version: str = "rules-v1"
    prompt_version: str = "prompt-v1"
    max_upload_size_mb: int = 10
    max_ai_requests_per_minute: int = 10
    max_assessments_per_minute: int = 10

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    def validate_runtime(self) -> None:
        missing = []
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        if not (self.supabase_service_role_key or self.supabase_secret_key):
            missing.append("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY")
        if self.app_env == "production":
            if not self.supabase_db_url:
                missing.append("SUPABASE_DB_URL")
            if not self.cors_origins or "*" in self.cors_origins:
                missing.append("CORS_ALLOWED_ORIGINS (specific origins required)")
        if missing:
            raise RuntimeError(f"Required configuration missing: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
