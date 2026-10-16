from __future__ import annotations

import pytest

from app.services.workflows import WorkflowError, WorkflowRegistry


@pytest.fixture(scope="module")
def reg() -> WorkflowRegistry:
    return WorkflowRegistry()


def test_templates_load(reg):
    keys = [t.key for t in reg.list()]
    assert "image_basic_txt2img.v1" in keys
    assert "video_wan22_5b_t2v.v1" in keys


def test_get_latest_and_specific(reg):
    assert reg.get("image_basic_txt2img").version == 1
    assert reg.get("image_basic_txt2img", 1).key == "image_basic_txt2img.v1"
    with pytest.raises(WorkflowError):
        reg.get("image_basic_txt2img", 99)
    with pytest.raises(WorkflowError):
        reg.get("nope")


def test_build_applies_params_and_defaults(reg):
    t = reg.get("image_basic_txt2img")
    graph, resolved = t.build({"prompt": "two cats", "steps": "8", "seed": 42})
    assert graph["6"]["inputs"]["text"] == "two cats"
    assert graph["3"]["inputs"]["steps"] == 8 and isinstance(graph["3"]["inputs"]["steps"], int)
    assert graph["3"]["inputs"]["seed"] == 42
    assert graph["7"]["inputs"]["text"] == t.inputs["negative_prompt"].default
    assert resolved["width"] == 1024
    # template graph must not be mutated
    assert t.graph["6"]["inputs"]["text"] == ""


def test_build_randomises_negative_seed(reg):
    t = reg.get("image_basic_txt2img")
    g1, r1 = t.build({"seed": -1})
    g2, r2 = t.build({"seed": -1})
    assert r1["seed"] >= 0 and r2["seed"] >= 0
    assert g1["3"]["inputs"]["seed"] == r1["seed"]


def test_build_rejects_unknown_and_out_of_range(reg):
    t = reg.get("image_basic_txt2img")
    with pytest.raises(WorkflowError):
        t.build({"bogus": 1})
    with pytest.raises(WorkflowError):
        t.build({"width": 10})
    with pytest.raises(WorkflowError):
        t.build({"steps": "many"})


def test_manifest_has_no_graph(reg):
    m = reg.get("video_wan22_5b_t2v").manifest()
    assert "graph" not in m
    assert m["output_kind"] == "video" and m["validated"] is False
    assert m["inputs"]["frames"]["default"] == 121
