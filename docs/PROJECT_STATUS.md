# FRAMEFORGE — Project Status

Last updated: 2026-10-16 (RTX 4090 laptop: SDXL references, Simple/Advanced UI)

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
- Installed this session: Node.js 24.20 LTS, Git 2.55, Ollama 0.40.5 (`qwen3:14b` + `qwen3:8b`),
  ComfyUI 0.41 at `C:\AI\ComfyUI` with torch 2.14.1+cu130 (`scripts/install-comfyui-gpu.ps1`; the cu128
  index stops at torch 2.11), worker venv `backend/.venv-tts` (CPU torch). Python 3.12.3 and FFmpeg 8.0.1
  were already present. The folder came from a ZIP; it was linked to `origin/main` (identical tree).
- `backend/.env` here: `FRAMEFORGE_OLLAMA_MODEL=qwen3:14b`. Everything else matches the CPU defaults
  (`render_mode=cpu`: the procedural animator still renders the shots).
- Tests: 38/38 pass, none skipped. Fixed a test leak: `conftest.py` now pins the Ollama model, because a
  GPU machine's `.env` (`qwen3:14b`) made the stand-in planner test fail.
- **First live run on this machine:** one-click pipeline, 60 s "two cats" prompt, succeeded in 6 min 45 s
  end to end. Script `qwen3:14b` (19 lines, 143 words), Kokoro voices (69.4 s), 3 reference images on
  the 4090 via `image_sd15_lcm` (11 s first image incl. model load, then ~1 s each vs 70–100 s on CPU),
  22 shots / 1665 frames at 960x540, final.mp4 with 19 subtitle cues; all QC checks passed.
  Spot-checked 4 frames: subtitles readable, speaker's mouth opens, wide/close-up cuts work.
  Seen problem: the second "cat" came out puppy-like (SD 1.5 prompt adherence). Audio not reviewed.
- **SDXL references (validated):** new `image_sdxl` template (SDXL base 1.0, 28 steps, ~9 s per image at
  896x1152 / 1344x768 on the 4090). Templates can now declare native sizes in `"hints"`; the refs stage uses
  them (SD 1.5 sizes stay the fallback). `POST /projects/{id}/refs?workflow=...` overrides the template per
  run. This machine's `.env` uses `FRAMEFORGE_IMAGE_WORKFLOW=image_sdxl`.
- **Puppy bug root cause:** image prompts never named the species ("Waffles, calico…") and included the
  character's name, so the image model guessed a dog. Plan characters now have a `species` field (LLM
  instructed: basic kind of being, never a coat/breed); `character_image_prompt()` leads with and repeats
  it and drops the name. Live check with qwen3:14b: "Waffles the calico" → `species='cat'`.
- **Second live run (SDXL, via the new Simple UI):** "Café cats" example, 60 s, 3D animated — succeeded
  in ~4 min, both characters clearly cats, QC passed (57.7 s, 12 cues).
- **Simple / Advanced UI toggle** (header, remembered in localStorage, default Simple). Simple: one-line
  engine readiness with fix-it hints, "Make a video" form (prompt tips + examples, Length/Look/Quality
  chips; creates the project and starts the pipeline in one click), "Your videos" with plain statuses,
  friendly step progress, Try again on failure (resumes from checkpoints), big player + Download, script
  collapsed and read-only, "Make a new version" (force re-run, confirmed). Advanced: the previous full
  UI with editing always on. The open project is also remembered across reloads.
- **Fixed:** the final-video player and download links used backend-relative URLs and 404'd against the
  frontend origin (the player never played). URLs are now made absolute in `api.getRender`, and
  `files/...?download=true` sends a Content-Disposition attachment named after the project.
- Aspect ratio is stored but the CPU animator always renders 16:9; Simple hides it, Advanced labels it.
- Tests: 40/40. `conftest.py` also pins `IMAGE_WORKFLOW` and `RENDER_MODE` against `.env` leaks.
- Next on this machine: the GPU animate path (Wan 2.2 S2V, Phase 0 tests T1–T7), which this laptop can
  run as a 5080 stand-in; per-shot regeneration; character/environment consistency across shots.

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
