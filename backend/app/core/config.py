from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://filmos:filmos@localhost:5432/filmos"
    REDIS_URL: str = "redis://localhost:6379"
    AUTH_SECRET: str = "dev-secret-change-me"
    SENTRY_DSN: str = ""
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
