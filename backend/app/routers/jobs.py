from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Job, JobStatus
from ..schemas import JobOut
from ..services.runner import JobRunner

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_runner(request: Request) -> JobRunner:
    return request.app.state.runner


def _get_or_404(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"job {job_id} not found")
    return job


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
    return JobOut.model_validate(_get_or_404(session, job_id))


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, runner: JobRunner = Depends(get_runner)) -> JobOut:
    """Cancel a queued job immediately, or interrupt a running one in ComfyUI."""
    try:
        return runner.request_cancel(job_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"job {job_id} not found") from None


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: str, runner: JobRunner = Depends(get_runner)) -> JobOut:
    """Re-queue a failed or cancelled job with the same parameters."""
    try:
        return runner.retry(job_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"job {job_id} not found") from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/{job_id}/outputs/{filename}")
def get_output(
    job_id: str,
    filename: str,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
) -> FileResponse:
    job = _get_or_404(session, job_id)
    safe = Path(filename).name
    if safe != filename or safe in ("", ".", ".."):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid filename")
    path = runner.output_dir(job.project_id, job.id) / safe
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "output not found")
    return FileResponse(path)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: str,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
) -> None:
    job = _get_or_404(session, job_id)
    if job.status == JobStatus.running:
        raise HTTPException(status.HTTP_409_CONFLICT, "cancel the job before deleting it")
    runner.delete_outputs(job.project_id, job.id)
    session.delete(job)
    session.commit()
