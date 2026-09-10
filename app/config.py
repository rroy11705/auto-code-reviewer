from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # GitHub Settings
    GITHUB_TOKEN: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""

    # OpenHands Model Settings (Developer-hosted OpenHands model)
    OPENHANDS_ENDPOINT: str = "http://localhost:50000/api"
    OPENHANDS_MODEL_NAME: str = "openhands-code-reviewer"
    OPENHANDS_API_KEY: Optional[str] = None

    # Fallback / Alternative Model Providers
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"

    # Antigravity CLI Settings
    AGY_BIN_PATH: str = "agy"

    # AWS SES Settings
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    SES_SENDER_EMAIL: str = "reviewer-bot@yourdomain.com"
    SES_DEFAULT_RECIPIENT: str = "dev-team@yourdomain.com"
    SES_DRY_RUN: bool = False


# Global settings singleton
settings = Settings()
