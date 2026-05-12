import json
import os
from functools import lru_cache
from typing import Any, Literal, Optional, Union

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    ENV_STATE: Optional[str] = None
    SENTRY_DSN: Optional[str] = None
    SECRET_KEY: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ALGORITHM: str = "HS256"
    CONFIRM_TOKEN_EXPIRE_MINUTES: int = 1440
    RESET_TOKEN_EXPIRE_MINUTES: int = 60
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class GlobalConfig(BaseConfig):
    APP_NAME: str = "Task Buddy Backend"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: Optional[str] = None
    REDIS_URL: str = "redis://localhost:6379/0"
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
    def ensure_secret_key(self):
        """Fail-fast in production when SECRET_KEY is not set."""
        if not self.SECRET_KEY:
            raise ValueError(
                "PROD_SECRET_KEY (SECRET_KEY) must be set in production; refusing to start without a secure secret."
            )
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
# Preference order for SECRET_KEY: env `SECRET_KEY` -> configured value -> unprefixed .env -> env `PROD_SECRET_KEY`
_unprefixed_secret = None
try:
    _unprefixed_secret = BaseConfig().SECRET_KEY
except Exception:
    _unprefixed_secret = None

_raw_secret: Any = (
    os.environ.get("SECRET_KEY")
    or getattr(config, "SECRET_KEY", None)
    or _unprefixed_secret
    or os.environ.get("PROD_SECRET_KEY")
)

if not _raw_secret:
    raise RuntimeError("SECRET_KEY must be set via environment or config")

SECRET_KEY: str = str(_raw_secret)
ALGORITHM = getattr(config, "ALGORITHM", "HS256")
REDIS_URL = getattr(config, "REDIS_URL", "redis://localhost:6379/0")
ACCESS_TOKEN_EXPIRE_MINUTES = getattr(config, "ACCESS_TOKEN_EXPIRE_MINUTES", 30)
CONFIRM_TOKEN_EXPIRE_MINUTES = getattr(config, "CONFIRM_TOKEN_EXPIRE_MINUTES", 1440)
RESET_TOKEN_EXPIRE_MINUTES = getattr(config, "RESET_TOKEN_EXPIRE_MINUTES", 60)
COOKIE_SECURE = getattr(config, "COOKIE_SECURE", False)
COOKIE_SAMESITE = config.COOKIE_SAMESITE
FRONTEND_URL = config.FRONTEND_URL
RATE_LIMIT_STATS_OVERVIEW = config.RATE_LIMIT_STATS_OVERVIEW
