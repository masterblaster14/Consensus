"""Settings loaded from environment / .env via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://consensus:consensus@localhost:5432/consensus"
    redis_url: str = "redis://localhost:6379"

    # Stance extraction (the one LLM call in the declare path)
    anthropic_api_key: str | None = None
    stance_provider: Literal["anthropic", "keyword"] = "anthropic"
    stance_model: str = "claude-opus-5"

    # Embeddings
    embedding_provider: Literal["openai", "hashing"] = "openai"
    openai_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Integrations
    github_token: str | None = None
    github_webhook_secret: str | None = None
    notion_token: str | None = None
    notion_tasks_db_id: str | None = None
    enable_github: bool = True
    enable_notion: bool = True

    # Comparison thresholds
    concept_similarity_threshold: float = 0.82
    dedup_similarity_threshold: float = 0.92
    axis_match_overlap: float = 0.67  # overlap coefficient above which two axis positions count as the same

    default_project_id: str | None = None
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # Long-poll ceiling for wait verdicts (seconds)
    max_wait_seconds: int = Field(default=120, ge=1, le=600)

    # -- auth -------------------------------------------------------------
    secret_key: str = "change-me-in-production"          # signs session JWTs
    jwt_ttl_hours: int = 24 * 7
    frontend_url: str = "http://localhost:5173"          # OAuth / magic-link redirects land here
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_oauth_scopes: str = "read:user user:email repo"
    magic_link_ttl_minutes: int = 15
    invite_ttl_days: int = 7
    # DEV_AUTH=true enables POST /api/auth/dev-login and returns magic links in the
    # response instead of emailing them. Never enable in production.
    dev_auth: bool = False
    # When false, unauthenticated MCP calls are allowed and land on DEFAULT_PROJECT_ID /
    # the first project (the pre-auth behaviour). Keep true.
    mcp_auth_required: bool = True

    # -- email (magic links, invites). Unset SMTP_HOST = links are logged, not sent. --
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "Consensus <no-reply@localhost>"
    smtp_starttls: bool = True

    # -- encryption at rest for stored GitHub / Notion tokens. A Fernet key; comma-separate
    #    several to rotate (first encrypts, all decrypt). Unset = derived from SECRET_KEY.
    #    Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str | None = None

    # -- background PR sync: seconds between sync_open_prs passes over live projects; 0 disables.
    pr_sync_interval_seconds: int = 300

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def github_enabled(self) -> bool:
        return self.enable_github and bool(self.github_token)

    @property
    def notion_enabled(self) -> bool:
        return self.enable_notion and bool(self.notion_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()
