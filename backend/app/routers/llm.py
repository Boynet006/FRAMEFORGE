from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import LLMStatusResponse
from ..services.llm_client import OllamaClient

router = APIRouter(prefix="/llm", tags=["llm"])


def get_llm(request: Request) -> OllamaClient:
    runner = request.app.state.runner
    return OllamaClient(runner.ollama_url, runner.settings.ollama_model, runner.settings.ollama_timeout_s)


@router.get("/status", response_model=LLMStatusResponse)
async def llm_status(request: Request) -> LLMStatusResponse:
    """Live Ollama connectivity and whether the configured model is pulled."""
    return LLMStatusResponse(**await get_llm(request).status())
