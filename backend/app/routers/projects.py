from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pydantic import ValidationError

from ..db import get_session
from ..models import Job, JobStatus, Project, ProjectStatus
from ..plan import ProductionPlan
from ..schemas import JobCreate, JobOut, ProjectCreate, ProjectDetail, ProjectOut, ProjectUpdate
from ..services.workflows import WorkflowError, get_registry

router = APIRouter(prefix="/projects", tags=["projects"])


def _out(project: Project) -> ProjectOut:
    item = ProjectOut.model_validate(project)
    item.has_plan = project.plan is not None
    return item


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
        item = _out(project)
        item.job_count = n
        out.append(item)
    return out


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)) -> ProjectOut:
    project = Project(title=body.title, prompt=body.prompt, settings=body.settings)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _out(project)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, session: Session = Depends(get_session)) -> ProjectDetail:
    project = _get_or_404(session, project_id)
    detail = ProjectDetail.model_validate(project)
    detail.has_plan = project.plan is not None
    detail.jobs = [JobOut.model_validate(j) for j in project.jobs]
    detail.job_count = len(detail.jobs)
    return detail


# ---------- pipeline stages ----------


def _queue_stage(session: Session, request: Request, project: Project, kind: str,
                 payload: dict | None = None, *, max_attempts: int = 2) -> JobOut:
    active = session.scalars(
        select(Job.id).where(Job.project_id == project.id, Job.kind == kind,
                             Job.status.in_((JobStatus.queued, JobStatus.running))).limit(1)
    ).first()
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{kind} already queued (job {active})")
    runner = request.app.state.runner
    job = Job(project_id=project.id, kind=kind, payload=payload or {}, max_attempts=max_attempts)
    session.add(job)
    session.commit()
    session.refresh(job)
    out = JobOut.model_validate(job)
    runner._sync_project_status(session, project.id)
    runner.bus.publish({"type": "job", "job": out.model_dump(mode="json")})
    runner.wake()
    return out


@router.post("/{project_id}/tts", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def generate_tts(project_id: str, request: Request, session: Session = Depends(get_session)) -> JobOut:
    """Queue speech generation for every line of the plan (Phase 4)."""
    project = _get_or_404(session, project_id)
    if project.plan is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "generate the plan first")
    return _queue_stage(session, request, project, "tts.generate")


@router.post("/{project_id}/refs", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def generate_refs(project_id: str, request: Request, force: bool = False, workflow: str | None = None,
                  session: Session = Depends(get_session)) -> JobOut:
    """Queue character + environment reference image generation via ComfyUI (Phase 5/6).

    `workflow` overrides the configured image template (FRAMEFORGE_IMAGE_WORKFLOW) for this run."""
    project = _get_or_404(session, project_id)
    if project.plan is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "generate the plan first")
    payload: dict = {"force": force}
    if workflow:
        try:
            get_registry().get(workflow)
        except WorkflowError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        payload["workflow"] = workflow
    return _queue_stage(session, request, project, "refs.generate", payload, max_attempts=3)


@router.post("/{project_id}/animate", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def animate(project_id: str, request: Request, max_seconds: float = 0,
            session: Session = Depends(get_session)) -> JobOut:
    """Render the silent picture track from the plan, references and dialogue timeline."""
    project = _get_or_404(session, project_id)
    if project.plan is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "generate the plan first")
    return _queue_stage(session, request, project, "animate.render", {"max_seconds": max_seconds})


@router.post("/{project_id}/assemble", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def assemble(project_id: str, request: Request, session: Session = Depends(get_session)) -> JobOut:
    """Mux picture, dialogue, music and subtitles into render/final.mp4 with quality checks."""
    project = _get_or_404(session, project_id)
    if project.plan is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "generate the plan first")
    return _queue_stage(session, request, project, "assemble.render")


@router.post("/{project_id}/generate", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def generate_full(project_id: str, request: Request, force: bool = False,
                  session: Session = Depends(get_session)) -> JobOut:
    """Generate the complete video: plan -> voices -> references -> animation -> final MP4.

    Finished stages are reused on re-runs unless force=true.
    """
    project = _get_or_404(session, project_id)
    active = session.scalars(
        select(Job.id).where(Job.project_id == project_id,
                             Job.status.in_((JobStatus.queued, JobStatus.running))).limit(1)
    ).first()
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"project already has an active job ({active})")
    return _queue_stage(session, request, project, "pipeline.full", {"force": force}, max_attempts=2)


@router.get("/{project_id}/render")
def get_render(project_id: str, request: Request, session: Session = Depends(get_session)) -> dict:
    """What exists on disk for this project: refs, audio, picture track, final video."""
    _get_or_404(session, project_id)
    root = request.app.state.runner.project_dir(project_id)

    def info(rel: str) -> dict | None:
        p = root / rel
        if not p.is_file():
            return None
        return {"path": rel, "size": p.stat().st_size, "url": f"/api/projects/{project_id}/files/{rel}"}

    refs = sorted(p.name for p in (root / "refs").glob("*.png")) if (root / "refs").is_dir() else []
    return {
        "plan": root.joinpath("plan.json").is_file(),
        "dialogue": info("audio/dialogue.wav"),
        "timeline": info("audio/dialogue.json"),
        "music": info("audio/music.wav"),
        "refs": [info(f"refs/{n}") for n in refs if not n.startswith("cutout_")],
        "video_silent": info("render/video_silent.mp4"),
        "subtitles": info("render/subtitles.srt"),
        "final": info("render/final.mp4"),
    }


@router.get("/{project_id}/timeline")
def get_timeline(project_id: str, request: Request, session: Session = Depends(get_session)) -> dict:
    """The timed dialogue manifest produced by the TTS stage."""
    _get_or_404(session, project_id)
    path = request.app.state.runner.project_dir(project_id) / "audio" / "dialogue.json"
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no dialogue timeline yet; run TTS first")
    import json

    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/{project_id}/files/{path:path}")
def get_project_file(project_id: str, path: str, request: Request, download: bool = False,
                     session: Session = Depends(get_session)):
    """Serve a generated file from the project's data folder (audio, images, renders).

    `download=true` sends it as an attachment named after the project (the HTML `download`
    attribute is ignored for cross-origin links, so the browser needs the header)."""
    import re

    from fastapi.responses import FileResponse

    project = _get_or_404(session, project_id)
    root = request.app.state.runner.project_dir(project_id).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    if download:
        stem = re.sub(r"[^A-Za-z0-9]+", "-", project.title).strip("-")[:60] or project_id
        name = f"{stem}{target.suffix}" if target.stem == "final" else f"{stem}-{target.name}"
        return FileResponse(target, filename=name)
    return FileResponse(target)


# ---------- production plan (Phase 3) ----------


@router.post("/{project_id}/plan", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def generate_plan(project_id: str, request: Request, session: Session = Depends(get_session)) -> JobOut:
    """Queue script/production-plan generation with the local LLM."""
    project = _get_or_404(session, project_id)
    active = session.scalars(
        select(Job.id).where(Job.project_id == project_id, Job.kind == "plan.generate",
                             Job.status.in_((JobStatus.queued, JobStatus.running))).limit(1)
    ).first()
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"plan generation already queued (job {active})")
    runner = request.app.state.runner
    job = Job(project_id=project_id, kind="plan.generate",
              payload={"prompt": project.prompt, "settings": project.settings}, max_attempts=2)
    project.status = ProjectStatus.planning
    session.add(job)
    session.commit()
    session.refresh(job)
    out = JobOut.model_validate(job)
    runner.bus.publish({"type": "job", "job": out.model_dump(mode="json")})
    runner.wake()
    return out


@router.get("/{project_id}/plan")
def get_plan(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = _get_or_404(session, project_id)
    if project.plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project has no plan yet")
    plan = ProductionPlan.model_validate(project.plan)
    return {"plan": plan.model_dump(), "summary": plan.summary()}


@router.put("/{project_id}/plan")
def put_plan(project_id: str, body: dict, session: Session = Depends(get_session)) -> dict:
    """Replace the plan (advanced mode editing). The body is validated as a ProductionPlan."""
    project = _get_or_404(session, project_id)
    try:
        plan = ProductionPlan.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()[0].get("msg", "invalid plan")) from exc
    project.plan = plan.model_dump()
    session.commit()
    return {"plan": plan.model_dump(), "summary": plan.summary()}


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str, body: ProjectUpdate, session: Session = Depends(get_session)
) -> ProjectOut:
    project = _get_or_404(session, project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    session.commit()
    session.refresh(project)
    return _out(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, request: Request, session: Session = Depends(get_session)) -> None:
    project = _get_or_404(session, project_id)
    for job in project.jobs:
        request.app.state.runner.delete_outputs(project_id, job.id)
    session.delete(project)
    session.commit()


@router.post("/{project_id}/jobs", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    project_id: str, body: JobCreate, request: Request, session: Session = Depends(get_session)
) -> JobOut:
    """Queue a ComfyUI workflow run for this project. Parameters are validated now, run later."""
    _get_or_404(session, project_id)
    try:
        template = get_registry().get(body.workflow, body.version)
        template.build(body.params)  # fail fast on bad params; the runner rebuilds with a fresh seed
    except WorkflowError as exc:
        raise HTTPException(422, str(exc)) from exc
    runner = request.app.state.runner
    job = Job(
        project_id=project_id,
        kind="comfy.workflow",
        payload={"workflow": template.name, "version": template.version, "params": body.params},
        max_attempts=runner.settings.job_max_attempts,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    out = JobOut.model_validate(job)
    runner._sync_project_status(session, project_id)
    runner.bus.publish({"type": "job", "job": out.model_dump(mode="json")})
    runner.wake()
    return out
