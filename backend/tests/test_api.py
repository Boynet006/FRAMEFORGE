"""API smoke tests. Run from backend/:  pytest -q

Environment isolation (temp SQLite, unreachable ComfyUI URL) is set up in conftest.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_cors_origins_parse_from_comma_separated_env():
    assert get_settings().cors_origin_list == ["http://localhost:3000", "http://127.0.0.1:3000"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database_ok"] is True
    assert isinstance(body["gpu"], list)


def test_comfy_status_unreachable_is_truthful(client):
    r = client.get("/api/comfy/status")
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is False
    assert body["error"]


def test_project_crud(client):
    r = client.post(
        "/api/projects",
        json={"title": "Cats", "prompt": "two cats argue about food", "settings": {"duration_s": 60}},
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    # Timestamps must carry an explicit UTC offset so browsers don't misread them as local time.
    assert r.json()["created_at"].endswith(("Z", "+00:00"))

    r = client.get("/api/projects")
    assert any(p["id"] == pid for p in r.json())

    r = client.patch(f"/api/projects/{pid}", json={"status": "planning"})
    assert r.status_code == 200 and r.json()["status"] == "planning"

    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 200 and r.json()["jobs"] == []

    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_jobs_empty(client):
    r = client.get("/api/jobs")
    assert r.status_code == 200 and r.json() == []
