"""Dialogue room mix: per-line speech -> one stereo dialogue track that sounds like it was recorded in
the scene's location. Runs in backend/.venv-tts (numpy + scipy).

    python room_worker.py --project <dir> --rooms '{"s1": "small"}' --out audio/dialogue.wav

Reads audio/dialogue.json (line files and start times). Lines are summed, so slight overlaps
(interruptions) play both voices. Per scene, the dry speech is convolved with a synthetic impulse
response for its room preset (outdoor: none, small: ~0.35 s, large: ~1.3 s), using slightly different
left/right responses for width. A gentle high-pass removes rumble. Output: 24 kHz stereo 16-bit.
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

ROOMS = {
    # rt60 (s), pre-delay (s), wet gain, damping low-pass (Hz)
    "outdoor": None,
    "small": (0.35, 0.008, 0.16, 5500.0),
    "large": (1.30, 0.022, 0.24, 4000.0),
}


def impulse_response(preset: str, sr: int, seed: int) -> np.ndarray | None:
    p = ROOMS.get(preset)
    if p is None:
        return None
    rt60, pre, _wet, lp = p
    rng = np.random.default_rng(seed)
    n = int(sr * (pre + rt60 * 1.1))
    t = np.arange(n) / sr
    tail = rng.standard_normal(n) * np.exp(-6.91 * np.maximum(t - pre, 0) / rt60)
    tail[: int(pre * sr)] = 0.0
    tail = sosfilt(butter(2, lp, "low", fs=sr, output="sos"), tail)
    # a few early reflections give the room its size
    for delay_ms, gain in ((7, 0.55), (11, 0.4), (17, 0.32), (23, 0.25), (31, 0.18)):
        i = int((pre + delay_ms / 1000 * (rt60 / 0.35) ** 0.5) * sr)
        if i < n:
            tail[i] += gain * (1 if rng.random() > 0.5 else -1)
    return tail / (np.sqrt(np.sum(tail ** 2)) + 1e-12)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--rooms", default="{}", help="JSON {scene_id: outdoor|small|large}")
    ap.add_argument("--out", default="audio/dialogue.wav")
    args = ap.parse_args()
    project = Path(args.project)
    timeline = json.loads((project / "audio" / "dialogue.json").read_text(encoding="utf-8"))
    rooms: dict[str, str] = json.loads(args.rooms)

    sr = 24000
    total = int((timeline["duration_s"] + 2.0) * sr)
    dry = np.zeros(total, dtype=np.float32)
    for line in timeline["lines"]:
        audio, sr_line = read_wav(project / line["file"])
        if sr_line != sr:
            raise SystemExit(f"{line['file']}: expected {sr} Hz, got {sr_line}")
        off = int(line["start_s"] * sr)
        end = min(off + len(audio), total)
        dry[off:end] += audio[: end - off]
    dry = sosfilt(butter(2, 80.0, "high", fs=sr, output="sos"), dry).astype(np.float32)

    left, right = dry.copy(), dry.copy()
    for k, scene in enumerate(timeline["scenes"]):
        preset = rooms.get(scene["id"], "small")
        if ROOMS.get(preset) is None:
            continue
        wet_gain = ROOMS[preset][2]
        a, b = int(scene["start_s"] * sr), min(int(scene["end_s"] * sr), total)
        seg = dry[a:b]
        if seg.size == 0:
            continue
        for chan, seed in ((left, 1000 + k), (right, 2000 + k)):
            ir = impulse_response(preset, sr, seed)
            wet = fftconvolve(seg, ir)[: total - a] * wet_gain
            chan[a:a + len(wet)] += wet.astype(np.float32)
        print(f"INFO scene {scene['id']}: room {preset}", file=sys.stderr, flush=True)

    stereo = np.stack([left, right], axis=1)
    stereo = stereo[: int(timeline["duration_s"] * sr) + sr // 2]
    peak = float(np.max(np.abs(stereo))) or 1.0
    if peak > 0.97:
        stereo *= 0.97 / peak
    out = project / args.out
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())
    print(json.dumps({"out": args.out, "rooms": {s["id"]: rooms.get(s["id"], "small") for s in timeline["scenes"]},
                      "duration_s": round(len(stereo) / sr, 3)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
