"""Phase 5/6 (CPU mode): drive media_worker/animate_worker.py to render the silent picture track."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ...plan import ProductionPlan

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]
WORKER = Path(__file__).resolve().parent.parent.parent.parent / "media_worker" / "animate_worker.py"

PROFILES = {
    "draft": {"width": 960, "height": 540, "fps": 24},
    "final": {"width": 1280, "height": 720, "fps": 24},
}


class AnimateError(RuntimeError):
    pass


async def run_worker(cmd: list[str], cwd: Path, progress: ProgressCb, label: str) -> str:
    """Run a worker subprocess, forward PROGRESS lines, return its last stdout line."""
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, cwd=str(cwd))
    stderr_task = asyncio.create_task(proc.stderr.read())  # type: ignore[union-attr]
    assert proc.stdout is not None
    last = ""
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith("PROGRESS "):
            _, i, n = line.split()
            await progress(min(int(i) / max(int(n), 1), 0.999), f"{label} {i}/{n}")
        elif line:
            last = line
    rc = await proc.wait()
    stderr = (await stderr_task).decode("utf-8", "replace")
    for l in stderr.splitlines():
        if l.startswith(("INFO", "WARN")):
            log.info("worker: %s", l)
    if rc != 0:
        tail = "\n".join(stderr.strip().splitlines()[-10:])
        raise AnimateError(f"{label} worker failed (exit {rc}): {tail or 'no error output'}")
    return last


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
        last = await run_worker(cmd, WORKER.parent, progress, "frames")
        try:
            info = json.loads(last)
        except ValueError:
            info = {}
        await progress(1.0, None)
        return {"video": "render/video_silent.mp4", "shots": "render/shots.json", "profile": prof, **info}
