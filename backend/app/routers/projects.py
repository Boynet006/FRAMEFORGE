from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Job, Project
from ..schemas import JobOut, ProjectCreate, ProjectDetail, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


def _get_or_404(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"project {project_id} not found")
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)) -> list[ProjectOut]:
    stmt = (
        select(Project, func.count(Job.id))
        .outerjoin(Job, Job.project_id == Project.id)
        .group_by(Project.id)
        .order_by(Project.created_at.desc())
    )
    out: list[ProjectOut] = []
    for project, n in session.execute(stmt):
        item = ProjectOut.model_validate(project)
        item.job_count = n
        out.append(item)
    return out


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)) -> ProjectOut:
    project = Project(title=body.title, prompt=body.prompt, settings=body.settings)
    session.add(project)
    session.commit()
    session.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, session: Session = Depends(get_session)) -> ProjectDetail:
    project = _get_or_404(session, project_id)
    detail = ProjectDetail.model_validate(project)
    detail.jobs = [JobOut.model_validate(j) for j in project.jobs]
    detail.job_count = len(detail.jobs)
    return detail


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str, body: ProjectUpdate, session: Session = Depends(get_session)
) -> ProjectOut:
    project = _get_or_404(session, project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    session.commit()
    session.refresh(project)
    return ProjectOut.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, session: Session = Depends(get_session)) -> None:
    project = _get_or_404(session, project_id)
    session.delete(project)
    session.commit()
