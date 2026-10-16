"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import JobStatus, ProjectStatus


def _as_utc(v: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; every stored timestamp is UTC, so restore it on the way out."""
    if v is not None and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v

# ---------- health / connectivity ----------


class GpuInfo(BaseModel):
    name: str
    driver_version: str | None = None
    memory_total_mb: int | None = None
    memory_used_mb: int | None = None


class ServiceCheck(BaseModel):
    name: str
    url: str
    reachable: bool
    latency_ms: float | None = None
    detail: dict[str, Any] | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    version: str
    uptime_s: float
    time: datetime
    database_ok: bool
    gpu: list[GpuInfo]
    python: str
    platform: str


class ComfyStatusResponse(BaseModel):
    reachable: bool
    url: str
    latency_ms: float | None = None
    comfyui_version: str | None = None
    python_version: str | None = None
    pytorch_version: str | None = None
    devices: list[dict[str, Any]] = Field(default_factory=list)
    queue_running: int | None = None
    queue_pending: int | None = None
    error: str | None = None


# ---------- projects ----------


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, min_length=1)
    settings: dict[str, Any] | None = None
    status: ProjectStatus | None = None


class JobCreate(BaseModel):
    workflow: str = Field(min_length=1, description="template name, e.g. image_basic_txt2img")
    version: int | None = Field(default=None, description="template version; latest when omitted")
    params: dict[str, Any] = Field(default_factory=dict)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    kind: str
    status: JobStatus
    progress: float
    attempt: int
    max_attempts: int
    payload: dict[str, Any]
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    _utc = field_validator("created_at", "started_at", "finished_at")(_as_utc)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    prompt: str
    settings: dict[str, Any]
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    job_count: int = 0

    _utc = field_validator("created_at", "updated_at")(_as_utc)


class ProjectDetail(ProjectOut):
    jobs: list[JobOut] = Field(default_factory=list)
