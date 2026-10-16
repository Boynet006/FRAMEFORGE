from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..schemas import ComfyStatusResponse
from ..services.comfy_client import ComfyClient

router = APIRouter(prefix="/comfy", tags=["comfyui"])


def get_comfy(settings: Settings = Depends(get_settings)) -> ComfyClient:
    return ComfyClient(settings.comfyui_url, settings.comfyui_timeout_s)


@router.get("/status", response_model=ComfyStatusResponse)
async def comfy_status(client: ComfyClient = Depends(get_comfy)) -> ComfyStatusResponse:
    """Live connectivity check against the configured ComfyUI instance."""
    return ComfyStatusResponse(**await client.status())
