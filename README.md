# VoxCPM Local Launcher

Local Windows-first launcher for `OpenBMB/VoxCPM`, with a decoupled FastAPI service, the upstream Gradio WebUI, and a small compatibility layer for OpenAI-style TTS clients.

[中文说明](./README_zh.md) | [API Docs](./docs/API.md) | [API 文档](./docs/API_zh.md)

## What This Repo Provides

- `pixi` environment management
- local model download into `./models`
- upstream `OpenBMB/VoxCPM` as a git submodule
- official Gradio WebUI launcher
- standalone FastAPI server
- OpenAI-compatible `/v1/audio/speech`
- native VoxCPM routes
- local voice registry under `runtime/voices/`
- compatibility with the `vllm-omni` VoxCPM2 example request shape

## Quick Start

### 1. Clone With Submodules

```powershell
git clone --recurse-submodules https://github.com/neiroha/<repo-name>.git
cd <repo-name>
```

If you already cloned the outer repo:

```powershell
git submodule update --init --recursive
```

### 2. Install

```powershell
pixi install
```

### 3. Download the Main Model

```powershell
pixi run install
```

Optional ASR model:

```powershell
pixi run install-asr
```

### 4. Start the Service

API only:

```powershell
pixi run api
```

Default API task uses `--no-optimize`, because on this Windows setup it benchmarked faster than `torch.compile` for typical VoxCPM requests.

API with optimization enabled explicitly:

```powershell
pixi run api-optimize
```

API with ASR:

```powershell
pixi run api-asr
```

API with ASR and optimization enabled explicitly:

```powershell
pixi run api-asr-optimize
```

WebUI only:

```powershell
pixi run webui
```

Combined API + WebUI:

```powershell
pixi run combined
```

See all launcher options:

```powershell
python -B scripts/launch_voxcpm.py --help
```

## Neiroha Front-End Integration

For the Neiroha front-end, the recommended baseline is:

- Base URL: `http://127.0.0.1:8000`
- TTS endpoint: `POST /v1/audio/speech`
- Voice list: `GET /v1/audio/voices`
- Model id: `voxcpm2`

Recommended request body:

```json
{
  "model": "voxcpm2",
  "input": "Hello from Neiroha.",
  "voice": "default",
  "response_format": "wav"
}
```

For one-off voice cloning, send `ref_audio` or `reference_audio`.

For reusable local speakers, create a voice profile with `POST /voxcpm/voices`, then call:

```json
{
  "model": "voxcpm2",
  "input": "Read this in the registered voice.",
  "voice": "taichi_cn_01"
}
```

## Repo Layout

```text
.
├─ app/
├─ docs/
├─ models/
├─ runtime/
├─ scripts/
├─ VoxCPM/
├─ pixi.toml
└─ plan.md
```

## Notes

- model weights are not committed
- runtime caches, outputs, logs, and local voices are not committed
- this repo currently targets Windows + CUDA + Pixi
- API details live in one page: [docs/API.md](./docs/API.md)
