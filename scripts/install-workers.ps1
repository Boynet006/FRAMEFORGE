# Create backend\.venv-tts: the Python 3.12 environment used by the TTS, animation and music workers.
#   powershell -ExecutionPolicy Bypass -File scripts\install-workers.ps1
# Installs CPU PyTorch, Kokoro (TTS), Pillow/OpenCV/numpy (animator) and rembg (character cutouts).
# Success: prints the versions of kokoro, torch, cv2 and rembg at the end.
$ErrorActionPreference = 'Stop'
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
Push-Location $backend
try {
  if (-not (Test-Path ".\.venv-tts\Scripts\python.exe")) { py -3.12 -m venv .venv-tts }
  $py = ".\.venv-tts\Scripts\python.exe"
  & $py -m pip install --upgrade pip
  & $py -m pip install torch --index-url https://download.pytorch.org/whl/cpu
  # OpenCV 5 dropped the Haar cascade face detector the animator uses (cv2.CascadeClassifier); keep 4.x.
  & $py -m pip install "kokoro>=0.9.4" soundfile pillow "opencv-python-headless>=4.10,<5" numpy "rembg[cpu]"
  & $py -c "import kokoro, torch, cv2, rembg, PIL; assert hasattr(cv2, 'CascadeClassifier'), 'OpenCV without CascadeClassifier'; print('kokoro', kokoro.__version__, 'torch', torch.__version__, 'cv2', cv2.__version__, 'pillow', PIL.__version__, 'rembg ok')"
  Write-Host "Worker environment ready at backend\.venv-tts"
} finally {
  Pop-Location
}
