"""One prompt -> finished MP4: runs every stage in order inside a single job.

Stages: plan -> tts -> refs -> animate -> assemble. Each stage's outputs are
checkpoints; a re-run (or a retry after a crash) skips stages whose outputs
already exist unless `force` is set, so a failed 10-minute render resumes
instead of starting over.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]

# (stage, progress range start, end)
STAGES = [("plan", 0.0, 0.12), ("tts", 0.12, 0.30), ("refs", 0.30, 0.55), ("animate", 0.55, 0.85), ("assemble", 0.85, 1.0)]


class PipelineEngine:
    def __init__(self, stage_runner: Callable[[str, ProgressCb], Awaitable[dict[str, Any]]],
                 project_dir: Path, has_plan: Callable[[], bool], force: bool = False) -> None:
        self.stage_runner = stage_runner
        self.project_dir = project_dir
        self.has_plan = has_plan
        self.force = force

    def _done(self, stage: str) -> bool:
        if self.force:
            return False
        p = self.project_dir
        if stage == "plan":
            return self.has_plan()
        if stage == "tts":
            return (p / "audio" / "dialogue.json").exists() and (p / "audio" / "dialogue.wav").exists()
        if stage == "refs":
            return False  # refs engine skips existing images itself
        if stage == "animate":
            v, tl = p / "render" / "video_silent.mp4", p / "audio" / "dialogue.json"
            return v.exists() and tl.exists() and v.stat().st_mtime >= tl.stat().st_mtime
        if stage == "assemble":
            f, v = p / "render" / "final.mp4", p / "render" / "video_silent.mp4"
            return f.exists() and v.exists() and f.stat().st_mtime >= v.stat().st_mtime
        return False

    async def run(self, *, progress: ProgressCb) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for stage, lo, hi in STAGES:
            if self._done(stage):
                results[stage] = {"skipped": True}
                await progress(hi, f"{stage}: reused")
                log.info("pipeline: %s reused", stage)
                continue

            async def sub(v: float, label: str | None, _lo: float = lo, _hi: float = hi, _stage: str = stage) -> None:
                await progress(_lo + (_hi - _lo) * v, f"{_stage}: {label}" if label else _stage)

            await sub(0.0, None)
            results[stage] = await self.stage_runner(stage, sub)
            log.info("pipeline: %s done", stage)
        final = results.get("assemble", {})
        return {"stages": results, "final": "render/final.mp4", "ok": final.get("ok", True)}
