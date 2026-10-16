"""Persistent records: Project (a video to make) and Job (one unit of work).

Phase 1 keeps the schema small. Later phases add script, timeline, shots and
assets as separate tables that reference these two.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class ProjectStatus(str, enum.Enum):
    draft = "draft"
    planning = "planning"
    generating = "generating"
    assembling = "assembling"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    # Generation settings chosen in the UI (duration, style, aspect, quality, voices...)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    # ProductionPlan (see app/plan.py) once the planner has run; editable in advanced mode.
    plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=False), default=ProjectStatus.draft
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    jobs: Mapped[list["Job"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Job.created_at"
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    # e.g. "comfy.image", "comfy.video", "llm.script", "tts.line", "ffmpeg.assemble"
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.queued
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    # Engine-specific payload (ComfyUI prompt_id, workflow name, inputs...)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # Engine-specific result (output paths, durations, metrics...)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="jobs")
