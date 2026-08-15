import json
import os
from functools import lru_cache
from typing import Any, Literal, Optional, Union

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    ENV_STATE: Optional[str] = None
    SENTRY_DSN: Optional[str] = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def _get_env_state() -> str:
    """Helper to get ENV_STATE even if not in os.environ yet."""
    state = os.environ.get("ENV_STATE")
    if state:
        return state
    # Try to read from .env manually if Pydantic hasn't loaded it into os.environ
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                if line.startswith("ENV_STATE="):
                    return line.split("=")[1].strip()
    return "dev"


class GlobalConfig(BaseConfig):
    APP_NAME: str = "Task Buddy Backend"
    ENV_STATE: str = "dev"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: Optional[str] = os.environ.get("DATABASE_URL")
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    SECRET_KEY: Optional[str] = os.environ.get("SECRET_KEY")
    SUPABASE_SIGNING_KEY_FILE: str = "supabase_signing_key.json"
    SUPABASE_REALTIME_TOKEN_EXPIRE_SECONDS: int = 300

    @field_validator("SUPABASE_REALTIME_TOKEN_EXPIRE_SECONDS")
    @classmethod
    def validate_realtime_token_expire(cls, v: int) -> int:
        if v < 1:
            raise ValueError("SUPABASE_REALTIME_TOKEN_EXPIRE_SECONDS must be >= 1")
        return v

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
    MAIL_FROM_EMAIL: Optional[str] = os.environ.get("MAIL_FROM_EMAIL")
    MAIL_SMTP_HOST: Optional[str] = None
    MAIL_SMTP_PORT: int = 587
    MAIL_SMTP_USERNAME: Optional[str] = None
    MAIL_SMTP_PASSWORD: Optional[str] = None
    MAIL_SMTP_USE_TLS: bool = True
    # Pool sized under Supabase's pooler cap (15 clients, session mode).
    # LLM endpoints hold a connection for 20-60s, so the app pool plus boot
    # alembic/background-task connections must never approach the cap
    # (verified 2026-08-15: EMAXCONNSESSION during the auth-refresh storm).
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 3
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    B2_KEY_ID: Optional[str] = None
    B2_APPLICATION_KEY: Optional[str] = None
    B2_BUCKET_NAME: Optional[str] = None
    FRONTEND_URL: str = "http://localhost:5173"
    VAPID_PUBLIC_KEY: Optional[str] = None
    VAPID_PRIVATE_KEY: Optional[str] = None
    VAPID_ADMIN_EMAIL: str = "admin@taskbuddy.com"
    RATE_LIMIT_STATS_OVERVIEW: str = "60/minute"
    RATE_LIMIT_AUTH_REGISTER: str = "5/minute"
    RATE_LIMIT_AUTH_RESEND: str = "5/minute"
    RATE_LIMIT_AUTH_LOGIN: str = "5/minute"
    RATE_LIMIT_AUTH_FORGOT_PASSWORD: str = "5/minute"
    RATE_LIMIT_AUTH_RESET_PASSWORD: str = "5/minute"
    RATE_LIMIT_USER_UPDATE_USERNAME: str = "5/minute"
    RATE_LIMIT_USER_UPDATE_PASSWORD: str = "5/minute"
    RATE_LIMIT_PROJECT_CREATE: str = "20/minute"
    RATE_LIMIT_PROJECT_UPDATE: str = "20/minute"
    RATE_LIMIT_PROJECT_DELETE: str = "20/minute"
    RATE_LIMIT_TASK_GET: str = "50/minute"
    RATE_LIMIT_TASK_CREATE: str = "25/minute"
    RATE_LIMIT_TASK_UPDATE: str = "25/minute"
    RATE_LIMIT_TASK_DELETE: str = "25/minute"
    RATE_LIMIT_SUBTASK_CREATE: str = "60/minute"
    RATE_LIMIT_SUBTASK_UPDATE: str = "60/minute"
    RATE_LIMIT_SUBTASK_DELETE: str = "60/minute"
    RATE_LIMIT_KNOWLEDGE_CREATE: str = "30/minute"
    RATE_LIMIT_KNOWLEDGE_LIST: str = "50/minute"
    RATE_LIMIT_KNOWLEDGE_UPDATE: str = "30/minute"
    RATE_LIMIT_KNOWLEDGE_DELETE: str = "30/minute"
    RATE_LIMIT_TAG_CREATE: str = "50/minute"
    RATE_LIMIT_TAG_UPDATE: str = "50/minute"
    RATE_LIMIT_TAG_DELETE: str = "50/minute"
    RATE_LIMIT_TAG_CREATE_ATTACH: str = "50/minute"
    RATE_LIMIT_TAG_ATTACH: str = "50/minute"
    RATE_LIMIT_TAG_DETACH: str = "50/minute"
    RATE_LIMIT_AUDIT_LIST: str = "100/minute"
    RATE_LIMIT_NOTIFICATION_LIST: str = "60/minute"
    RATE_LIMIT_NOTIFICATION_READ: str = "60/minute"
    RATE_LIMIT_NOTIFICATION_READ_ALL: str = "60/minute"
    RATE_LIMIT_PUSH_SUBSCRIBE: str = "10/minute"
    RATE_LIMIT_REALTIME_TOKEN: str = "30/minute"
    RATE_LIMIT_SYNC: str = "60/minute"
    # Embedding provider: "local" (sentence-transformers, zero per-query cost,
    # offline) or "openai" (text-embedding-3-small, ~$0.02/1M tokens).
    # Production uses openai: the ~470MB local model OOMs Render's 512MB tier
    # on first knowledge call (verified 2026-08-15 during dogfood probing).
    EMBEDDING_PROVIDER: str = "local"
    # Local embedding model (zero per-query cost, offline-capable). Multilingual
    # per user decision 2026-08-12 — real task notes are mixed English/Tagalog.
    EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_DIM: int = 384
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    # Pre-warm the embedding model at boot. Dev/test warm it (fast first
    # query); prod overrides to False so the ~470MB model never loads into
    # Render's 512MB free tier at startup (get_embedder() stays lazy there).
    EMBEDDER_PREWARM: bool = True
    # OpenAI LLM settings (generation + judge). The key comes from env only —
    # never hardcoded. Rates are USD per 1M tokens for OPENAI_MODEL
    # (gpt-4o-mini). gpt-4.1-mini upgrade path = change OPENAI_MODEL + these two
    # rates only.
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_INPUT_RATE_PER_1M: float = 0.15
    OPENAI_OUTPUT_RATE_PER_1M: float = 0.60
    RATE_LIMIT_KNOWLEDGE_ASK: str = "10/minute"
    RATE_LIMIT_MEMORY_SIMILAR: str = "10/minute"
    RATE_LIMIT_KNOWLEDGE_FEEDBACK: str = "30/minute"
    RATE_LIMIT_PLAN: str = "10/minute"
    # Demo calendar connector gated on by default (D-11) — no ProdConfig override.
    SYNTHETIC_CALENDAR_ENABLED: bool = True
    PLANNER_WORKING_WINDOW_START_HOUR: int = 18
    PLANNER_WORKING_WINDOW_END_HOUR: int = 22
    PLANNER_DEFAULT_AVAILABLE_MINUTES: int = 120
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
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
                parsed = json.loads(v)
            except json.JSONDecodeError:
                return [v]
            if isinstance(parsed, list):
                return parsed
            return [parsed]
        if isinstance(v, list):
            return v
        return [str(v)]

    @model_validator(mode="after")
    def fix_database_url(self) -> "GlobalConfig":
        """Fix postgres:// prefix to postgresql:// for SQLAlchemy 2.0."""
        if self.DATABASE_URL and self.DATABASE_URL.startswith("postgres://"):
            self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return self


class DevConfig(GlobalConfig):
    ENV_STATE: str = "dev"
    model_config = SettingsConfigDict(env_prefix="DEV_", env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def fallback_settings(self) -> "DevConfig":
        if not self.SECRET_KEY:
            self.SECRET_KEY = os.environ.get("SECRET_KEY")
        if not self.MAIL_FROM_EMAIL:
            self.MAIL_FROM_EMAIL = os.environ.get("MAIL_FROM_EMAIL") or "hello@example.com"
        if not self.MAIL_FROM_NAME:
            self.MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "Task Buddy")
        if not self.MAIL_URL:
            self.MAIL_URL = os.environ.get("MAIL_URL")
        if not self.MAIL_API_KEY:
            self.MAIL_API_KEY = os.environ.get("MAIL_API_KEY")

        # VAPID fallbacks
        if not self.VAPID_PUBLIC_KEY:
            self.VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
        if not self.VAPID_PRIVATE_KEY:
            self.VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
        if not self.VAPID_ADMIN_EMAIL or self.VAPID_ADMIN_EMAIL == "admin@taskbuddy.com":
            self.VAPID_ADMIN_EMAIL = os.environ.get("VAPID_ADMIN_EMAIL", "admin@taskbuddy.com")

        return self


class ProdConfig(GlobalConfig):
    ENV_STATE: str = "prod"
    DEBUG: bool = False
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: Literal["lax", "none", "strict"] = "none"
    # OpenAI embeddings (text-embedding-3-small, 1536-dim): the ~470MB local
    # model OOMs the 512MB free tier on first knowledge call, taking the whole
    # service down mid-request. The migration 1e2f3a4b5c6d alters the column.
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_DIM: int = 1536
    EMBEDDER_PREWARM: bool = False
    model_config = SettingsConfigDict(env_prefix="PROD_", env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def ensure_required_vars(self) -> "ProdConfig":
        """Fail-fast in production when critical vars are not set."""
        self._validate_critical_vars()
        self._apply_mail_fallbacks()
        self._apply_infrastructure_fallbacks()
        return self

    def _validate_critical_vars(self) -> None:
        # ProdConfig reads PROD_-prefixed vars only; no unprefixed fallbacks.
        if not self.SECRET_KEY:
            raise ValueError("PROD_SECRET_KEY must be set in production")

        if not self.DATABASE_URL:
            raise ValueError("PROD_DATABASE_URL must be set in production")

        try:
            from app.libs.supabase_signing import SigningKeyCache

            SigningKeyCache().load(self.SUPABASE_SIGNING_KEY_FILE)
        except ValueError as e:
            raise ValueError(f"Supabase signing key is required in production: {e}") from e

    def _apply_mail_fallbacks(self) -> None:
        # Fallback for MAIL settings if PROD_ prefix is missing
        if not self.MAIL_SMTP_HOST:
            self.MAIL_SMTP_HOST = os.environ.get("MAIL_SMTP_HOST")
        if not self.MAIL_SMTP_USERNAME:
            self.MAIL_SMTP_USERNAME = os.environ.get("MAIL_SMTP_USERNAME")
        if not self.MAIL_SMTP_PASSWORD:
            self.MAIL_SMTP_PASSWORD = os.environ.get("MAIL_SMTP_PASSWORD")
        if not self.MAIL_FROM_EMAIL:
            self.MAIL_FROM_EMAIL = os.environ.get("MAIL_FROM_EMAIL")
        if not self.MAIL_FROM_NAME:
            self.MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "Task Buddy")

    def _apply_infrastructure_fallbacks(self) -> "ProdConfig":
        # Fallback for Redis
        if not self.REDIS_URL:
            self.REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

        # Fallback for URLs
        if not self.FRONTEND_URL or self.FRONTEND_URL == "http://localhost:5173":
            self.FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

        if not self.MAIL_URL:
            self.MAIL_URL = os.environ.get("MAIL_URL")

        # VAPID fallbacks
        if not self.VAPID_PUBLIC_KEY:
            self.VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
        if not self.VAPID_PRIVATE_KEY:
            self.VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
        if not self.VAPID_ADMIN_EMAIL or self.VAPID_ADMIN_EMAIL == "admin@taskbuddy.com":
            self.VAPID_ADMIN_EMAIL = os.environ.get("VAPID_ADMIN_EMAIL", "admin@taskbuddy.com")

        return self


class TestConfig(GlobalConfig):
    ENV_STATE: str = "test"
    DATABASE_URL: str = "sqlite:///./test.db"
    DB_FORCE_ROLL_BACK: bool = True
    RATE_LIMIT_ENABLED: bool = False
    DEBUG: bool = False
    RATE_LIMIT_STATS_OVERVIEW: str = "20/minute"
    RATE_LIMIT_AUTH_REGISTER: str = "5/minute"
    RATE_LIMIT_AUTH_RESEND: str = "3/minute"
    RATE_LIMIT_AUTH_LOGIN: str = "5/minute"
    RATE_LIMIT_AUTH_FORGOT_PASSWORD: str = "3/minute"
    RATE_LIMIT_AUTH_RESET_PASSWORD: str = "3/minute"
    RATE_LIMIT_USER_UPDATE_USERNAME: str = "5/minute"
    RATE_LIMIT_USER_UPDATE_PASSWORD: str = "5/minute"
    RATE_LIMIT_PROJECT_CREATE: str = "10/minute"
    RATE_LIMIT_PROJECT_UPDATE: str = "20/minute"
    RATE_LIMIT_PROJECT_DELETE: str = "10/minute"
    RATE_LIMIT_TASK_GET: str = "20/minute"
    RATE_LIMIT_TASK_CREATE: str = "20/minute"
    RATE_LIMIT_TASK_UPDATE: str = "30/minute"
    RATE_LIMIT_TASK_DELETE: str = "20/minute"
    RATE_LIMIT_SUBTASK_CREATE: str = "30/minute"
    RATE_LIMIT_SUBTASK_UPDATE: str = "30/minute"
    RATE_LIMIT_SUBTASK_DELETE: str = "20/minute"
    RATE_LIMIT_KNOWLEDGE_CREATE: str = "20/minute"
    RATE_LIMIT_KNOWLEDGE_LIST: str = "30/minute"
    RATE_LIMIT_KNOWLEDGE_UPDATE: str = "20/minute"
    RATE_LIMIT_KNOWLEDGE_DELETE: str = "20/minute"
    RATE_LIMIT_KNOWLEDGE_ASK: str = "10/minute"
    RATE_LIMIT_MEMORY_SIMILAR: str = "10/minute"
    RATE_LIMIT_KNOWLEDGE_FEEDBACK: str = "30/minute"
    RATE_LIMIT_PLAN: str = "10/minute"
    RATE_LIMIT_TAG_CREATE: str = "20/minute"
    RATE_LIMIT_TAG_UPDATE: str = "20/minute"
    RATE_LIMIT_TAG_DELETE: str = "20/minute"
    RATE_LIMIT_TAG_CREATE_ATTACH: str = "30/minute"
    RATE_LIMIT_TAG_ATTACH: str = "30/minute"
    RATE_LIMIT_TAG_DETACH: str = "30/minute"
    RATE_LIMIT_AUDIT_LIST: str = "100/minute"
    RATE_LIMIT_NOTIFICATION_LIST: str = "60/minute"
    RATE_LIMIT_NOTIFICATION_READ: str = "60/minute"
    RATE_LIMIT_NOTIFICATION_READ_ALL: str = "60/minute"
    RATE_LIMIT_PUSH_SUBSCRIBE: str = "10/minute"
    RATE_LIMIT_REALTIME_TOKEN: str = "30/minute"
    RATE_LIMIT_SYNC: str = "60/minute"

    model_config = SettingsConfigDict(env_prefix="TEST_", env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def fallback_settings(self) -> "TestConfig":
        if not self.SECRET_KEY:
            self.SECRET_KEY = os.environ.get("SECRET_KEY")
        if not self.MAIL_FROM_EMAIL:
            self.MAIL_FROM_EMAIL = os.environ.get("MAIL_FROM_EMAIL") or "hello@example.com"
        if not self.MAIL_FROM_NAME:
            self.MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "Task Buddy")
        if not self.MAIL_URL:
            self.MAIL_URL = os.environ.get("MAIL_URL")
        if not self.MAIL_API_KEY:
            self.MAIL_API_KEY = os.environ.get("MAIL_API_KEY")

        # VAPID fallbacks
        if not self.VAPID_PUBLIC_KEY:
            self.VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
        if not self.VAPID_PRIVATE_KEY:
            self.VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
        if not self.VAPID_ADMIN_EMAIL or self.VAPID_ADMIN_EMAIL == "admin@taskbuddy.com":
            self.VAPID_ADMIN_EMAIL = os.environ.get("VAPID_ADMIN_EMAIL", "admin@taskbuddy.com")

        return self


@lru_cache
def get_config(env_state: str) -> GlobalConfig:
    configs = {"dev": DevConfig, "prod": ProdConfig, "test": TestConfig}
    return configs[env_state.lower() if env_state else "dev"]()


config = get_config(_get_env_state())

DEV_SECRET_KEY = "dev-secret-key-do-not-use-in-production"


def _resolve_secret_key(secret_key: Optional[str], env_state: str) -> str:
    """Return a usable SECRET_KEY, or fail hard outside dev/test.

    The well-known dev key is only acceptable for local development and
    tests. Any other environment (prod, staging, typo'd states) must
    provide a real key; silently falling back would sign JWTs with a
    publicly known secret.
    """
    if secret_key and secret_key != DEV_SECRET_KEY:
        return secret_key
    if env_state in ("dev", "test"):
        return DEV_SECRET_KEY
    raise RuntimeError("SECRET_KEY (or PROD_SECRET_KEY) must be set in production environment")


# Convenience top-level exports so other modules can import settings directly
DATABASE_URL = config.DATABASE_URL
SECRET_KEY: str = _resolve_secret_key(config.SECRET_KEY, config.ENV_STATE)

ALGORITHM = config.ALGORITHM
REDIS_URL = config.REDIS_URL
ACCESS_TOKEN_EXPIRE_MINUTES = config.ACCESS_TOKEN_EXPIRE_MINUTES
CONFIRM_TOKEN_EXPIRE_MINUTES = config.CONFIRM_TOKEN_EXPIRE_MINUTES
RESET_TOKEN_EXPIRE_MINUTES = config.RESET_TOKEN_EXPIRE_MINUTES
COOKIE_SECURE = config.COOKIE_SECURE
COOKIE_SAMESITE = config.COOKIE_SAMESITE
FRONTEND_URL = config.FRONTEND_URL
RATE_LIMIT_STATS_OVERVIEW = config.RATE_LIMIT_STATS_OVERVIEW
RATE_LIMIT_AUTH_REGISTER = config.RATE_LIMIT_AUTH_REGISTER
RATE_LIMIT_AUTH_RESEND = config.RATE_LIMIT_AUTH_RESEND
RATE_LIMIT_AUTH_LOGIN = config.RATE_LIMIT_AUTH_LOGIN
RATE_LIMIT_AUTH_FORGOT_PASSWORD = config.RATE_LIMIT_AUTH_FORGOT_PASSWORD
RATE_LIMIT_AUTH_RESET_PASSWORD = config.RATE_LIMIT_AUTH_RESET_PASSWORD
RATE_LIMIT_USER_UPDATE_USERNAME = config.RATE_LIMIT_USER_UPDATE_USERNAME
RATE_LIMIT_USER_UPDATE_PASSWORD = config.RATE_LIMIT_USER_UPDATE_PASSWORD
RATE_LIMIT_PROJECT_CREATE = config.RATE_LIMIT_PROJECT_CREATE
RATE_LIMIT_PROJECT_UPDATE = config.RATE_LIMIT_PROJECT_UPDATE
RATE_LIMIT_PROJECT_DELETE = config.RATE_LIMIT_PROJECT_DELETE
RATE_LIMIT_TASK_GET = config.RATE_LIMIT_TASK_GET
RATE_LIMIT_TASK_CREATE = config.RATE_LIMIT_TASK_CREATE
RATE_LIMIT_TASK_UPDATE = config.RATE_LIMIT_TASK_UPDATE
RATE_LIMIT_TASK_DELETE = config.RATE_LIMIT_TASK_DELETE
RATE_LIMIT_SUBTASK_CREATE = config.RATE_LIMIT_SUBTASK_CREATE
RATE_LIMIT_SUBTASK_UPDATE = config.RATE_LIMIT_SUBTASK_UPDATE
RATE_LIMIT_SUBTASK_DELETE = config.RATE_LIMIT_SUBTASK_DELETE
RATE_LIMIT_KNOWLEDGE_CREATE = config.RATE_LIMIT_KNOWLEDGE_CREATE
RATE_LIMIT_KNOWLEDGE_LIST = config.RATE_LIMIT_KNOWLEDGE_LIST
RATE_LIMIT_KNOWLEDGE_UPDATE = config.RATE_LIMIT_KNOWLEDGE_UPDATE
RATE_LIMIT_KNOWLEDGE_DELETE = config.RATE_LIMIT_KNOWLEDGE_DELETE
RATE_LIMIT_TAG_CREATE = config.RATE_LIMIT_TAG_CREATE
RATE_LIMIT_TAG_UPDATE = config.RATE_LIMIT_TAG_UPDATE
RATE_LIMIT_TAG_DELETE = config.RATE_LIMIT_TAG_DELETE
RATE_LIMIT_TAG_CREATE_ATTACH = config.RATE_LIMIT_TAG_CREATE_ATTACH
RATE_LIMIT_TAG_ATTACH = config.RATE_LIMIT_TAG_ATTACH
RATE_LIMIT_TAG_DETACH = config.RATE_LIMIT_TAG_DETACH
RATE_LIMIT_AUDIT_LIST = config.RATE_LIMIT_AUDIT_LIST
RATE_LIMIT_NOTIFICATION_LIST = config.RATE_LIMIT_NOTIFICATION_LIST
RATE_LIMIT_NOTIFICATION_READ = config.RATE_LIMIT_NOTIFICATION_READ
RATE_LIMIT_NOTIFICATION_READ_ALL = config.RATE_LIMIT_NOTIFICATION_READ_ALL
RATE_LIMIT_PUSH_SUBSCRIBE = config.RATE_LIMIT_PUSH_SUBSCRIBE
RATE_LIMIT_REALTIME_TOKEN = config.RATE_LIMIT_REALTIME_TOKEN
RATE_LIMIT_SYNC = config.RATE_LIMIT_SYNC
RATE_LIMIT_KNOWLEDGE_ASK = config.RATE_LIMIT_KNOWLEDGE_ASK
RATE_LIMIT_MEMORY_SIMILAR = config.RATE_LIMIT_MEMORY_SIMILAR
RATE_LIMIT_KNOWLEDGE_FEEDBACK = config.RATE_LIMIT_KNOWLEDGE_FEEDBACK
RATE_LIMIT_PLAN = config.RATE_LIMIT_PLAN
EMBEDDING_MODEL = config.EMBEDDING_MODEL
EMBEDDING_DIM = config.EMBEDDING_DIM
EMBEDDING_PROVIDER = config.EMBEDDING_PROVIDER
OPENAI_EMBEDDING_MODEL = config.OPENAI_EMBEDDING_MODEL
SYNTHETIC_CALENDAR_ENABLED = config.SYNTHETIC_CALENDAR_ENABLED
PLANNER_WORKING_WINDOW_START_HOUR = config.PLANNER_WORKING_WINDOW_START_HOUR
PLANNER_WORKING_WINDOW_END_HOUR = config.PLANNER_WORKING_WINDOW_END_HOUR
PLANNER_DEFAULT_AVAILABLE_MINUTES = config.PLANNER_DEFAULT_AVAILABLE_MINUTES
OPENAI_API_KEY = config.OPENAI_API_KEY
OPENAI_MODEL = config.OPENAI_MODEL
OPENAI_INPUT_RATE_PER_1M = config.OPENAI_INPUT_RATE_PER_1M
OPENAI_OUTPUT_RATE_PER_1M = config.OPENAI_OUTPUT_RATE_PER_1M
