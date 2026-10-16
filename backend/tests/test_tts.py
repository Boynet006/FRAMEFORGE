from __future__ import annotations

import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.plan import Character, Environment, Line, ProductionPlan, Scene, Voice
from app.services.engines.tts_engine import TTSEngine, TTSError


def _plan() -> ProductionPlan:
    return ProductionPlan(
        title="t", target_duration_s=30,
        characters=[Character(id="a", name="A", voice=Voice(voice="af_heart")),
                    Character(id="b", name="B", voice=Voice(voice="am_michael", speed=1.1))],
        environments=[Environment(id="room", name="Room")],
        scenes=[
            Scene(id="s1", environment_id="room", lines=[
                Line(id="s1l1", character_id="a", text="Hello there, how are you today?", pause_after_s=0.3),
                Line(id="s1l2", character_id="b", text="Fine. Mostly.", pause_after_s=0.3),
            ]),
            Scene(id="s2", environment_id="room", lines=[
                Line(id="s2l1", character_id="a", text="Good.", pause_after_s=0.3),
            ]),
        ],
    )


async def _noop(_v: float, _n: str | None) -> None:
    pass


def test_fake_engine_layout_and_mix(tmp_path: Path):
    engine = TTSEngine(sys.executable, engine="fake")
    progress: list[float] = []

    async def prog(v: float, _n: str | None) -> None:
        progress.append(v)

    result = asyncio.run(engine.run(_plan(), tmp_path, progress=prog))
    assert result["lines"] == 3 and result["engine"] == "fake"
    assert progress and progress[-1] == 1.0 and progress == sorted(progress)

    tl = json.loads((tmp_path / "audio" / "dialogue.json").read_text())
    lines = tl["lines"]
    assert [l["id"] for l in lines] == ["s1l1", "s1l2", "s2l1"]
    # monotonic, non-overlapping; lead-in, pauses, tail and scene establishing gap respected
    assert lines[0]["start_s"] == 1.5
    assert lines[1]["start_s"] >= lines[0]["end_s"] + 0.3 - 1e-6
    assert lines[2]["start_s"] >= lines[1]["end_s"] + 0.6 + 1.0 - 1e-6
    assert tl["duration_s"] >= lines[2]["end_s"]
    assert len(tl["scenes"]) == 2
    assert tl["scenes"][0]["start_s"] == 0.0 and tl["scenes"][1]["start_s"] == tl["scenes"][0]["end_s"]
    assert tl["scenes"][1]["start_s"] + 1.0 <= lines[2]["start_s"] + 1e-6
    # word timings are absolute and inside the line
    w = lines[0]["words"]
    assert len(w) == 6 and w[0]["start_s"] >= lines[0]["start_s"] and w[-1]["end_s"] <= lines[0]["end_s"] + 1e-6

    with wave.open(str(tmp_path / "audio" / "dialogue.wav"), "rb") as mix:
        assert mix.getframerate() == 24000
        assert abs(mix.getnframes() / 24000 - (tl["duration_s"] + 0.5)) < 0.01
    for l in lines:
        assert (tmp_path / l["file"]).is_file()


def test_worker_failure_is_reported(tmp_path: Path):
    engine = TTSEngine(sys.executable, engine="fake")
    engine.python = "definitely-not-a-python-binary"
    with pytest.raises((TTSError, OSError)):
        asyncio.run(engine.run(_plan(), tmp_path, progress=_noop))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        runner = app.state.runner
        runner.settings.tts_engine = "fake"
        runner.settings.tts_python = Path(sys.executable)
        yield c


def _wait(client: TestClient, job_id: str, *states: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {states}; last: {job}")


def test_tts_api(client):
    pid = client.post("/api/projects", json={"title": "t", "prompt": "p"}).json()["id"]
    assert client.post(f"/api/projects/{pid}/tts").status_code == 409  # no plan yet
    assert client.put(f"/api/projects/{pid}/plan", json=_plan().model_dump()).status_code == 200

    r = client.post(f"/api/projects/{pid}/tts")
    assert r.status_code == 202 and r.json()["kind"] == "tts.generate"
    done = _wait(client, r.json()["id"], "succeeded", "failed")
    assert done["status"] == "succeeded", done
    assert done["result"]["lines"] == 3

    tl = client.get(f"/api/projects/{pid}/timeline")
    assert tl.status_code == 200 and tl.json()["lines"][0]["character_id"] == "a"

    f = client.get(f"/api/projects/{pid}/files/audio/dialogue.wav")
    assert f.status_code == 200 and f.content[:4] == b"RIFF"
    assert client.get(f"/api/projects/{pid}/files/../../x").status_code == 404
