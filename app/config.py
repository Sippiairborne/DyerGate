import logging
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "sqlite:///./data/dyergate.db"
    UPSTREAM_PROVIDER: str = "ollama"
    UPSTREAM_API_URL: str = "http://host.docker.internal:11434"
    UPSTREAM_API_PATH: str = "/api/chat"
    UPSTREAM_API_KEY: str = ""

    GATEWAY_HOST: str = "0.0.0.0"
    GATEWAY_PORT: int = 8080

    SECRET_KEY: str = "CHANGE_ME"
    ADMIN_API_KEY: str = "CHANGE_ME"

    DEFAULT_RATE_LIMIT_PER_MIN: int = 60
    REQUEST_TIMEOUT_SECONDS: float = 120.0
    MAX_OUTPUT_TOKENS_SAFETY_CAP: int = 32000
    MARGIN_MULTIPLIER: float = 1.0

    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_SUCCESS_URL: str = "http://localhost:8080/admin/topup/success"
    STRIPE_CANCEL_URL: str = "http://localhost:8080/admin/topup/cancel"
    PUBLIC_BASE_URL: str = "http://localhost:8080"

    ALERT_WEBHOOK_URL: str = ""
    ALERT_WEBHOOK_SECRET: str = ""
    LOW_BALANCE_THRESHOLD: float = 1.00

    REDIS_URL: str = ""
    RESEND_API_KEY: str = ""

    AUTO_TOPUP_ENABLED: bool = True
    AUTO_TOPUP_INTERVAL_SECONDS: int = 300
    KEY_ROTATION_GRACE_HOURS: int = 24
    DASHBOARD_ENABLED: bool = True

    # ---- SaaS mode ----
    SAAS_MODE: bool = False
    PLATFORM_DOMAIN: str = "dyergate.cloud"
    PLATFORM_NAME: str = "DyerGate Cloud"
    STRIPE_CONNECT_ENABLED: bool = False
    PLATFORM_FEE_BPS: int = 1500  # basis points (15%)

    CUSTOM_DOMAIN_ENABLED: bool = False
    TLS_PROVIDER: str = "caddy"

    EMAIL_FROM: str = "DyerGate Cloud <noreply@dyergate.cloud>"

    PRIMARY_REGION: str = "us-east-1"
    SECONDARY_REGION: str = "us-west-2"
    HEALTHCHECK_URL: str = ""

    STATUS_PAGE_ENABLED: bool = True


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.SECRET_KEY == "CHANGE_ME" or s.ADMIN_API_KEY == "CHANGE_ME":
        logging.getLogger("dyergate").warning(
            "Using default SECRET_KEY / ADMIN_API_KEY. Override them in .env!"
        )
    return s


settings = get_settings()
