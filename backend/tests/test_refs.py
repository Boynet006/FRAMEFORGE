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
    assert "content-disposition" not in img.headers  # inline by default, so <img>/<video> can show it
    dl = client.get(f"/api/projects/{pid}/files/refs/character_a.png?download=true")
    assert dl.status_code == 200 and 'filename="t-character_a.png"' in dl.headers["content-disposition"]

    # second run reuses existing files
    job = client.post(f"/api/projects/{pid}/refs").json()
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["result"]["generated"] == 0 and done["result"]["skipped"] == 3
    # force regenerates
    job = client.post(f"/api/projects/{pid}/refs?force=true").json()
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["result"]["generated"] == 3


def test_refs_use_template_size_hints(client, fake_comfy):
    pid = client.post("/api/projects", json={"title": "t", "prompt": "p", "settings": {}}).json()["id"]
    client.put(f"/api/projects/{pid}/plan", json=_plan().model_dump())
    assert client.post(f"/api/projects/{pid}/refs?workflow=nope").status_code == 400

    n_before = len(fake_comfy.fake.submitted)
    job = client.post(f"/api/projects/{pid}/refs?workflow=image_sdxl").json()
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["status"] == "succeeded", done
    assert done["result"]["workflow"] == "image_sdxl"
    sent = fake_comfy.fake.submitted[n_before:]
    # SDXL template declares ~1 MP native sizes in its hints
    assert sent[0]["prompt"]["5"]["inputs"]["width"] == 896 and sent[0]["prompt"]["5"]["inputs"]["height"] == 1152
    assert sent[2]["prompt"]["5"]["inputs"]["width"] == 1344 and sent[2]["prompt"]["5"]["inputs"]["height"] == 768
    assert sent[0]["prompt"]["4"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"
    assert client.get("/api/workflows/image_sdxl").json()["hints"]["character_size"] == [896, 1152]
