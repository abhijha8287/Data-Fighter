"""Environment-driven settings. See .env.example for the full list."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    datahub_mode: Literal["mock", "real"] = "mock"
    datahub_gms_url: str | None = None
    datahub_gms_token: str | None = None
    datahub_mutation_enabled: bool = False

    github_token: str | None = None
    github_demo_repo: str | None = None  # "owner/repo"

    checkpoint_db_path: str = "./data-firefighter-checkpoints.db"

    fixture_dir: Path = REPO_ROOT / "examples" / "incidents" / "customer_email_deletion"


settings = Settings()
