"""Phase 5/6 (CPU mode): drive media_worker/animate_worker.py to render the silent picture track."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ...plan import ProductionPlan
from ..subproc import WorkerError, run_worker

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]
WORKER = Path(__file__).resolve().parent.parent.parent.parent / "media_worker" / "animate_worker.py"

PROFILES = {
    "draft": {"width": 960, "height": 540, "fps": 24},
    "final": {"width": 1280, "height": 720, "fps": 24},
}


class AnimateError(RuntimeError):
    pass


class AnimateEngine:
    def __init__(self, python: str | None, ffmpeg: str = "ffmpeg") -> None:
        self.python = python or sys.executable
        self.ffmpeg = ffmpeg

    async def run(self, plan: ProductionPlan, project_dir: Path, quality: str, *, progress: ProgressCb,
                  max_seconds: float = 0) -> dict[str, Any]:
        if not (project_dir / "audio" / "dialogue.json").exists():
            raise AnimateError("no dialogue timeline; run the TTS stage first")
        (project_dir / "plan.json").write_text(json.dumps(plan.model_dump(), indent=1), encoding="utf-8")
        prof = PROFILES.get(quality, PROFILES["draft"])
        cmd = [self.python, str(WORKER), "--project", str(project_dir), "--out", "render/video_silent.mp4",
               "--shots", "render/shots.json", "--width", str(prof["width"]), "--height", str(prof["height"]),
               "--fps", str(prof["fps"]), "--ffmpeg", self.ffmpeg]
        if max_seconds:
            cmd += ["--max-seconds", str(max_seconds)]
        try:
            last = await run_worker(cmd, WORKER.parent, progress, "frame")
        except WorkerError as exc:
            raise AnimateError(str(exc)) from exc
        try:
            info = json.loads(last)
        except ValueError:
            info = {}
        await progress(1.0, None)
        return {"video": "render/video_silent.mp4", "shots": "render/shots.json", "profile": prof, **info}
