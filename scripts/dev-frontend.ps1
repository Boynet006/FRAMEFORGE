# Start the FRAMEFORGE Next.js frontend in dev mode.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\dev-frontend.ps1
# Success: "Ready" in the console and http://localhost:3000 shows the dashboard.

$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root 'frontend'

# winget installs Node for the machine; refresh PATH in case this shell predates the install.
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')

Push-Location $frontend
try {
  if (-not (Test-Path 'node_modules')) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Yellow
    npm install
  }
  if (-not (Test-Path '.env.local')) {
    Copy-Item '.env.local.example' '.env.local'
    Write-Host "Created frontend\.env.local from .env.local.example" -ForegroundColor Yellow
  }
  npm run dev
} finally {
  Pop-Location
}
