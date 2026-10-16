# FRAMEFORGE Phase 0 - environment probe
# Run this in PowerShell ON THE MACHINE THAT HAS THE RTX 5080, from any folder:
#   powershell -ExecutionPolicy Bypass -File .\probe_env.ps1
# It only reads system information. It installs nothing and changes nothing.
# Paste the whole output back into the FRAMEFORGE session.

$ErrorActionPreference = 'SilentlyContinue'

function Section($t) { ""; "=== $t ==="; }

Section "OS / CPU / RAM"
$os = Get-CimInstance Win32_OperatingSystem
"OS: $($os.Caption) $($os.Version) build $($os.BuildNumber)"
$cs = Get-CimInstance Win32_ComputerSystem
"Machine: $($cs.Manufacturer) $($cs.Model)"
$cpu = Get-CimInstance Win32_Processor
"CPU: $($cpu.Name) cores=$($cpu.NumberOfCores) threads=$($cpu.NumberOfLogicalProcessors)"
"RAM total GB: " + [math]::Round($os.TotalVisibleMemorySize/1MB,1)
"RAM free  GB: " + [math]::Round($os.FreePhysicalMemory/1MB,1)

Section "Disks"
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
  "Drive $($_.DeviceID) total GB: $([math]::Round($_.Size/1GB)) free GB: $([math]::Round($_.FreeSpace/1GB))"
}
Get-PhysicalDisk | Select-Object FriendlyName, MediaType, BusType, @{n='SizeGB';e={[math]::Round($_.Size/1GB)}} | Format-Table -AutoSize

Section "GPU (Windows view)"
Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, Status | Format-Table -AutoSize

Section "GPU (nvidia-smi)"
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if (-not $smi) {
  $cand = "$env:SystemRoot\System32\nvidia-smi.exe", "$env:ProgramFiles\NVIDIA Corporation\NVSMI\nvidia-smi.exe" | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($cand) { $smi = Get-Command $cand }
}
if ($smi) {
  & $smi.Source --query-gpu=name,driver_version,memory.total,memory.used,compute_cap,pstate --format=csv
  & $smi.Source | Select-String "CUDA Version"
} else { "nvidia-smi NOT FOUND -> NVIDIA driver is not installed or not on PATH" }

Section "Dev tools on PATH"
foreach ($c in 'python','py','pip','uv','conda','node','npm','pnpm','git','ffmpeg','ffprobe','ollama','nvcc','docker','wsl','winget') {
  $p = Get-Command $c -ErrorAction SilentlyContinue
  if ($p) { "{0,-8} {1}" -f $c, $p.Source } else { "{0,-8} NOT FOUND" -f $c }
}

Section "Versions"
try { "python: " + (python --version 2>&1) } catch {}
try { py -0p } catch {}
try { "node:   " + (node --version) } catch {}
try { "git:    " + (git --version) } catch {}
try { "ffmpeg: " + ((ffmpeg -version | Select-Object -First 1)) } catch {}
try { "nvcc:   " + ((nvcc --version | Select-Object -Last 1)) } catch {}
try { "ollama: " + (ollama --version) } catch {}

Section "Python packages of interest (default interpreter)"
pip list 2>$null | Select-String -Pattern '^(torch|torchvision|torchaudio|xformers|triton|sageattention|numpy|transformers|diffusers|accelerate|fastapi|uvicorn|onnxruntime)\s'

Section "PyTorch CUDA check (if torch is installed)"
$torchOut = cmd /c "python -c ""import torch;print('torch',torch.__version__,'cuda',torch.version.cuda,'available',torch.cuda.is_available());print('archs',torch.cuda.get_arch_list());print('device',torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"" 2>&1"
if ($LASTEXITCODE -eq 0) { $torchOut } else { "torch not importable in the default interpreter (expected if PyTorch is not installed yet)" }

Section "Existing AI tools (folder scan, shallow)"
$hits = @()
foreach ($root in @("$env:USERPROFILE","$env:USERPROFILE\Desktop","$env:USERPROFILE\Documents","$env:USERPROFILE\Downloads","C:\","D:\","E:\","C:\AI","C:\Tools","$env:LOCALAPPDATA\Programs","$env:ProgramFiles")) {
  if (Test-Path $root) {
    Get-ChildItem $root -Directory -ErrorAction SilentlyContinue | Where-Object {
      $_.Name -match 'comfy|stable|sd-?webui|forge|automatic|ollama|lmstudio|lm-studio|kobold|text-gen|pinokio|whisper|tts|wav2lip|sadtalker|liveportrait|musetalk|latentsync|wan|ltx'
    } | ForEach-Object { $hits += $_.FullName }
  }
}
if ($hits) { $hits } else { "none found in common locations" }

Section "Services listening"
foreach ($pair in @(@('ComfyUI',8188), @('Ollama',11434), @('LM Studio',1234))) {
  $name,$port = $pair
  try { $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 2; "$name on $port : responding (HTTP $($r.StatusCode))" }
  catch { if ($_.Exception.Response) { "$name on $port : responding" } else { "$name on $port : nothing" } }
}

Section "Installed programs of interest"
Get-ItemProperty HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*, HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*, HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\* -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -match 'NVIDIA|CUDA|Python|Node|Git|FFmpeg|Ollama|ComfyUI|LM Studio|Build Tools|Docker|Windows Subsystem' } |
  Select-Object DisplayName, DisplayVersion | Sort-Object DisplayName -Unique | Format-Table -AutoSize

""
"=== done ==="
