# Create backend\.venv-chatterbox: the expressive voice engine (Resemble AI Chatterbox, MIT).
#   powershell -ExecutionPolicy Bypass -File scripts\install-chatterbox.ps1 [-Cuda cu124]
# Chatterbox 0.1.7 pins torch==2.6.0 on Python 3.12, which clashes with the Kokoro/animator venv, so it
# lives in its own environment. cu124 wheels run on RTX 20xx-40xx. RTX 50xx (Blackwell) is not supported
# by torch 2.6: there, use Python 3.14 (Chatterbox then allows torch>=2.9 with cu130 wheels).
# Then set FRAMEFORGE_TTS_ENGINE=chatterbox in backend\.env.
# Success: prints the torch/CUDA line and "Chatterbox environment ready".
param(
  [string]$Cuda = "cu124"
)
$ErrorActionPreference = 'Stop'
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
Push-Location $backend
try {
  if (-not (Test-Path ".\.venv-chatterbox\Scripts\python.exe")) { py -3.12 -m venv .venv-chatterbox }
  $py = ".\.venv-chatterbox\Scripts\python.exe"
  & $py -m pip install --upgrade pip
  # CUDA build first, so chatterbox's torch==2.6.0 pin is already satisfied by the +cuXXX wheel
  & $py -m pip install "torch==2.6.0" "torchaudio==2.6.0" --index-url "https://download.pytorch.org/whl/$Cuda"
  if ($LASTEXITCODE -ne 0) { throw "torch install failed" }
  & $py -m pip install "chatterbox-tts==0.1.7" soundfile
  if ($LASTEXITCODE -ne 0) { throw "chatterbox install failed" }
  & $py -c "import torch, chatterbox; ok = torch.cuda.is_available(); print('torch', torch.__version__, 'cuda', ok, torch.cuda.get_device_name(0) if ok else '')"
  Write-Host "Chatterbox environment ready at backend\.venv-chatterbox"
} finally {
  Pop-Location
}
