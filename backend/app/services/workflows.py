"""Versioned ComfyUI workflow templates.

A template is a JSON file `backend/workflows/<name>.v<N>.json` holding an
API-format ComfyUI graph plus a manifest describing which node fields are
exposed as parameters. `build()` turns (template, params) into the exact
`prompt` dict that ComfyUI's POST /prompt accepts.
"""

from __future__ import annotations

import copy
import json
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent.parent / "workflows"
_FILE_RE = re.compile(r"^(?P<name>[a-z0-9_]+)\.v(?P<version>\d+)\.json$")
_SEED_MAX = 2**53 - 1  # keeps seeds exact in JSON/JS


class WorkflowError(ValueError):
    pass


@dataclass
class InputSpec:
    node: str
    field: str
    type: str  # string | integer | number | boolean
    default: Any = None
    label: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None

    def coerce(self, name: str, value: Any) -> Any:
        try:
            if self.type == "integer":
                value = int(value)
            elif self.type == "number":
                value = float(value)
            elif self.type == "boolean":
                value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
            elif self.type == "string":
                value = str(value)
        except (TypeError, ValueError) as exc:
            raise WorkflowError(f"parameter '{name}' must be {self.type}") from exc
        if self.type in ("integer", "number"):
            if self.min is not None and value < self.min:
                raise WorkflowError(f"parameter '{name}' below minimum {self.min}")
            if self.max is not None and value > self.max:
                raise WorkflowError(f"parameter '{name}' above maximum {self.max}")
        return value


@dataclass
class WorkflowTemplate:
    name: str
    version: int
    engine: str
    description: str
    output_kind: str
    validated: bool
    requires: dict[str, Any]
    inputs: dict[str, InputSpec]
    outputs: list[dict[str, str]]
    graph: dict[str, Any]
    path: Path = field(repr=False)
    # Free-form hints for engines that drive the template, e.g. native sizes
    # {"character_size": [w, h], "environment_size": [w, h]} for reference images.
    hints: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.name}.v{self.version}"

    def manifest(self) -> dict[str, Any]:
        """Public description for the API/UI (no graph)."""
        return {
            "name": self.name,
            "version": self.version,
            "key": self.key,
            "engine": self.engine,
            "description": self.description,
            "output_kind": self.output_kind,
            "validated": self.validated,
            "requires": self.requires,
            "inputs": {
                k: {
                    "type": s.type, "default": s.default, "label": s.label or k,
                    "min": s.min, "max": s.max, "step": s.step,
                }
                for k, s in self.inputs.items()
            },
            "outputs": self.outputs,
            "hints": self.hints,
        }

    def build(self, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (prompt_graph, resolved_params). Unknown params are an error."""
        params = dict(params or {})
        unknown = set(params) - set(self.inputs)
        if unknown:
            raise WorkflowError(f"unknown parameter(s) for {self.key}: {sorted(unknown)}")
        graph = copy.deepcopy(self.graph)
        resolved: dict[str, Any] = {}
        for name, spec in self.inputs.items():
            value = params.get(name, spec.default)
            if value is None:
                continue
            value = spec.coerce(name, value)
            if spec.field == "seed" and isinstance(value, int) and value < 0:
                value = random.randint(0, _SEED_MAX)
            node = graph.get(spec.node)
            if node is None:
                raise WorkflowError(f"{self.key}: input '{name}' points at missing node {spec.node}")
            node.setdefault("inputs", {})[spec.field] = value
            resolved[name] = value
        return graph, resolved


def _parse(path: Path) -> WorkflowTemplate:
    m = _FILE_RE.match(path.name)
    if not m:
        raise WorkflowError(f"bad workflow filename {path.name}; expected <name>.v<N>.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    name, version = m.group("name"), int(m.group("version"))
    if data.get("name") != name or int(data.get("version", -1)) != version:
        raise WorkflowError(f"{path.name}: name/version inside the file do not match the filename")
    inputs = {k: InputSpec(**v) for k, v in data.get("inputs", {}).items()}
    graph = data["graph"]
    for k, spec in inputs.items():
        if spec.node not in graph:
            raise WorkflowError(f"{path.name}: input '{k}' references missing node {spec.node}")
    for out in data.get("outputs", []):
        if out["node"] not in graph:
            raise WorkflowError(f"{path.name}: output references missing node {out['node']}")
    return WorkflowTemplate(
        name=name,
        version=version,
        engine=data.get("engine", "comfyui"),
        description=data.get("description", ""),
        output_kind=data.get("output_kind", "image"),
        validated=bool(data.get("validated", False)),
        requires=data.get("requires", {}),
        inputs=inputs,
        outputs=data.get("outputs", []),
        graph=graph,
        path=path,
        hints=data.get("hints", {}),
    )


class WorkflowRegistry:
    def __init__(self, directory: Path = WORKFLOWS_DIR) -> None:
        self.directory = directory
        self._templates: dict[str, WorkflowTemplate] = {}
        self.reload()

    def reload(self) -> None:
        found: dict[str, WorkflowTemplate] = {}
        for path in sorted(self.directory.glob("*.v*.json")):
            try:
                t = _parse(path)
            except Exception as exc:  # noqa: BLE001
                log.error("skipping workflow %s: %s", path.name, exc)
                continue
            found[t.key] = t
        self._templates = found
        log.info("loaded %d workflow template(s) from %s", len(found), self.directory)

    def list(self) -> list[WorkflowTemplate]:
        return sorted(self._templates.values(), key=lambda t: (t.name, t.version))

    def get(self, name: str, version: int | None = None) -> WorkflowTemplate:
        if version is not None:
            t = self._templates.get(f"{name}.v{version}")
            if t is None:
                raise WorkflowError(f"workflow {name} v{version} not found")
            return t
        candidates = [t for t in self._templates.values() if t.name == name]
        if not candidates:
            raise WorkflowError(f"workflow {name} not found")
        return max(candidates, key=lambda t: t.version)


_registry: WorkflowRegistry | None = None


def get_registry() -> WorkflowRegistry:
    global _registry
    if _registry is None:
        _registry = WorkflowRegistry()
    return _registry
