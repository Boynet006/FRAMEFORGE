# Start the FRAMEFORGE FastAPI backend with auto-reload.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1
# Success: log line "FRAMEFORGE backend 0.1.0 started" and http://127.0.0.1:8000/api/health returns JSON.

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
  Write-Host "No venv found. Creating backend\.venv and installing requirements..." -ForegroundColor Yellow
  Push-Location $backend
  py -3 -m venv .venv
  & $python -m pip install --upgrade pip
  & $python -m pip install -r requirements.txt
  Pop-Location
}

if (-not (Test-Path (Join-Path $backend '.env'))) {
  Copy-Item (Join-Path $backend '.env.example') (Join-Path $backend '.env')
  Write-Host "Created backend\.env from .env.example" -ForegroundColor Yellow
}

Push-Location $backend
try {
  & $python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
} finally {
  Pop-Location
}
