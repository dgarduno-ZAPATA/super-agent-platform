from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+asyncpg://app_user:change_me@db:5432/super_agent_platform",
        alias="DATABASE_URL",
    )
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    brand_path: Path = Field(default=Path("./brand"), alias="BRAND_PATH")
    evolution_base_url: str = Field(
        default="https://evo.zapata.com",
        alias="EVOLUTION_BASE_URL",
        validation_alias=AliasChoices("EVOLUTION_BASE_URL", "EVOLUTION_API_URL"),
    )
    evolution_instance_name: str = Field(
        default="selectrucks-zapata",
        alias="EVOLUTION_INSTANCE_NAME",
    )
    evolution_api_key: str = Field(
        default="",
        alias="EVOLUTION_API_KEY",
    )
    gcp_project_id: str = Field(default="change-me-project", alias="GCP_PROJECT_ID")
    gcp_region: str = Field(default="us-central1", alias="GCP_REGION")
    vertex_model_name: str = Field(
        default="gemini-2.5-flash-lite",
        alias="VERTEX_MODEL_NAME",
    )
    vertex_embedding_model_name: str = Field(
        default="text-embedding-004",
        alias="VERTEX_EMBEDDING_MODEL_NAME",
    )
    branch_sheet_url: str = Field(
        default=(
            "https://docs.google.com/spreadsheets/d/e/2PACX-1vTILMYUv--RRf7VSfpW5HjiyAyBMx5eFCpMk"
            "FH8IbRH4C6SmMQOojgP070SyqudI8-DQCKrEUawl5WA/pub?output=csv"
        ),
        alias="BRANCH_SHEET_URL",
    )
    inventory_sheet_url: str = Field(
        default=(
            "https://docs.google.com/spreadsheets/d/e/2PACX-1vRIgFsCIXQspySgSDAQHFoERzthu_JEk5Gedz"
            "izT7R9N5kTtH83nRc7XNmMyeKijmPIdqjReOL09eKw/pub?output=csv"
        ),
        alias="INVENTORY_SHEET_URL",
    )
    branch_cache_ttl_seconds: int = Field(default=600, alias="BRANCH_CACHE_TTL_SECONDS")
    inventory_cache_ttl_seconds: int = Field(default=300, alias="INVENTORY_CACHE_TTL_SECONDS")
    campaign_batch_size: int = Field(default=10, alias="CAMPAIGN_BATCH_SIZE")
    campaign_rate_limit_ms: int = Field(default=300, alias="CAMPAIGN_RATE_LIMIT_MS")
    campaign_scheduler_interval_seconds: int = Field(
        default=60, alias="CAMPAIGN_SCHEDULER_INTERVAL_SECONDS"
    )
    campaign_scheduler_enabled: bool = Field(default=True, alias="CAMPAIGN_SCHEDULER_ENABLED")
    internal_token: str = Field(default="", alias="INTERNAL_TOKEN")
    jwt_secret_key: str = Field(default="", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=60 * 8, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
