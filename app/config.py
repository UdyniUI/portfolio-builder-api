"""Configuration management for the application"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://portfoliosos:dev_password_123@localhost:5432/portfoliosos_dev"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Environment
    environment: str = "development"
    debug: bool = True

    # API
    api_title: str = "PortfolioOS API"
    api_version: str = "0.1.0"
    api_description: str = "AI-powered portfolio builder with GraphQL API"

    # Auth0
    auth0_domain: str = ""
    auth0_client_id: str = ""
    auth0_client_secret: str = ""

    # Security
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Claude API
    claude_api_key: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings():
    return Settings()
