from __future__ import annotations

import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.plan import Character, Environment, Line, ProductionPlan, Scene, Voice
from app.services.engines.delivery import gap_after
from app.services.engines.tts_engine import MIN_SPACING_S, TTSEngine, TTSError


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
    # lead-in, conversational gap (delivery.gap_after), tail and scene establishing gap respected
    assert lines[0]["start_s"] == 1.5
    gap = gap_after("Hello there, how are you today?", "neutral", "Fine. Mostly.", "neutral", False, "s1l1")
    assert 0.1 < gap < 0.35                      # an answer to a question comes quickly
    assert abs(lines[1]["start_s"] - (lines[0]["end_s"] + gap)) < 0.002
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


def test_interruption_overlaps_and_mix_sums(tmp_path: Path):
    plan = _plan()
    plan.scenes[0].lines[0].text = "I was just about to say—"
    plan.scenes[0].lines[1].text = "Wait, what?"
    engine = TTSEngine(sys.executable, engine="fake", room_mix=False)
    result = asyncio.run(engine.run(plan, tmp_path, progress=_noop))
    assert result["room_mix"] == {"applied": False, "reason": "disabled"}
    tl = json.loads((tmp_path / "audio" / "dialogue.json").read_text())
    a, b = tl["lines"][0], tl["lines"][1]
    assert b["start_s"] < a["end_s"]                                  # cut off: reply overlaps the tail
    assert b["start_s"] >= a["start_s"] + MIN_SPACING_S - 1e-6
    # room mix off: the dry track is the dialogue track
    assert (tmp_path / "audio" / "dialogue.wav").read_bytes() == (tmp_path / "audio" / "dialogue_dry.wav").read_bytes()


def test_mix_sums_overlapping_lines(tmp_path: Path):
    audio = tmp_path / "audio"
    audio.mkdir()
    for name, value in (("x.wav", 1000), ("y.wav", 1500)):
        with wave.open(str(audio / name), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
            w.writeframes(int(value).to_bytes(2, "little", signed=True) * 24000)   # 1 s constant level
    timeline = {"duration_s": 2.0, "lines": [{"file": "audio/x.wav", "start_s": 0.0},
                                              {"file": "audio/y.wav", "start_s": 0.5}]}
    TTSEngine._mix(audio, timeline, 24000)
    with wave.open(str(audio / "dialogue_dry.wav"), "rb") as w:
        data = w.readframes(w.getnframes())
    at = lambda s: int.from_bytes(data[int(s * 24000) * 2:int(s * 24000) * 2 + 2], "little", signed=True)  # noqa: E731
    assert (at(0.25), at(0.75), at(1.25), at(1.75)) == (1000, 2500, 1500, 0)


_SETTINGS = get_settings()
_CHATTERBOX = Path(_SETTINGS.resolved_chatterbox_python)
_WORKERS = Path(_SETTINGS.resolved_tts_python)


@pytest.mark.skipif(not _CHATTERBOX.exists() or not _WORKERS.exists(),
                    reason="Chatterbox venv (scripts/install-chatterbox.ps1) and worker venv are required")
def test_chatterbox_real_voices(tmp_path: Path):
    """Real engine: Kokoro reference clips -> Chatterbox cloned, emotion-driven lines -> room mix."""
    plan = _plan()
    plan.scenes[0].lines[1].emotion = "annoyed"
    engine = TTSEngine(str(_WORKERS), engine="chatterbox", chatterbox_python=str(_CHATTERBOX))
    result = asyncio.run(engine.run(plan, tmp_path, progress=_noop))
    assert result["engine"] == "chatterbox" and result["lines"] == 3
    assert result["room_mix"]["applied"] is True and result["room_mix"]["rooms"] == {"s1": "small", "s2": "small"}
    for v in ("af_heart", "am_michael"):
        assert (tmp_path / "audio" / "voices" / f"ref_{v}.wav").stat().st_size > 24000 * 2 * 5  # >5 s reference
    job = json.loads((tmp_path / "audio" / "tts_job.json").read_text())
    assert job["lines"][1]["exaggeration"] > job["lines"][0]["exaggeration"]               # annoyed > neutral
    tl = json.loads((tmp_path / "audio" / "dialogue.json").read_text())
    for line in tl["lines"]:
        with wave.open(str(tmp_path / line["file"]), "rb") as w:
            assert w.getframerate() == 24000 and w.getnchannels() == 1
            assert 0.3 < w.getnframes() / 24000 < 8
    with wave.open(str(tmp_path / "audio" / "dialogue.wav"), "rb") as w:
        assert w.getnchannels() == 2                                                      # room mix is stereo


def test_chatterbox_missing_is_a_clear_error(tmp_path: Path):
    engine = TTSEngine(sys.executable, engine="chatterbox", chatterbox_python=str(tmp_path / "nope.exe"))
    with pytest.raises(TTSError, match="install-chatterbox"):
        asyncio.run(engine.run(_plan(), tmp_path, progress=_noop))


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
