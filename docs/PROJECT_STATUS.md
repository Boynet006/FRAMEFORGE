# FRAMEFORGE — Project Status

Last updated: 2026-10-16 (Phase 2 built)

## Current phase

**Phase 0 — Environment and feasibility** is still open (waiting for the 5080 PC probe, the
commercial-use answer and the visual-style answer). **Phases 1 and 2** were built on the dev
machine because they need no GPU; Phase 2 awaits validation against a real ComfyUI.

## Summary

| Phase | Status | Notes |
|---|---|---|
| 0 Environment & feasibility | In progress | Session machine probed: HP all-in-one, Intel iGPU, 15 GB RAM, **no NVIDIA GPU**. RTX 5080 machine not yet probed. Candidate model stack drafted. See [PHASE0_ENVIRONMENT_REPORT.md](PHASE0_ENVIRONMENT_REPORT.md). |
| 1 Project foundation | **Done (on the AIO dev machine), 2026-10-16** | FastAPI backend with `/api/health`, `/api/comfy/status`, project + job persistence (SQLite); Next.js 16 + Tailwind 4 dark dashboard; dev scripts; git repo. Tested: 5 backend tests pass, dashboard verified in browser, project created end to end. ComfyUI check truthfully reports "unreachable" here. Remaining: re-run on the 5080 PC with ComfyUI up. |
| 2 UI + ComfyUI integration | **Built and tested against a stand-in ComfyUI, 2026-10-16.** Real-engine validation pending. | Full ComfyUI API client (HTTP + WebSocket), versioned workflow templates, background job runner with cancel/retry/resume, jobs API, WebSocket events, generation UI with live progress and previews. 26 backend tests pass; UI verified in the browser against the stand-in. **Not yet run against a real ComfyUI**; the two templates are marked `validated: false`. |
| 3 Script & production planning | Not started | |
| 4 Dialogue & voices | Not started | |
| 5 Character animation & lip sync | Not started | Highest technical risk: audio-driven animation of non-human characters at 16 GB. |
| 6 Automated scene generation | Not started | |
| 7 Editing & final render | Not started | |
| 8 Full 10-minute production | Not started | Expect 6-14 h final renders; checkpointing is mandatory. |
| 9 Reliability & usability | Not started | |

## Architecture decisions (so far)

- One heavy model family on the GPU at a time; orchestrator enforces stage order and unloads
  between stages (ComfyUI `/free`, Ollama `keep_alive: 0`).
- Hybrid generation: reference images → audio-driven speaking shots (Wan 2.2 S2V) → generative
  non-speaking shots (Wan 2.2 14B / LTX-2) → deterministic FFmpeg assembly from a master timeline.
- **Deployment layout (decided 2026-10-16): everything runs on the RTX 5080 PC** — frontend,
  backend, ComfyUI, Ollama, TTS. The HP all-in-one is only a client. The FRAMEFORGE folder and
  the Claude Code session should move to the 5080 PC so installs and GPU tests can run directly.
- Fully local, no cloud inference. Edge TTS from the earlier `ollamatalks` experiment is excluded.
- Default licenses Apache 2.0 / MIT; LTX-2 and Flux Kontext are opt-in with license caveats.

## Open questions

1. Probe output from the 5080 PC (`scripts/probe_env.ps1`): OS, RAM, free disk, existing ComfyUI/Ollama. **Pending.**
2. ~~Deployment layout~~ — decided: single machine (5080 PC).
3. Commercial use intended? (Decides whether LTX-2 / Flux Kontext are allowed.) **Pending.**
4. Visual style target: stylized/cartoon vs photoreal animals. (Decides lip-sync model test order.) **Pending.**

## Phase 1 summary

What works and was tested:
- Backend: `GET /api/health` (version, uptime, DB check, NVIDIA GPU detection via nvidia-smi),
  `GET /api/comfy/status` (real HTTP call to ComfyUI `/system_stats` + `/queue`, truthful error
  on failure), full project CRUD, job listing. Settings via `FRAMEFORGE_*` env / `.env`.
- Frontend: dark dashboard polling both status endpoints every 5 s, project creation form with
  duration / aspect / style / quality, project list with delete. Type-check and lint clean.
- Dev setup: `scripts/dev-backend.ps1`, `scripts/dev-frontend.ps1`, `.claude/launch.json`, README.
- Tests: `backend/tests/test_api.py` (5 tests) incl. a regression test for a real bug found during
  bring-up (comma-separated CORS list crashed settings loading).

Outstanding:
- Dev machine runs Python 3.14; the 5080 PC should use 3.12 for ML-package compatibility
  (the backend itself is version-agnostic).
- No background job runner or WebSocket yet (Phase 2).
- Verified only with ComfyUI absent; the "connected" branch of the ComfyUI card is untested
  until ComfyUI runs.

## Phase 2 summary

Built on the dev machine without a GPU, so every ComfyUI interaction was exercised against
`backend/tests/fake_comfy.py`, a stand-in that reproduces the real API's request/response shapes
(`POST /prompt`, `GET /history/{id}`, `/view`, `/interrupt`, `/queue`, `/free`, `WS /ws`).
The application code only ever talks to whatever is at `FRAMEFORGE_COMFYUI_URL`; nothing in the
runtime fabricates progress.

What works and was tested:
- `services/comfy_client.py`: submit graph, websocket progress stream, history, output download,
  interrupt, queue delete, free. Typed errors distinguish "unreachable" (retryable) from
  "ComfyUI rejected/failed" (not retried automatically).
- `services/workflows.py` + `workflows/*.v1.json`: versioned templates with parameter manifests;
  `build()` applies params with type/range checks and random seeds. Templates:
  `image_basic_txt2img` (ComfyUI default checkpoint graph) and `video_wan22_5b_t2v`
  (Wan 2.2 5B native template).
- `services/runner.py`: one job at a time, FIFO, persisted in SQLite. Re-queues jobs left
  `running` after a restart; retries unreachable ComfyUI up to `FRAMEFORGE_JOB_MAX_ATTEMPTS`
  with backoff; cancel = `/interrupt` + queue delete; retry re-queues failed/cancelled jobs.
  Keeps project status in sync (`generating` while jobs are active).
- API: `GET /api/workflows`, `POST /api/projects/{id}/jobs`, `POST /api/jobs/{id}/cancel`,
  `POST /api/jobs/{id}/retry`, `GET /api/jobs/{id}/outputs/{file}`, `DELETE /api/jobs/{id}`,
  `POST /api/comfy/free`, `WS /api/ws`.
- Frontend: template picker with manifest-driven parameter form, live jobs panel (WebSocket with
  polling fallback), cancel / retry / delete, image/video/audio previews, download links.
- Tests: 26 pass (`backend/tests/`), including success, execution error, retry, cancel of running
  and queued jobs, WebSocket event ordering, unreachable-ComfyUI retry exhaustion, output deletion.

Outstanding before Phase 2 can be called done:
- Run both templates on the RTX 5080 PC against real ComfyUI and flip `validated` to true.
  Node names/fields in `video_wan22_5b_t2v.v1.json` were written from the ComfyUI template and
  need confirmation against the installed ComfyUI version.
- Output `kind` detection relies on history key/extension heuristics; confirm with real SaveVideo output.
- No per-job VRAM/throughput metrics yet (Phase 6/8).

Next: close Phase 0 on the 5080 PC (probe, install plan, tests T1–T7), validate Phase 2 there,
then Phase 3 (local LLM script and production planning).

## Files

- `README.md` — setup, run, API table, troubleshooting.
- `docs/PHASE0_ENVIRONMENT_REPORT.md` — findings, model candidates, VRAM strategy, test plan.
- `docs/PHASE0_INSTALL_PLAN.md` — ordered installation sequence for the 5080 PC, gated on probe results.
- `scripts/probe_env.ps1` — read-only probe to run on the RTX 5080 machine.
