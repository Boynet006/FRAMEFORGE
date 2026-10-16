"""Best-effort GPU detection via nvidia-smi. Returns [] when no NVIDIA GPU/driver exists."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_QUERY = "--query-gpu=name,driver_version,memory.total,memory.used"


def _find_nvidia_smi() -> str | None:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    import os

    for p in (
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
    ):
        if p.exists():
            return str(p)
    return None


def detect_gpus() -> list[dict]:
    exe = _find_nvidia_smi()
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, _QUERY, "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
    except Exception as exc:  # noqa: BLE001
        log.warning("nvidia-smi failed: %s", exc)
        return []
    gpus: list[dict] = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            gpus.append({
                "name": parts[0],
                "driver_version": parts[1],
                "memory_total_mb": int(float(parts[2])),
                "memory_used_mb": int(float(parts[3])),
            })
        except ValueError:
            gpus.append({"name": parts[0], "driver_version": parts[1]})
    return gpus
