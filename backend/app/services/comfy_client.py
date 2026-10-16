"""Thin async client for the ComfyUI HTTP API.

Phase 1 only needs connectivity and system info. Later phases add
/prompt submission, /history polling, /view output retrieval, /interrupt and
the WebSocket progress stream, all through this one module.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)


class ComfyClient:
    def __init__(self, base_url: str, timeout_s: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def _get(self, path: str) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.get(f"{self.base_url}{path}")
            r.raise_for_status()
            return r.json()

    async def system_stats(self) -> dict[str, Any]:
        """GET /system_stats -> {"system": {...}, "devices": [...]}"""
        return await self._get("/system_stats")

    async def queue(self) -> dict[str, Any]:
        """GET /queue -> {"queue_running": [...], "queue_pending": [...]}"""
        return await self._get("/queue")

    async def status(self) -> dict[str, Any]:
        """Combine system_stats and queue into one connectivity report.

        Never raises; failures are reported in the returned dict so the API
        can show a truthful "unreachable" state.
        """
        t0 = time.perf_counter()
        try:
            stats = await self.system_stats()
            latency_ms = (time.perf_counter() - t0) * 1000
            system = stats.get("system", {})
            out: dict[str, Any] = {
                "reachable": True,
                "url": self.base_url,
                "latency_ms": round(latency_ms, 1),
                "comfyui_version": system.get("comfyui_version"),
                "python_version": system.get("python_version"),
                "pytorch_version": system.get("pytorch_version"),
                "devices": stats.get("devices", []),
            }
            try:
                q = await self.queue()
                out["queue_running"] = len(q.get("queue_running", []))
                out["queue_pending"] = len(q.get("queue_pending", []))
            except Exception as exc:  # queue is secondary; don't fail the whole check
                log.debug("ComfyUI /queue failed: %s", exc)
            return out
        except httpx.ConnectError as exc:
            err = f"connection refused: {exc}"
        except httpx.TimeoutException:
            err = f"timed out after {self.timeout_s}s"
        except httpx.HTTPStatusError as exc:
            err = f"HTTP {exc.response.status_code} from {exc.request.url}"
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
        log.info("ComfyUI unreachable at %s (%s)", self.base_url, err)
        return {"reachable": False, "url": self.base_url, "error": err}
