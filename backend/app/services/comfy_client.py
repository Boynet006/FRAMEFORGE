"""Async client for the ComfyUI HTTP + WebSocket API.

Endpoints used (all native ComfyUI, no custom nodes required):
  GET  /system_stats           versions + devices
  GET  /queue                  running / pending items
  POST /prompt                 submit an API-format graph -> prompt_id
  GET  /history/{prompt_id}    final status + outputs (source of truth)
  GET  /view?filename=..       download an output file
  POST /interrupt              stop the currently executing prompt
  POST /queue {"delete":[id]}  remove a pending prompt
  POST /free                   unload models / free VRAM
  POST /upload/image           put an input file (image or audio) into ComfyUI's input folder
  WS   /ws?clientId=..         live progress messages
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import websockets

log = logging.getLogger(__name__)


class ComfyError(RuntimeError):
    """ComfyUI reported a failure (graph rejected, execution error)."""


class ComfyUnavailable(ComfyError):
    """ComfyUI could not be reached. Treated as retryable by the runner."""


@dataclass
class OutputFile:
    node: str
    filename: str
    subfolder: str
    type: str  # "output" | "temp"
    kind: str  # image | video | audio | file

    @property
    def view_params(self) -> dict[str, str]:
        return {"filename": self.filename, "subfolder": self.subfolder, "type": self.type}


def _kind_for(filename: str, key: str, item: dict[str, Any]) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("mp4", "webm", "mov", "mkv", "gif") or key in ("gifs", "videos") or item.get("animated"):
        return "video"
    if ext in ("png", "jpg", "jpeg", "webp"):
        return "image"
    if ext in ("wav", "mp3", "flac", "ogg") or key == "audio":
        return "audio"
    return "file"


def parse_history_outputs(outputs: dict[str, Any]) -> list[OutputFile]:
    """Flatten ComfyUI's history `outputs` dict into files, whatever the node type.

    SaveImage uses {"images": [...]}, SaveVideo/VHS use "images"/"gifs"/"videos",
    SaveAudio uses "audio". Each item has filename/subfolder/type.
    """
    files: list[OutputFile] = []
    for node_id, node_out in (outputs or {}).items():
        if not isinstance(node_out, dict):
            continue
        for key, items in node_out.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and "filename" in item:
                    files.append(OutputFile(
                        node=str(node_id),
                        filename=item["filename"],
                        subfolder=item.get("subfolder", "") or "",
                        type=item.get("type", "output") or "output",
                        kind=_kind_for(item["filename"], key, item),
                    ))
    return files


class ComfyClient:
    def __init__(self, base_url: str, timeout_s: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    # ---------- low level ----------

    @property
    def ws_url(self) -> str:
        return self.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws"

    async def _request(self, method: str, path: str, *, timeout: float | None = None, **kw: Any) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout_s) as client:
                r = await client.request(method, f"{self.base_url}{path}", **kw)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ComfyUnavailable(f"ComfyUI unreachable at {self.base_url}: {exc}") from exc
        return r

    async def _get_json(self, path: str, **kw: Any) -> Any:
        r = await self._request("GET", path, **kw)
        if r.status_code >= 400:
            raise ComfyError(f"GET {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    # ---------- info ----------

    async def system_stats(self) -> dict[str, Any]:
        return await self._get_json("/system_stats")

    async def queue(self) -> dict[str, Any]:
        return await self._get_json("/queue")

    async def status(self) -> dict[str, Any]:
        """Connectivity report that never raises; used by /api/comfy/status."""
        t0 = time.perf_counter()
        try:
            stats = await self.system_stats()
        except ComfyUnavailable as exc:
            return {"reachable": False, "url": self.base_url, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"reachable": False, "url": self.base_url, "error": f"{type(exc).__name__}: {exc}"}
        system = stats.get("system", {})
        out: dict[str, Any] = {
            "reachable": True,
            "url": self.base_url,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "comfyui_version": system.get("comfyui_version"),
            "python_version": system.get("python_version"),
            "pytorch_version": system.get("pytorch_version"),
            "devices": stats.get("devices", []),
        }
        try:
            q = await self.queue()
            out["queue_running"] = len(q.get("queue_running", []))
            out["queue_pending"] = len(q.get("queue_pending", []))
        except Exception as exc:  # noqa: BLE001
            log.debug("ComfyUI /queue failed: %s", exc)
        return out

    # ---------- execution ----------

    async def queue_prompt(self, graph: dict[str, Any], client_id: str) -> str:
        r = await self._request("POST", "/prompt", json={"prompt": graph, "client_id": client_id}, timeout=30)
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {"error": r.text[:500]}
            raise ComfyError(f"ComfyUI rejected the graph: {json.dumps(body)[:1500]}")
        data = r.json()
        if data.get("node_errors"):
            raise ComfyError(f"ComfyUI node errors: {json.dumps(data['node_errors'])[:1500]}")
        return str(data["prompt_id"])

    async def history(self, prompt_id: str) -> dict[str, Any] | None:
        data = await self._get_json(f"/history/{prompt_id}")
        return data.get(prompt_id)

    async def interrupt(self) -> None:
        await self._request("POST", "/interrupt")

    async def delete_queued(self, prompt_id: str) -> None:
        await self._request("POST", "/queue", json={"delete": [prompt_id]})

    async def free(self, unload_models: bool = True, free_memory: bool = True) -> None:
        await self._request("POST", "/free", json={"unload_models": unload_models, "free_memory": free_memory})

    async def upload(self, data: bytes, filename: str) -> str:
        """Put a file into ComfyUI's input folder (images, and audio for LoadAudio) and return the
        name LoadImage/LoadAudio expect. ComfyUI's endpoint is called /upload/image whatever the type."""
        r = await self._request("POST", "/upload/image", timeout=120,
                                files={"image": (filename, data, "application/octet-stream")},
                                data={"overwrite": "true", "type": "input"})
        if r.status_code >= 400:
            raise ComfyError(f"upload {filename} -> HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        sub = body.get("subfolder") or ""
        return f"{sub}/{body['name']}" if sub else str(body["name"])

    async def download(self, out: OutputFile) -> bytes:
        r = await self._request("GET", "/view", params=out.view_params, timeout=600)
        if r.status_code >= 400:
            raise ComfyError(f"/view {out.filename} -> HTTP {r.status_code}")
        return r.content

    async def events(self, client_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield JSON progress messages from /ws. Binary preview frames are skipped.

        Raises ComfyUnavailable if the socket cannot be opened or drops.
        """
        try:
            async with websockets.connect(
                f"{self.ws_url}?clientId={client_id}", max_size=None, open_timeout=self.timeout_s
            ) as ws:
                async for msg in ws:
                    if isinstance(msg, bytes):
                        continue
                    try:
                        yield json.loads(msg)
                    except ValueError:
                        continue
        except (OSError, websockets.exceptions.WebSocketException) as exc:
            raise ComfyUnavailable(f"ComfyUI websocket failed: {exc}") from exc
