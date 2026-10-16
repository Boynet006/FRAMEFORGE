from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Job, JobStatus
from ..schemas import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(
    project_id: str | None = None,
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[JobOut]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if project_id:
        stmt = stmt.where(Job.project_id == project_id)
    if status_filter:
        stmt = stmt.where(Job.status == status_filter)
    return [JobOut.model_validate(j) for j in session.scalars(stmt)]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: Session = Depends(get_session)) -> JobOut:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"job {job_id} not found")
    return JobOut.model_validate(job)
