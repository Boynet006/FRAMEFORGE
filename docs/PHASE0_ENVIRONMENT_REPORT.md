# FRAMEFORGE — Phase 0 Environment Report

Date: 2026-10-16
Status: **BLOCKED on hardware confirmation.** The machine this session runs on is not the RTX 5080 machine.

## 1. What was inspected

Everything below was read directly from the computer running this Claude Code session
(`C:\Users\W11User\Desktop\FRAMEFORGE`). Nothing was installed or changed.

| Item | Found |
|---|---|
| Machine | HP ProStudio 4 All-in-One G1i 23.8" Desktop AI PC |
| OS | Windows 11 Pro 10.0.26200 (build 26200) |
| CPU | Intel Core Ultra 7 265T, 20 cores / 20 threads |
| RAM | 15.4 GB total, ~5.7 GB free at probe time |
| GPU | **Intel integrated graphics only.** No NVIDIA PCI device, no NVIDIA driver, no `nvidia-smi`. |
| Disk | C: 476 GB, 258 GB free (single volume) |
| Python | 3.14.7 (64-bit), only 3 pip packages installed, no PyTorch |
| Node / npm | not installed |
| Git | not installed |
| FFmpeg | not on PATH, but a portable **FFmpeg 9.0.2 essentials** (gyan.dev) exists at `Desktop\ollamatalks\ffmpeg-portable\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe` with libx264, libx265, aac, NVENC and QSV encoders |
| Ollama | not installed (an empty `~/.ollama` folder exists, no models) |
| ComfyUI | not installed, nothing on port 8188 |
| Docker Desktop | 4.93.0 installed, daemon not running; WSL2 present (docker-desktop distro only) |
| winget | v1.29 available |
| VS Code | 1.133 installed |
| Prior work | `Desktop\ollamatalks`: a small experiment using Edge TTS (cloud) and a talking-llama photo animation. No FRAMEFORGE prototype code exists in the working directory, which is empty. |

## 2. Critical finding

**This computer cannot run the FRAMEFORGE generation pipeline.** It is an all-in-one PC with no
discrete GPU and 15 GB of RAM. An all-in-one chassis cannot accept a desktop RTX 5080.

Consequences:

- The RTX 5080 must live in a different computer. Its OS, RAM, disk and installed software are
  currently **unknown** and must be probed before any model decisions are final.
  Run [scripts/probe_env.ps1](../scripts/probe_env.ps1) on that machine and paste the output.
- Two deployment layouts are possible. The choice changes Phase 1:
  1. **Everything on the 5080 PC** (simplest; recommended). Frontend, backend, ComfyUI, Ollama,
     TTS all on one machine. This AIO is just where you open the browser or edit code.
  2. **Split**: web app + orchestrator on this AIO, ComfyUI/Ollama/TTS on the 5080 PC over LAN.
     Possible because every engine exposes an HTTP API, but adds network transfer of multi-GB
     outputs and a second machine to keep up to date.
- **System RAM on the 5080 PC matters as much as VRAM.** The 16 GB VRAM strategy below depends on
  offloading text encoders and inactive models to system RAM. If the 5080 PC also has only
  16 GB RAM, the 14B video models will page to disk and become impractically slow. 32 GB is the
  realistic minimum; 64 GB is comfortable.

## 3. Toolchain facts verified online (October 2026)

- **RTX 5080 = Blackwell, compute capability sm_120.** Requires CUDA 12.8 or newer. PyTorch
  2.7+ stable wheels on the `cu128` index support it; older cu121/cu126 wheels fail with
  "sm_120 is not compatible". Verify with `torch.cuda.get_arch_list()` containing `sm_120`.
  Sources: [PyTorch forum 1](https://discuss.pytorch.org/t/pytorch-cannot-detect-rtx-5080-requires-cuda-12-8-nightly-build-fails-to-install-correctly-on-windows/223957),
  [PyTorch forum 2](https://discuss.pytorch.org/t/cuda-support-for-rtx-50x-on-windows/221309).
- **ComfyUI** ships Windows portable builds with cu128 PyTorch; it is the right host for Wan,
  LTX, Qwen-Image and S2V workflows and has an HTTP + WebSocket API.

## 4. Candidate model stack for 16 GB VRAM

Nothing here is final until tested on the actual card (Phase 0 tests, section 6).

### 4.1 Video generation (shots, B-roll, wide shots)

| Model | Fit on 16 GB | License | Notes |
|---|---|---|---|
| **Wan 2.2 14B T2V/I2V, GGUF Q5_K_M + LightX2V 4-step LoRA** | Yes (community-reported at 720p; ~10.8 GB per expert file, two experts loaded sequentially) | Apache 2.0 | Best quality/consistency among open models; slow without the distill LoRA. **Primary candidate.** |
| Wan 2.2 5B TI2V (fp16) | Yes, comfortably | Apache 2.0 | Much faster, lower quality; good **draft mode**. |
| **LTX-2 / LTX-2.3 22B dev, FP8** | Yes at 720p, short clips (official minimum for bf16 is 32 GB) | Lightricks license: free commercial use under a $10M revenue threshold, verify text | Fastest high-quality option; generates **audio+video jointly** incl. speech, but lip sync is reported to be the first thing that degrades at FP8/16 GB. **Secondary candidate / fast mode.** |
| HunyuanVideo 13B | Marginal | Tencent community license | Not pursued; heavier than Wan for similar quality. |

Sources: [Wan2.2 Distill models](https://huggingface.co/lightx2v/Wan2.2-Distill-Models),
[Wan VRAM by GPU](https://localaimaster.com/blog/wan-vram-requirements-by-gpu),
[Wan 2.2 GGUF guide](https://blog.segmind.com/wan-comfyui-setup-gguf-workflow-tutorial/),
[LTX-2 local setup](https://aivideosensei.com/guides/ltx-2-local-setup),
[Wan + LTX-2 setup](https://evezone.evetech.co.za/build-lab/how-to-set-up-local-ai-video-generation-with-wan-and-ltx-2),
[LTX-2.5 announcement](https://rits.shanghai.nyu.edu/ai/ltx-2-5-adds-native-multi-shot-video-and-a-diffusion-decoder/).

### 4.2 Audio-driven speaking characters (the core of the "conversation" requirement)

| Model | Fit on 16 GB | License | Notes |
|---|---|---|---|
| **Wan 2.2 S2V 14B, fp8_scaled** | Expected with offload; ComfyUI has a native template | Apache 2.0 | Speech-to-video from one reference image + audio. Vendor docs list cartoons and animals as supported inputs. **Primary candidate** for talking cats. |
| **InfiniteTalk** (Wan 2.1 based) | Expected with offload (no published 16 GB figure) | Apache 2.0 | Long-form audio-driven dubbing, supports image-to-video. Alternative if S2V quality on animals is weak. |
| LatentSync 1.6 / MuseTalk | Yes (small) | Apache 2.0 / MIT | Human-face lip-sync; **rely on human face detection, expected to fail on cats.** Only relevant if characters are human. |
| LivePortrait (animals variant) | Yes (small) | MIT, but animal variant needs XPose build, painful on Windows | Expression retargeting, not audio-driven. Backup for blinks/head motion only. |

Sources: [ComfyUI Wan2.2 S2V tutorial](https://docs.comfy.org/tutorials/video/wan/wan2-2-s2v),
[ComfyUI Wiki S2V](https://comfyui-wiki.com/en/tutorial/advanced/video/wan2.2/wan2-2-s2v),
[Comfy model page listing InfiniteTalk](https://www.comfy.org/workflows/model/wan/).

Open risk: no independent test of S2V or InfiniteTalk on cartoon/animal mouths at 16 GB was found.
This is exactly what Phase 0 test T5 measures.

### 4.3 Character reference images and consistency

| Model | Fit on 16 GB | License | Notes |
|---|---|---|---|
| **Qwen-Image 20B, GGUF Q4/Q5** | Yes with GGUF (fp8 is 20 GB, too large) | Apache 2.0 | Character sheets, environments. |
| **Qwen-Image-Edit 2511, GGUF** | Yes with GGUF | Apache 2.0 | Pose/angle/expression variants of the same character. |
| Flux.1 Kontext dev, fp8 | Yes with offload (12 GB file) | **Non-commercial** | Strong identity preservation, but license blocks commercial use. Use only if output is non-commercial. |
| Flux.1 schnell / SDXL | Yes | Apache 2.0 / OpenRAIL | Fallbacks. |

Sources: [Qwen-Image-Edit vs Kontext](https://diffusiondoodles.substack.com/p/qwen-image-edit-vs-flux1-kontext),
[Kontext on ComfyUI](https://docs.comfy.org/tutorials/partner-nodes/black-forest-labs/flux-1-kontext),
[Qwen 2511 comparison](https://aiindigo.com/compare/qwen-image-edit-2511-vs-flux).

### 4.4 Text-to-speech (character voices)

| Model | Fit | License | Notes |
|---|---|---|---|
| **Kokoro 82M** | Trivial; runs on CPU | Apache 2.0 | 54 fixed voices, very fast, no cloning. **Default engine.** |
| **Chatterbox** | ~3-4 GB VRAM or CPU | MIT | Voice cloning from ~10 s, emotion control. For distinct custom cat voices. |
| Dia 1.6B | ~6 GB | Apache 2.0 | Multi-speaker dialogue in one pass; worth a test for conversational timing. |
| F5-TTS | ~4 GB | MIT (verify; earlier builds were CC-BY-NC) | Cloning alternative. |
| XTTS v2, Fish Audio S2 | — | CPML / research license | **Excluded**: commercial restrictions. |
| Edge TTS (used in `ollamatalks`) | — | Microsoft cloud | **Excluded**: violates the no-cloud rule. |

Sources: [Open-source TTS guide 2026](https://tts.ai/blog/open-source-text-to-speech-guide-2026/),
[TTS comparison March 2026](https://codesota.com/guides/tts-models).

### 4.5 Local LLM (script, shot planning, structured JSON)

| Model | VRAM | License | Notes |
|---|---|---|---|
| **Qwen3 14B Q4_K_M via Ollama** | ~9-12 GB | Apache 2.0 | ~60 tok/s on a 4080-class card. Good instruction following. Use Ollama `format` with a JSON schema. |
| gpt-oss 20B | ~13 GB | Apache 2.0 | Faster, alternative. |

The LLM is **never resident at the same time as a video model**; it runs in the planning stage,
then Ollama is told to unload (`keep_alive: 0`) before ComfyUI work starts.

Sources: [16 GB Ollama comparison](https://www.glukhov.org/post/2026/01/choosing-best-llm-for-ollama-on-16gb-vram-gpu/),
[Best local LLM 16 GB](https://bestllmfor.com/guides/best-local-llm-16gb-vram/).

### 4.6 Assembly

FFmpeg 9.x (already present as a portable build; will be re-downloaded onto the 5080 PC),
with `h264_nvenc`/`hevc_nvenc` for fast final encodes and `libx264` for maximum compatibility.

## 5. VRAM strategy

Only **one heavy model family is on the GPU at a time**. The orchestrator enforces this order per
project and frees memory between stages (ComfyUI `/free` endpoint with `unload_models` and
`free_memory`; Ollama `keep_alive: 0`; `torch.cuda.empty_cache()` in the TTS worker):

1. **Plan** — Ollama / Qwen3 14B (≤12 GB). Unload.
2. **Voices** — Kokoro (CPU) or Chatterbox (≤4 GB). Unload.
3. **Character & environment references** — Qwen-Image GGUF (≤12 GB + text encoder offloaded to RAM). Unload.
4. **Speaking shots** — Wan 2.2 S2V fp8 (model ~14 GB file, run with ComfyUI `--lowvram`/block
   swapping and the UMT5 text encoder in fp8 on CPU). Batched: all speaking shots for a scene in
   one ComfyUI session so the model is loaded once.
5. **Non-speaking shots** (wide, reaction, establishing) — Wan 2.2 14B GGUF + LightX2V, or LTX-2 FP8
   in fast mode. Also batched.
6. **Assembly** — FFmpeg, GPU only for NVENC.

Quality profiles:

- **Draft**: Wan 2.2 5B / LTX-2 FP8, 480p, 4-step distill, 12 fps. For script and timing review.
- **Final**: Wan 2.2 14B Q5 + S2V fp8, 720p, 16-24 fps.

## 6. Phase 0 validation tests (to run on the 5080 PC after probe)

| ID | Test | Pass criterion |
|---|---|---|
| T0 | `probe_env.ps1` | Full output captured; RAM ≥ 32 GB recommended, ≥ 200 GB free disk |
| T1 | ComfyUI portable + cu128 PyTorch | `torch.cuda.is_available()` true, `sm_120` in arch list, ComfyUI `/system_stats` returns the 5080 |
| T2 | Image: Qwen-Image GGUF, 1024², a cat character sheet | Completes, peak VRAM < 15.5 GB, time recorded |
| T3 | Video: Wan 2.2 14B Q5 + LightX2V, 81 frames 480p | Completes without OOM, time recorded; then 720p |
| T4 | Video fast path: LTX-2 FP8, 5 s 720p | Completes, time recorded |
| T5 | **Audio-driven: Wan 2.2 S2V fp8 with a cat image + a 6 s Kokoro WAV** | Mouth visibly tracks speech; identity preserved; VRAM and time recorded. Repeat with InfiniteTalk if weak. |
| T6 | TTS: Kokoro and Chatterbox, two distinct voices, 20 lines | Audible distinctness, correct word timings, generation time |
| T7 | LLM: Qwen3 14B via Ollama, JSON-schema script output | Valid JSON for a 2-minute script, time recorded |

Each test records: wall time, peak VRAM, peak system RAM, output path. These feed the
10-minute estimate below.

## 7. Realistic performance expectations for a 10-minute video

Assumptions: average shot 5 s, so **~120 shots**, roughly half speaking (S2V) and half
non-speaking. These are ranges to be replaced by T3-T5 measurements.

| Stage | Per unit (expected on 5080, 16 GB) | Total |
|---|---|---|
| Script + plan (LLM) | — | 2-5 min |
| TTS, ~1,500 words | — | 1-3 min (Kokoro) / 5-10 min (Chatterbox) |
| Character/environment refs, ~20 images | 30-60 s | 10-20 min |
| Speaking shots, 60 × 5 s, S2V fp8 720p | 3-8 min each | 3-8 h |
| Non-speaking shots, 60 × 5 s, Wan 14B Q5 + distill 720p | 2-5 min each | 2-5 h |
| Assembly + encode | — | 5-10 min |
| **Total final-quality render** | | **~6-14 hours** |
| **Draft render** (5B / LTX-2 480p) | | **~1-2 hours** |

Implication: a 10-minute project is an overnight job. Resumable, checkpointed, scene-by-scene
generation is a requirement, not a nice-to-have, and the UI must show per-shot progress and ETA.

## 8. Licensing summary

- Core pipeline can be fully Apache 2.0 / MIT: Wan 2.2 (+S2V), Qwen-Image(-Edit), Kokoro,
  Chatterbox, Qwen3, ComfyUI (GPL-3.0 as an application, outputs unrestricted), FFmpeg (LGPL/GPL build).
- Optional with conditions: LTX-2 (revenue threshold), Flux Kontext dev (non-commercial).
- Excluded: Edge TTS (cloud), XTTS v2 and Fish Audio S2 (commercial restrictions).

## 9. Decisions needed before Phase 0 installation

See the questions at the end of the session message. In short: where the RTX 5080 is, that
machine's RAM/disk/OS, which deployment layout, whether commercial use is intended, and the
intended visual style (cartoon vs photoreal animals), which decides the lip-sync model test order.
