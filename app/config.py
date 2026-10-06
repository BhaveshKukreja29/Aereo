from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEREO_", extra="ignore")

    database_url: str = "sqlite:///./data/aereo.db"
    data_dir: Path = Path("./data")
    max_upload_bytes: int = 50 * 1024 * 1024


def get_settings() -> Settings:
    return Settings()
