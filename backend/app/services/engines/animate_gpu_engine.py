"""Phase 5/6 (GPU mode): speaking shots rendered by an audio-driven video model (Wan 2.2 S2V).

Flow, per project:
  1. The CPU animator plans the shot list (single-character framing for every spoken line) and renders
     each speaking shot's first frame with the mouth closed: the reference image for S2V.
  2. For each speaking shot, the matching slice of the speaker's line audio is cut (padded with silence
     to whole S2V chunks), both files are uploaded to ComfyUI, and the S2V template is run with as many
     extension chunks as the shot needs. Clips are checkpointed in render/s2v/ and reused when the shot,
     audio and settings are unchanged, so a failed or cancelled render resumes where it stopped.
  3. The CPU animator renders the full picture track, splicing the S2V clips in for the speaking shots
     and drawing the rest (establishing and reaction shots) procedurally.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import shutil
import wave
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ...plan import ProductionPlan
from ..subproc import WorkerError, run_worker
from .animate_engine import PROFILES, WORKER, AnimateError
from .comfy_engine import ComfyEngine

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]

S2V_WORKFLOW = "video_wan22_s2v"

# S2V generation settings per project quality. Output is upscaled to the animate profile size.
# Measured on an RTX 4090 Laptop (16 GB), one 77-frame chunk: 4 steps + Lightning LoRA ~95-110 s at
# 848x480 and ~180 s at 1024x576 (peak ~14.5 GB VRAM); lips track the audio (mouth/loudness r=0.56 at
# zero lag). 20 steps / CFG 6 without the LoRA took ~900 s per chunk and was more expressive, but heads
# turned away and drifted out of frame, so both qualities use the Lightning setting.
S2V_PROFILES: dict[str, dict[str, Any]] = {
    "draft": {"width": 848, "height": 480, "steps": 4, "cfg": 1.0, "lora_strength": 1.0},
    "final": {"width": 1024, "height": 576, "steps": 4, "cfg": 1.0, "lora_strength": 1.0},
}

STAGE_STILLS = (0.0, 0.03)
STAGE_S2V = (0.03, 0.90)
STAGE_COMPOSE = (0.90, 1.0)


def chunk_count(duration_s: float, fps: int, chunk_frames: int, tolerance_s: float = 0.5) -> int:
    """Number of S2V chunks needed to cover a shot. Up to `tolerance_s` past the last whole chunk is
    covered by holding the final frame instead of paying for another chunk (~100 s each): a speaking
    shot runs until the next line starts, so its tail is nearly always the pause after the speech."""
    frames = math.ceil(duration_s * fps) - int(tolerance_s * fps)
    return max(1, math.ceil(frames / chunk_frames))


def extend_graph(graph: dict[str, Any], hints: dict[str, Any], chunks: int) -> dict[str, Any]:
    """Append (chunks - 1) WanSoundImageToVideoExtend + KSampler + LatentConcat groups, mirroring the
    "Video S2V Extend" subgraph of ComfyUI's template, and re-point every consumer of the first chunk's
    latent at the concatenated result."""
    if chunks <= 1:
        return graph
    ext = hints["extend"]
    graph = copy.deepcopy(graph)
    src = list(ext["latent_source"])
    base_sampler = graph[ext["sampler_node"]]["inputs"]
    length = graph[ext["length_node"]]["inputs"]["length"]
    prev = src
    new: dict[str, Any] = {}
    for k in range(1, chunks):
        e, s, c = f"ext{k}", f"ext{k}_sample", f"ext{k}_concat"
        new[e] = {"class_type": "WanSoundImageToVideoExtend", "inputs": {
            "positive": ext["positive"], "negative": ext["negative"], "vae": ext["vae"], "length": length,
            "video_latent": prev, "audio_encoder_output": ext["audio_encoder_output"], "ref_image": ext["ref_image"]}}
        new[s] = {"class_type": "KSampler", "inputs": {
            **{k2: base_sampler[k2] for k2 in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise")},
            "model": ext["model"], "positive": [e, 0], "negative": [e, 1], "latent_image": [e, 2]}}
        new[c] = {"class_type": "LatentConcat", "inputs": {"samples1": prev, "samples2": [s, 0], "dim": "t"}}
        prev = [c, 0]
    for node in graph.values():
        for key, value in node.get("inputs", {}).items():
            if value == src:
                node["inputs"][key] = prev
    graph.update(new)
    return graph


def slice_audio(src: Path, dst: Path, offset_s: float, duration_s: float, pad_to_s: float) -> None:
    """Cut [offset, offset+duration) out of a WAV and pad with silence to pad_to_s seconds."""
    with wave.open(str(src), "rb") as w:
        params = w.getparams()
        rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
        w.setpos(min(max(0, int(offset_s * rate)), w.getnframes()))
        data = w.readframes(max(0, int(duration_s * rate)))
    frame_bytes = width * ch
    want = int(pad_to_s * rate) * frame_bytes
    data = data[:want] + b"\x00" * max(0, want - len(data))
    with wave.open(str(dst), "wb") as out:
        out.setparams(params)
        out.writeframes(data)


def shot_prompt(plan: ProductionPlan, character_id: str, emotion: str) -> str:
    """Describes who talks and how; the words themselves come from the audio (quoting them in the prompt
    invites the model to draw text)."""
    c = next((x for x in plan.characters if x.id == character_id), None)
    who = f"A {c.species}" if c and c.species else "The character"
    look = f" ({c.appearance})" if c and c.appearance else ""
    mood = f" in a {emotion} way" if emotion else ""
    return (f"{who}{look} is talking{mood}, looking toward someone just off camera. Clear, expressive mouth and "
            f"lip movement that matches the speech, subtle natural head motion and blinking. {plan.style} style. "
            f"The camera is still and the background stays the same.")


class GpuAnimateEngine:
    def __init__(self, python: str, ffmpeg: str, comfy: ComfyEngine, *, workflow: str = S2V_WORKFLOW) -> None:
        self.python = python
        self.ffmpeg = ffmpeg
        self.comfy = comfy
        self.workflow = workflow

    async def run(self, plan: ProductionPlan, project_dir: Path, quality: str, job_id: str, *,
                  progress: ProgressCb, cancel_requested: Callable[[], bool],
                  max_seconds: float = 0) -> dict[str, Any]:
        timeline_path = project_dir / "audio" / "dialogue.json"
        if not timeline_path.exists():
            raise AnimateError("no dialogue timeline; run the TTS stage first")
        (project_dir / "plan.json").write_text(json.dumps(plan.model_dump(), indent=1), encoding="utf-8")
        prof = PROFILES.get(quality, PROFILES["draft"])
        s2v = S2V_PROFILES.get(quality, S2V_PROFILES["draft"])
        template = self.comfy.registry.get(self.workflow)
        fps, chunk = int(template.hints.get("fps", 16)), int(template.hints.get("chunk_frames", 77))
        base = [self.python, str(WORKER), "--project", str(project_dir), "--shots", "render/shots.json",
                "--width", str(prof["width"]), "--height", str(prof["height"]), "--fps", str(prof["fps"]),
                "--ffmpeg", self.ffmpeg, "--no-two-shots"]

        # 1. shot list + reference stills
        await progress(STAGE_STILLS[0], "planning shots")
        try:
            await run_worker(base + ["--stills", "speaking", "--stills-dir", "render/s2v"], WORKER.parent, None, "stills")
        except WorkerError as exc:
            raise AnimateError(str(exc)) from exc
        shots = json.loads((project_dir / "render" / "shots.json").read_text(encoding="utf-8"))
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        lines = {l["id"]: l for l in timeline["lines"]}
        texts = {l.id: (l.text, l.emotion) for s in plan.scenes for l in s.lines}
        speaking = [s for s in shots if s["kind"] == "speaking" and s.get("line_id") in lines]
        if max_seconds:
            speaking = [s for s in speaking if s["start_s"] < max_seconds]

        # 2. S2V clip per speaking shot (checkpointed)
        s2v_dir = project_dir / "render" / "s2v"
        clips: dict[str, str] = {}
        total_s = sum(s["end_s"] - s["start_s"] for s in speaking) or 1.0
        done_s = 0.0
        generated = reused = 0
        timings: list[dict[str, Any]] = []
        lo, hi = STAGE_S2V
        for shot in speaking:
            sid, dur = shot["id"], shot["end_s"] - shot["start_s"]
            line = lines[shot["line_id"]]
            n_chunks = chunk_count(dur, fps, chunk)
            text, emotion = texts.get(line["id"], ("", ""))
            settings = {"workflow": template.key, "s2v": s2v, "chunks": n_chunks, "start": round(shot["start_s"], 3),
                        "end": round(shot["end_s"], 3), "line": line["id"], "speaker": shot["speaker_id"],
                        "text": text, "audio": line["file"], "still": _sha(s2v_dir / f"{sid}.png")}
            clip, meta = s2v_dir / f"{sid}.mp4", s2v_dir / f"{sid}.json"
            if clip.exists() and meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("settings") == settings:
                reused += 1
            else:
                wav = s2v_dir / f"{sid}.wav"
                slice_audio(project_dir / line["file"], wav, shot["start_s"] - line["start_s"], dur,
                            n_chunks * chunk / fps)
                stem = f"ff_{project_dir.name}_{sid}"
                img_name = await self.comfy.client.upload((s2v_dir / f"{sid}.png").read_bytes(), f"{stem}.png")
                wav_name = await self.comfy.client.upload(wav.read_bytes(), f"{stem}.wav")
                params = {"prompt": shot_prompt(plan, shot["speaker_id"], emotion), "image": img_name,
                          "audio": wav_name, "width": s2v["width"], "height": s2v["height"], "steps": s2v["steps"],
                          "cfg": s2v["cfg"], "lora_strength": s2v["lora_strength"], "length": chunk, "fps": fps}

                async def sub(v: float, _node: str | None, _done: float = done_s, _dur: float = dur,
                              _sid: str = sid) -> None:
                    await progress(lo + (hi - lo) * (_done + v * _dur) / total_s, f"talking shot {_sid}")

                tmp = project_dir / "jobs" / job_id / f"s2v_{sid}"
                result = await self.comfy.run(f"{job_id}-s2v-{sid}", {"workflow": self.workflow, "params": params},
                                              tmp, progress=sub, persist_payload=_noop, cancel_requested=cancel_requested,
                                              graph_hook=lambda g, t, _r, _n=n_chunks: extend_graph(g, t.hints, _n))
                video = next((o for o in result["outputs"] if o["kind"] == "video"), None)
                if video is None:
                    raise AnimateError(f"S2V produced no video for shot {sid}")
                shutil.copyfile(tmp / video["filename"], clip)
                meta.write_text(json.dumps({"settings": settings, "seed": result["params"].get("seed"),
                                            "duration_s": result["duration_s"]}, indent=1), encoding="utf-8")
                generated += 1
                timings.append({"shot": sid, "seconds_of_video": round(dur, 2), "chunks": n_chunks,
                                "render_s": result["duration_s"]})
                log.info("S2V shot %s: %.2f s of video, %d chunk(s), %.1f s render", sid, dur, n_chunks,
                         result["duration_s"])
            clips[sid] = f"render/s2v/{sid}.mp4"
            done_s += dur
            await progress(lo + (hi - lo) * done_s / total_s, f"talking shot {sid}")
        (s2v_dir / "clips.json").write_text(json.dumps(clips, indent=1), encoding="utf-8")

        # 3. full picture track with the clips spliced in
        cmd = base + ["--out", "render/video_silent.mp4", "--clips", "render/s2v/clips.json"]
        if max_seconds:
            cmd += ["--max-seconds", str(max_seconds)]
        try:
            last = await run_worker(cmd, WORKER.parent, progress, "frame", lo=STAGE_COMPOSE[0], hi=STAGE_COMPOSE[1])
        except WorkerError as exc:
            raise AnimateError(str(exc)) from exc
        try:
            info = json.loads(last)
        except ValueError:
            info = {}
        await progress(1.0, None)
        return {"video": "render/video_silent.mp4", "shots": "render/shots.json", "profile": prof, "mode": "gpu",
                "s2v": {"workflow": template.key, **s2v, "speaking_shots": len(speaking), "generated": generated,
                        "reused": reused, "timings": timings}, **info}


def _sha(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16] if path.exists() else ""


async def _noop(_payload: dict[str, Any]) -> None:
    pass
