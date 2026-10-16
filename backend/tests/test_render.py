"""Animate + assemble + pipeline tests.

The animator and music workers need the worker venv (numpy/Pillow) and FFmpeg;
when either is missing on the test machine these tests are skipped, not faked.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.fake_comfy import _PNG
from tests.test_tts import _plan

_WORKER_PY = Path(get_settings().resolved_tts_python)
needs_workers = pytest.mark.skipif(
    not _WORKER_PY.exists() or not shutil.which("ffmpeg"),
    reason="worker venv (backend/.venv-tts) and ffmpeg are required",
)


@pytest.fixture(scope="module")
def client(fake_comfy, fake_ollama):
    with TestClient(app) as c:
        runner = app.state.runner
        runner.comfy_url = fake_comfy.url
        runner.ollama_url = fake_ollama.url
        runner.settings.tts_engine = "fake"  # audio shape is what matters here, not voice quality
        yield c


def _wait(client: TestClient, job_id: str, *states: str, timeout: float = 240.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in states:
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not reach {states}; last: {job}")


def _ready_project(client: TestClient) -> str:
    pid = client.post("/api/projects", json={"title": "t", "prompt": "p", "settings": {"quality": "draft"}}).json()["id"]
    plan = _plan()
    client.put(f"/api/projects/{pid}/plan", json=plan.model_dump())
    # fake refs (1x1 PNGs are enough for the animator's fallbacks)
    root = app.state.runner.project_dir(pid)
    (root / "refs").mkdir(parents=True, exist_ok=True)
    for c in plan.characters:
        (root / "refs" / f"character_{c.id}.png").write_bytes(_PNG)
    for e in plan.environments:
        (root / "refs" / f"environment_{e.id}.png").write_bytes(_PNG)
    for c in plan.characters:
        c.reference_image = f"refs/character_{c.id}.png"
    for e in plan.environments:
        e.reference_image = f"refs/environment_{e.id}.png"
    client.put(f"/api/projects/{pid}/plan", json=plan.model_dump())
    return pid


def test_stage_order_is_enforced(client):
    pid = client.post("/api/projects", json={"title": "t", "prompt": "p"}).json()["id"]
    assert client.post(f"/api/projects/{pid}/animate").status_code == 409
    client.put(f"/api/projects/{pid}/plan", json=_plan().model_dump())
    job = client.post(f"/api/projects/{pid}/animate").json()
    done = _wait(client, job["id"], "failed", "succeeded", timeout=30)
    assert done["status"] == "failed" and "TTS" in done["error"]


@needs_workers
def test_animate_and_assemble(client):
    pid = _ready_project(client)
    done = _wait(client, client.post(f"/api/projects/{pid}/tts").json()["id"], "succeeded", "failed")
    assert done["status"] == "succeeded"

    job = client.post(f"/api/projects/{pid}/animate?max_seconds=2").json()
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["status"] == "succeeded", done
    assert done["result"]["frames"] == 48 and done["result"]["shots"] >= 3
    root = app.state.runner.project_dir(pid)
    shots = json.loads((root / "render" / "shots.json").read_text())
    assert shots[0]["start_s"] == 0.0 and all(a["end_s"] == b["start_s"] for a, b in zip(shots, shots[1:]))
    assert {s["kind"] for s in shots} >= {"wide", "speaking"}

    job = client.post(f"/api/projects/{pid}/assemble").json()
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["status"] == "succeeded", done
    res = done["result"]
    assert res["probe"]["video"]["codec_name"] == "h264" and res["probe"]["audio"]["codec_name"] == "aac"
    # the picture track was cut to 2 s on purpose, so the duration check must flag the mismatch honestly
    dur_check = next(c for c in res["checks"] if c["check"] == "duration_matches_timeline")
    assert dur_check["ok"] is False and res["ok"] is False
    assert (root / "render" / "subtitles.srt").read_text(encoding="utf-8").startswith("1\n00:00:01,500 --> ")
    render = client.get(f"/api/projects/{pid}/render").json()
    assert render["final"]["size"] > 0 and len(render["refs"]) == 3


@needs_workers
def test_full_pipeline_reuses_finished_stages(client, fake_ollama):
    pid = _ready_project(client)
    job = client.post(f"/api/projects/{pid}/generate").json()
    assert job["kind"] == "pipeline.full"
    assert client.post(f"/api/projects/{pid}/generate").status_code == 409  # one active job per project
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["status"] == "succeeded", done
    stages = done["result"]["stages"]
    assert stages["plan"] == {"skipped": True}          # plan was uploaded
    assert stages["refs"]["skipped"] == 3 and stages["refs"]["generated"] == 0
    assert stages["animate"]["frames"] > 0
    assert done["result"]["ok"] is True, stages["assemble"]["checks"]
    assert client.get(f"/api/projects/{pid}").json()["status"] == "completed"

    # second run reuses every stage
    job = client.post(f"/api/projects/{pid}/generate").json()
    done = _wait(client, job["id"], "succeeded", "failed")
    assert all(v == {"skipped": True} for k, v in done["result"]["stages"].items() if k != "refs")
