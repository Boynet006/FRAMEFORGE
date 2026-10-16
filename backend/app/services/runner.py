"""Single-worker background job runner.

One job executes at a time (one GPU). Jobs are persisted in SQLite so the
queue survives restarts: on start-up, jobs left in `running` are re-queued,
and a ComfyUI job whose prompt already finished is recovered from history
instead of being regenerated.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..config import Settings
from ..db import SessionLocal
from ..models import Job, JobStatus, Project, ProjectStatus
from ..plan import ProductionPlan
from ..schemas import JobOut
from .comfy_client import ComfyClient, ComfyError, ComfyUnavailable
from .engines.comfy_engine import ComfyEngine, JobCancelled
from .engines.animate_engine import AnimateEngine, AnimateError
from .engines.assemble_engine import AssembleEngine, AssembleError
from .engines.pipeline_engine import PipelineEngine
from .engines.plan_engine import PlanEngine
from .engines.refs_engine import RefsEngine
from .engines.tts_engine import TTSEngine, TTSError
from .events import EventBus
from .llm_client import LLMError, LLMUnavailable, OllamaClient
from .workflows import WorkflowError, WorkflowRegistry

log = logging.getLogger(__name__)

ACTIVE = (JobStatus.queued, JobStatus.running)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobRunner:
    def __init__(self, settings: Settings, bus: EventBus, registry: WorkflowRegistry) -> None:
        self.settings = settings
        self.bus = bus
        self.registry = registry
        self.comfy_url = settings.comfyui_url  # mutable so tests can point at a stand-in
        self.ollama_url = settings.ollama_url
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self.current_job_id: str | None = None
        self._cancel_requested: set[str] = set()

    # ---------- lifecycle ----------

    async def start(self) -> None:
        self._recover()
        self._task = asyncio.create_task(self._loop(), name="job-runner")
        log.info("job runner started")

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        log.info("job runner stopped")

    def wake(self) -> None:
        self._wake.set()

    # ---------- public controls ----------

    def request_cancel(self, job_id: str) -> JobOut:
        with SessionLocal() as s:
            job = s.get(Job, job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status == JobStatus.queued:
                job.status = JobStatus.cancelled
                job.finished_at = _now()
                job.error = "cancelled before start"
                s.commit()
                s.refresh(job)
                out = JobOut.model_validate(job)
                self._sync_project_status(s, job.project_id)
            elif job.status == JobStatus.running:
                self._cancel_requested.add(job_id)
                out = JobOut.model_validate(job)
            else:
                out = JobOut.model_validate(job)
        self._publish(out)
        return out

    def retry(self, job_id: str) -> JobOut:
        with SessionLocal() as s:
            job = s.get(Job, job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status not in (JobStatus.failed, JobStatus.cancelled):
                raise ValueError(f"job is {job.status.value}; only failed or cancelled jobs can be retried")
            payload = dict(job.payload)
            payload.pop("prompt_id", None)
            job.payload = payload
            job.status = JobStatus.queued
            job.progress = 0.0
            job.error = None
            job.result = {}
            job.started_at = None
            job.finished_at = None
            s.commit()
            s.refresh(job)
            out = JobOut.model_validate(job)
            self._sync_project_status(s, job.project_id)
        self._publish(out)
        self.wake()
        return out

    def project_dir(self, project_id: str) -> Path:
        return self.settings.resolved_data_dir / "projects" / project_id

    def output_dir(self, project_id: str, job_id: str) -> Path:
        return self.project_dir(project_id) / "jobs" / job_id

    def _load_plan(self, project_id: str) -> ProductionPlan:
        with SessionLocal() as s:
            project = s.get(Project, project_id)
            if project is None or project.plan is None:
                raise ValueError("project has no production plan yet; run the planner first")
            return ProductionPlan.model_validate(project.plan)

    def _save_plan(self, project_id: str, plan: ProductionPlan) -> None:
        with SessionLocal() as s:
            project = s.get(Project, project_id)
            if project is not None:
                project.plan = plan.model_dump()
                s.commit()

    def _comfy_engine(self) -> ComfyEngine:
        return ComfyEngine(
            ComfyClient(self.comfy_url, self.settings.comfyui_timeout_s),
            self.registry,
            poll_s=self.settings.comfyui_poll_s,
            timeout_s=self.settings.job_timeout_s,
        )

    def delete_outputs(self, project_id: str, job_id: str) -> None:
        shutil.rmtree(self.output_dir(project_id, job_id), ignore_errors=True)

    # ---------- internals ----------

    def _recover(self) -> None:
        with SessionLocal() as s:
            stuck = s.scalars(select(Job).where(Job.status == JobStatus.running)).all()
            for job in stuck:
                job.status = JobStatus.queued
                job.progress = 0.0
                job.error = None
                log.warning("re-queued job %s left running by a previous process", job.id)
            s.commit()

    async def _loop(self) -> None:
        while not self._stopping:
            job_id = self._next_queued()
            if job_id is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                continue
            try:
                await self._run_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("runner crashed on job %s", job_id)
                self._update(job_id, status=JobStatus.failed, error="internal runner error", finished_at=_now())

    def _next_queued(self) -> str | None:
        with SessionLocal() as s:
            job = s.scalars(
                select(Job).where(Job.status == JobStatus.queued).order_by(Job.created_at).limit(1)
            ).first()
            return job.id if job else None

    async def _run_job(self, job_id: str) -> None:
        with SessionLocal() as s:
            job = s.get(Job, job_id)
            if job is None or job.status != JobStatus.queued:
                return
            job.status = JobStatus.running
            job.started_at = _now()
            job.attempt += 1
            job.error = None
            s.commit()
            s.refresh(job)
            out = JobOut.model_validate(job)
            self._sync_project_status(s, job.project_id)
        self.current_job_id = job_id
        self._publish(out)
        log.info("job %s started (%s, attempt %d/%d)", job_id, out.kind, out.attempt, out.max_attempts)

        last_pct = -1

        async def progress(value: float, node: str | None) -> None:
            nonlocal last_pct
            pct = int(value * 100)
            if pct != last_pct:
                last_pct = pct
                self._update(job_id, progress=round(value, 4))

        async def persist_payload(payload: dict[str, Any]) -> None:
            self._update(job_id, payload=payload)

        try:
            if out.kind == "comfy.workflow":
                engine = self._comfy_engine()
                result = await engine.run(
                    job_id,
                    out.payload,
                    self.output_dir(out.project_id, job_id),
                    progress=progress,
                    persist_payload=persist_payload,
                    cancel_requested=lambda: job_id in self._cancel_requested,
                )
            elif out.kind in ("plan.generate", "tts.generate", "refs.generate", "animate.render", "assemble.render"):
                result = await self._run_stage(out.kind.split(".")[0], job_id, out, progress)
            elif out.kind == "pipeline.full":
                pipeline = PipelineEngine(
                    lambda stage, prog: self._run_stage(stage, job_id, out, prog),
                    self.project_dir(out.project_id),
                    has_plan=lambda: self._has_plan(out.project_id),
                    force=bool(out.payload.get("force")),
                )
                result = await pipeline.run(progress=progress)
                with SessionLocal() as s:
                    project = s.get(Project, out.project_id)
                    if project is not None:
                        project.status = ProjectStatus.completed if result.get("ok") else ProjectStatus.failed
                        s.commit()
                        self.bus.publish({"type": "project", "project": {"id": project.id, "status": project.status.value}})
            else:
                raise ValueError(f"unknown job kind {out.kind}")
            self._update(job_id, status=JobStatus.succeeded, progress=1.0, result=result, finished_at=_now())
            log.info("job %s succeeded in %ss", job_id, result.get("duration_s"))
        except JobCancelled:
            self._update(job_id, status=JobStatus.cancelled, error="cancelled by user", finished_at=_now())
            log.info("job %s cancelled", job_id)
        except (ComfyUnavailable, LLMUnavailable) as exc:
            if out.attempt < out.max_attempts:
                delay = min(2 ** out.attempt, 30)
                log.warning("job %s: %s; retrying in %ss", job_id, exc, delay)
                self._update(job_id, status=JobStatus.queued, progress=0.0, error=f"retrying: {exc}")
                await asyncio.sleep(delay)
            else:
                self._update(job_id, status=JobStatus.failed, error=str(exc), finished_at=_now())
        except (ComfyError, LLMError, TTSError, AnimateError, AssembleError, WorkflowError, ValueError,
                RuntimeError, OSError) as exc:
            msg = str(exc) or f"{type(exc).__name__} (no message)"
            self._update(job_id, status=JobStatus.failed, error=msg, finished_at=_now())
            log.error("job %s failed: %s", job_id, msg, exc_info=not str(exc))
        finally:
            self._cancel_requested.discard(job_id)
            self.current_job_id = None

    # ---------- pipeline stages ----------

    def _has_plan(self, project_id: str) -> bool:
        with SessionLocal() as s:
            project = s.get(Project, project_id)
            return project is not None and project.plan is not None

    async def _run_stage(self, stage: str, job_id: str, out: JobOut, progress: Any) -> dict[str, Any]:
        """Run one named production stage for the job's project. Shared by stage jobs and the pipeline."""
        project_dir = self.project_dir(out.project_id)
        payload = out.payload
        if stage == "plan":
            with SessionLocal() as s:
                project = s.get(Project, out.project_id)
                if project is None:
                    raise ValueError("project disappeared")
                prompt, settings = project.prompt, dict(project.settings)
            llm = OllamaClient(self.ollama_url, self.settings.ollama_model, self.settings.ollama_timeout_s)
            plan = await PlanEngine(llm).run(settings, prompt, progress=progress)
            await llm.unload()
            with SessionLocal() as s:
                project = s.get(Project, out.project_id)
                if project is not None:
                    project.plan = plan.model_dump()
                    if project.status == ProjectStatus.planning:
                        project.status = ProjectStatus.draft
                    s.commit()
            self.bus.publish({"type": "project", "project": {"id": out.project_id, "has_plan": True}})
            return {"summary": plan.summary()}

        plan = self._load_plan(out.project_id)
        if stage == "tts":
            engine = TTSEngine(self.settings.resolved_tts_python, self.settings.tts_engine, self.settings.tts_lang)
            return await engine.run(plan, project_dir, progress=progress)
        if stage == "refs":
            refs = RefsEngine(self._comfy_engine(), payload.get("workflow") or self.settings.image_workflow,
                              force=bool(payload.get("force") or payload.get("force_refs")))

            async def persist_plan(p: ProductionPlan) -> None:
                self._save_plan(out.project_id, p)

            result = await refs.run(plan, project_dir, job_id, progress=progress, persist_plan=persist_plan,
                                    cancel_requested=lambda: job_id in self._cancel_requested)
            self._save_plan(out.project_id, plan)
            return result
        if stage == "animate":
            with SessionLocal() as s:
                project = s.get(Project, out.project_id)
                quality = str((project.settings if project else {}).get("quality") or "draft")
            engine = AnimateEngine(self.settings.resolved_tts_python, self.settings.resolved_ffmpeg)
            return await engine.run(plan, project_dir, quality, progress=progress,
                                    max_seconds=float(payload.get("max_seconds") or 0))
        if stage == "assemble":
            engine = AssembleEngine(self.settings.resolved_tts_python, self.settings.resolved_ffmpeg,
                                    self.settings.resolved_ffprobe)
            return await engine.run(plan, project_dir, progress=progress)
        raise ValueError(f"unknown stage {stage}")

    def _update(self, job_id: str, **fields: Any) -> None:
        with SessionLocal() as s:
            job = s.get(Job, job_id)
            if job is None:
                return
            for k, v in fields.items():
                setattr(job, k, v)
            s.commit()
            s.refresh(job)
            out = JobOut.model_validate(job)
            if "status" in fields:
                self._sync_project_status(s, job.project_id)
        self._publish(out)

    def _sync_project_status(self, s: Any, project_id: str) -> None:
        project = s.get(Project, project_id)
        if project is None:
            return
        active = s.scalars(select(Job.id).where(Job.project_id == project_id, Job.status.in_(ACTIVE)).limit(1)).first()
        new_status = ProjectStatus.generating if active else ProjectStatus.draft
        if project.status in (ProjectStatus.draft, ProjectStatus.generating) and project.status != new_status:
            project.status = new_status
            s.commit()
            self.bus.publish({"type": "project", "project": {"id": project.id, "status": project.status.value}})

    def _publish(self, job: JobOut) -> None:
        self.bus.publish({"type": "job", "job": job.model_dump(mode="json")})
