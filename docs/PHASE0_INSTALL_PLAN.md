# FRAMEFORGE — Phase 0 Installation Sequence (RTX 5080 PC)

Status: **drafted, not started.** Nothing in this file runs until the probe output from the
5080 PC is reviewed and the strategy below is agreed.

All commands are for **Windows PowerShell on the RTX 5080 PC**, run from the FRAMEFORGE folder
unless stated otherwise. Each step says what success looks like. Steps are ordered so that each
one is verifiable before the next starts, and so that no large model download happens before the
GPU/PyTorch stack is proven to work.

## Gate 0 — Probe results must satisfy

| Check | Minimum | Why |
|---|---|---|
| NVIDIA driver | Present, `nvidia-smi` reports `CUDA Version: 12.8` or newer | Blackwell (sm_120) needs CUDA 12.8+ |
| System RAM | 32 GB (16 GB = degraded; see Note A) | Text encoders and idle models are offloaded to RAM |
| Free disk | 200 GB on an SSD, 300 GB preferred | Model set below is ~110-150 GB; renders add tens of GB per project |
| Windows | 10 22H2 or 11 | ComfyUI portable builds target these |

**Note A — if RAM is 16 GB:** the 14B Wan models are still runnable with ComfyUI `--lowvram`
and GGUF Q4 instead of Q5, but expect 1.5-3× slower shots and occasional swapping. Recommend
upgrading RAM before Phase 6 (automated scene generation) if so.

## Step 1 — Move the project and the Claude Code session to the 5080 PC

Copy `C:\Users\W11User\Desktop\FRAMEFORGE` (docs and scripts only so far) to the 5080 PC and open
Claude Code there. From that point, installs and GPU tests can be run and verified directly
instead of relayed by hand.

Success: `scripts\probe_env.ps1` runs on the 5080 PC from inside the copied folder.

## Step 2 — Base tooling via winget (small, fast, reversible)

```powershell
winget install --id Git.Git -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Python.Python.3.12 -e
winget install --id Gyan.FFmpeg -e
winget install --id Ollama.Ollama -e
```

Why Python 3.12 and not 3.14: PyTorch cu128 wheels, ComfyUI custom nodes and most TTS packages
are published for 3.10-3.12 only. 3.14 can stay installed; FRAMEFORGE uses its own 3.12 venvs.

Open a **new** PowerShell afterwards so PATH refreshes. Success:

```powershell
git --version; node --version; py -3.12 --version; ffmpeg -version | Select-Object -First 1; ollama --version
```

All five print a version.

## Step 3 — ComfyUI with cu128 PyTorch (no models yet)

Use the official **ComfyUI Windows portable** build from the ComfyUI GitHub releases page.
Pick the release labelled for NVIDIA with **CUDA 12.8 / 50-series** support. Extract to a path
with no spaces, for example `C:\AI\ComfyUI`. The path is configured in FRAMEFORGE, never hardcoded.

Success criteria, run inside the portable folder:

```powershell
.\python_embeded\python.exe -c "import torch;print(torch.__version__, torch.version.cuda);print(torch.cuda.get_arch_list());print(torch.cuda.get_device_name(0))"
```

Must print a CUDA version of 12.8 or higher, a list containing `sm_120`, and `NVIDIA GeForce RTX 5080`.
Then start ComfyUI with `run_nvidia_gpu.bat` and confirm:

```powershell
Invoke-RestMethod http://127.0.0.1:8188/system_stats | ConvertTo-Json -Depth 4
```

The JSON lists the RTX 5080 with ~16 GB `vram_total`.

If the portable build ships an older torch: in the portable folder run

```powershell
.\python_embeded\python.exe -m pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

## Step 4 — ComfyUI Manager and the GGUF loader node

Install **ComfyUI-Manager** (clone into `custom_nodes`) and then, through Manager, **ComfyUI-GGUF**.
GGUF is required for the Q5 Wan and Qwen-Image files. Restart ComfyUI.

Success: ComfyUI's node search shows `Unet Loader (GGUF)`.

## Step 5 — First small model and test T2 (image)

Download only the Qwen-Image files needed for a 1024² render:

- `qwen_image` diffusion model, **GGUF Q4_K_M** (~12 GB) → `models/unet/`
- Qwen 2.5-VL 7B text encoder, **fp8 scaled** (~9 GB) → `models/text_encoders/`
- Qwen-Image VAE → `models/vae/`

Run the ComfyUI Qwen-Image template with the text encoder on CPU if VRAM is tight.
Record wall time and peak VRAM from `nvidia-smi`.

Success: a cat character sheet image renders without out-of-memory; VRAM peak < 15.5 GB.

## Step 6 — TTS and LLM (independent of ComfyUI; can run while Step 5 downloads)

```powershell
ollama pull qwen3:14b
ollama run qwen3:14b "Reply with JSON only: {\"ok\": true}"
```

Success: valid JSON back, `ollama ps` shows the model on GPU, then `ollama stop qwen3:14b` frees VRAM.

TTS, in a dedicated venv in the FRAMEFORGE folder:

```powershell
py -3.12 -m venv .venv-tts
.\.venv-tts\Scripts\pip install kokoro soundfile
```

Generate two 6-second WAVs with two different Kokoro voices (test T6, part 1). These WAVs are the
input for the lip-sync test. Chatterbox is installed and tested only after Kokoro passes.

## Step 7 — Audio-driven animation, test T5 (highest risk, do before the big video models)

Download the ComfyUI Wan 2.2 S2V template files:

- `wan2.2_s2v_14B_fp8_scaled.safetensors` (~15 GB) → `models/diffusion_models/`
- `umt5_xxl_fp8_e4m3fn_scaled.safetensors` (~6.7 GB) → `models/text_encoders/`
- `wan_2.1_vae.safetensors` → `models/vae/`
- `wav2vec2_large_english_fp16.safetensors` → `models/audio_encoders/`

Input: the cat image from Step 5 and one Kokoro WAV from Step 6. Run the native S2V template at
480p first, then 720p. Judge: does the mouth track the speech, does the cat stay the same cat,
how long did it take, what was peak VRAM.

If the result is poor on the cat, install the WanVideoWrapper custom node and repeat with
**InfiniteTalk** (shares the UMT5 encoder and VAE already downloaded).

Success: visibly synchronized speech on a non-human character within 16 GB. **If both fail,
stop and revisit the strategy before downloading anything else.**

## Step 8 — Video generation, tests T3 and T4

Only after Step 7 passes:

- Wan 2.2 T2V 14B **high-noise and low-noise GGUF Q5_K_M** (~10.8 GB each) + LightX2V 4-step LoRAs.
  Reuses the UMT5 encoder and VAE from Step 7. Run 81 frames at 480p, then 720p. Record times.
- Wan 2.2 TI2V 5B fp16 (~10 GB) for draft mode. Record time.
- Optional, only if commercial-use answer allows it: LTX-2 dev FP8 checkpoint, 5 s at 720p.

## Step 9 — Write results into the environment report

Fill the "Per unit (expected)" column of section 7 of
[PHASE0_ENVIRONMENT_REPORT.md](PHASE0_ENVIRONMENT_REPORT.md) with measured numbers, decide the
final model set, and close Phase 0.

## Approximate download budget

| Item | Size |
|---|---|
| ComfyUI portable | ~3 GB |
| Qwen-Image Q4 + encoder + VAE | ~21 GB |
| Qwen3 14B | ~9 GB |
| Kokoro | <1 GB |
| Wan 2.2 S2V fp8 + UMT5 fp8 + VAE + wav2vec | ~23 GB |
| Wan 2.2 T2V 14B Q5 ×2 + LoRAs | ~23 GB |
| Wan 2.2 5B | ~10 GB |
| LTX-2 FP8 (optional) | ~25 GB |
| **Total** | **~90-115 GB** |

## Troubleshooting (common failures)

- **`sm_120 is not compatible` / `no kernel image available`**: the installed torch is cu121/cu126.
  Reinstall from the `cu128` index (Step 3).
- **`nvidia-smi` shows CUDA 12.6 or lower**: update the NVIDIA driver (Game Ready or Studio, latest).
- **ComfyUI OOM on a 14B model**: add `--lowvram` to `run_nvidia_gpu.bat`; drop GGUF from Q5 to Q4;
  reduce frames before reducing resolution; make sure nothing else (Ollama, browser GPU
  acceleration) holds VRAM — `ollama stop <model>` and check `nvidia-smi`.
- **Very slow with high RAM use**: system RAM is the bottleneck (Note A). Use fp8 text encoder,
  Q4 GGUF, and close other applications.
- **pip wheel not found for a package**: you are on Python 3.14. Use the 3.12 venv.
