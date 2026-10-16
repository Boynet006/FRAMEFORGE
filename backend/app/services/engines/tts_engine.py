"""Phase 4: plan -> per-line speech files -> timed dialogue track.

Engines (FRAMEFORGE_TTS_ENGINE):
  kokoro      Kokoro-82M in backend/.venv-tts: fast, clean, little emotion (speed follows the line's emotion)
  chatterbox  Resemble Chatterbox in backend/.venv-chatterbox: expressive delivery driven by each line's
              emotion (exaggeration / cfg_weight); each character's voice is cloned from a ~10 s reference
              read by that character's Kokoro voice, so voices stay distinct and consistent
  fake        tone bursts, for tests

Then the lines are laid out with conversational timing (delivery.gap_after), mixed dry, and given the
scene's room acoustics (media_worker/room_worker.py). Writes:
  audio/<line_id>.wav         one file per line (dry, edge silence trimmed)
  audio/voices/ref_<voice>.wav  Chatterbox reference clips (cached)
  audio/dialogue_dry.wav      all lines at their timeline positions
  audio/dialogue.wav          the same with room acoustics: what the final film uses
  audio/dialogue.json         the timing manifest used by animation and assembly
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import zlib
from array import array
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
import wave

from ...plan import ProductionPlan
from ..subproc import WorkerError, run_worker
from .delivery import delivery, gap_after, room_preset

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]
_BACKEND = Path(__file__).resolve().parent.parent.parent.parent
WORKER = _BACKEND / "tts_worker" / "kokoro_worker.py"
CHATTERBOX_WORKER = _BACKEND / "tts_worker" / "chatterbox_worker.py"
ROOM_WORKER = _BACKEND / "media_worker" / "room_worker.py"
LEAD_IN_S = 1.5      # establishing shot before the first line of the film
SCENE_GAP_S = 1.0    # establishing shot at the start of every later scene
TAIL_S = 0.6         # hold after the last line of a scene
MIN_SPACING_S = 0.35  # an overlapping reply never starts earlier than this after the previous line began

# Read by each character's Kokoro voice once; Chatterbox clones the voice from it. Varied punctuation
# and ~10 s of speech give the cloner enough material.
REFERENCE_TEXT = ("Oh, hello there. I've been waiting all morning, and honestly, I have quite a lot to say "
                  "about it. Shall we get started? Good. Let's begin.")


class TTSError(RuntimeError):
    pass


class TTSEngine:
    def __init__(self, python: str | None, engine: str = "kokoro", lang: str = "a", *,
                 chatterbox_python: str | None = None, room_mix: bool = True) -> None:
        self.python = python or sys.executable
        self.engine = engine
        self.lang = lang
        self.chatterbox_python = chatterbox_python
        self.room_mix = room_mix

    async def run(self, plan: ProductionPlan, project_dir: Path, *, progress: ProgressCb) -> dict[str, Any]:
        audio_dir = project_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        voices = {c.id: c.voice for c in plan.characters}
        lines = [(s, l) for s in plan.scenes for l in s.lines]
        if not lines:
            raise TTSError("plan has no dialogue lines")
        job_path = audio_dir / "tts_job.json"
        result_path = audio_dir / "tts_result.json"
        if result_path.exists():
            result_path.unlink()

        if self.engine == "chatterbox":
            if not self.chatterbox_python or not Path(self.chatterbox_python).exists():
                raise TTSError("Chatterbox is not installed: run scripts\\install-chatterbox.ps1 "
                               "(or set FRAMEFORGE_TTS_ENGINE=kokoro)")
            refs = await self._references(audio_dir, sorted({v.voice for v in voices.values()}), progress)
            job = {"lines": [{
                "id": l.id, "text": l.text, "ref": str(refs[voices[l.character_id].voice]),
                "exaggeration": delivery(l.emotion).exaggeration, "cfg_weight": delivery(l.emotion).cfg_weight,
                "seed": zlib.crc32(l.id.encode()) % 2**31,
            } for _, l in lines]}
            cmd = [self.chatterbox_python, str(CHATTERBOX_WORKER), "--job", str(job_path), "--out", str(audio_dir),
                   "--result", str(result_path)]
            lo = 0.15
        else:
            job = {"lang": self.lang, "lines": [{
                "id": l.id, "text": l.text, "voice": voices[l.character_id].voice,
                "speed": round(voices[l.character_id].speed * delivery(l.emotion).speed, 3),
            } for _, l in lines]}
            cmd = [self.python, str(WORKER), "--job", str(job_path), "--out", str(audio_dir),
                   "--result", str(result_path), "--engine", self.engine]
            lo = 0.05
        job_path.write_text(json.dumps(job), encoding="utf-8")
        log.info("tts: %s lines via %s", len(job["lines"]), self.engine)
        try:
            await run_worker(cmd, Path(cmd[1]).parent, progress, "line", lo=lo, hi=0.85)
        except WorkerError as exc:
            raise TTSError(str(exc)) from exc
        if not result_path.exists():
            raise TTSError("tts worker exited without writing a result file")

        result = json.loads(result_path.read_text(encoding="utf-8"))
        by_id = {l["id"]: l for l in result["lines"]}
        timeline = self._layout(plan, by_id)
        (audio_dir / "dialogue.json").write_text(json.dumps(timeline, indent=1), encoding="utf-8")
        await progress(0.88, "mixing dialogue track")
        self._mix(audio_dir, timeline, int(result.get("sample_rate", 24000)))
        room = await self._room(plan, project_dir, timeline, progress)
        await progress(1.0, None)
        return {
            "engine": result.get("engine", self.engine),
            "lines": len(timeline["lines"]),
            "duration_s": timeline["duration_s"],
            "dialogue": "audio/dialogue.wav",
            "timeline": "audio/dialogue.json",
            "room_mix": room,
        }

    async def _references(self, audio_dir: Path, voice_ids: list[str], progress: ProgressCb) -> dict[str, Path]:
        """Reference clip per Kokoro voice (cached in audio/voices/)."""
        ref_dir = audio_dir / "voices"
        ref_dir.mkdir(exist_ok=True)
        refs = {v: ref_dir / f"ref_{v}.wav" for v in voice_ids}
        missing = [v for v, p in refs.items() if not p.exists()]
        if missing:
            await progress(0.02, "reference voices")
            job = {"lang": self.lang, "lines": [{"id": f"ref_{v}", "text": REFERENCE_TEXT, "voice": v, "speed": 1.0}
                                                for v in missing]}
            job_path, res_path = ref_dir / "refs_job.json", ref_dir / "refs_result.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            try:
                await run_worker([self.python, str(WORKER), "--job", str(job_path), "--out", str(ref_dir),
                                  "--result", str(res_path), "--engine", "kokoro"], WORKER.parent, None, "reference")
            except WorkerError as exc:
                raise TTSError(f"could not create reference voices: {exc}") from exc
        return refs

    @staticmethod
    def _layout(plan: ProductionPlan, by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
        t = 0.0
        lines: list[dict[str, Any]] = []
        scenes: list[dict[str, Any]] = []
        for si, scene in enumerate(plan.scenes):
            scene_start = t
            t += LEAD_IN_S if si == 0 else SCENE_GAP_S
            prev_start = -1.0
            for i, line in enumerate(scene.lines):
                r = by_id.get(line.id)
                if r is None:
                    raise TTSError(f"worker produced no audio for line {line.id}")
                t = max(t, prev_start + MIN_SPACING_S)
                start, end = t, t + float(r["duration_s"])
                lines.append({
                    "id": line.id, "scene_id": scene.id, "character_id": line.character_id, "text": line.text,
                    "emotion": line.emotion, "file": f"audio/{r['file']}", "start_s": round(start, 3),
                    "end_s": round(end, 3), "duration_s": float(r["duration_s"]),
                    "words": [{**w, "start_s": round(start + w["start_s"], 3), "end_s": round(start + w["end_s"], 3)}
                              for w in r.get("words", [])],
                })
                prev_start = start
                if i < len(scene.lines) - 1:
                    nxt = scene.lines[i + 1]
                    t = end + gap_after(line.text, line.emotion, nxt.text, nxt.emotion,
                                        nxt.character_id == line.character_id, line.id)
                else:
                    t = max(end, max(l["end_s"] for l in lines if l["scene_id"] == scene.id)) + TAIL_S
            scenes.append({"id": scene.id, "environment_id": scene.environment_id, "start_s": round(scene_start, 3),
                           "end_s": round(t, 3)})
        return {"version": 2, "duration_s": round(t, 3), "scenes": scenes, "lines": lines}

    @staticmethod
    def _mix(audio_dir: Path, timeline: dict[str, Any], sr: int) -> None:
        """Dry dialogue: lines summed at their positions (overlaps play both voices), clipped to 16 bit.
        Written to dialogue_dry.wav and, until the room mix replaces it, dialogue.wav."""
        total = int(timeline["duration_s"] * sr) + sr // 2
        acc = array("i", bytes(4 * total))
        for line in timeline["lines"]:
            with wave.open(str(audio_dir / Path(line["file"]).name), "rb") as w:
                if w.getframerate() != sr or w.getnchannels() != 1 or w.getsampwidth() != 2:
                    raise TTSError(f"{line['file']}: expected {sr} Hz mono 16-bit")
                samples = array("h", w.readframes(w.getnframes()))
            off = int(line["start_s"] * sr)
            for k in range(min(len(samples), total - off)):
                acc[off + k] += samples[k]
        out = array("h", (max(-32768, min(32767, v)) for v in acc))
        for name in ("dialogue_dry.wav", "dialogue.wav"):
            with wave.open(str(audio_dir / name), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes(out.tobytes())

    async def _room(self, plan: ProductionPlan, project_dir: Path, timeline: dict[str, Any],
                    progress: ProgressCb) -> dict[str, Any]:
        """Scene acoustics on the dialogue track. Needs the worker venv (numpy/scipy). If it is off
        (FRAMEFORGE_ROOM_MIX=false) or fails, the dry track stays as dialogue.wav and the result says why."""
        if not self.room_mix:
            return {"applied": False, "reason": "disabled"}
        envs = {e.id: f"{e.name} {e.description}" for e in plan.environments}
        rooms = {s.id: room_preset(envs.get(s.environment_id, "")) for s in plan.scenes}
        await progress(0.92, "room acoustics")
        try:
            await run_worker([self.python, str(ROOM_WORKER), "--project", str(project_dir),
                              "--rooms", json.dumps(rooms), "--out", "audio/dialogue.wav"],
                             ROOM_WORKER.parent, None, "room")
        except WorkerError as exc:
            log.warning("room mix failed, keeping the dry dialogue: %s", exc)
            shutil.copyfile(project_dir / "audio" / "dialogue_dry.wav", project_dir / "audio" / "dialogue.wav")
            return {"applied": False, "reason": str(exc)[:300]}
        return {"applied": True, "rooms": rooms}
