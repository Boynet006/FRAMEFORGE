"""Expressive TTS worker: Resemble AI Chatterbox (MIT), run in backend/.venv-chatterbox (own torch pin).

    python chatterbox_worker.py --job job.json --out <dir> --result result.json

job.json: {"lines": [{"id", "text", "ref": "<reference wav, ~10 s of the character's voice>",
                      "exaggeration": 0.5, "cfg_weight": 0.5, "seed": 123}, ...]}
result.json: same shape as kokoro_worker: {"sample_rate", "engine", "lines": [{"id", "file", "duration_s", "words"}]}

Every line is cloned from its character's reference clip, so a character keeps one voice for the whole
film while delivery follows the line's emotion. Leading/trailing silence is trimmed so the timeline,
not the model, decides the pauses. Chatterbox gives no word timings; "words" are estimated by spreading
the line's words over its voiced span (nothing downstream needs exact word times today).
Output is 24 kHz mono 16-bit like Kokoro, so both engines feed the same timeline and mixer.
Generated audio carries Resemble's imperceptible Perth watermark (built into the library).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SR_OUT = 24000


def trim_silence(audio, sr: int, threshold_db: float = -42.0, keep_s: float = 0.04):
    """Cut leading/trailing near-silence, keeping a few ms so consonants aren't clipped."""
    import numpy as np

    if audio.size == 0:
        return audio
    frame = max(1, int(sr * 0.01))
    n = len(audio) // frame
    if n == 0:
        return audio
    rms = np.sqrt(np.mean(audio[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    level = 20 * np.log10(rms / (np.max(rms) + 1e-12))
    voiced = np.where(level > threshold_db)[0]
    if voiced.size == 0:
        return audio
    keep = int(keep_s * sr)
    start = max(0, voiced[0] * frame - keep)
    end = min(len(audio), (voiced[-1] + 1) * frame + keep)
    return audio[start:end]


def estimate_words(text: str, duration_s: float) -> list[dict]:
    words = text.split()
    if not words:
        return []
    weights = [max(1, len(w.strip(".,!?;:'\"—-"))) + 1 for w in words]
    total = sum(weights)
    t, out = 0.0, []
    for w, k in zip(words, weights):
        d = duration_s * k / total
        out.append({"text": w, "start_s": round(t, 3), "end_s": round(t + d, 3), "estimated": True})
        t += d
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--result", required=True)
    args = ap.parse_args()
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    import numpy as np
    import soundfile as sf
    import torch
    from chatterbox.tts import ChatterboxTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"INFO chatterbox on {device}", file=sys.stderr, flush=True)
    model = ChatterboxTTS.from_pretrained(device=device)
    sr = int(model.sr)
    lines = []
    n = len(job["lines"])
    for i, line in enumerate(job["lines"], 1):
        torch.manual_seed(int(line.get("seed", 0)))
        wav = model.generate(
            line["text"],
            audio_prompt_path=line["ref"],
            exaggeration=float(line.get("exaggeration", 0.5)),
            cfg_weight=float(line.get("cfg_weight", 0.5)),
        )
        audio = wav.squeeze(0).detach().cpu().numpy().astype(np.float32)
        if sr != SR_OUT:
            import librosa

            audio = librosa.resample(audio, orig_sr=sr, target_sr=SR_OUT)
        audio = trim_silence(audio, SR_OUT)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 0.98:
            audio = audio * (0.98 / peak)
        f = out / f"{line['id']}.wav"
        sf.write(str(f), audio, SR_OUT, subtype="PCM_16")
        dur = len(audio) / SR_OUT
        lines.append({"id": line["id"], "file": f.name, "duration_s": round(dur, 3),
                      "words": estimate_words(line["text"], dur)})
        print(f"PROGRESS {i} {n}", flush=True)
    Path(args.result).write_text(json.dumps({"sample_rate": SR_OUT, "engine": "chatterbox", "lines": lines}),
                                 encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
