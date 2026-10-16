"""CPU animator: plan + dialogue timeline + reference images -> silent video.

Runs in backend/.venv-tts (Python 3.12 with numpy, Pillow, OpenCV, rembg).
This is the "animatic" render mode for machines without a GPU: characters are
cut out of their reference portraits and placed in their environment; the
speaking character's mouth is driven by the real dialogue audio envelope;
blinks, head motion, listener reactions, shot/reverse-shot cutting and camera
moves are procedural. On a GPU machine the same shot list drives audio-driven
video models instead (Phase 5/6 GPU path).

    python animate_worker.py --project <dir> --out render/video_silent.mp4 --shots render/shots.json
                             [--width 1280 --height 720 --fps 24 --ffmpeg ffmpeg]

stdout: "PROGRESS <frame> <total>" lines.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ----------------------------------------------------------------------------- data


@dataclass
class Shot:
    id: str
    start_s: float
    end_s: float
    kind: str            # wide | speaking | reaction | two
    environment_id: str
    speaker_id: str | None = None   # character whose line plays
    framed_id: str | None = None    # character on screen (reaction shots frame the listener)
    line_id: str | None = None
    framing: str = "medium"         # close | medium | two | wide
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class CharacterAsset:
    id: str
    image: Image.Image            # RGBA cutout, padded so jaw warps never clip
    face: tuple[int, int, int, int]   # x, y, w, h in cutout coordinates
    skin: tuple[int, int, int]
    seed: int


# ----------------------------------------------------------------------------- shot planning


def plan_shots(plan: dict[str, Any], timeline: dict[str, Any]) -> list[Shot]:
    chars = [c["id"] for c in plan["characters"]]
    shots: list[Shot] = []
    lines = timeline["lines"]
    scenes = timeline["scenes"]
    for scene in scenes:
        s_lines = [l for l in lines if l["scene_id"] == scene["id"]]
        env = scene["environment_id"]
        first_start = s_lines[0]["start_s"] if s_lines else scene["end_s"]
        if first_start - scene["start_s"] > 0.15:
            shots.append(Shot(f"{scene['id']}_est", scene["start_s"], first_start, "wide", env, framing="wide"))
        for i, line in enumerate(s_lines):
            nxt = s_lines[i + 1]["start_s"] if i + 1 < len(s_lines) else scene["end_s"]
            speaker = line["character_id"]
            listener = next((c for c in chars if c != speaker), None)
            framing = "two" if (i % 4 == 3 and listener) else ("close" if i % 2 == 0 else "medium")
            dur = nxt - line["start_s"]
            # long line: cut to the listener for a reaction in the middle, then back
            if dur > 5.0 and listener and framing != "two":
                a = line["start_s"] + dur * 0.55
                b = min(a + 1.1, nxt - 0.6)
                shots.append(Shot(f"{line['id']}_a", line["start_s"], a, "speaking", env, speaker, speaker, line["id"], framing))
                shots.append(Shot(f"{line['id']}_r", a, b, "reaction", env, speaker, listener, line["id"], "medium"))
                shots.append(Shot(f"{line['id']}_b", b, nxt, "speaking", env, speaker, speaker, line["id"], "close"))
            else:
                shots.append(Shot(line["id"], line["start_s"], nxt, "two" if framing == "two" else "speaking",
                                  env, speaker, speaker, line["id"], framing))
    # make shots contiguous from 0 to the end
    if shots and shots[0].start_s > 0:
        shots[0].start_s = 0.0
    for a, b in zip(shots, shots[1:]):
        a.end_s = b.start_s
    if shots:
        shots[-1].end_s = max(shots[-1].end_s, timeline["duration_s"])
    return shots


# ----------------------------------------------------------------------------- assets


def _cutout(path: Path, cache: Path) -> Image.Image:
    if cache.exists():
        return Image.open(cache).convert("RGBA")
    img = Image.open(path).convert("RGBA")
    try:
        from rembg import remove

        out = remove(img)  # RGBA with alpha matte
        if out.getchannel("A").getextrema()[1] < 10:
            raise RuntimeError("empty matte")
    except Exception as exc:  # noqa: BLE001  (rembg missing/failed -> soft oval mask)
        print(f"WARN cutout fallback for {path.name}: {exc}", file=sys.stderr, flush=True)
        mask = Image.new("L", img.size, 0)
        d = ImageDraw.Draw(mask)
        w, h = img.size
        d.ellipse((w * 0.08, h * 0.02, w * 0.92, h * 1.15), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(w * 0.03))
        out = img.copy()
        out.putalpha(mask)
    out.save(cache)
    return out


def _detect_face(rgba: Image.Image) -> tuple[int, int, int, int]:
    """Largest cat/human face via OpenCV cascades; falls back to the top of the alpha bbox."""
    alpha = np.asarray(rgba.getchannel("A"))
    ys, xs = np.where(alpha > 40)
    if len(xs) == 0:
        w, h = rgba.size
        return int(w * 0.3), int(h * 0.1), int(w * 0.4), int(h * 0.4)
    bx0, bx1, by0, by1 = xs.min(), xs.max(), ys.min(), ys.max()
    try:
        import cv2

        gray = cv2.cvtColor(np.asarray(rgba.convert("RGB")), cv2.COLOR_RGB2GRAY)
        best: tuple[int, int, int, int] | None = None
        for name in ("haarcascade_frontalcatface_extended.xml", "haarcascade_frontalcatface.xml",
                     "haarcascade_frontalface_default.xml"):
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + name)
            if cascade.empty():
                continue
            faces = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4,
                                             minSize=(int(gray.shape[1] * 0.18), int(gray.shape[1] * 0.18)))
            for (x, y, w, h) in faces:
                if best is None or w * h > best[2] * best[3]:
                    best = (int(x), int(y), int(w), int(h))
            if best:
                break
        if best:
            return best
    except Exception as exc:  # noqa: BLE001
        print(f"WARN face detection unavailable: {exc}", file=sys.stderr, flush=True)
    bw = bx1 - bx0
    bh = by1 - by0
    side = int(min(bw * 0.7, bh * 0.5))
    return int(bx0 + (bw - side) / 2), int(by0 + bh * 0.05), side, side


def _skin_color(rgba: Image.Image, face: tuple[int, int, int, int]) -> tuple[int, int, int]:
    x, y, w, h = face
    region = np.asarray(rgba.convert("RGB").crop((x + w * 0.3, y + h * 0.55, x + w * 0.7, y + h * 0.7)))
    if region.size == 0:
        return (120, 100, 90)
    med = np.median(region.reshape(-1, 3), axis=0)
    return tuple(int(v) for v in med)


def load_characters(plan: dict[str, Any], project: Path) -> dict[str, CharacterAsset]:
    out: dict[str, CharacterAsset] = {}
    for i, c in enumerate(plan["characters"]):
        ref = c.get("reference_image")
        if not ref or not (project / ref).exists():
            raise FileNotFoundError(f"character {c['id']} has no reference image; run the refs stage first")
        cut = _cutout(project / ref, project / "refs" / f"cutout_{c['id']}.png")
        # pad so jaw warps and rotation have room
        pad = int(cut.height * 0.12)
        padded = Image.new("RGBA", (cut.width + 2 * pad, cut.height + 2 * pad), (0, 0, 0, 0))
        padded.paste(cut, (pad, pad))
        fx, fy, fw, fh = _detect_face(cut)
        face = (fx + pad, fy + pad, fw, fh)
        out[c["id"]] = CharacterAsset(c["id"], padded, face, _skin_color(padded, face), seed=1000 + i)
        print(f"INFO character {c['id']}: face box {face} in {padded.size}", file=sys.stderr, flush=True)
    return out


def load_environments(plan: dict[str, Any], project: Path, size: tuple[int, int]) -> dict[str, Image.Image]:
    out: dict[str, Image.Image] = {}
    for e in plan["environments"]:
        ref = e.get("reference_image")
        if ref and (project / ref).exists():
            img = Image.open(project / ref).convert("RGB")
        else:
            img = Image.new("RGB", size, (28, 30, 38))
        # oversize for Ken Burns headroom
        target = (int(size[0] * 1.25), int(size[1] * 1.25))
        out[e["id"]] = _cover(img, target)
    return out


def _cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    sw, sh = img.size
    scale = max(size[0] / sw, size[1] / sh)
    img = img.resize((max(1, int(sw * scale + 0.5)), max(1, int(sh * scale + 0.5))), Image.LANCZOS)
    x = (img.width - size[0]) // 2
    y = (img.height - size[1]) // 2
    return img.crop((x, y, x + size[0], y + size[1]))


# ----------------------------------------------------------------------------- audio envelope


class Envelope:
    """Per-frame mouth openness (0..1) from each line's WAV."""

    def __init__(self, project: Path, timeline: dict[str, Any], fps: int) -> None:
        self.fps = fps
        self.lines: dict[str, tuple[float, np.ndarray]] = {}
        for line in timeline["lines"]:
            p = project / line["file"]
            with wave.open(str(p), "rb") as w:
                sr = w.getframerate()
                data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
            hop = max(1, sr // fps)
            n = max(1, len(data) // hop)
            rms = np.array([np.sqrt(np.mean(data[i * hop:(i + 1) * hop] ** 2) + 1e-9) for i in range(n)])
            ref = np.percentile(rms, 95) or 1.0
            env = np.clip(rms / ref, 0, 1) ** 0.7
            # light smoothing so the jaw doesn't flicker
            k = np.array([0.25, 0.5, 0.25])
            env = np.convolve(env, k, mode="same")
            self.lines[line["id"]] = (line["start_s"], env)

    def at(self, line_id: str | None, t: float) -> float:
        if not line_id or line_id not in self.lines:
            return 0.0
        start, env = self.lines[line_id]
        i = int((t - start) * self.fps)
        if i < 0 or i >= len(env):
            return 0.0
        return float(env[i])


# ----------------------------------------------------------------------------- character rendering


def render_character(asset: CharacterAsset, t: float, mouth: float, speaking: bool, rng: random.Random,
                     blink_times: list[float]) -> Image.Image:
    img = asset.image.copy()
    fx, fy, fw, fh = asset.face
    draw = ImageDraw.Draw(img)

    # --- jaw drop: stretch a strip at the mouth line downwards proportional to openness
    mouth_y = int(fy + fh * 0.80)
    mouth_cx = int(fx + fw * 0.5)
    jaw = int(mouth * fh * 0.10)
    if jaw > 0:
        strip_h = max(4, int(fh * 0.06))
        strip = img.crop((fx - fw // 4, mouth_y - strip_h, fx + fw + fw // 4, mouth_y))
        below = img.crop((fx - fw // 4, mouth_y, fx + fw + fw // 4, img.height))
        stretched = strip.resize((strip.width, strip_h + jaw), Image.BILINEAR)
        img.paste(stretched, (fx - fw // 4, mouth_y - strip_h), stretched)
        img.paste(below, (fx - fw // 4, mouth_y + jaw), below)
        draw = ImageDraw.Draw(img)
    # --- mouth interior
    mw = fw * (0.22 + 0.10 * mouth)
    mh = fh * (0.02 + 0.16 * mouth)
    if mouth > 0.08:
        draw.ellipse((mouth_cx - mw / 2, mouth_y + jaw - mh / 2, mouth_cx + mw / 2, mouth_y + jaw + mh / 2),
                     fill=(38, 16, 20, 235))
        if mouth > 0.45:
            tw, th = mw * 0.5, mh * 0.45
            draw.ellipse((mouth_cx - tw / 2, mouth_y + jaw + mh * 0.1, mouth_cx + tw / 2, mouth_y + jaw + mh * 0.1 + th),
                         fill=(170, 70, 85, 220))
    # --- blink
    blinking = any(0 <= t - b < 0.13 for b in blink_times)
    if blinking:
        ey = fy + fh * 0.42
        for ex in (fx + fw * 0.32, fx + fw * 0.68):
            ew, eh = fw * 0.16, fh * 0.07
            draw.ellipse((ex - ew / 2, ey - eh / 2, ex + ew / 2, ey + eh / 2), fill=asset.skin + (255,))
    # --- head motion
    if speaking:
        angle = 1.6 * math.sin(t * 2.1 + asset.seed) + 0.8 * math.sin(t * 5.3)
        dy = 0.012 * fh * math.sin(t * 3.7) * (0.5 + mouth)
    else:
        angle = 0.8 * math.sin(t * 0.9 + asset.seed)
        nod = math.sin(t * 1.3 + asset.seed * 0.5)
        dy = 0.02 * fh * (nod if nod > 0.7 else 0.0)  # occasional nod
    img = img.rotate(angle, resample=Image.BILINEAR, center=(fx + fw / 2, fy + fh * 1.4))
    if abs(dy) >= 1:
        shifted = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shifted.paste(img, (0, int(dy)))
        img = shifted
    return img


# ----------------------------------------------------------------------------- frame composition


def _place(frame: Image.Image, char: Image.Image, height_frac: float, cx_frac: float, mirror: bool) -> None:
    h = int(frame.height * height_frac)
    scale = h / char.height
    w = max(1, int(char.width * scale))
    c = char.resize((w, h), Image.LANCZOS)
    if mirror:
        c = c.transpose(Image.FLIP_LEFT_RIGHT)
    x = int(frame.width * cx_frac - w / 2)
    y = frame.height - h + int(h * 0.12)  # slightly below the bottom edge
    frame.paste(c, (x, y), c)


def compose(shot: Shot, t: float, envs: dict[str, Image.Image], chars: dict[str, CharacterAsset],
            envelope: Envelope, size: tuple[int, int], blinks: dict[str, list[float]], rng: random.Random,
            order: list[str]) -> Image.Image:
    W, H = size
    u = (t - shot.start_s) / max(shot.duration_s, 1e-3)
    bg_full = envs.get(shot.environment_id) or next(iter(envs.values()))
    # Ken Burns: zoom 1.0 -> 1.06, drift sideways
    zoom = 1.0 + 0.06 * u
    vw, vh = int(W / zoom * 1.0), int(H / zoom * 1.0)
    drift = (0.5 + (0.08 * (u - 0.5)) * (1 if hash(shot.id) % 2 else -1))
    x0 = int((bg_full.width - vw) * drift)
    y0 = int((bg_full.height - vh) * 0.5)
    bg = bg_full.crop((x0, y0, x0 + vw, y0 + vh)).resize((W, H), Image.BILINEAR)
    if shot.framing in ("close", "medium"):
        bg = bg.filter(ImageFilter.GaussianBlur(6 if shot.framing == "close" else 3))
    frame = bg.convert("RGBA")

    if shot.framing == "wide":
        # establishing: both characters small in the scene
        for i, cid in enumerate(order[:2]):
            a = chars[cid]
            img = render_character(a, t, 0.0, False, rng, blinks[cid])
            _place(frame, img, 0.55, 0.3 + 0.4 * i, mirror=(i == 1))
    elif shot.framing == "two":
        for i, cid in enumerate(order[:2]):
            a = chars[cid]
            speaking = cid == shot.speaker_id
            img = render_character(a, t, envelope.at(shot.line_id, t) if speaking else 0.0, speaking, rng, blinks[cid])
            _place(frame, img, 0.78, 0.27 + 0.46 * i, mirror=(i == 1))
    else:
        cid = shot.framed_id or shot.speaker_id or order[0]
        a = chars[cid]
        speaking = shot.kind == "speaking"
        img = render_character(a, t, envelope.at(shot.line_id, t) if speaking else 0.0, speaking, rng, blinks[cid])
        side = order.index(cid) if cid in order else 0
        _place(frame, img, 1.15 if shot.framing == "close" else 0.88, 0.42 if side == 0 else 0.58, mirror=(side == 1))
    # subtle vignette
    return frame.convert("RGB")


def _blink_schedule(rng: random.Random, duration: float) -> list[float]:
    times: list[float] = []
    t = rng.uniform(0.8, 2.5)
    while t < duration:
        times.append(t)
        t += rng.uniform(2.2, 5.0)
    return times


# ----------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="render/video_silent.mp4")
    ap.add_argument("--shots", default="render/shots.json")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--max-seconds", type=float, default=0, help="debug: render only the first N seconds")
    args = ap.parse_args()

    project = Path(args.project)
    plan = json.loads((project / "plan.json").read_text(encoding="utf-8"))
    timeline = json.loads((project / "audio" / "dialogue.json").read_text(encoding="utf-8"))
    size = (args.width - args.width % 2, args.height - args.height % 2)

    shots = plan_shots(plan, timeline)
    out_path = project / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    (project / args.shots).write_text(json.dumps([s.to_json() for s in shots], indent=1), encoding="utf-8")

    chars = load_characters(plan, project)
    envs = load_environments(plan, project, size)
    envelope = Envelope(project, timeline, args.fps)
    order = [c["id"] for c in plan["characters"]]
    rng = random.Random(42)
    duration = timeline["duration_s"] if not args.max_seconds else min(timeline["duration_s"], args.max_seconds)
    blinks = {cid: _blink_schedule(random.Random(a.seed), duration + 1) for cid, a in chars.items()}
    total = int(duration * args.fps)

    cmd = [args.ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{size[0]}x{size[1]}", "-r", str(args.fps), "-i", "-",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    si = 0
    try:
        for f in range(total):
            t = f / args.fps
            while si + 1 < len(shots) and t >= shots[si + 1].start_s:
                si += 1
            frame = compose(shots[si], t, envs, chars, envelope, size, blinks, rng, order)
            proc.stdin.write(frame.tobytes())
            if f % args.fps == 0:
                print(f"PROGRESS {f} {total}", flush=True)
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        print(f"ffmpeg exited with {rc}", file=sys.stderr)
        return 1
    print(f"PROGRESS {total} {total}", flush=True)
    print(json.dumps({"frames": total, "fps": args.fps, "size": size, "shots": len(shots), "duration_s": duration}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
