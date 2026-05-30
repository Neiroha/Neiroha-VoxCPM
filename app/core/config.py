from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = WORKSPACE_ROOT / "configs"
SERVER_CONFIG_PATH = CONFIG_ROOT / "server.toml"
MODEL_PRESETS_DIR = CONFIG_ROOT / "model-presets"
VOICE_SETS_DIR = CONFIG_ROOT / "voice-sets"
MODELS_ROOT = WORKSPACE_ROOT / "models"
RUNTIME_ROOT = WORKSPACE_ROOT / "runtime"
CACHE_ROOT = RUNTIME_ROOT / "cache"
LOCAL_TEMP_DIR = RUNTIME_ROOT / "temp"
UPLOAD_TEMP_DIR = LOCAL_TEMP_DIR / "uploads"
MODELSCOPE_CACHE_ROOT = CACHE_ROOT / "modelscope"
LOCAL_ASR_MODEL_DIR = MODELS_ROOT / "iic__SenseVoiceSmall"
VOICES_ROOT = RUNTIME_ROOT / "voices"
LOGS_ROOT = RUNTIME_ROOT / "logs"
OUTPUTS_ROOT = RUNTIME_ROOT / "outputs"


def prepare_runtime_environment() -> None:
    for path in (
        CONFIG_ROOT,
        MODEL_PRESETS_DIR,
        VOICE_SETS_DIR,
        MODELS_ROOT,
        RUNTIME_ROOT,
        CACHE_ROOT,
        LOCAL_TEMP_DIR,
        UPLOAD_TEMP_DIR,
        MODELSCOPE_CACHE_ROOT,
        VOICES_ROOT,
        LOGS_ROOT,
        OUTPUTS_ROOT,
    ):
        path.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("TMPDIR", str(LOCAL_TEMP_DIR))
    os.environ.setdefault("TEMP", str(LOCAL_TEMP_DIR))
    os.environ.setdefault("TMP", str(LOCAL_TEMP_DIR))
    os.environ.setdefault("GRADIO_TEMP_DIR", str(LOCAL_TEMP_DIR / "gradio"))
    os.environ.setdefault("MODELSCOPE_CACHE", str(MODELSCOPE_CACHE_ROOT))
    os.environ.setdefault("MODELSCOPE_MODULES_CACHE", str(MODELSCOPE_CACHE_ROOT / "modules"))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


prepare_runtime_environment()
