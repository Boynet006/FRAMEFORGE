# Install ComfyUI for CPU-only use (development machines without an NVIDIA GPU).
#   powershell -ExecutionPolicy Bypass -File scripts\install-comfyui-cpu.ps1 [-Dir C:\AI\ComfyUI]
# Installs: ComfyUI (git), a Python 3.12 venv with CPU PyTorch, Stable Diffusion 1.5 (fp16) and the
# LCM LoRA so a 512x512 image takes seconds-to-a-minute on a modern CPU instead of many minutes.
# Licenses: ComfyUI GPL-3.0; SD 1.5 CreativeML OpenRAIL-M; LCM-LoRA OpenRAIL-M. Both allow commercial use
# of outputs under the OpenRAIL use restrictions.
# Success: the last lines print the torch version and "ComfyUI CPU install complete".
param(
  [string]$Dir = "C:\AI\ComfyUI"
)
$ErrorActionPreference = 'Stop'
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')

if (-not (Test-Path $Dir)) {
  New-Item -ItemType Directory -Force (Split-Path -Parent $Dir) | Out-Null
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git $Dir
}
Push-Location $Dir
try {
  if (-not (Test-Path ".\venv\Scripts\python.exe")) { py -3.12 -m venv venv }
  $py = ".\venv\Scripts\python.exe"
  & $py -m pip install --upgrade pip
  & $py -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
  & $py -m pip install -r requirements.txt
  & $py -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

  $ckpt = "models\checkpoints\v1-5-pruned-emaonly-fp16.safetensors"
  if (-not (Test-Path $ckpt)) {
    Write-Host "Downloading Stable Diffusion 1.5 fp16 (~2.1 GB)..."
    curl.exe -L --retry 5 -o $ckpt "https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly-fp16.safetensors"
  }
  $lora = "models\loras\lcm-lora-sdv1-5.safetensors"
  if (-not (Test-Path $lora)) {
    Write-Host "Downloading LCM LoRA for SD 1.5 (~135 MB)..."
    curl.exe -L --retry 5 -o $lora "https://huggingface.co/latent-consistency/lcm-lora-sdv1-5/resolve/main/pytorch_lora_weights.safetensors"
  }
  Get-Item $ckpt, $lora | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB)}} | Format-Table -AutoSize
  Write-Host "ComfyUI CPU install complete. Start it with: scripts\run-comfyui-cpu.ps1"
} finally {
  Pop-Location
}
