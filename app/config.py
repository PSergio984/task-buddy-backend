from typing import Optional
from functools import lru_cache
import os
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    ENV_STATE: Optional[str] = None
    SENTRY_DSN: Optional[str] = None
    SECRET_KEY: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ALGORITHM: str = "HS256"
    CONFIRM_TOKEN_EXPIRE_MINUTES: int = 1440
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class GlobalConfig(BaseConfig):
    APP_NAME: str = "Task Buddy Backend"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: Optional[str] = None
    DB_FORCE_ROLL_BACK: bool = False
    MAIL_API_KEY: Optional[str] = None
    MAIL_URL: Optional[str] = None


class DevConfig(GlobalConfig):
    model_config = SettingsConfigDict(env_prefix="DEV_", extra="ignore")


class ProdConfig(GlobalConfig):
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
    DB_FORCE_ROLL_BACK: bool = True

    model_config = SettingsConfigDict(env_prefix="TEST_", extra="ignore")


@lru_cache()
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

SECRET_KEY = (
    os.environ.get("SECRET_KEY")
    or getattr(config, "SECRET_KEY", None)
    or _unprefixed_secret
    or os.environ.get("PROD_SECRET_KEY")
)
ALGORITHM = getattr(config, "ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = getattr(config, "ACCESS_TOKEN_EXPIRE_MINUTES", 30)
CONFIRM_TOKEN_EXPIRE_MINUTES = getattr(config, "CONFIRM_TOKEN_EXPIRE_MINUTES", 1440)
