# Install ComfyUI with CUDA PyTorch for NVIDIA GPUs (RTX 4090 laptop, RTX 5080).
#   powershell -ExecutionPolicy Bypass -File scripts\install-comfyui-gpu.ps1 [-Dir C:\AI\ComfyUI] [-Cuda cu130]
# Installs: ComfyUI (git), a Python 3.12 venv with CUDA PyTorch, Stable Diffusion 1.5 (fp16) + LCM LoRA
# (image_sd15_lcm, shared with the CPU install) and SDXL base 1.0 (image_sdxl, the GPU default).
# cu130 wheels cover Ada (RTX 40xx) and Blackwell (RTX 50xx) and need an NVIDIA driver with CUDA 13
# support (580+). The cu128 index stopped at torch 2.11; use -Cuda cu128 only with an older driver.
# Licenses: ComfyUI GPL-3.0; SD 1.5 CreativeML OpenRAIL-M; LCM-LoRA OpenRAIL-M.
# Success: prints "cuda True" with the GPU name and "ComfyUI GPU install complete".
param(
  [string]$Dir = "C:\AI\ComfyUI",
  [string]$Cuda = "cu130"
)
$ErrorActionPreference = 'Stop'
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')

if (-not (Test-Path $Dir)) {
  New-Item -ItemType Directory -Force (Split-Path -Parent $Dir) | Out-Null
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git $Dir
  if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
}
Push-Location $Dir
try {
  if (-not (Test-Path ".\venv\Scripts\python.exe")) { py -3.12 -m venv venv }
  $py = ".\venv\Scripts\python.exe"
  & $py -m pip install --upgrade pip
  & $py -m pip install torch torchvision torchaudio --index-url "https://download.pytorch.org/whl/$Cuda"
  if ($LASTEXITCODE -ne 0) { throw "torch install failed" }
  & $py -m pip install -r requirements.txt
  if ($LASTEXITCODE -ne 0) { throw "ComfyUI requirements install failed" }
  & $py -c "import torch; ok = torch.cuda.is_available(); print('torch', torch.__version__, 'cuda', ok, torch.cuda.get_device_name(0) if ok else '')"

  New-Item -ItemType Directory -Force "models\checkpoints", "models\loras" | Out-Null
  $ckpt = "models\checkpoints\v1-5-pruned-emaonly-fp16.safetensors"
  if (-not (Test-Path $ckpt)) {
    Write-Host "Downloading Stable Diffusion 1.5 fp16 (~2.1 GB)..."
    curl.exe -L --fail --retry 5 -o $ckpt "https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly-fp16.safetensors"
  }
  $lora = "models\loras\lcm-lora-sdv1-5.safetensors"
  if (-not (Test-Path $lora)) {
    Write-Host "Downloading LCM LoRA for SD 1.5 (~135 MB)..."
    curl.exe -L --fail --retry 5 -o $lora "https://huggingface.co/latent-consistency/lcm-lora-sdv1-5/resolve/main/pytorch_lora_weights.safetensors"
  }
  # SDXL base for the image_sdxl template (set FRAMEFORGE_IMAGE_WORKFLOW=image_sdxl in backend\.env).
  $sdxl = "models\checkpoints\sd_xl_base_1.0.safetensors"
  if (-not (Test-Path $sdxl)) {
    Write-Host "Downloading Stable Diffusion XL base 1.0 (~6.9 GB)..."
    curl.exe -L --fail --retry 5 -o $sdxl "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"
  }
  Get-Item $ckpt, $lora, $sdxl | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB)}} | Format-Table -AutoSize
  Write-Host "ComfyUI GPU install complete. Start it with: scripts\run-comfyui-gpu.ps1"
} finally {
  Pop-Location
}
