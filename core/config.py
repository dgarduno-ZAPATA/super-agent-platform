from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    )
    evolution_instance_name: str = Field(
        default="selectrucks-zapata",
        alias="EVOLUTION_INSTANCE_NAME",
    )
    evolution_api_key: str = Field(
        default="change-me",
        alias="EVOLUTION_API_KEY",
    )

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
