"""End-to-end job tests: API -> runner -> (fake) ComfyUI -> outputs on disk -> events."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client(fake_comfy):
    with TestClient(app) as c:
        app.state.runner.comfy_url = fake_comfy.url
        yield c


def _wait(client: TestClient, job_id: str, *states: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {states}; last: {job}")


def _project(client: TestClient) -> str:
    r = client.post("/api/projects", json={"title": "t", "prompt": "p"})
    assert r.status_code == 201
    return r.json()["id"]


def test_workflows_listed(client):
    r = client.get("/api/workflows")
    assert r.status_code == 200
    names = {w["name"] for w in r.json()}
    assert {"image_basic_txt2img", "video_wan22_5b_t2v"} <= names
    assert client.get("/api/workflows/image_basic_txt2img").json()["version"] == 1
    assert client.get("/api/workflows/nope").status_code == 404


def test_bad_params_rejected_before_queueing(client):
    pid = _project(client)
    r = client.post(f"/api/projects/{pid}/jobs", json={"workflow": "image_basic_txt2img", "params": {"bogus": 1}})
    assert r.status_code == 422
    r = client.post(f"/api/projects/{pid}/jobs", json={"workflow": "missing"})
    assert r.status_code == 422


def test_job_runs_to_success_with_outputs(client, fake_comfy):
    pid = _project(client)
    r = client.post(f"/api/projects/{pid}/jobs",
                    json={"workflow": "image_basic_txt2img", "params": {"prompt": "a cat", "seed": 7}})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "queued" and job["kind"] == "comfy.workflow"

    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["status"] == "succeeded", done
    assert done["progress"] == 1.0 and done["attempt"] == 1
    assert done["payload"]["prompt_id"]
    out = done["result"]["outputs"]
    assert len(out) == 1 and out[0]["kind"] == "image"
    assert done["result"]["params"]["seed"] == 7

    f = client.get(f"/api/jobs/{job['id']}/outputs/{out[0]['filename']}")
    assert f.status_code == 200 and f.content.startswith(b"\x89PNG")
    assert client.get(f"/api/jobs/{job['id']}/outputs/..%2Fx").status_code in (400, 404)

    # the real graph reached "ComfyUI" with the parameter applied
    sent = fake_comfy.fake.submitted[-1]["prompt"]
    assert sent["6"]["inputs"]["text"] == "a cat"

    # project status went generating -> draft once nothing is active
    assert client.get(f"/api/projects/{pid}").json()["status"] == "draft"


def test_execution_error_marks_failed_and_retry_requeues(client):
    pid = _project(client)
    ok = client.post(f"/api/projects/{pid}/jobs", json={"workflow": "image_basic_txt2img"}).json()
    _wait(client, ok["id"], "succeeded")
    # retry must refuse a job that did not fail
    assert client.post(f"/api/jobs/{ok['id']}/retry").status_code == 409

    # "__fail__" in the prompt makes the stand-in raise execution_error, as a real ComfyUI
    # would for e.g. a missing model file. Execution errors are NOT retried automatically.
    bad = client.post(f"/api/projects/{pid}/jobs",
                      json={"workflow": "image_basic_txt2img", "params": {"prompt": "__fail__"}}).json()
    done = _wait(client, bad["id"], "failed", "succeeded")
    assert done["status"] == "failed" and "fake failure" in done["error"] and done["attempt"] == 1

    r = client.post(f"/api/jobs/{bad['id']}/retry")
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["error"] is None
    done = _wait(client, bad["id"], "failed", "succeeded")
    assert done["status"] == "failed" and done["attempt"] == 2


def test_cancel_running_job(client, fake_comfy):
    pid = _project(client)
    r = client.post(f"/api/projects/{pid}/jobs", json={"workflow": "video_wan22_5b_t2v", "params": {"steps": 60}})
    job = r.json()
    # Slow the stand-in down (4 ticks x 0.3 s) so the cancel lands mid-execution.
    fake_comfy.fake.tick_s = 0.3
    try:
        running = _wait(client, job["id"], "running")
        assert running["status"] == "running"
        time.sleep(0.3)
        r = client.post(f"/api/jobs/{job['id']}/cancel")
        assert r.status_code == 200
        done = _wait(client, job["id"], "cancelled", "succeeded", "failed", timeout=15)
        assert done["status"] == "cancelled", done
        assert fake_comfy.fake.interrupted is True
    finally:
        fake_comfy.fake.tick_s = 0.02

    # retry works on a cancelled job and succeeds
    r = client.post(f"/api/jobs/{job['id']}/retry")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    done = _wait(client, job["id"], "succeeded", "failed")
    assert done["status"] == "succeeded" and done["attempt"] == 2
    assert done["result"]["outputs"][0]["kind"] == "video"


def test_cancel_queued_job_is_immediate(client, fake_comfy):
    pid = _project(client)
    fake_comfy.fake.tick_s = 0.3
    try:
        first = client.post(f"/api/projects/{pid}/jobs", json={"workflow": "image_basic_txt2img"}).json()
        second = client.post(f"/api/projects/{pid}/jobs", json={"workflow": "image_basic_txt2img"}).json()
        _wait(client, first["id"], "running")
        r = client.post(f"/api/jobs/{second['id']}/cancel")
        assert r.json()["status"] == "cancelled"
        _wait(client, first["id"], "succeeded", "failed", timeout=15)
    finally:
        fake_comfy.fake.tick_s = 0.02


def test_websocket_receives_job_events(client):
    pid = _project(client)
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        job = client.post(f"/api/projects/{pid}/jobs", json={"workflow": "image_basic_txt2img"}).json()
        seen: list[str] = []
        deadline = time.time() + 10
        while time.time() < deadline:
            ev = ws.receive_json()
            if ev["type"] == "job" and ev["job"]["id"] == job["id"]:
                seen.append(ev["job"]["status"])
                if ev["job"]["status"] in ("succeeded", "failed"):
                    break
        assert seen[0] == "queued" and "running" in seen and seen[-1] == "succeeded"


def test_unreachable_comfy_retries_then_fails(client, fake_comfy):
    pid = _project(client)
    app.state.runner.comfy_url = "http://127.0.0.1:1"
    try:
        job = client.post(f"/api/projects/{pid}/jobs", json={"workflow": "image_basic_txt2img"}).json()
        done = _wait(client, job["id"], "failed", timeout=40)
        assert done["attempt"] == done["max_attempts"] == 3
        assert "unreachable" in done["error"]
    finally:
        app.state.runner.comfy_url = fake_comfy.url


def test_delete_job_removes_outputs(client):
    pid = _project(client)
    job = client.post(f"/api/projects/{pid}/jobs", json={"workflow": "image_basic_txt2img"}).json()
    done = _wait(client, job["id"], "succeeded")
    fn = done["result"]["outputs"][0]["filename"]
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert client.get(f"/api/jobs/{job['id']}/outputs/{fn}").status_code == 404
