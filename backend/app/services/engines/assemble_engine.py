"""Phase 7: final assembly with FFmpeg.

picture track + dialogue track + procedural music + burned-in subtitles -> render/final.mp4
plus quality checks (durations, stream presence) recorded in the job result.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ...plan import ProductionPlan
from ..subproc import WorkerError, run_cmd, run_worker

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]
MUSIC_WORKER = Path(__file__).resolve().parent.parent.parent.parent / "media_worker" / "music_worker.py"


class AssembleError(RuntimeError):
    pass


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _wrap(text: str, width: int = 42) -> str:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > 2:  # balance into two lines
        half = len(words) // 2
        lines = [" ".join(words[:half]), " ".join(words[half:])]
    return "\n".join(lines)


def write_srt(plan: ProductionPlan, timeline: dict[str, Any], path: Path) -> int:
    names = {c.id: c.name for c in plan.characters}
    cues: list[str] = []
    for i, line in enumerate(timeline["lines"], 1):
        end = max(line["end_s"], line["start_s"] + 0.8)
        text = _wrap(f"{names.get(line['character_id'], '')}: {line['text']}")
        cues.append(f"{i}\n{_ts(line['start_s'])} --> {_ts(end)}\n{text}\n")
    path.write_text("\n".join(cues), encoding="utf-8")
    return len(cues)


async def _run(cmd: list[str], what: str) -> str:
    try:
        return await run_cmd(cmd, what)
    except WorkerError as exc:
        raise AssembleError(str(exc)) from exc


async def probe(ffprobe: str, path: Path) -> dict[str, Any]:
    out = await _run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                     "ffprobe")
    data = json.loads(out)
    streams = {s["codec_type"]: s for s in data.get("streams", [])}
    return {
        "duration_s": float(data.get("format", {}).get("duration", 0) or 0),
        "size_bytes": int(data.get("format", {}).get("size", 0) or 0),
        "video": {k: streams["video"].get(k) for k in ("codec_name", "width", "height", "r_frame_rate")} if "video" in streams else None,
        "audio": {k: streams["audio"].get(k) for k in ("codec_name", "sample_rate", "channels")} if "audio" in streams else None,
    }


class AssembleEngine:
    def __init__(self, python: str | None, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self.python = python or sys.executable
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    async def run(self, plan: ProductionPlan, project_dir: Path, *, progress: ProgressCb) -> dict[str, Any]:
        video = project_dir / "render" / "video_silent.mp4"
        dialogue = project_dir / "audio" / "dialogue.wav"
        tl_path = project_dir / "audio" / "dialogue.json"
        for p, what in ((video, "picture track (run animate)"), (dialogue, "dialogue track (run tts)")):
            if not p.exists():
                raise AssembleError(f"missing {what}: {p.name}")
        if not shutil.which(self.ffmpeg) and not Path(self.ffmpeg).exists():
            raise AssembleError(f"ffmpeg not found ({self.ffmpeg}); install FFmpeg and/or set FRAMEFORGE_FFMPEG")
        timeline = json.loads(tl_path.read_text(encoding="utf-8"))
        render = project_dir / "render"
        render.mkdir(exist_ok=True)

        await progress(0.05, "subtitles")
        srt = render / "subtitles.srt"
        n_cues = write_srt(plan, timeline, srt) if plan.subtitles else 0

        inputs = ["-i", str(video), "-i", str(dialogue)]
        music_path = project_dir / "audio" / "music.wav"
        has_music = False
        if plan.music.enabled:
            await progress(0.15, "music")
            try:
                await run_worker([self.python, str(MUSIC_WORKER), "--mood", plan.music.mood,
                                  "--duration", str(timeline["duration_s"] + 0.5), "--out", str(music_path)],
                                 MUSIC_WORKER.parent, progress, "music", lo=0.15, hi=0.3)
            except WorkerError as exc:
                raise AssembleError(str(exc)) from exc
            inputs += ["-i", str(music_path)]
            has_music = True

        await progress(0.35, "encoding")
        if has_music:
            afilter = (f"[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo,volume=1.0[d];"
                       f"[2:a]aformat=sample_fmts=fltp:channel_layouts=stereo,volume={plan.music.volume_db}dB[m];"
                       f"[d][m]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a]")
        else:
            afilter = "[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a]"
        vfilters: list[str] = []
        if n_cues:
            # ffmpeg's subtitles filter needs forward slashes and escaped colons on Windows
            srt_arg = str(srt).replace("\\", "/").replace(":", "\\:")
            vfilters.append(f"subtitles='{srt_arg}':force_style='FontSize=20,Outline=1,Shadow=0,MarginV=28'")
        final = render / "final.mp4"
        cmd = [self.ffmpeg, "-y", "-loglevel", "error", *inputs, "-filter_complex", afilter,
               "-map", "0:v:0", "-map", "[a]"]
        if vfilters:
            cmd += ["-vf", ",".join(vfilters)]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(final)]
        await _run(cmd, "ffmpeg assembly")

        await progress(0.9, "checking")
        info = await probe(self.ffprobe, final)
        checks: list[dict[str, Any]] = []
        expected = float(timeline["duration_s"])
        drift = abs(info["duration_s"] - expected)
        checks.append({"check": "duration_matches_timeline", "ok": drift <= 1.0,
                       "detail": f"final {info['duration_s']:.2f}s vs timeline {expected:.2f}s"})
        checks.append({"check": "has_video_stream", "ok": info["video"] is not None})
        checks.append({"check": "has_audio_stream", "ok": info["audio"] is not None})
        checks.append({"check": "subtitles_written", "ok": (n_cues > 0) == plan.subtitles, "detail": f"{n_cues} cues"})
        await progress(1.0, None)
        return {"final": "render/final.mp4", "subtitles": "render/subtitles.srt" if n_cues else None,
                "music": "audio/music.wav" if has_music else None, "probe": info, "checks": checks,
                "ok": all(c["ok"] for c in checks)}
