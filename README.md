# VoxCPM Local Launcher

Local Windows-first launcher for `OpenBMB/VoxCPM`, with a decoupled FastAPI service, the upstream Gradio WebUI, and a small compatibility layer for OpenAI-style TTS clients.

[中文说明](./README_zh.md) | [API Docs](./docs/API.md) | [API 文档](./docs/API_zh.md) | [Model Sources](./docs/model-sources.md)

## What This Repo Provides

- `pixi` environment management
- local model download into `./models`
- upstream `OpenBMB/VoxCPM` as a git submodule
- official Gradio WebUI launcher
- standalone FastAPI server
- config-driven `pixi run serve` entrypoint for API, Admin, or both
- OpenAI-compatible `/v1/audio/speech`
- native VoxCPM routes under `/api/voxcpm/...`
- TOML voice sets and local voice profiles under `configs/` and `runtime/voices/`
- compatibility with the `vllm-omni` VoxCPM2 example request shape

OpenAI-style `model=default` means a voice set, not the underlying VoxCPM2 weights. The native VoxCPM2 model path and runtime options live in `configs/model-presets/default.toml`. The default voice set preserves the three VoxCPM2 inference modes as file-backed profiles:

- `voxcpm2-design`: text-only voice design
- `voxcpm2-clone`: reference-audio controllable cloning
- `voxcpm2-ultimate-clone`: `prompt_audio` + `prompt_text` high-fidelity cloning

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

Default API + Neiroha Admin:

```powershell
pixi run serve
```

API only:

```powershell
pixi run api
```

Ports, startup surface, preload behavior, and the default model preset come from `configs/server.toml` and `configs/model-presets/default.toml`; pixi tasks do not hardcode model paths or ports.

Neiroha Admin only:

```powershell
pixi run admin
```

For other startup surfaces or engine options, edit `configs/server.toml` and `configs/model-presets/default.toml`, or call `scripts/launch_engine.py --help` for one-off overrides.

Contract checks:

```powershell
pixi run test
pixi run smoke
```

See all launcher options:

```powershell
python -B scripts/launch_engine.py --help
```

## Neiroha Front-End Integration

For the Neiroha front-end, the recommended baseline is:

- Base URL: `http://127.0.0.1:8000`
- TTS endpoint: `POST /v1/audio/speech`
- Voice list: `GET /v1/audio/voices`
- Model id: `default`

Recommended request body:

```json
{
  "model": "default",
  "input": "Hello from Neiroha.",
  "voice": "default",
  "response_format": "wav"
}
```

For one-off voice cloning, send `ref_audio` or `reference_audio`.

For reusable local speakers, create a voice profile with `POST /api/voxcpm/voices`, then call:

```json
{
  "model": "default",
  "input": "Read this in the registered voice.",
  "voice": "taichi_cn_01"
}
```

Legacy model ids `voxcpm2`, `openbmb/VoxCPM2`, and `voxcpm-openai-tts` remain accepted as compatibility aliases. Native routes are standardized under `/api/voxcpm/*`; legacy `/voxcpm/*` routes remain available.

## Repo Layout

```text
.
├─ app/
├─ configs/
├─ docs/
├─ models/
├─ runtime/
├─ scripts/
├─ tests/
├─ VoxCPM/
└─ pixi.toml
```

## Notes

- model weights are not committed
- runtime caches, outputs, logs, and local voices are not committed
- model source and license notes live in [docs/model-sources.md](./docs/model-sources.md)
- this repo currently targets Windows + CUDA + Pixi
- API details live in one page: [docs/API.md](./docs/API.md)
