# FRAMEFORGE — context for Claude Code (read this first on any machine)

FRAMEFORGE is a fully local AI video studio: one prompt → script → voices → character/environment
images → animated shots → final MP4 with subtitles and music. Target hardware is an RTX 5080
(16 GB VRAM); it also runs in a **CPU mode** on machines without an NVIDIA GPU.

## Where the truth lives

- `docs/PROJECT_STATUS.md` — phase-by-phase status, decisions, what is tested, what is next. **Update it
  at the end of every working session and push.**
- `docs/PHASE0_ENVIRONMENT_REPORT.md` — model/VRAM strategy for the 5080 PC.
- `docs/PHASE0_INSTALL_PLAN.md` — GPU-machine install sequence.
- `README.md` — how to install and run on a fresh machine.
- Git: `https://github.com/Boynet006/FRAMEFORGE` (private). Commit and push after every completed step.

## Working rules (from the project owner)

1. Work phase by phase; never report a feature as working until it has been tested.
2. Real engine responses only (ComfyUI, Ollama, FFmpeg); the stand-in servers in `backend/tests/` are for tests.
3. No cloud AI APIs. No machine-specific paths or secrets in code (use `backend/.env`, `frontend/.env.local`).
4. Pin dependencies (`backend/requirements.lock.txt`, `frontend/package-lock.json`).
5. Keep frontend, orchestration backend and generation workflows modular.
6. Push to GitHub after every step so work can continue on another computer.

## Architecture in one minute

```
frontend/   Next.js 16 + Tailwind 4 dashboard (port 3000). Polls /api/health, /api/comfy/status, /api/llm/status;
            live job events over WS /api/ws; project workspace with stage buttons and plan editor.
backend/    FastAPI (port 8000). SQLite via SQLAlchemy (backend/data/frameforge.db).
  app/services/runner.py        single-worker job queue; job kinds: comfy.workflow, plan.generate, tts.generate,
                                refs.generate, animate.render, assemble.render, pipeline.full
  app/services/engines/         one module per stage; pipeline_engine chains them with checkpoint reuse
  app/services/comfy_client.py  ComfyUI HTTP + WebSocket client
  app/services/llm_client.py    Ollama /api/chat with JSON-schema output
  app/services/subproc.py       thread-based worker runner (Windows selector loop can't spawn asyncio subprocesses)
  app/plan.py                   ProductionPlan schema (characters, voices, environments, scenes, lines)
  workflows/*.v<N>.json         versioned ComfyUI API-format graphs with parameter manifests
  tts_worker/, media_worker/    scripts run in backend/.venv-tts (Python 3.12): Kokoro TTS, animator, music
  data/projects/<id>/           plan.json, audio/, refs/, render/ (gitignored)
```

Stage outputs per project: `audio/dialogue.json` (timed lines + word timestamps), `refs/*.png`,
`render/shots.json`, `render/video_silent.mp4`, `render/subtitles.srt`, `render/final.mp4`.

## Run it

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1     # FastAPI on :8000
powershell -ExecutionPolicy Bypass -File scripts\dev-frontend.ps1    # Next.js on :3000
powershell -ExecutionPolicy Bypass -File scripts\run-comfyui-cpu.ps1 # ComfyUI on :8188 (CPU mode)
```

Backend tests (40): `cd backend; .\.venv\Scripts\python.exe -m pytest -q`. The render tests need
`backend/.venv-tts` (create with `scripts\install-workers.ps1`) and FFmpeg on PATH; they skip otherwise.

## Engines on a CPU-only machine (what the dev all-in-one uses)

- Ollama `qwen3:4b` for scripts (`FRAMEFORGE_OLLAMA_MODEL`); ~1 min per 60 s script.
- Kokoro-82M for voices (CPU, about real-time).
- ComfyUI `--cpu` with SD 1.5 + LCM LoRA (`image_sd15_lcm` template) for reference images, ~70–100 s each.
- `media_worker/animate_worker.py` procedural animator (rembg cutouts, OpenCV face boxes, audio-driven
  mouth, blinks, head motion, shot/reverse-shot). This replaces video-diffusion + lip-sync models, which
  cannot run on an iGPU with 15 GB RAM.
- FFmpeg 9 for assembly.

On the RTX 5080 PC the same pipeline is meant to swap the animate stage for ComfyUI video models
(Wan 2.2 S2V / 14B) — see the environment report. That path is designed but not built yet.

## Conventions

- Backend code is Python 3.12+; the dev machine's backend venv happens to be 3.14, workers are 3.12.
- Editing files under `backend/app` or `backend/workflows` restarts the dev backend (uvicorn --reload),
  which kills running jobs (they re-queue). Don't edit those while a long render is running.
- Job errors must never be empty strings; the runner substitutes the exception type.
- New ComfyUI templates start with `"validated": false` until run on a real ComfyUI.
