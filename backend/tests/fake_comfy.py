"""A small stand-in for ComfyUI's HTTP/WebSocket API, used only by the test-suite.

It reproduces the request/response *shapes* of the real server (POST /prompt,
GET /history/{id}, /view, /interrupt, /queue, /free, /system_stats, WS /ws)
so the client and job runner can be exercised without a GPU. It is never used
by the application itself.

Behaviour hooks for tests (via node inputs in the submitted graph):
  "__fail__": true, or a "text" input containing "__fail__"
                            -> execution_error after a few progress ticks
  "__slow_steps__": N       -> N progress ticks (default 4); tick_s sets their duration
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

# 1x1 transparent PNG
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da6364"
    "f8cfc0000000030001a5e7b76a0000000049454e44ae426082"
)


class FakeComfy:
    def __init__(self, output_dir: Path, tick_s: float = 0.02) -> None:
        self.output_dir = output_dir
        self.tick_s = tick_s
        self.app = FastAPI()
        self.history: dict[str, dict[str, Any]] = {}
        self.pending: list[str] = []
        self.running: str | None = None
        self.interrupted = False
        self.prompts: dict[str, dict[str, Any]] = {}
        self.clients: set[WebSocket] = set()
        self.submitted: list[dict[str, Any]] = []
        self.free_calls = 0
        self._routes()

    # ---------- helpers ----------

    async def _broadcast(self, msg: dict[str, Any]) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:  # noqa: BLE001
                self.clients.discard(ws)

    async def _run(self, prompt_id: str) -> None:
        graph = self.prompts[prompt_id]
        self.pending.remove(prompt_id)
        self.running = prompt_id
        self.interrupted = False
        await self._broadcast({"type": "execution_start", "data": {"prompt_id": prompt_id}})
        fail = any(
            n.get("inputs", {}).get("__fail__") or "__fail__" in str(n.get("inputs", {}).get("text", ""))
            for n in graph.values()
        )
        steps = next((int(n["inputs"]["__slow_steps__"]) for n in graph.values() if "__slow_steps__" in n.get("inputs", {})), 4)
        sampler = next((nid for nid, n in graph.items() if n.get("class_type") == "KSampler"), "3")
        await self._broadcast({"type": "executing", "data": {"node": sampler, "prompt_id": prompt_id}})
        for i in range(1, steps + 1):
            await asyncio.sleep(self.tick_s)
            if self.interrupted:
                self.history[prompt_id] = {"status": {"status_str": "error", "completed": False,
                                                      "messages": [["execution_interrupted", {"prompt_id": prompt_id}]]},
                                           "outputs": {}}
                await self._broadcast({"type": "execution_interrupted", "data": {"prompt_id": prompt_id, "node_id": sampler}})
                self.running = None
                return
            await self._broadcast({"type": "progress", "data": {"value": i, "max": steps, "prompt_id": prompt_id, "node": sampler}})
            if fail and i == 2:
                self.history[prompt_id] = {"status": {"status_str": "error", "completed": False,
                                                      "messages": [["execution_error", {"prompt_id": prompt_id, "exception_message": "fake failure"}]]},
                                           "outputs": {}}
                await self._broadcast({"type": "execution_error", "data": {"prompt_id": prompt_id, "node_id": sampler,
                                                                          "exception_message": "fake failure"}})
                self.running = None
                return
        outputs: dict[str, Any] = {}
        for nid, node in graph.items():
            ct = node.get("class_type")
            if ct == "SaveImage":
                fn = f"{prompt_id[:8]}_00001_.png"
                (self.output_dir / fn).write_bytes(_PNG)
                outputs[nid] = {"images": [{"filename": fn, "subfolder": "", "type": "output"}]}
            elif ct == "SaveVideo":
                fn = f"{prompt_id[:8]}_00001_.mp4"
                (self.output_dir / fn).write_bytes(b"FAKE_MP4" * 64)
                outputs[nid] = {"images": [{"filename": fn, "subfolder": "", "type": "output"}], "animated": [True]}
            if nid in outputs:
                await self._broadcast({"type": "executed", "data": {"node": nid, "output": outputs[nid], "prompt_id": prompt_id}})
        self.history[prompt_id] = {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": outputs}
        await self._broadcast({"type": "executing", "data": {"node": None, "prompt_id": prompt_id}})
        await self._broadcast({"type": "execution_success", "data": {"prompt_id": prompt_id}})
        self.running = None

    # ---------- routes ----------

    def _routes(self) -> None:
        app = self.app

        @app.get("/system_stats")
        async def system_stats() -> dict[str, Any]:
            return {"system": {"comfyui_version": "fake-0.1", "python_version": "3.x", "pytorch_version": "fake"},
                    "devices": [{"name": "FakeGPU", "type": "cuda", "vram_total": 16_000_000_000, "vram_free": 15_000_000_000}]}

        @app.get("/queue")
        async def queue() -> dict[str, Any]:
            return {"queue_running": [[0, self.running]] if self.running else [],
                    "queue_pending": [[i, p] for i, p in enumerate(self.pending)]}

        @app.post("/prompt")
        async def prompt(req: Request) -> JSONResponse:
            body = await req.json()
            graph = body.get("prompt") or {}
            self.submitted.append(body)
            bad = {nid: ["missing class_type"] for nid, n in graph.items() if "class_type" not in n}
            if bad or not graph:
                return JSONResponse({"error": {"type": "invalid_prompt", "message": "bad graph"}, "node_errors": bad}, status_code=400)
            pid = uuid.uuid4().hex
            self.prompts[pid] = graph
            self.pending.append(pid)
            asyncio.create_task(self._run(pid))
            return JSONResponse({"prompt_id": pid, "number": len(self.history), "node_errors": {}})

        @app.get("/history/{pid}")
        async def history(pid: str) -> dict[str, Any]:
            return {pid: self.history[pid]} if pid in self.history else {}

        @app.get("/view")
        async def view(filename: str, subfolder: str = "", type: str = "output"):  # noqa: A002
            p = self.output_dir / filename
            if not p.exists():
                return JSONResponse({"error": "not found"}, status_code=404)
            return FileResponse(p)

        @app.post("/interrupt")
        async def interrupt() -> dict[str, Any]:
            self.interrupted = True
            return {}

        @app.post("/queue")
        async def queue_post(req: Request) -> dict[str, Any]:
            body = await req.json()
            for pid in body.get("delete", []):
                if pid in self.pending:
                    self.pending.remove(pid)
            return {}

        @app.post("/free")
        async def free() -> dict[str, Any]:
            self.free_calls += 1
            return {}

        @app.websocket("/ws")
        async def ws(websocket: WebSocket) -> None:
            await websocket.accept()
            self.clients.add(websocket)
            await websocket.send_json({"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 0}}}})
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                self.clients.discard(websocket)


if __name__ == "__main__":  # manual UI testing:  python -m tests.fake_comfy --port 8188
    import argparse
    import tempfile

    ap = argparse.ArgumentParser(description="Run the stand-in ComfyUI server (tests only)")
    ap.add_argument("--port", type=int, default=8188)
    ap.add_argument("--tick", type=float, default=0.5, help="seconds per progress step")
    ap.add_argument("--steps", type=int, default=20, help="progress steps per job")
    args = ap.parse_args()
    out_dir = Path(tempfile.mkdtemp(prefix="fake-comfy-"))
    fake = FakeComfy(out_dir, tick_s=args.tick)
    _orig_run = fake._run

    async def _slow_run(pid: str) -> None:  # default more steps so progress is visible in the UI
        for node in fake.prompts[pid].values():
            node.setdefault("inputs", {}).setdefault("__slow_steps__", args.steps)
        await _orig_run(pid)

    fake._run = _slow_run  # type: ignore[method-assign]
    print(f"stand-in ComfyUI on http://127.0.0.1:{args.port}  outputs -> {out_dir}")
    uvicorn.run(fake.app, host="127.0.0.1", port=args.port, log_level="warning")


class FakeComfyServer:
    """Runs FakeComfy under uvicorn in a background thread."""

    def __init__(self, output_dir: Path) -> None:
        self.fake = FakeComfy(output_dir)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(self.fake.app, host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> "FakeComfyServer":
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started and time.time() < deadline:
            time.sleep(0.05)
        if not self._server.started:
            raise RuntimeError("fake ComfyUI did not start")
        return self

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)
