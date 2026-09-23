"""Configuration management for the application"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Database
    database_url: str = (
        "postgresql://portfoliosos:dev_password_123@localhost:5432/portfoliosos_dev"
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Environment
    environment: str = "development"
    debug: bool = True

    # API
    api_title: str = "PortfolioOS API"
    api_version: str = "0.1.0"
    api_description: str = "AI-powered portfolio builder with GraphQL API"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    # Local résumé uploads
    resume_upload_dir: str = "data/uploads/resumes"
    max_resume_size_bytes: int = 10 * 1024 * 1024
    local_auth_user_id: str = "local-dev-user"
    local_auth_email: str = "local@portfoliosos.dev"

    # Wireframe interpretation
    openai_api_key: str = ""
    openai_wireframe_model: str = "gpt-4o-mini"
    max_wireframe_size_bytes: int = 10 * 1024 * 1024

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


@lru_cache()
def get_settings():
    return Settings()
