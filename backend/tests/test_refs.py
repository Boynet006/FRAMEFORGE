from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_tts import _plan


@pytest.fixture(scope="module")
def client(fake_comfy):
    with TestClient(app) as c:
        app.state.runner.comfy_url = fake_comfy.url
        yield c


def _wait(client: TestClient, job_id: str, *states: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {states}; last: {job}")


def test_refs_generated_and_recorded(client, fake_comfy):
    pid = client.post("/api/projects", json={"title": "t", "prompt": "p", "settings": {"style": "cartoon"}}).json()["id"]
    assert client.post(f"/api/projects/{pid}/refs").status_code == 409
    plan = _plan()
    plan.style = "cartoon"
    client.put(f"/api/projects/{pid}/plan", json=plan.model_dump())

    n_before = len(fake_comfy.fake.submitted)
    job = client.post(f"/api/projects/{pid}/refs").json()
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["status"] == "succeeded", done
    assert done["result"]["generated"] == 3 and done["result"]["skipped"] == 0  # 2 characters + 1 environment

    # the image template was driven with the plan's prompts and sizes
    sent = fake_comfy.fake.submitted[n_before:]
    assert len(sent) == 3
    assert "cartoon illustration" in sent[0]["prompt"]["6"]["inputs"]["text"]
    assert sent[0]["prompt"]["5"]["inputs"] == {"width": 512, "height": 640, "batch_size": 1}
    assert sent[2]["prompt"]["5"]["inputs"]["width"] == 768

    plan = client.get(f"/api/projects/{pid}/plan").json()["plan"]
    assert plan["characters"][0]["reference_image"] == "refs/character_a.png"
    assert plan["environments"][0]["reference_image"] == "refs/environment_room.png"
    img = client.get(f"/api/projects/{pid}/files/refs/character_a.png")
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")

    # second run reuses existing files
    job = client.post(f"/api/projects/{pid}/refs").json()
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["result"]["generated"] == 0 and done["result"]["skipped"] == 3
    # force regenerates
    job = client.post(f"/api/projects/{pid}/refs?force=true").json()
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["result"]["generated"] == 3
