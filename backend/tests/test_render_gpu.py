"""GPU animate mode (Wan 2.2 S2V speaking shots) against the stand-in ComfyUI.

The stand-in returns a real FFmpeg test-pattern MP4 for SaveVideo, so the whole path runs: reference
stills, audio slicing, uploads, graph extension, clip checkpointing and splicing into the picture track.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.engines.animate_gpu_engine import chunk_count, extend_graph, slice_audio
from app.services.workflows import get_registry
from tests.test_render import _ready_project, _wait, needs_workers


def test_chunk_count():
    assert chunk_count(1.0, 16, 77) == 1
    assert chunk_count(77 / 16, 16, 77) == 1
    assert chunk_count(4.98, 16, 77) == 1          # 0.17 s over: hold the last frame (measured case)
    assert chunk_count(77 / 16 + 0.6, 16, 77) == 2
    assert chunk_count(77 / 16 + 0.01, 16, 77, tolerance_s=0) == 2
    assert chunk_count(10.0, 16, 77) == 2          # 154 frames + 0.375 s hold
    assert chunk_count(10.2, 16, 77) == 3


def test_extend_graph_adds_chunks_and_repoints_decoder():
    t = get_registry().get("video_wan22_s2v")
    graph, _ = t.build({"image": "a.png", "audio": "a.wav", "steps": 6, "seed": 5})
    assert extend_graph(graph, t.hints, 1) == graph

    g = extend_graph(graph, t.hints, 3)
    assert g["ext1"]["class_type"] == "WanSoundImageToVideoExtend"
    assert g["ext1"]["inputs"]["video_latent"] == ["3", 0]          # chains from the first chunk
    assert g["ext2"]["inputs"]["video_latent"] == ["ext1_concat", 0]
    assert g["ext2_sample"]["inputs"]["steps"] == 6 and g["ext2_sample"]["inputs"]["seed"] == 5
    assert g["ext1"]["inputs"]["length"] == 77
    # the first-frame fix and decoder now read the full concatenated latent
    assert g["94"]["inputs"]["samples"] == ["ext2_concat", 0]
    assert g["95"]["inputs"]["samples2"] == ["ext2_concat", 0]
    assert graph["94"]["inputs"]["samples"] == ["3", 0]               # input graph untouched


def test_slice_audio_cuts_and_pads(tmp_path: Path):
    src = tmp_path / "in.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(1000)
        w.writeframes(b"\x01\x00" * 3000)                            # 3 s of non-silence
    dst = tmp_path / "out.wav"
    slice_audio(src, dst, offset_s=2.0, duration_s=2.0, pad_to_s=4.0)
    with wave.open(str(dst), "rb") as w:
        assert w.getnframes() == 4000
        data = w.readframes(4000)
    assert data[:2000] == b"\x01\x00" * 1000 and data[2000:] == b"\x00" * 6000  # 1 s left of source, rest silence


@pytest.fixture(scope="module")
def client(fake_comfy, fake_ollama, tmp_path_factory):
    with TestClient(app) as c:
        runner = app.state.runner
        runner.comfy_url = fake_comfy.url
        runner.ollama_url = fake_ollama.url
        runner.settings.tts_engine = "fake"
        yield c
    fake_comfy.fake.video_bytes = None


@needs_workers
def test_gpu_animate_renders_speaking_shots_with_s2v(client, fake_comfy, tmp_path):
    clip = tmp_path / "pattern.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=848x480:rate=16",
                    "-t", "5", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(clip)], check=True)
    fake_comfy.fake.video_bytes = clip.read_bytes()

    pid = _ready_project(client)
    assert _wait(client, client.post(f"/api/projects/{pid}/tts").json()["id"], "succeeded", "failed")["status"] == "succeeded"
    assert client.post(f"/api/projects/{pid}/animate?render_mode=nope").status_code == 400

    n_sub, n_up = len(fake_comfy.fake.submitted), len(fake_comfy.fake.uploads)
    job = client.post(f"/api/projects/{pid}/animate?render_mode=gpu&max_seconds=6").json()
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["status"] == "succeeded", done
    res = done["result"]
    assert res["mode"] == "gpu" and res["frames"] == 6 * 24
    s2v = res["s2v"]
    assert s2v["speaking_shots"] >= 1 and s2v["generated"] == s2v["speaking_shots"] and s2v["reused"] == 0
    assert res["clip_shots"] == s2v["speaking_shots"]

    root = app.state.runner.project_dir(pid)
    shots = json.loads((root / "render" / "shots.json").read_text())
    assert not any(s["kind"] == "two" for s in shots)                  # GPU mode: one face per spoken shot
    speaking = [s for s in shots if s["kind"] == "speaking" and s["start_s"] < 6]
    for s in speaking:
        assert (root / "render" / "s2v" / f"{s['id']}.png").exists()    # reference still
        assert (root / "render" / "s2v" / f"{s['id']}.mp4").exists()    # checkpointed clip
    # each speaking shot uploaded its still and audio, and ran the S2V graph
    uploads = list(fake_comfy.fake.uploads)[n_up:]
    assert any(u.endswith(".png") for u in uploads) and any(u.endswith(".wav") for u in uploads)
    graphs = [b["prompt"] for b in fake_comfy.fake.submitted[n_sub:]]
    assert len(graphs) == s2v["generated"]
    assert all(any(n["class_type"] == "WanSoundImageToVideo" for n in g.values()) for g in graphs)
    assert all(g["52"]["inputs"]["image"].endswith(".png") and g["58"]["inputs"]["audio"].endswith(".wav") for g in graphs)

    # a second run reuses every clip
    done = _wait(client, client.post(f"/api/projects/{pid}/animate?render_mode=gpu&max_seconds=6").json()["id"],
                 "succeeded", "failed")
    assert done["status"] == "succeeded", done
    assert done["result"]["s2v"]["generated"] == 0 and done["result"]["s2v"]["reused"] == s2v["speaking_shots"]
