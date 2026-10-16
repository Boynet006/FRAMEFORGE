# FRAMEFORGE — Local AI Video Studio

One prompt in, a complete MP4 out, generated entirely on local hardware
(target: NVIDIA RTX 5080, 16 GB VRAM). See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)
for the current phase and [docs/PHASE0_ENVIRONMENT_REPORT.md](docs/PHASE0_ENVIRONMENT_REPORT.md)
for the model and VRAM strategy.

## Layout

```
backend/    FastAPI orchestration API (Python 3.12+), SQLite project/job store
frontend/   Next.js + TypeScript + Tailwind dashboard
scripts/    Windows PowerShell helpers (environment probe, dev servers)
docs/       Status, environment report, install plan
```

## Prerequisites (Windows)

- Python 3.12 or newer (`py -3 --version`)
- Node.js LTS 20+ and npm (`node --version`)
- Git
- Optional for Phase 1, required later: ComfyUI running on `http://127.0.0.1:8188`

Install the first three with winget:

```powershell
winget install --id Python.Python.3.12 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Git.Git -e
```

## Run the development servers

Open two PowerShell windows in the repository root.

Backend (creates the venv, installs requirements and `.env` on first run):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1
```

Success: a log line `FRAMEFORGE backend 0.1.0 started`, and
`http://127.0.0.1:8000/api/health` returns JSON with `"status": "ok"`.
Interactive API docs: `http://127.0.0.1:8000/docs`.

Frontend (installs node_modules and `.env.local` on first run):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev-frontend.ps1
```

Success: `Ready` in the console; `http://localhost:3000` shows the dashboard with the backend
card green and the ComfyUI card reporting its real reachability.

## Configuration

Backend settings live in `backend/.env` (copy from `backend/.env.example`). All variables are
prefixed `FRAMEFORGE_`. The important one for Phase 1 is `FRAMEFORGE_COMFYUI_URL`.

Frontend settings live in `frontend/.env.local` (copy from `frontend/.env.local.example`):
`NEXT_PUBLIC_API_URL` must point at the backend.

## Source control

The repository lives at `https://github.com/Boynet006/FRAMEFORGE`. Day-to-day workflow from the
repository root:

```powershell
git status
```

```powershell
git add -A; git commit -m "describe the change"
```

```powershell
git push
```

Large generated files (models, renders, audio) are ignored by `.gitignore` on purpose; never
force-add them. Secrets stay in `backend/.env` and `frontend/.env.local`, which are also ignored.

## Tests

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Backend version, uptime, database check, detected NVIDIA GPUs |
| GET | `/api/comfy/status` | Live ComfyUI connectivity: version, devices, queue, or the error |
| POST | `/api/comfy/free` | Ask ComfyUI to unload models and free VRAM |
| GET | `/api/workflows` | Versioned workflow templates with parameter manifests |
| GET/POST | `/api/projects` | List / create projects |
| GET/PATCH/DELETE | `/api/projects/{id}` | Read (with jobs) / update / delete a project |
| POST | `/api/projects/{id}/jobs` | Queue a workflow run `{workflow, version?, params}` |
| GET | `/api/jobs` | List jobs, filter by `project_id` and `status` |
| GET | `/api/jobs/{id}` | Read one job |
| POST | `/api/jobs/{id}/cancel` | Cancel a queued job or interrupt a running one |
| POST | `/api/jobs/{id}/retry` | Re-queue a failed or cancelled job |
| GET | `/api/jobs/{id}/outputs/{file}` | Download a generated output |
| DELETE | `/api/jobs/{id}` | Delete a finished job and its outputs |
| WS | `/api/ws` | Live job and project events |

## Workflow templates

Templates live in `backend/workflows/<name>.v<N>.json`: an API-format ComfyUI graph plus an
`inputs` manifest mapping parameter names to node fields. Add a new version as a new file; the
API serves the latest unless a version is requested. `validated: false` marks templates that
have not yet been run on real hardware. `POST /api/workflows/reload` re-reads the folder.

To try the UI without a GPU, run the stand-in ComfyUI from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m tests.fake_comfy --port 8188
```

It mimics the real API shapes and produces placeholder files. It is for development only.

## Troubleshooting

- **`py` not found**: install Python from python.org or winget; make sure "py launcher" is selected.
- **`node` not found after installing**: open a new terminal so PATH refreshes.
- **Backend starts but the frontend shows "backend unreachable"**: check `NEXT_PUBLIC_API_URL` in
  `frontend/.env.local` matches the backend host/port, and that `FRAMEFORGE_CORS_ORIGINS` in
  `backend/.env` includes `http://localhost:3000`.
- **ComfyUI card red**: expected until ComfyUI is installed and running on the configured URL.
  Start ComfyUI, then the card refreshes on its own.
- **Port already in use**: change `FRAMEFORGE_PORT` / `--port` and update `NEXT_PUBLIC_API_URL`.
