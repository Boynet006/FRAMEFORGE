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
    comfyui_poll_s: float = 2.0
    # Hard ceiling for one ComfyUI job (long video renders on a 16 GB card can take an hour).
    job_timeout_s: float = 6 * 3600
    job_max_attempts: int = 3

    ollama_url: str = "http://127.0.0.1:11434"
    # Small enough for CPU-only development; use qwen3:14b on the RTX 5080 PC.
    ollama_model: str = "qwen3:4b"
    ollama_timeout_s: float = 900.0

    # Workflow template used for character/environment reference images.
    # CPU machines: image_sd15_lcm. RTX 5080: a Qwen-Image/SDXL template once validated.
    image_workflow: str = "image_sd15_lcm"

    # Text-to-speech worker: separate interpreter (Python 3.12 venv with kokoro installed).
    tts_engine: str = "kokoro"  # kokoro | fake
    tts_python: Path = Field(default=Path("./.venv-tts/Scripts/python.exe"))
    tts_lang: str = "a"  # Kokoro language code: a = American English, b = British English

    # Media workers (animator, music) share the TTS venv. FFmpeg from PATH unless overridden.
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    # "cpu" = procedural animatic renderer (this machine); "gpu" = ComfyUI video models (RTX 5080, later phases)
    render_mode: str = "cpu"

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

    def _resolve_tool(self, name: str) -> str:
        """Find ffmpeg/ffprobe even when this process inherited a PATH from before the install
        (winget updates the registry PATH, not running processes)."""
        import os
        import shutil

        if Path(name).is_absolute() or shutil.which(name):
            return name
        candidates: list[Path] = []
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if local.exists():
            candidates += list(local.glob(f"Gyan.FFmpeg*/**/bin/{Path(name).stem}.exe"))
        for p in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ffmpeg" / "bin",
                  Path(r"C:\ffmpeg\bin")):
            candidates.append(p / f"{Path(name).stem}.exe")
        for c in candidates:
            if c.exists():
                return str(c)
        return name

    @property
    def resolved_ffmpeg(self) -> str:
        return self._resolve_tool(self.ffmpeg)

    @property
    def resolved_ffprobe(self) -> str:
        return self._resolve_tool(self.ffprobe)

    @property
    def resolved_tts_python(self) -> str:
        p = self.tts_python
        return str(p if p.is_absolute() else (BACKEND_DIR / p).resolve())

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
