# Start ComfyUI on the NVIDIA GPU on http://127.0.0.1:8188 (see install-comfyui-gpu.ps1).
#   powershell -ExecutionPolicy Bypass -File scripts\run-comfyui-gpu.ps1 [-Dir C:\AI\ComfyUI]
param(
  [string]$Dir = "C:\AI\ComfyUI",
  [int]$Port = 8188
)
Push-Location $Dir
try {
  & .\venv\Scripts\python.exe main.py --listen 127.0.0.1 --port $Port --disable-auto-launch
} finally {
  Pop-Location
}
