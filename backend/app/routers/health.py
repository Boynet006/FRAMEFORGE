from __future__ import annotations

import platform
import sys
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import __version__
from ..db import get_session
from ..schemas import HealthResponse
from ..services.gpu import detect_gpus

router = APIRouter(tags=["health"])
_STARTED = time.monotonic()


@router.get("/health", response_model=HealthResponse)
def health(session: Session = Depends(get_session)) -> HealthResponse:
    db_ok = True
    try:
        session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=__version__,
        uptime_s=round(time.monotonic() - _STARTED, 1),
        time=datetime.now(timezone.utc),
        database_ok=db_ok,
        gpu=detect_gpus(),
        python=sys.version.split()[0],
        platform=f"{platform.system()} {platform.release()}",
    )
