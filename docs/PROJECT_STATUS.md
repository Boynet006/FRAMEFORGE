# FRAMEFORGE — Project Status

Last updated: 2026-10-16

## Current phase

**Phase 0 — Environment and feasibility** is still open (waiting for the 5080 PC probe, the
commercial-use answer and the visual-style answer). **Phase 1 — Project foundation** was built
in parallel on the dev machine because it needs no GPU; see the table below.

## Summary

| Phase | Status | Notes |
|---|---|---|
| 0 Environment & feasibility | In progress | Session machine probed: HP all-in-one, Intel iGPU, 15 GB RAM, **no NVIDIA GPU**. RTX 5080 machine not yet probed. Candidate model stack drafted. See [PHASE0_ENVIRONMENT_REPORT.md](PHASE0_ENVIRONMENT_REPORT.md). |
| 1 Project foundation | **Done (on the AIO dev machine), 2026-10-16** | FastAPI backend with `/api/health`, `/api/comfy/status`, project + job persistence (SQLite); Next.js 16 + Tailwind 4 dark dashboard; dev scripts; git repo. Tested: 5 backend tests pass, dashboard verified in browser, project created end to end. ComfyUI check truthfully reports "unreachable" here. Remaining: re-run on the 5080 PC with ComfyUI up. |
| 2 UI + ComfyUI integration | Not started | |
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

Next: Phase 2 — ComfyUI workflow manager, real image/short-video job submission, live progress,
cancel/retry, output previews. Requires the 5080 PC with ComfyUI installed (Phase 0 install plan).

## Files

- `README.md` — setup, run, API table, troubleshooting.
- `docs/PHASE0_ENVIRONMENT_REPORT.md` — findings, model candidates, VRAM strategy, test plan.
- `docs/PHASE0_INSTALL_PLAN.md` — ordered installation sequence for the 5080 PC, gated on probe results.
- `scripts/probe_env.ps1` — read-only probe to run on the RTX 5080 machine.
