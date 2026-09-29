"""Settings read from environment variables (docs/outbound/02-ARCHITECTURE.md §6).

Secrets are SecretStr so they never show up in logs or reprs. Trunks and caller IDs are
rows in `sip_trunks`, not settings.
"""

from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def to_async_url(url: str) -> str:
    """Normalize postgres:// / postgresql:// (Railway style) to the asyncpg driver URL."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"

    database_url: str = "postgresql+asyncpg://maria:maria@localhost:5432/maria"
    redis_url: str | None = None

    anthropic_api_key: SecretStr | None = None
    deepgram_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None

    livekit_url: str | None = None
    livekit_api_key: SecretStr | None = None
    livekit_api_secret: SecretStr | None = None
    livekit_agent_name: str = "maria-outbound"

    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None

    internal_api_secret: SecretStr | None = None

    email_provider: str = "resend"
    resend_api_key: SecretStr | None = None
    from_email: str | None = None

    sms_provider: str = "telnyx"
    telnyx_api_key: SecretStr | None = None
    telnyx_messaging_profile_id: str | None = None

    omnicx_base_url: str | None = None
    omnicx_api_key: SecretStr | None = None
    openleads_base_url: str | None = None
    openleads_api_key: SecretStr | None = None

    max_concurrent_calls: int = 10
    default_recording_retention_days: int = 180

    jwt_secret: SecretStr | None = None
    jwt_expire_minutes: int = 720

    # Used only by `python -m app.seed`.
    seed_admin_email: str = "admin@altria.local"
    seed_admin_password: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        return to_async_url(v)

    @property
    def is_development(self) -> bool:
        return self.env.lower() in ("development", "dev", "local", "test")

    def check_production_secrets(self) -> None:
        """Refuse to boot outside development without real secrets."""
        if self.is_development:
            return
        secret = self.jwt_secret.get_secret_value() if self.jwt_secret else ""
        if len(secret) < 32 or secret.startswith("dev-only"):
            raise RuntimeError("JWT_SECRET must be set to a random value of 32+ characters")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
