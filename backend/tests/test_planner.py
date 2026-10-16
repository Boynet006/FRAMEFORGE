from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.plan import ProductionPlan
from app.services.engines.plan_engine import PlanEngine
from app.services.llm_client import LLMError, OllamaClient


async def _noop(_v: float, _n: str | None) -> None:
    pass


def test_engine_builds_valid_plan(fake_ollama):
    llm = OllamaClient(fake_ollama.url, "qwen3:4b", timeout_s=5)
    plan = asyncio.run(PlanEngine(llm).run({"duration_s": 120, "style": "cartoon"}, "two cats argue", progress=_noop))
    assert isinstance(plan, ProductionPlan)
    assert plan.title == "Kibble Court" and plan.style == "cartoon"
    assert {c.id for c in plan.characters} == {"miso", "biscuit"}
    # distinct voices per character
    assert len({c.voice.voice for c in plan.characters}) == 2
    assert len(plan.scenes) == 2  # 120 s -> 2 scenes
    assert all(l.character_id in ("miso", "biscuit") for s in plan.scenes for l in s.lines)
    assert plan.line_count >= 10 and plan.estimated_duration_s > 0
    # stand-in sizes scenes to the word budget, so the estimate lands near the target
    assert 0.6 * 120 <= plan.estimated_duration_s <= 1.4 * 120
    # outline + one call per scene
    assert len(fake_ollama.fake.calls) == 3
    assert fake_ollama.fake.calls[0]["think"] is False and fake_ollama.fake.calls[0]["format"]["type"] == "object"


def test_engine_missing_model_is_error(fake_ollama):
    llm = OllamaClient(fake_ollama.url, "nope:1b", timeout_s=5)
    with pytest.raises(LLMError):
        asyncio.run(PlanEngine(llm).run({}, "x", progress=_noop))


def test_llm_status(fake_ollama):
    assert asyncio.run(OllamaClient("http://127.0.0.1:1", "qwen3:4b", 1).status())["reachable"] is False
    st = asyncio.run(OllamaClient(fake_ollama.url, "qwen3:4b", 1).status())
    assert st["reachable"] is True and st["model_available"] is True
    st = asyncio.run(OllamaClient(fake_ollama.url, "qwen3:14b", 1).status())
    assert st["model_available"] is False


@pytest.fixture(scope="module")
def client(fake_ollama):
    with TestClient(app) as c:
        app.state.runner.ollama_url = fake_ollama.url
        yield c


def _wait(client: TestClient, job_id: str, *states: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {states}; last: {job}")


def test_plan_api_roundtrip(client, fake_ollama):
    r = client.post("/api/projects", json={"title": "t", "prompt": "two cats argue about food",
                                           "settings": {"duration_s": 60, "style": "cartoon"}})
    pid = r.json()["id"]
    assert r.json()["has_plan"] is False
    assert client.get(f"/api/projects/{pid}/plan").status_code == 404
    assert client.get("/api/llm/status").json()["reachable"] is True

    r = client.post(f"/api/projects/{pid}/plan")
    assert r.status_code == 202 and r.json()["kind"] == "plan.generate"
    # (a second POST while queued returns 409; not asserted here because the stand-in
    #  finishes planning in milliseconds, which makes the check racy)
    done = _wait(client, r.json()["id"], "succeeded", "failed")
    assert done["status"] == "succeeded", done
    assert done["result"]["summary"]["scenes"] == 1
    assert fake_ollama.fake.unloads >= 1  # LLM memory released after planning

    p = client.get(f"/api/projects/{pid}")
    assert p.json()["status"] == "draft" and p.json()["has_plan"] is True and p.json()["plan"]["title"] == "Kibble Court"

    # advanced-mode edit: valid change is stored, broken reference is rejected
    plan = client.get(f"/api/projects/{pid}/plan").json()["plan"]
    plan["scenes"][0]["lines"][0]["text"] = "Edited line."
    r = client.put(f"/api/projects/{pid}/plan", json=plan)
    assert r.status_code == 200 and r.json()["plan"]["scenes"][0]["lines"][0]["text"] == "Edited line."
    plan["scenes"][0]["lines"][0]["character_id"] = "ghost"
    assert client.put(f"/api/projects/{pid}/plan", json=plan).status_code == 422


def test_plan_failure_is_reported(client, fake_ollama):
    pid = client.post("/api/projects", json={"title": "t", "prompt": "p", "settings": {"duration_s": 30}}).json()["id"]
    fake_ollama.fake.fail_next = 10  # every call errors -> outline fails
    try:
        job = client.post(f"/api/projects/{pid}/plan").json()
        done = _wait(client, job["id"], "failed", "succeeded")
        assert done["status"] == "failed" and "Ollama HTTP 500" in done["error"]
    finally:
        fake_ollama.fake.fail_next = 0
