"""FastAPI application entry point.

Run from the backend/ folder:
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import get_settings
from .db import init_db
from .logging_config import configure_logging
from .routers import comfy, health, jobs, projects

settings = get_settings()
configure_logging(settings.log_level)
log = logging.getLogger("frameforge")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    log.info(
        "FRAMEFORGE backend %s started; data dir %s; ComfyUI %s",
        __version__, settings.resolved_data_dir, settings.comfyui_url,
    )
    yield
    log.info("FRAMEFORGE backend stopped")


app = FastAPI(
    title="FRAMEFORGE API",
    version=__version__,
    description="Local AI video studio orchestration backend.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(comfy.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"internal error: {type(exc).__name__}", "path": request.url.path},
    )


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"name": "FRAMEFORGE API", "version": __version__, "docs": "/docs"}
