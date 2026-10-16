from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from ..services.workflows import WorkflowError, get_registry

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("", response_model=list[dict[str, Any]])
def list_workflows() -> list[dict[str, Any]]:
    """All versioned workflow templates with their parameter manifests."""
    return [t.manifest() for t in get_registry().list()]


@router.get("/{name}")
def get_workflow(name: str, version: int | None = None) -> dict[str, Any]:
    try:
        return get_registry().get(name, version).manifest()
    except WorkflowError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/reload", status_code=status.HTTP_204_NO_CONTENT)
def reload_workflows() -> None:
    """Re-read the workflows/ folder (after editing or adding a template)."""
    get_registry().reload()
