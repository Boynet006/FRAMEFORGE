from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from .fake_comfy import FakeComfyServer
from .fake_ollama import FakeOllamaServer

# Isolate every test run from the developer database / data dir and make the
# environment deterministic before any app module is imported.
_tmp = Path(tempfile.mkdtemp(prefix="frameforge-test-"))
os.environ["FRAMEFORGE_DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["FRAMEFORGE_DATA_DIR"] = str(_tmp / "data")
os.environ["FRAMEFORGE_COMFYUI_URL"] = "http://127.0.0.1:1"  # overridden per test when a fake is used
os.environ["FRAMEFORGE_COMFYUI_TIMEOUT_S"] = "1"
os.environ["FRAMEFORGE_OLLAMA_URL"] = "http://127.0.0.1:1"
os.environ["FRAMEFORGE_OLLAMA_TIMEOUT_S"] = "5"
# Pin machine-specific engine choices so a GPU machine's backend/.env (qwen3:14b, image_sdxl, ...)
# doesn't leak into the stand-in tests. Tests that need another template pass it explicitly.
os.environ["FRAMEFORGE_OLLAMA_MODEL"] = "qwen3:4b"
os.environ["FRAMEFORGE_IMAGE_WORKFLOW"] = "image_sd15_lcm"
os.environ["FRAMEFORGE_RENDER_MODE"] = "cpu"
os.environ["FRAMEFORGE_CORS_ORIGINS"] = "http://localhost:3000, http://127.0.0.1:3000"
os.environ["FRAMEFORGE_LOG_LEVEL"] = "WARNING"


@pytest.fixture(scope="session")
def fake_comfy():
    out = _tmp / "comfy_out"
    out.mkdir(parents=True, exist_ok=True)
    server = FakeComfyServer(out).start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def fake_ollama():
    server = FakeOllamaServer().start()
    yield server
    server.stop()
