"""Stand-in for Ollama's /api/chat used by the planner tests (no model needed).

It inspects the requested JSON schema to decide whether an outline or scene
lines are wanted and returns deterministic, valid content.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

OUTLINE = {
    "title": "Kibble Court",
    "logline": "Two cats put humanity on trial for its food choices.",
    "characters": [
        {"name": "Miso", "role": "prosecutor", "personality": "dramatic, smug, loves monologues",
         "appearance": "sleek black cat with green eyes and a tiny red bow tie", "voice_gender": "female"},
        {"name": "Biscuit", "role": "defender", "personality": "lazy, deadpan, secretly wise",
         "appearance": "chubby orange tabby with a white chest and half-closed eyes", "voice_gender": "male"},
    ],
    "environments": [
        {"name": "Kitchen Counter", "description": "sunlit kitchen counter with a fruit bowl and a half-eaten sandwich"},
    ],
    "scenes": [],
    "music_mood": "playful jazz",
}

LINES = [
    {"character": "Miso", "text": "Members of the jury, I present exhibit A: a sandwich with kale in it.", "emotion": "smug"},
    {"character": "Biscuit", "text": "Objection. Kale is technically food.", "emotion": "deadpan"},
    {"character": "Miso", "text": "Technically! That word is doing a lot of heavy lifting, Biscuit.", "emotion": "amused"},
    {"character": "Biscuit", "text": "Everything I do is heavy lifting. Have you seen me?", "emotion": "proud"},
    {"character": "Miso", "text": "The prosecution rests. On the warm laptop, specifically.", "emotion": "satisfied"},
]


class FakeOllama:
    def __init__(self, models: list[str] | None = None) -> None:
        self.models = models if models is not None else ["qwen3:4b"]
        self.app = FastAPI()
        self.calls: list[dict[str, Any]] = []
        self.unloads = 0
        self.fail_next = 0
        self._routes()

    def _routes(self) -> None:
        app = self.app

        @app.get("/api/tags")
        async def tags() -> dict[str, Any]:
            return {"models": [{"name": m} for m in self.models]}

        @app.post("/api/chat")
        async def chat(req: Request) -> JSONResponse:
            body = await req.json()
            self.calls.append(body)
            if self.fail_next > 0:
                self.fail_next -= 1
                return JSONResponse({"error": "model crashed"}, status_code=500)
            if body.get("model") not in self.models:
                return JSONResponse({"error": f"model '{body.get('model')}' not found"}, status_code=404)
            required = set(body.get("format", {}).get("required", []))
            user = body["messages"][-1]["content"]
            if "scenes" in required:
                import re

                n = int(re.search(r"exactly (\d+) scene", user).group(1))
                total = int(re.search(r"about (\d+) words total", user).group(1))
                out = dict(OUTLINE)
                out["scenes"] = [
                    {"environment": "Kitchen Counter", "summary": f"Scene {i + 1} of the trial",
                     "time_of_day": "afternoon", "word_budget": total // n}
                    for i in range(n)
                ]
                content = json.dumps(out)
            else:
                import re

                m = re.search(r"About (\d+) words", user)
                budget = int(m.group(1)) if m else 60
                lines: list[dict[str, Any]] = []
                while sum(len(l["text"].split()) for l in lines) < budget * 0.8:
                    lines.extend(LINES)
                content = json.dumps({"lines": lines})
            return JSONResponse({"model": body["model"], "message": {"role": "assistant", "content": content}, "done": True})

        @app.post("/api/generate")
        async def generate(req: Request) -> dict[str, Any]:
            body = await req.json()
            if body.get("keep_alive") == 0:
                self.unloads += 1
            return {"done": True}


class FakeOllamaServer:
    def __init__(self, models: list[str] | None = None) -> None:
        self.fake = FakeOllama(models)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._server = uvicorn.Server(uvicorn.Config(self.fake.app, host="127.0.0.1", port=self.port, log_level="warning"))
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> "FakeOllamaServer":
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started and time.time() < deadline:
            time.sleep(0.05)
        if not self._server.started:
            raise RuntimeError("fake Ollama did not start")
        return self

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)
