# VoxCPM Local Launcher API

Single-page API reference for the local VoxCPM launcher.

[中文 API 文档](./API_zh.md) | [README](../README.md) | [中文 README](../README_zh.md)

## Overview

This server exposes three groups of routes:

- OpenAI-compatible TTS routes
- native VoxCPM routes under `/api/voxcpm/...`
- TOML voice set / voice profile registry routes

The current FastAPI entrypoint is assembled in `app/api/main.py`, while request normalization and mode mapping are handled in `app/services/synthesis_service.py`.

## Compatibility Notes

This server is compatible with the baseline `vllm-omni` VoxCPM2 OpenAI example in these areas:

- `POST /v1/audio/speech`
- model aliases `voxcpm2` and `openbmb/VoxCPM2`
- placeholder `voice: "default"`
- voice cloning via `ref_audio`

Additional compatibility behavior:

- `ref_audio` is accepted as an alias of `reference_audio`
- `ref_text` is accepted as an alias of `prompt_text`
- audio references may be:
  - local file path
  - `file://` URI
  - `http(s)` URL
  - `data:audio/...;base64,...`

## Base URL

Default local API address:

```text
http://127.0.0.1:8000
```

## Model IDs And Config Semantics

For the OpenAI-compatible route, `model` means voice set. The default mapping is:

- `model=default` -> `configs/voice-sets/default.toml`
- `voice=voxcpm2-design` -> `runtime/voices/voxcpm2-design/voice.toml`
- `voice=voxcpm2-clone` -> `runtime/voices/voxcpm2-clone/voice.toml`
- `voice=voxcpm2-ultimate-clone` -> `runtime/voices/voxcpm2-ultimate-clone/voice.toml`
- underlying VoxCPM2 weights -> `configs/model-presets/default.toml`

Legacy model ids remain accepted for compatibility:

- `voxcpm2`
- `openbmb/VoxCPM2`
- `voxcpm-openai-tts`
- `tts-1`
- `tts-1-hd`
- the exact local model id used by the launcher, such as `models/OpenBMB__VoxCPM2`

Query available ids:

- `GET /v1/models`

## Route Summary

### System

- `GET /`
- `GET /health`
- `GET /api/health`
- `GET /v1/models`
- `GET /api/voxcpm/models`
- `GET /api/voxcpm/capabilities`
- `GET /api/voxcpm/meta`
- `GET /api/voxcpm/logs`
- `POST /api/voxcpm/load`
- `POST /api/voxcpm/unload`
- `POST /api/voxcpm/reload`

### OpenAI-Compatible TTS

- `GET /v1/audio/voices`
- `GET /v1/audio/speakers`
- `GET /speakers`
- `POST /v1/audio/speech`

### Native VoxCPM

- `POST /api/voxcpm/tts`
- `POST /api/voxcpm/tts/upload`
- aliases:
  - `POST /voxcpm/speech`
  - `POST /voxcpm/generate`
  - `POST /voxcpm/speech/upload`
  - `POST /api/v1/tts/voxcpm`
  - `POST /api/tts/voxcpm`
  - `POST /api/tts`

### Voice Registry

- `GET /api/voxcpm/voices`
- `POST /api/voxcpm/voices`
- `GET /api/voxcpm/voices/{voice_id}`
- `DELETE /api/voxcpm/voices/{voice_id}`

## Mode Model

Internally, requests are normalized into three execution modes:

- `design`
  - text only
- `clone`
  - reference audio or registered voice
- `ultimate_clone`
  - prompt text plus prompt/reference audio

Accepted external aliases include:

- `preset_voice`
- `reference`
- `reference_with_text`
- `cross_lingual`
- `instruction`
- `voice_design`
- `tts`

## Special Tokens and Style Markers

After checking the upstream `VoxCPM/` submodule, this project does not currently document a public list of text-side special tokens like `[Surprise-ah]` for client use.

What the upstream repo does document:

- for voice design, put a natural-language voice description in parentheses at the start of `text`
- for controllable cloning, use a natural-language style hint in parentheses at the start of `text`
- for ultimate cloning, provide `prompt_text` together with prompt/reference audio

Examples from the upstream usage pattern:

```text
(A young woman, gentle and sweet voice)Hello, welcome to VoxCPM2!
(slightly faster, cheerful tone)This is a cloned voice with style control.
```

Important clarification:

- there is no verified upstream public token table in this repo for tags like `[Surprise-ah]`
- do not rely on undocumented bracket tokens in client requests
- the phrase `ref_audio tokens` appears in the upstream implementation, but that refers to internal model structure, not a public text prompt syntax

Recommended client behavior:

- use natural-language control text
- keep style hints short and front-loaded
- prefer explicit fields like `reference_audio`, `prompt_audio`, `prompt_text`, `voice`, and `voice_id`

## OpenAI-Compatible TTS

### Zero-Shot

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"default\", \"input\": \"Hello, this is VoxCPM2.\", \"voice\": \"voxcpm2-design\"}" \
  --output output.wav
```

### Voice Clone With `vllm-omni`-Style `ref_audio`

```json
{
  "model": "default",
  "input": "This should sound like the reference speaker.",
  "voice": "default",
  "ref_audio": "data:audio/wav;base64,...",
  "response_format": "wav"
}
```

### Preferred Local Extension Fields

The OpenAI route also accepts local extension fields:

- `reference_audio`
- `prompt_audio`
- `prompt_text`
- `mode`
- `instruction`
- `auto_asr`
- `cfg_value`
- `inference_timesteps`
- `normalize`
- `denoise`

### Important Behavior

- `voice` does not automatically create a persistent speaker
- `voice` only becomes a reusable registered speaker when it matches an existing voice profile id
- a one-off `ref_audio` or `reference_audio` request is just a temporary clone request

## Native VoxCPM API

### JSON API

```json
{
  "model": "voxcpm2",
  "text": "Text to synthesize",
  "mode": "reference_with_text",
  "reference_audio": "file:///D:/voices/ref.wav",
  "prompt_text": "Reference transcript",
  "response_format": "wav"
}
```

### Upload API

`POST /api/voxcpm/tts/upload` accepts multipart form fields:

- `text`
- `mode`
- `voice_id`
- `reference_audio`
- `prompt_audio`
- `prompt_text`
- `response_format`

Uploaded files are temporary and are cleaned up after the request finishes. They are not automatically stored as reusable voices.

## Voice Registry

Voice profiles default to TOML:

```text
runtime/voices/<voice_id>/voice.toml
```

### Create or Update

```json
{
  "id": "taichi_cn_01",
  "display_name": "Taichi CN",
  "mode_hint": "reference_with_text",
  "audio_path": "file:///D:/voices/taichi/ref.wav",
  "prompt_text": "Reference transcript",
  "copy_audio_to_registry": true
}
```

### List

```bash
curl http://localhost:8000/api/voxcpm/voices
```

### Delete

```bash
curl -X DELETE http://localhost:8000/api/voxcpm/voices/taichi_cn_01
```

### Reuse a Registered Voice

OpenAI-compatible request:

```json
{
  "model": "default",
  "input": "Read this with the registered voice.",
  "voice": "taichi_cn_01"
}
```

Native request:

```json
{
  "model": "voxcpm2",
  "text": "Read this with the registered voice.",
  "voice_id": "taichi_cn_01"
}
```

## Deletion Semantics

- temporary uploaded audio is deleted automatically after the request
- registered voices must be deleted with `DELETE /api/voxcpm/voices/{voice_id}`
- on Windows, physical directory cleanup may be delayed by file locks, but the voice is logically deleted immediately

## Response Format

Current output format support:

- `wav`

The server responds with:

- `Content-Type: audio/wav`
- raw audio bytes in the body
- `X-VoxCPM-Model`: resolved local model id
- `X-VoxCPM-Sample-Rate`: output sample rate
- `X-VoxCPM-Audio-Seconds`: generated audio duration in seconds
- `X-VoxCPM-Output-Bytes`: final WAV payload size in bytes
- `X-VoxCPM-Synthesis-Seconds`: synthesis wall time in seconds
- `X-VoxCPM-RTF`: real-time factor, calculated as `synthesis_seconds / audio_seconds`
- `X-Neiroha-Backend`: backend slug, currently `voxcpm`
- `X-Neiroha-Model-Preset`: active model preset id
- `X-Neiroha-Voice`: resolved voice id
- `X-Neiroha-Sample-Rate`: output sample rate
- `X-Neiroha-Inference-Ms`: synthesis wall time in milliseconds
- `X-Neiroha-Output-Format`: output format
- `X-Neiroha-Output-Path`: header-safe path to the copy written under `runtime/outputs`
- `X-Neiroha-Audio-Seconds`
- `X-Neiroha-Elapsed-Seconds`
- `X-Neiroha-RTF`

Notes:

- `X-VoxCPM-Synthesis-Seconds` measures only the synthesis step after the request has been normalized.
- upload handling, remote `ref_audio` download, and response streaming are not included in that metric.

## Recommendation

Use the OpenAI route for Neiroha front-end integration and generic OpenAI-style clients.

Use the native routes when you need:

- multipart uploads
- explicit mode control
- voice registry management
- clearer local-only semantics

## Error Shape

JSON errors use a stable Neiroha shape:

```json
{
  "error": {
    "code": "unsupported_format",
    "message": "Only response_format='wav' is currently supported by this launcher.",
    "details": {},
    "type": "invalid_request_error"
  }
}
```
