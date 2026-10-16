"""Phase 4: plan -> per-line speech files -> timed dialogue track.

Runs the Kokoro worker as a subprocess in its own interpreter, then lays the
lines out on a timeline (scene gaps, per-line pauses) and writes:
  audio/<line_id>.wav         one file per line
  audio/dialogue.wav          all lines placed at their timeline positions
  audio/dialogue.json         the timing manifest used by animation and assembly
"""

from __future__ import annotations

import json
import logging
import sys
import wave
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ...plan import ProductionPlan
from ..subproc import WorkerError, run_worker

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]
WORKER = Path(__file__).resolve().parent.parent.parent.parent / "tts_worker" / "kokoro_worker.py"
LEAD_IN_S = 1.5      # establishing shot before the first line of the film
SCENE_GAP_S = 1.0    # establishing shot at the start of every later scene
TAIL_S = 0.6         # hold after the last line of a scene


class TTSError(RuntimeError):
    pass


class TTSEngine:
    def __init__(self, python: str | None, engine: str = "kokoro", lang: str = "a") -> None:
        self.python = python or sys.executable
        self.engine = engine
        self.lang = lang

    async def run(self, plan: ProductionPlan, project_dir: Path, *, progress: ProgressCb) -> dict[str, Any]:
        audio_dir = project_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        voices = {c.id: c.voice for c in plan.characters}
        job = {
            "lang": self.lang,
            "lines": [
                {"id": l.id, "text": l.text, "voice": voices[l.character_id].voice, "speed": voices[l.character_id].speed}
                for s in plan.scenes for l in s.lines
            ],
        }
        if not job["lines"]:
            raise TTSError("plan has no dialogue lines")
        job_path = audio_dir / "tts_job.json"
        result_path = audio_dir / "tts_result.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        if result_path.exists():
            result_path.unlink()

        cmd = [self.python, str(WORKER), "--job", str(job_path), "--out", str(audio_dir),
               "--result", str(result_path), "--engine", self.engine]
        log.info("tts: %s lines via %s (%s)", len(job["lines"]), self.engine, self.python)
        try:
            await run_worker(cmd, WORKER.parent, progress, "line", lo=0.05, hi=0.9)
        except WorkerError as exc:
            raise TTSError(str(exc)) from exc
        if not result_path.exists():
            raise TTSError("tts worker exited without writing a result file")

        result = json.loads(result_path.read_text(encoding="utf-8"))
        by_id = {l["id"]: l for l in result["lines"]}
        timeline = self._layout(plan, by_id)
        (audio_dir / "dialogue.json").write_text(json.dumps(timeline, indent=1), encoding="utf-8")
        await progress(0.93, "mixing dialogue track")
        self._mix(audio_dir, timeline, int(result.get("sample_rate", 24000)))
        await progress(1.0, None)
        return {
            "engine": result.get("engine", self.engine),
            "lines": len(timeline["lines"]),
            "duration_s": timeline["duration_s"],
            "dialogue": "audio/dialogue.wav",
            "timeline": "audio/dialogue.json",
        }

    @staticmethod
    def _layout(plan: ProductionPlan, by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
        t = 0.0
        lines: list[dict[str, Any]] = []
        scenes: list[dict[str, Any]] = []
        for si, scene in enumerate(plan.scenes):
            scene_start = t
            t += LEAD_IN_S if si == 0 else SCENE_GAP_S
            for i, line in enumerate(scene.lines):
                r = by_id.get(line.id)
                if r is None:
                    raise TTSError(f"worker produced no audio for line {line.id}")
                start, end = t, t + float(r["duration_s"])
                lines.append({
                    "id": line.id, "scene_id": scene.id, "character_id": line.character_id, "text": line.text,
                    "emotion": line.emotion, "file": f"audio/{r['file']}", "start_s": round(start, 3),
                    "end_s": round(end, 3), "duration_s": float(r["duration_s"]),
                    "words": [{**w, "start_s": round(start + w["start_s"], 3), "end_s": round(start + w["end_s"], 3)}
                              for w in r.get("words", [])],
                })
                t = end + (line.pause_after_s if i < len(scene.lines) - 1 else TAIL_S)
            scenes.append({"id": scene.id, "environment_id": scene.environment_id, "start_s": round(scene_start, 3),
                           "end_s": round(t, 3)})
        return {"version": 1, "duration_s": round(t, 3), "scenes": scenes, "lines": lines}

    @staticmethod
    def _mix(audio_dir: Path, timeline: dict[str, Any], sr: int) -> None:
        total = int(timeline["duration_s"] * sr) + sr // 2
        buf = bytearray(total * 2)
        for line in timeline["lines"]:
            with wave.open(str(audio_dir / Path(line["file"]).name), "rb") as w:
                if w.getframerate() != sr or w.getnchannels() != 1 or w.getsampwidth() != 2:
                    raise TTSError(f"{line['file']}: expected {sr} Hz mono 16-bit")
                data = w.readframes(w.getnframes())
            off = int(line["start_s"] * sr) * 2
            end = min(off + len(data), len(buf))
            buf[off:end] = data[: end - off]
        with wave.open(str(audio_dir / "dialogue.wav"), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(sr)
            out.writeframes(bytes(buf))
