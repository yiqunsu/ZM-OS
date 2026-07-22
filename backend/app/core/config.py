from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://filmos:filmos@localhost:5432/filmos"
    REDIS_URL: str = "redis://redis:6379"
    AUTH_SECRET: str = "dev-secret-change-me"
    SENTRY_DSN: str = ""
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # ─── Agent / LLM ──────────────────────────────────────────────────────────
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # ─── Phoenix (Arize) observability ─────────────────────────────────────────
    # Gated like SENTRY_DSN: when disabled the app behaves identically and never
    # talks to the collector. Traces are shipped over OTLP/HTTP to the Phoenix
    # container (see docker-compose `phoenix` service).
    PHOENIX_ENABLED: bool = False
    PHOENIX_COLLECTOR_ENDPOINT: str = "http://phoenix:6006"
    PHOENIX_PROJECT_NAME: str = "filmos-agent"

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def checkpointer_dsn(self) -> str:
        """LangGraph's Postgres checkpointer uses psycopg (not asyncpg), so it needs a
        plain postgresql:// DSN rather than the app's postgresql+asyncpg:// URL."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


settings = Settings()
