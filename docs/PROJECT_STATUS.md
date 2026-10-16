# FRAMEFORGE — Project Status

Last updated: 2026-10-16 (CPU-mode pipeline built end to end)

## Current phase

The owner decided to develop on the GPU-less HP all-in-one and demo there, so a **CPU mode** was
built that runs every stage with real local AI where feasible (Ollama script, Kokoro voices,
ComfyUI-CPU reference images) and a procedural animator where video diffusion and audio-driven
lip-sync models cannot run (Intel iGPU, 15 GB RAM). The GPU path for the RTX 5080 PC keeps the same
plan/timeline/shot data and is designed but not built (Phase 0 still open there: probe, licensing
and style answers pending).

| Stage | CPU-mode engine (this machine) | Status |
|---|---|---|
| Script | Ollama `qwen3:4b`, two-pass + length top-up | Working, tested live (48 s for a 60 s script) |
| Voices | Kokoro-82M in `backend/.venv-tts` | Working, tested live (~1x real-time, word timestamps) |
| References | ComfyUI 0.41 `--cpu`, SD 1.5 + LCM LoRA | Working, tested live (~70–100 s per image) |
| Animate | `media_worker/animate_worker.py` | Working in tests; first full live render in progress |
| Assemble | FFmpeg 9 + procedural music + SRT | Working in tests |
| One-click pipeline | `pipeline.full` job with checkpoint reuse | Working in tests; live run in progress |

## Summary

| Phase | Status | Notes |
|---|---|---|
| 0 Environment & feasibility | In progress | Session machine probed: HP all-in-one, Intel iGPU, 15 GB RAM, **no NVIDIA GPU**. RTX 5080 machine not yet probed. Candidate model stack drafted. See [PHASE0_ENVIRONMENT_REPORT.md](PHASE0_ENVIRONMENT_REPORT.md). |
| 1 Project foundation | **Done (on the AIO dev machine), 2026-10-16** | FastAPI backend with `/api/health`, `/api/comfy/status`, project + job persistence (SQLite); Next.js 16 + Tailwind 4 dark dashboard; dev scripts; git repo. Tested: 5 backend tests pass, dashboard verified in browser, project created end to end. ComfyUI check truthfully reports "unreachable" here. Remaining: re-run on the 5080 PC with ComfyUI up. |
| 2 UI + ComfyUI integration | **Built and tested against a stand-in ComfyUI, 2026-10-16.** Real-engine validation pending. | Full ComfyUI API client (HTTP + WebSocket), versioned workflow templates, background job runner with cancel/retry/resume, jobs API, WebSocket events, generation UI with live progress and previews. 26 backend tests pass; UI verified in the browser against the stand-in. **Not yet run against a real ComfyUI**; the two templates are marked `validated: false`. |
| 3 Script & production planning | **Done (CPU and GPU share it)** | `ProductionPlan` schema, Ollama JSON-schema planner, outline + per-scene passes, length top-up, editable in advanced mode. Tested with stand-in and live `qwen3:4b`. |
| 4 Dialogue & voices | **Done** | Kokoro worker (own venv), per-line WAV + word timestamps, timeline with pauses/scene gaps, mixed dialogue track. Tested live. |
| 5 Character animation & lip sync | **CPU mode done; GPU mode not built** | CPU: rembg cutouts, OpenCV cat/human face boxes, audio-envelope jaw/mouth, blinks, head motion, listener reactions. GPU (Wan 2.2 S2V / InfiniteTalk) pending the 5080 PC. |
| 6 Automated scene generation | **CPU mode done; GPU mode not built** | Shot planner (establishing, shot/reverse-shot, reaction cut-ins, two-shots) from the timeline; references via ComfyUI; checkpointed. GPU shot rendering pending. |
| 7 Editing & final render | **Done** | FFmpeg assembly: subtitles (SRT burn-in), procedural music mix, libx264/aac, ffprobe QC (duration/streams). In-app preview + download. |
| 8 Full 10-minute production | Partly | Pipeline is checkpointed and resumable; planner scales scenes by duration. Not yet exercised beyond ~1 minute; no ETA/VRAM telemetry yet. |
| 9 Reliability & usability | Partly | Project workspace UI, stage controls, plan editor, truthful errors, retry/cancel. Missing: project history/reusable characters, per-shot regeneration, docs for GPU setup validation. |

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

## Session machine 2026-10-16 (later): MSI laptop with RTX 4090 Laptop GPU

- Hardware: NVIDIA GeForce RTX 4090 Laptop GPU (16 GB VRAM, driver 595.79), Intel UHD iGPU, 64 GB RAM.
  Same VRAM budget as the RTX 5080 target, so the GPU path and Phase 0 tests can be exercised here.
- Present: Python 3.12.3, FFmpeg 8.0.1 (winget Gyan.FFmpeg). Installed this session: Node.js 24.20 LTS.
- Missing: Git, Ollama, ComfyUI, `backend/.venv-tts`. The folder came from a ZIP, not a clone, so there
  is no git history and no earlier project renders (`backend/data` is gitignored).
- Verified: backend and frontend start; dashboard loads with no console errors; health card detects the
  4090. ComfyUI and Ollama cards report unreachable, as expected.

## Handoff — where to pick up on the next machine

Clone the repo, follow README "Continue on another computer", start the three servers, then:

1. **Review the first full live render.** On the dev machine the one-click pipeline completed
   end to end on 2026-10-16: script (qwen3:4b) → voices (Kokoro) → references (ComfyUI CPU) →
   animate (1266 frames, 17 shots, 960x540) → assemble. `render/final.mp4` is 52.75 s with
   8 subtitle cues and music; all QC checks passed. The video was only spot-checked on one frame,
   not watched. Open the project in the dashboard and watch it. Judge: mouth movement follows
   speech, cuts between speakers, subtitles readable, music under dialogue. (Animate failed once
   before that because the backend process had a stale PATH without FFmpeg; fixed via
   `Settings.resolved_ffmpeg`.)
2. **Known rough edges to tune after watching:** mouth/jaw placement when the face box is wrong
   (the animator logs `face box` per character on stderr), character scale/position in two-shots,
   listener reaction timing, music volume (`plan.music.volume_db`).
3. **Then:** per-shot regeneration UI, a `stage` label on jobs (needs a DB column + migration),
   project history/reusable characters (Phase 9), and the RTX 5080 GPU path (Phase 0 tests
   T1–T7 from `PHASE0_ENVIRONMENT_REPORT.md`, then a `video_*`/S2V animate engine).

## CPU-mode build notes (2026-10-16)

- Installed on the dev machine: Python 3.12, Ollama 0.40 + `qwen3:4b`, FFmpeg 9 full, ComfyUI 0.41
  (`C:\AI\ComfyUI`, torch 2.14 CPU, SD 1.5 fp16 + LCM LoRA), worker venv `backend/.venv-tts`
  (torch CPU, kokoro, Pillow, OpenCV, rembg). Reproducible via `scripts/install-workers.ps1` and
  `scripts/install-comfyui-cpu.ps1`.
- Real bug found live: on Windows, uvicorn's selector event loop cannot spawn asyncio subprocesses
  (bare `NotImplementedError`, which also produced empty job errors). Workers now run through
  `app/services/subproc.py` in threads; the runner never stores an empty error.
- Timeline layout gives every scene an establishing gap (1.5 s lead-in, 1.0 s between scenes) so
  the shot planner always has a wide shot.
- Tests: 38 backend tests; render tests use the real worker venv and FFmpeg (skipped if absent).

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
