"""Text-to-speech worker. Runs in its own interpreter (backend/.venv-tts, Python 3.12)
because Kokoro's dependencies are not available for the backend's Python.

    python kokoro_worker.py --job job.json --out <dir> --result result.json [--engine kokoro|fake]

job.json: {"lang": "a", "lines": [{"id": "s1l1", "text": "...", "voice": "af_heart", "speed": 1.0}, ...]}
result.json: {"sample_rate": 24000, "lines": [{"id", "file", "duration_s", "words": [{"text","start_s","end_s"}]}]}

Progress is reported on stdout as lines "PROGRESS <i> <n>". The "fake" engine
writes synthetic audio (tone bursts per word) with the same result shape; it
exists so the pipeline can be tested on machines without Kokoro installed.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import wave
from pathlib import Path

SR = 24000
WORDS_PER_SECOND = 2.4


def _write_wav(path: Path, samples: list[float] | "object", sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for s in samples:
            v = max(-1.0, min(1.0, float(s)))
            frames += struct.pack("<h", int(v * 32767))
        w.writeframes(bytes(frames))


def _fake_line(text: str, speed: float) -> tuple[list[float], list[dict]]:
    words = text.split()
    per_word = 1.0 / (WORDS_PER_SECOND * speed)
    samples: list[float] = []
    timings: list[dict] = []
    t = 0.0
    for i, w in enumerate(words):
        dur = per_word * (0.6 + min(len(w), 10) / 12)
        n = int(dur * SR)
        freq = 180.0 + (i % 5) * 25
        for k in range(n):
            env = math.sin(math.pi * k / n)  # smooth burst
            samples.append(0.25 * env * math.sin(2 * math.pi * freq * k / SR))
        timings.append({"text": w, "start_s": round(t, 3), "end_s": round(t + dur, 3)})
        t += dur
        gap = int(0.06 * SR)
        samples.extend([0.0] * gap)
        t += 0.06
    return samples, timings


def run_fake(job: dict, out: Path) -> dict:
    lines = []
    n = len(job["lines"])
    for i, line in enumerate(job["lines"], 1):
        samples, words = _fake_line(line["text"], float(line.get("speed", 1.0)))
        f = out / f"{line['id']}.wav"
        _write_wav(f, samples)
        lines.append({"id": line["id"], "file": f.name, "duration_s": round(len(samples) / SR, 3), "words": words})
        print(f"PROGRESS {i} {n}", flush=True)
    return {"sample_rate": SR, "engine": "fake", "lines": lines}


def _voiced_span(audio, sr: int, threshold_db: float = -42.0, keep_s: float = 0.04) -> tuple[int, int]:
    """Sample range without leading/trailing near-silence (a few ms kept so consonants survive)."""
    import numpy as np

    frame = max(1, int(sr * 0.01))
    n = len(audio) // frame
    if n == 0:
        return 0, len(audio)
    rms = np.sqrt(np.mean(audio[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    level = 20 * np.log10(rms / (np.max(rms) + 1e-12))
    voiced = np.where(level > threshold_db)[0]
    if voiced.size == 0:
        return 0, len(audio)
    keep = int(keep_s * sr)
    return max(0, voiced[0] * frame - keep), min(len(audio), (voiced[-1] + 1) * frame + keep)


def run_kokoro(job: dict, out: Path) -> dict:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    lang = job.get("lang", "a")
    pipeline = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
    lines = []
    n = len(job["lines"])
    for i, line in enumerate(job["lines"], 1):
        chunks: list[np.ndarray] = []
        words: list[dict] = []
        offset = 0.0
        for result in pipeline(line["text"], voice=line.get("voice", "af_heart"), speed=float(line.get("speed", 1.0))):
            audio = result.audio
            if audio is None:
                continue
            arr = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            chunks.append(arr.astype(np.float32))
            for tok in getattr(result, "tokens", None) or []:
                st, et = getattr(tok, "start_ts", None), getattr(tok, "end_ts", None)
                text = (getattr(tok, "text", "") or "").strip()
                if st is not None and et is not None and text:
                    words.append({"text": text, "start_s": round(offset + float(st), 3), "end_s": round(offset + float(et), 3)})
            offset += len(arr) / SR
        data = np.concatenate(chunks) if chunks else np.zeros(int(0.3 * SR), dtype=np.float32)
        # trim edge silence so the timeline, not the model, decides the pauses (same as chatterbox_worker)
        start, end = _voiced_span(data, SR)
        data = data[start:end]
        lead = start / SR
        words = [{**w, "start_s": round(max(0.0, w["start_s"] - lead), 3), "end_s": round(max(0.0, w["end_s"] - lead), 3)}
                 for w in words]
        f = out / f"{line['id']}.wav"
        f.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(f), data, SR)
        lines.append({"id": line["id"], "file": f.name, "duration_s": round(len(data) / SR, 3), "words": words})
        print(f"PROGRESS {i} {n}", flush=True)
    return {"sample_rate": SR, "engine": "kokoro", "lines": lines}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--engine", default="kokoro", choices=["kokoro", "fake"])
    args = ap.parse_args()
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = run_fake(job, out) if args.engine == "fake" else run_kokoro(job, out)
    Path(args.result).write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
