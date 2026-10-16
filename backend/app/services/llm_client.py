"""Minimal async client for a local Ollama server.

Uses /api/chat with `format` set to a JSON schema so the model is constrained to
valid JSON. Thinking is disabled for speed on reasoning models (qwen3 etc.).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_s: float = 600.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    async def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=kw.pop("timeout", self.timeout_s)) as client:
                return await client.request(method, f"{self.base_url}{path}", **kw)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise LLMUnavailable(f"Ollama unreachable at {self.base_url}: {exc}") from exc

    async def status(self) -> dict[str, Any]:
        """Never raises. Reports reachability and whether the configured model is present."""
        try:
            r = await self._request("GET", "/api/tags", timeout=3)
            r.raise_for_status()
            models = [m.get("name") for m in r.json().get("models", [])]
        except LLMUnavailable as exc:
            return {"reachable": False, "url": self.base_url, "model": self.model, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"reachable": False, "url": self.base_url, "model": self.model, "error": f"{type(exc).__name__}: {exc}"}
        have = any(m == self.model or m.split(":")[0] == self.model.split(":")[0] and m.startswith(self.model) for m in models)
        return {"reachable": True, "url": self.base_url, "model": self.model, "model_available": have, "models": models}

    async def chat_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        temperature: float = 0.7,
        keep_alive: str | int = "5m",
    ) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "think": False,
            "keep_alive": keep_alive,
            "options": {"temperature": temperature},
        }
        r = await self._request("POST", "/api/chat", json=body)
        if r.status_code >= 400:
            raise LLMError(f"Ollama HTTP {r.status_code}: {r.text[:500]}")
        content = r.json().get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except ValueError as exc:
            raise LLMError(f"model returned invalid JSON: {content[:300]}") from exc

    async def unload(self) -> None:
        """Free the model's memory so a later stage (ComfyUI) can use it."""
        try:
            await self._request("POST", "/api/generate", json={"model": self.model, "keep_alive": 0}, timeout=10)
        except LLMUnavailable:
            pass
