"""Subprocess helpers that work on every asyncio event loop.

Windows + uvicorn uses the selector event loop, which cannot spawn asyncio
subprocesses (NotImplementedError). So workers are run with the blocking
`subprocess` module inside a thread, and progress lines are relayed back to
the event loop with run_coroutine_threadsafe.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]


class WorkerError(RuntimeError):
    pass


async def run_worker(cmd: list[str], cwd: Path | None, progress: ProgressCb | None, label: str,
                     *, lo: float = 0.0, hi: float = 0.999) -> str:
    """Run a worker, forward "PROGRESS i n" stdout lines to `progress`, return the last other stdout line.

    Raises WorkerError with the stderr tail when the process exits non-zero.
    """
    loop = asyncio.get_running_loop()

    def work() -> tuple[int, str, str]:
        try:
            proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        except OSError as exc:
            raise WorkerError(f"cannot start {label} worker ({cmd[0]}): {exc}") from exc
        err_lines: list[str] = []

        def drain() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                err_lines.append(line.rstrip())

        t = threading.Thread(target=drain, daemon=True)
        t.start()
        last = ""
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.strip()
            if line.startswith("PROGRESS ") and progress is not None:
                try:
                    _, i, n = line.split()
                    value = lo + (hi - lo) * min(int(i) / max(int(n), 1), 1.0)
                    asyncio.run_coroutine_threadsafe(progress(value, f"{label} {i}/{n}"), loop).result(timeout=10)
                except Exception as exc:  # noqa: BLE001  (progress must never kill the worker)
                    log.debug("progress relay failed: %s", exc)
            elif line:
                last = line
        rc = proc.wait()
        t.join(timeout=5)
        return rc, last, "\n".join(err_lines)

    rc, last, stderr = await asyncio.to_thread(work)
    for l in stderr.splitlines():
        if l.startswith(("INFO", "WARN")):
            log.info("%s worker: %s", label, l)
    if rc != 0:
        tail = "\n".join(stderr.strip().splitlines()[-10:])
        raise WorkerError(f"{label} worker failed (exit {rc}): {tail or 'no error output'}")
    return last


async def run_cmd(cmd: list[str], what: str) -> str:
    """Run a short command to completion in a thread; return stdout; raise WorkerError on failure."""

    def work() -> tuple[int, str, str]:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        except OSError as exc:
            raise WorkerError(f"cannot start {what} ({cmd[0]}): {exc}") from exc
        return p.returncode, p.stdout, p.stderr

    rc, out, err = await asyncio.to_thread(work)
    if rc != 0:
        tail = "\n".join(err.strip().splitlines()[-8:])
        raise WorkerError(f"{what} failed (exit {rc}): {tail}")
    return out
