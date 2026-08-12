from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import Optional
import secrets

class Settings(BaseSettings):
    # App
    APP_NAME: str = "BOASTLIB"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/boastlib"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if isinstance(value, str):
            if value.startswith("postgres://"):
                return "postgresql+asyncpg://" + value[len("postgres://"):]
            if value.startswith("postgresql://") and not value.startswith("postgresql+asyncpg://"):
                return "postgresql+asyncpg://" + value[len("postgresql://"):]
        return value

    # JWT
    JWT_SECRET_KEY: str = secrets.token_urlsafe(64)
    JWT_REFRESH_SECRET: str = secrets.token_urlsafe(64)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # CORS
    CORS_ORIGINS: str = "https://boastlib.space,https://www.boastlib.space,https://smm-frontend-blue.vercel.app,http://localhost:3000"

    # Paystack (card payments)
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_PUBLIC_KEY: str = ""
    # Optional: leave blank to use the Paystack merchant account default currency.
    PAYSTACK_CURRENCY: str = ""

    # Dodo Payments
    DODO_PAYMENTS_API_KEY: str = ""
    DODO_PAYMENTS_ENVIRONMENT: str = "test_mode"
    DODO_PAYMENTS_WEBHOOK_KEY: str = ""
    DODO_PAYMENTS_PRODUCT_ID: str = ""

    # DPO / PawaPay (mobile money)
    PAWAPAY_API_KEY: str = ""
    PAWAPAY_BASE_URL: str = "https://api.pawapay.io"

    # SMM Providers
    MORETHANPANEL_API_KEY: str = ""
    MORETHANPANEL_API_URL: str = "https://morethanpanel.com/api/v2"
    WIZSMM_API_KEY: str = ""
    WIZSMM_API_URL: str = "https://wizsmm.com/api/v2"

    # Email (Brevo)
    BREVO_API_KEY: str = ""
    FROM_EMAIL: str = "noreply@boastlib.com"
    FROM_NAME: str = "BOASTLIB"
    # Admin notification target (comma-separated emails)
    ADMIN_NOTIFICATION_EMAILS: str = ""
    # Order sync interval seconds (default 300 = 5 minutes)
    ORDER_SYNC_INTERVAL_SECONDS: int = 300

    # Frontend
    FRONTEND_URL: str = "https://boastlib.space"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
