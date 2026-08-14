from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://filmos:filmos@localhost:5432/filmos"
    REDIS_URL: str = "redis://redis:6379"
    AUTH_SECRET: str = "dev-secret-change-me"
    AUTH_PROVIDER: Literal["local", "casdoor"] = "local"
    CASDOOR_ISSUER: str = ""
    CASDOOR_CLIENT_ID: str = ""
    CASDOOR_JWKS_URL: str = ""
    CASDOOR_ORGANIZATION: str = "filmos"
    CASDOOR_ALLOWED_ALGORITHM: Literal["RS256"] = "RS256"
    CASDOOR_JWKS_CACHE_SECONDS: int = Field(default=300, gt=0)
    CASDOOR_HTTP_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)
    SENTRY_DSN: str = ""
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # ─── Agent / LLM ──────────────────────────────────────────────────────────
    # OpenAI-compatible contract. The defaults target Alibaba Cloud Model Studio;
    # switching providers only requires changing these three environment values.
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen3.7-plus"
    LLM_VISION_MODEL: str = "qwen3-vl-plus"
    LLM_REQUEST_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0)
    AGENT_IMAGE_MAX_BYTES: int = Field(default=5 * 1024 * 1024, gt=0)
    CHAT_ATTACHMENT_DIR: str = "var/chat-attachments"

    AGENT_RUNTIME: Literal["langgraph", "openclaw"] = "langgraph"
    OPENCLAW_BASE_URL: str = "http://openclaw:18789"
    OPENCLAW_GATEWAY_TOKEN: str = ""
    OPENCLAW_AGENT_ID: str = "filmos-web"
    OPENCLAW_REQUEST_TIMEOUT_SECONDS: float = 120.0

    # ─── Phoenix (Arize) observability ─────────────────────────────────────────
    # Gated like SENTRY_DSN: when disabled the app behaves identically and never
    # talks to the collector. Traces are shipped over OTLP/HTTP to the Phoenix
    # container (see docker-compose `phoenix` service).
    PHOENIX_ENABLED: bool = False
    PHOENIX_COLLECTOR_ENDPOINT: str = "http://phoenix:6006"
    PHOENIX_PROJECT_NAME: str = "filmos-agent"

    # Ignore retired provider-specific variables left in an untracked local .env.
    # Active settings are still explicitly declared above and validated normally.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_authentication_settings(self) -> Self:
        if self.ENVIRONMENT == "production" and self.AUTH_PROVIDER != "casdoor":
            raise ValueError("production requires AUTH_PROVIDER=casdoor")

        if self.AUTH_PROVIDER == "casdoor":
            required = {
                "CASDOOR_ISSUER": self.CASDOOR_ISSUER,
                "CASDOOR_CLIENT_ID": self.CASDOOR_CLIENT_ID,
                "CASDOOR_JWKS_URL": self.CASDOOR_JWKS_URL,
                "CASDOOR_ORGANIZATION": self.CASDOOR_ORGANIZATION,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"Casdoor authentication requires: {', '.join(missing)}")
        return self

    @property
    def checkpointer_dsn(self) -> str:
        """LangGraph's Postgres checkpointer uses psycopg (not asyncpg), so it needs a
        plain postgresql:// DSN rather than the app's postgresql+asyncpg:// URL."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


settings = Settings()
