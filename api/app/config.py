from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RESUME_", env_file=".env", extra="ignore", env_file_encoding="utf-8"
    )
    environment: Literal["development", "production"] = "development"
    metadata_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://127.0.0.1:6379/1"
    data_dir: Path = Path("../.local/sessions")
    allowed_origins: list[str] = ["http://127.0.0.1:4321", "http://localhost:4321"]
    ip_salt: SecretStr = SecretStr("development-only-do-not-use-in-production")
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    admin_token: SecretStr = SecretStr("")
    cookie_name: str = "resume_session"
    idle_seconds: int = Field(7200, ge=1)
    hard_seconds: int = Field(21600, ge=1)
    upload_bytes: int = 5 * 1024 * 1024
    jd_bytes: int = 2 * 1024 * 1024
    max_analysis_chars: int = 30000
    max_active_jobs: int = Field(2, ge=1, le=8)
    free_daily: int = 3
    global_daily: int = 200
    daily_tokens: int = 3_000_000
    llm_timeout: float = 60
    task_timeout: float = 180

    @model_validator(mode="after")
    def validate_production(self):
        if self.environment == "production":
            if self.metadata_backend != "redis":
                raise ValueError("Production requires Redis metadata")
            if self.ip_salt.get_secret_value().startswith("development-"):
                raise ValueError("Production requires a random IP salt")
            if not self.allowed_origins or any(
                not value.startswith("https://") for value in self.allowed_origins
            ):
                raise ValueError("Production requires explicit HTTPS origins")
        if self.llm_base_url:
            url = urlsplit(self.llm_base_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("The station model endpoint must be an approved HTTPS URL")
        return self

    @property
    def secure_cookie(self) -> bool:
        return self.environment == "production"
