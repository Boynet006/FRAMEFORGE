"""Procedural background music (no model, no download): a soft chord pad with a
light arpeggio, shaped by a mood string. Runs in backend/.venv-tts (numpy).

    python music_worker.py --mood "playful jazz" --duration 62.5 --out audio/music.wav [--seed 7]
"""

from __future__ import annotations

import argparse
import math
import random
import wave

import numpy as np

SR = 44100

# mood keywords -> (tempo bpm, chord progression as semitone roots, major?, brightness)
MOODS = {
    "playful": (112, [0, 7, 9, 5], True, 1.0),
    "jazz": (96, [0, 5, 7, 2], True, 0.8),
    "tense": (84, [0, 8, 3, 7], False, 0.5),
    "sad": (72, [0, 8, 5, 3], False, 0.4),
    "epic": (90, [0, 5, 3, 7], False, 0.9),
    "calm": (76, [0, 5, 9, 7], True, 0.6),
    "light": (104, [0, 9, 5, 7], True, 0.9),
}


def _pick(mood: str) -> tuple[int, list[int], bool, float]:
    m = mood.lower()
    for key, val in MOODS.items():
        if key in m:
            return val
    return MOODS["light"]


def _note(freq: float, n: int, attack: float, release: float, wave_mix: float) -> np.ndarray:
    t = np.arange(n) / SR
    sig = np.sin(2 * math.pi * freq * t) * (1 - wave_mix) + wave_mix * (2 / math.pi) * np.arcsin(np.sin(2 * math.pi * freq * t))
    env = np.ones(n)
    a = max(1, int(attack * SR))
    r = max(1, int(release * SR))
    env[:a] = np.linspace(0, 1, a)
    env[-r:] *= np.linspace(1, 0, r)
    return sig * env


def _add(out: np.ndarray, start: int, sig: np.ndarray) -> None:
    """Mix `sig` into `out` at `start`, clipping to the buffer."""
    if start >= len(out):
        return
    n = min(len(sig), len(out) - start)
    out[start:start + n] += sig[:n]


def render(mood: str, duration: float, seed: int) -> np.ndarray:
    rng = random.Random(seed)
    bpm, prog, major, bright = _pick(mood)
    beat = 60 / bpm
    bar = beat * 4
    base = 110.0 * (2 ** (rng.choice([0, 2, 3, 5]) / 12))  # A2.. transposed
    third = 4 if major else 3
    total = int(duration * SR)
    out = np.zeros(total + SR, dtype=np.float64)
    t = 0.0
    bar_i = 0
    while t < duration:
        root = base * 2 ** (prog[bar_i % len(prog)] / 12)
        n = int(bar * SR)
        start = int(t * SR)
        # pad: root, third, fifth, octave
        for k, semis in enumerate((0, third, 7, 12)):
            f = root * 2 ** (semis / 12)
            amp = 0.11 if k < 3 else 0.06
            _add(out, start, amp * _note(f, n, 0.6, 0.8, 0.25 * bright))
        # arpeggio on eighth notes
        for e in range(8):
            if rng.random() < 0.35:
                continue
            semis = rng.choice((0, third, 7, 12, 12 + third))
            f = root * 2 ** (semis / 12) * 2
            s0 = start + int(e * beat / 2 * SR)
            m = int(beat * 0.45 * SR)
            _add(out, s0, 0.07 * bright * _note(f, m, 0.01, 0.2, 0.0))
        t += bar
        bar_i += 1
    out = out[:total]
    # gentle low-pass via moving average, fade in/out, normalise
    k = 24
    out = np.convolve(out, np.ones(k) / k, mode="same")
    fade = int(min(2.0, duration / 4) * SR)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    peak = np.max(np.abs(out)) or 1.0
    out = out / peak * 0.6
    stereo = np.stack([out, np.roll(out, 300)], axis=1)
    return (stereo * 32767).astype(np.int16)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mood", default="light, playful")
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    data = render(args.mood, args.duration, args.seed)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    print(f"wrote {args.out} {args.duration:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
