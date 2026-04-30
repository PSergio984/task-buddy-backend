"""
Configuration module for the Task Buddy Backend.

Handles environment variables and application settings.
"""

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Can be configured via .env file or environment variables.
    """

    # Application settings
    app_name: str = "Task Buddy Backend"
    debug: bool = False
    log_level: str = "INFO"

    # Database settings
    database_url: Optional[str] = None

    # Security settings
    secret_key: str = "your-secret-key-here-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # CORS settings
    cors_origins: list = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list = ["*"]
    cors_allow_headers: list = ["*"]

    class Config:
        """Pydantic configuration."""

        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
