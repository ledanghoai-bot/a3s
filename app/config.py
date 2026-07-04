from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # Meta / Messenger
    meta_verify_token: str = "change-me"
    meta_app_secret: str = ""
    page_access_token: str = ""

    # Ha tang
    database_url: str = "postgresql+asyncpg://alpha3s:alpha3s@db:5432/alpha3s"
    redis_url: str = "redis://redis:6379/0"

    # LLM
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-4-5"
    embedding_model: str = "text-embedding-3-small"


settings = Settings()
