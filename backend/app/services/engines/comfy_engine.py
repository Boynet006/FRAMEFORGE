"""Runs one `comfy.workflow` job against a ComfyUI instance.

Progress comes from ComfyUI's own websocket messages; the final result always
comes from GET /history/{prompt_id}, which is the server's source of truth.
If the websocket drops, the engine falls back to polling history.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..comfy_client import ComfyClient, ComfyError, ComfyUnavailable, parse_history_outputs
from ..workflows import WorkflowRegistry

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]
PersistCb = Callable[[dict[str, Any]], Awaitable[None]]


class JobCancelled(Exception):
    pass


class ComfyEngine:
    def __init__(
        self,
        client: ComfyClient,
        registry: WorkflowRegistry,
        *,
        poll_s: float = 2.0,
        timeout_s: float = 6 * 3600,
    ) -> None:
        self.client = client
        self.registry = registry
        self.poll_s = poll_s
        self.timeout_s = timeout_s

    async def run(
        self,
        job_id: str,
        payload: dict[str, Any],
        output_dir: Path,
        *,
        progress: ProgressCb,
        persist_payload: PersistCb,
        cancel_requested: Callable[[], bool],
        graph_hook: Callable[[dict[str, Any], Any, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        template = self.registry.get(payload["workflow"], payload.get("version"))
        graph, resolved = template.build(payload.get("params") or {})
        if graph_hook is not None:
            # engines that need a variable-size graph (e.g. S2V extension chunks) expand the template here
            graph = graph_hook(graph, template, resolved)
        client_id = f"frameforge-{job_id}"
        t0 = time.perf_counter()

        prompt_id = payload.get("prompt_id")
        if prompt_id and await self.client.history(prompt_id) is not None:
            log.info("job %s: prompt %s already in history, finalising", job_id, prompt_id)
        else:
            # Open the event stream first so no early message is missed.
            stream = _EventStream(self.client, client_id)
            await stream.start()
            try:
                prompt_id = await self.client.queue_prompt(graph, client_id)
                await persist_payload({**payload, "prompt_id": prompt_id, "workflow_key": template.key})
                log.info("job %s: queued ComfyUI prompt %s (%s)", job_id, prompt_id, template.key)
                await self._wait(prompt_id, stream, progress, cancel_requested)
            finally:
                await stream.stop()

        hist = await self._history_with_retry(prompt_id)
        status = hist.get("status", {})
        if not status.get("completed"):
            msgs = status.get("messages", [])
            if any(m and m[0] == "execution_interrupted" for m in msgs):
                raise JobCancelled()
            raise ComfyError(_error_from_messages(msgs) or "ComfyUI reported failure without details")

        files = parse_history_outputs(hist.get("outputs", {}))
        if not files:
            raise ComfyError("ComfyUI finished but produced no output files")
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs: list[dict[str, Any]] = []
        for f in files:
            data = await self.client.download(f)
            safe_name = Path(f.filename).name
            (output_dir / safe_name).write_bytes(data)
            outputs.append({"filename": safe_name, "kind": f.kind, "node": f.node, "size": len(data)})
        await progress(1.0, None)
        return {
            "prompt_id": prompt_id,
            "workflow": template.key,
            "params": resolved,
            "outputs": outputs,
            "duration_s": round(time.perf_counter() - t0, 1),
        }

    async def _wait(
        self,
        prompt_id: str,
        stream: "_EventStream",
        progress: ProgressCb,
        cancel_requested: Callable[[], bool],
    ) -> None:
        deadline = time.monotonic() + self.timeout_s
        interrupted = False
        last_poll = 0.0
        while True:
            if time.monotonic() > deadline:
                await self._interrupt(prompt_id)
                raise ComfyError(f"job exceeded {self.timeout_s}s timeout")
            if cancel_requested() and not interrupted:
                interrupted = True
                await self._interrupt(prompt_id)
            msg = await stream.next(timeout=1.0)
            if msg is not None:
                t = msg.get("type")
                d = msg.get("data", {}) or {}
                if d.get("prompt_id") not in (None, prompt_id):
                    continue
                if t == "progress" and d.get("max"):
                    await progress(min(d["value"] / d["max"], 0.999), d.get("node"))
                elif t == "executing" and d.get("node") is None and d.get("prompt_id") == prompt_id:
                    return  # finished executing; history has the result
                elif t == "execution_success":
                    return
                elif t == "execution_error":
                    raise ComfyError(d.get("exception_message") or "execution_error")
                elif t == "execution_interrupted":
                    raise JobCancelled()
                continue
            # No message within 1 s: if the stream is dead, poll history instead.
            if stream.failed and time.monotonic() - last_poll >= self.poll_s:
                last_poll = time.monotonic()
                hist = await self.client.history(prompt_id)
                if hist is not None and hist.get("status"):
                    return

    async def _interrupt(self, prompt_id: str) -> None:
        try:
            await self.client.delete_queued(prompt_id)
            await self.client.interrupt()
        except ComfyError as exc:
            log.warning("interrupt failed: %s", exc)

    async def _history_with_retry(self, prompt_id: str) -> dict[str, Any]:
        for _ in range(10):
            hist = await self.client.history(prompt_id)
            if hist is not None and hist.get("status"):
                return hist
            await asyncio.sleep(0.3)
        raise ComfyError(f"prompt {prompt_id} never appeared in ComfyUI history")


def _error_from_messages(msgs: list[Any]) -> str | None:
    for m in msgs:
        if m and m[0] == "execution_error":
            d = m[1] if len(m) > 1 and isinstance(m[1], dict) else {}
            return f"{d.get('exception_type', 'error')}: {d.get('exception_message', '')}".strip()
    return None


class _EventStream:
    """Background task reading ComfyUI websocket messages into a queue."""

    def __init__(self, client: ComfyClient, client_id: str) -> None:
        self.client = client
        self.client_id = client_id
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.failed = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._pump())
        await asyncio.sleep(0.05)

    async def _pump(self) -> None:
        try:
            async for msg in self.client.events(self.client_id):
                await self.queue.put(msg)
        except ComfyUnavailable as exc:
            log.warning("ComfyUI websocket unavailable, falling back to polling: %s", exc)
            self.failed = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("ComfyUI websocket error, falling back to polling: %s", exc)
            self.failed = True

    async def next(self, timeout: float) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except asyncio.TimeoutError:
            return None

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
