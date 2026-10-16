from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..config import Settings, get_settings
from ..schemas import ComfyStatusResponse
from ..services.comfy_client import ComfyClient, ComfyError

router = APIRouter(prefix="/comfy", tags=["comfyui"])


def get_comfy(request: Request, settings: Settings = Depends(get_settings)) -> ComfyClient:
    # The runner's URL is authoritative (tests may redirect it to a stand-in server).
    runner = getattr(request.app.state, "runner", None)
    url = runner.comfy_url if runner else settings.comfyui_url
    return ComfyClient(url, settings.comfyui_timeout_s)


@router.get("/status", response_model=ComfyStatusResponse)
async def comfy_status(client: ComfyClient = Depends(get_comfy)) -> ComfyStatusResponse:
    """Live connectivity check against the configured ComfyUI instance."""
    return ComfyStatusResponse(**await client.status())


@router.post("/free", status_code=204)
async def comfy_free(client: ComfyClient = Depends(get_comfy)) -> None:
    """Ask ComfyUI to unload models and free VRAM (used between pipeline stages)."""
    try:
        await client.free(unload_models=True, free_memory=True)
    except ComfyError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
