# Model Sources

This backend keeps large model assets under `models/` and generated caches under `runtime/cache/`.

## Main TTS Model

- Source: ModelScope `OpenBMB/VoxCPM2`
- Default local path: `models/OpenBMB__VoxCPM2`
- Download command: `pixi run install`
- Config reference: `configs/model-presets/default.toml`
- License: follow the upstream `OpenBMB/VoxCPM` model and repository license terms before redistribution or commercial use.

## Optional ASR Model

- Source: ModelScope `iic/SenseVoiceSmall`
- Default local path: `models/iic__SenseVoiceSmall`
- Download command: `pixi run install-asr`
- Config reference: `configs/model-presets/default.toml` under `[voxcpm2].asr_model_id`
- License: follow the upstream ModelScope model card license terms.

## Local Cache Policy

- Model weights belong in `models/`.
- ModelScope download cache and lock files belong in `runtime/cache/modelscope/`.
- Temporary uploads and Gradio temporary files belong in `runtime/temp/`.
- Generated audio belongs in `runtime/outputs/`.
- Runtime logs belong in `runtime/logs/`.

Large assets are intentionally ignored by Git. Keep only `.gitkeep` placeholders in committed model/runtime artifact directories.
