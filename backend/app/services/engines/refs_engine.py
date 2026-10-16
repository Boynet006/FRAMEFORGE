"""Phase 5/6 (part 1): reference images for every character and environment.

One ComfyUI run per reference through the configured image template, saved
under <project>/refs/ and recorded in the plan (`reference_image`).
Existing references are kept unless `force` is set, so re-runs are cheap.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ...plan import ProductionPlan
from .comfy_engine import ComfyEngine

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]

# Portrait for characters, 16:9 for environments (multiples of 8 for SD).
CHARACTER_SIZE = (512, 640)
ENVIRONMENT_SIZE = (768, 432)

STYLE_HINTS = {
    "cinematic": "cinematic lighting, film still, shallow depth of field",
    "cartoon": "cartoon illustration, bold outlines, flat vibrant colors",
    "3d-animated": "3d animated film style, pixar-like render, soft global illumination",
    "photoreal": "photorealistic, 85mm lens, natural light, highly detailed",
    "anime": "anime style, clean lineart, cel shading",
}


class RefsEngine:
    def __init__(self, comfy: ComfyEngine, workflow: str, *, force: bool = False) -> None:
        self.comfy = comfy
        self.workflow = workflow
        self.force = force

    async def run(self, plan: ProductionPlan, project_dir: Path, job_id: str, *, progress: ProgressCb,
                  persist_plan: Callable[[ProductionPlan], Awaitable[None]],
                  cancel_requested: Callable[[], bool]) -> dict[str, Any]:
        refs_dir = project_dir / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        style = STYLE_HINTS.get(plan.style, plan.style)
        targets: list[tuple[str, str, str, tuple[int, int], str]] = []
        for c in plan.characters:
            targets.append(("character", c.id, f"{c.image_prompt}, {style}", CHARACTER_SIZE, c.negative_prompt))
        for e in plan.environments:
            targets.append(("environment", e.id, f"{e.image_prompt}, {style}", ENVIRONMENT_SIZE,
                            "people, person, text, watermark, blurry, low quality"))

        generated: list[dict[str, Any]] = []
        skipped = 0
        for i, (kind, ident, prompt, size, negative) in enumerate(targets):
            rel = f"refs/{kind}_{ident}.png"
            target = project_dir / rel
            base = i / len(targets)
            await progress(base, f"{kind} {ident}")
            if target.exists() and not self.force:
                skipped += 1
                self._record(plan, kind, ident, rel)
                continue

            async def sub_progress(v: float, _node: str | None, _base: float = base) -> None:
                await progress(_base + v / len(targets) * 0.98, f"{kind} {ident}")

            payload = {"workflow": self.workflow, "params": {
                "prompt": prompt, "negative_prompt": negative, "width": size[0], "height": size[1]}}
            tmp_out = project_dir / "jobs" / job_id / f"{kind}_{ident}"
            result = await self.comfy.run(f"{job_id}-{kind}-{ident}", payload, tmp_out, progress=sub_progress,
                                          persist_payload=_noop_persist, cancel_requested=cancel_requested)
            first = next((o for o in result["outputs"] if o["kind"] == "image"), None)
            if first is None:
                raise RuntimeError(f"no image produced for {kind} {ident}")
            shutil.copyfile(tmp_out / first["filename"], target)
            self._record(plan, kind, ident, rel)
            await persist_plan(plan)
            generated.append({"kind": kind, "id": ident, "file": rel, "seed": result["params"].get("seed"),
                              "duration_s": result["duration_s"]})
        await progress(1.0, None)
        return {"generated": len(generated), "skipped": skipped, "refs": generated, "workflow": self.workflow}

    @staticmethod
    def _record(plan: ProductionPlan, kind: str, ident: str, rel: str) -> None:
        items = plan.characters if kind == "character" else plan.environments
        for item in items:
            if item.id == ident:
                item.reference_image = rel


async def _noop_persist(_payload: dict[str, Any]) -> None:
    pass
