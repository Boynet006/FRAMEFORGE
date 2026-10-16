from __future__ import annotations

import asyncio

import pytest

from app.services.comfy_client import ComfyClient, ComfyError, ComfyUnavailable, parse_history_outputs
from app.services.workflows import WorkflowRegistry


def test_status_unreachable():
    c = ComfyClient("http://127.0.0.1:1", timeout_s=1)
    out = asyncio.run(c.status())
    assert out["reachable"] is False and "unreachable" in out["error"]


def test_status_reachable(fake_comfy):
    c = ComfyClient(fake_comfy.url, timeout_s=2)
    out = asyncio.run(c.status())
    assert out["reachable"] is True
    assert out["comfyui_version"] == "fake-0.1"
    assert out["devices"][0]["name"] == "FakeGPU"
    assert out["queue_pending"] == 0


def test_queue_events_history_download(fake_comfy):
    c = ComfyClient(fake_comfy.url, timeout_s=2)
    graph, _ = WorkflowRegistry().get("image_basic_txt2img").build({"prompt": "x", "seed": 1})

    async def run():
        client_id = "test-client"
        progress: list[tuple[int, int]] = []
        done = asyncio.Event()

        async def listen():
            async for msg in c.events(client_id):
                if msg["type"] == "progress":
                    progress.append((msg["data"]["value"], msg["data"]["max"]))
                if msg["type"] in ("execution_success", "execution_error", "execution_interrupted"):
                    done.set()
                    return

        task = asyncio.create_task(listen())
        await asyncio.sleep(0.1)  # let the socket open before submitting
        pid = await c.queue_prompt(graph, client_id)
        await asyncio.wait_for(done.wait(), 5)
        task.cancel()
        hist = await c.history(pid)
        assert hist["status"]["completed"] is True
        files = parse_history_outputs(hist["outputs"])
        assert len(files) == 1 and files[0].kind == "image" and files[0].node == "9"
        data = await c.download(files[0])
        assert data.startswith(b"\x89PNG")
        return progress, pid

    progress, pid = asyncio.run(run())
    assert progress[-1] == (4, 4)
    assert fake_comfy.fake.submitted[-1]["client_id"] == "test-client"


def test_rejected_graph_raises(fake_comfy):
    c = ComfyClient(fake_comfy.url, timeout_s=2)
    with pytest.raises(ComfyError):
        asyncio.run(c.queue_prompt({"1": {"inputs": {}}}, "x"))


def test_unavailable_raises_on_events():
    c = ComfyClient("http://127.0.0.1:1", timeout_s=1)

    async def run():
        async for _ in c.events("x"):
            pass

    with pytest.raises(ComfyUnavailable):
        asyncio.run(run())


def test_parse_history_outputs_handles_video_and_audio():
    files = parse_history_outputs({
        "58": {"images": [{"filename": "a.mp4", "subfolder": "video", "type": "output"}], "animated": [True]},
        "60": {"audio": [{"filename": "b.flac", "subfolder": "", "type": "output"}]},
        "61": {"text": ["ignored"]},
    })
    kinds = {f.filename: f.kind for f in files}
    assert kinds == {"a.mp4": "video", "b.flac": "audio"}
