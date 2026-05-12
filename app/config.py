import json
import os
from functools import lru_cache
from typing import Any, Literal, Optional, Union

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    ENV_STATE: Optional[str] = os.environ.get("ENV_STATE")
    SENTRY_DSN: Optional[str] = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class GlobalConfig(BaseConfig):
    APP_NAME: str = "Task Buddy Backend"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: Optional[str] = os.environ.get("DATABASE_URL")
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    SECRET_KEY: Optional[str] = os.environ.get("SECRET_KEY")
    DB_FORCE_ROLL_BACK: bool = False
    ALLOWED_ORIGINS: Union[list[str], str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://task-buddy-frontend.vercel.app",
    ]
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: Literal["lax", "none", "strict"] = "lax"
    RATE_LIMIT_ENABLED: bool = True
    MAIL_API_KEY: Optional[str] = None
    MAIL_URL: Optional[str] = None
    MAIL_FROM_NAME: str = "Task Buddy"
    MAIL_FROM_EMAIL: Optional[str] = None
    MAIL_SMTP_HOST: Optional[str] = None
    MAIL_SMTP_PORT: int = 587
    MAIL_SMTP_USERNAME: Optional[str] = None
    MAIL_SMTP_PASSWORD: Optional[str] = None
    MAIL_SMTP_USE_TLS: bool = True
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    B2_KEY_ID: Optional[str] = None
    B2_APPLICATION_KEY: Optional[str] = None
    B2_BUCKET_NAME: Optional[str] = None
    FRONTEND_URL: str = "http://localhost:5173"
    RATE_LIMIT_STATS_OVERVIEW: str = "20/minute"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ALGORITHM: str = "HS256"
    CONFIRM_TOKEN_EXPIRE_MINUTES: int = 1440
    RESET_TOKEN_EXPIRE_MINUTES: int = 60

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [v]
        return v

    @model_validator(mode="after")
    def fix_database_url(self):
        """Fix postgres:// prefix to postgresql:// for SQLAlchemy 2.0."""
        if self.DATABASE_URL and self.DATABASE_URL.startswith("postgres://"):
            self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return self


class DevConfig(GlobalConfig):
    model_config = SettingsConfigDict(env_prefix="DEV_", extra="ignore")


class ProdConfig(GlobalConfig):
    DEBUG: bool = False
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: Literal["lax", "none", "strict"] = "none"
    model_config = SettingsConfigDict(env_prefix="PROD_", extra="ignore")

    @model_validator(mode="after")
    def ensure_required_vars(self):
        """Fail-fast in production when critical vars are not set."""
        if not self.SECRET_KEY:
            # Check if we have it unprefixed as a final fallback
            self.SECRET_KEY = os.environ.get("SECRET_KEY")
            if not self.SECRET_KEY:
                raise ValueError(
                    "SECRET_KEY (or PROD_SECRET_KEY) must be set in production; refusing to start without a secure secret."
                )
        if not self.DATABASE_URL:
             self.DATABASE_URL = os.environ.get("DATABASE_URL")
             if not self.DATABASE_URL:
                 raise ValueError("DATABASE_URL (or PROD_DATABASE_URL) must be set in production.")
        return self


class TestConfig(GlobalConfig):
    DATABASE_URL: str = "sqlite:///./test.db"
    DB_FORCE_ROLL_BACK: bool = False
    RATE_LIMIT_ENABLED: bool = False
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_prefix="TEST_", extra="ignore")


@lru_cache
def get_config(env_state: str) -> GlobalConfig:
    configs = {"dev": DevConfig, "prod": ProdConfig, "test": TestConfig}
    return configs[env_state.lower() if env_state else "dev"]()


config = get_config(BaseConfig().ENV_STATE)

# Convenience top-level exports so other modules can import settings directly
DATABASE_URL = config.DATABASE_URL
SECRET_KEY: str = config.SECRET_KEY or ""
if not SECRET_KEY and config.DEBUG is False:
    raise RuntimeError("SECRET_KEY must be set in production")

ALGORITHM = config.ALGORITHM
REDIS_URL = config.REDIS_URL
ACCESS_TOKEN_EXPIRE_MINUTES = config.ACCESS_TOKEN_EXPIRE_MINUTES
CONFIRM_TOKEN_EXPIRE_MINUTES = config.CONFIRM_TOKEN_EXPIRE_MINUTES
RESET_TOKEN_EXPIRE_MINUTES = config.RESET_TOKEN_EXPIRE_MINUTES
COOKIE_SECURE = config.COOKIE_SECURE
COOKIE_SAMESITE = config.COOKIE_SAMESITE
FRONTEND_URL = config.FRONTEND_URL
RATE_LIMIT_STATS_OVERVIEW = config.RATE_LIMIT_STATS_OVERVIEW
