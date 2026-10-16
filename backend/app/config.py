"""Application settings loaded from environment variables / .env.

All settings use the FRAMEFORGE_ prefix so they never collide with other tools
(ComfyUI, Ollama) that may run on the same machine.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FRAMEFORGE_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000

    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_timeout_s: float = 3.0

    ollama_url: str = "http://127.0.0.1:11434"

    database_url: str = "sqlite:///./data/frameforge.db"
    data_dir: Path = Field(default=Path("./data"))

    # Kept as a plain string because pydantic-settings JSON-decodes list fields
    # from env/.env before validators run; a comma-separated value would fail.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("comfyui_url", "ollama_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def resolved_data_dir(self) -> Path:
        p = self.data_dir
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()

    @property
    def resolved_database_url(self) -> str:
        """Make a relative sqlite path relative to backend/, not to the CWD."""
        prefix = "sqlite:///./"
        if self.database_url.startswith(prefix):
            rel = self.database_url[len(prefix):]
            return f"sqlite:///{(BACKEND_DIR / rel).resolve().as_posix()}"
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
