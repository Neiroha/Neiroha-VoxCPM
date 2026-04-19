from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.common import served_model_aliases
from app.api.dependencies import get_runtime, get_voice_registry
from app.core.registry import VoiceRegistry
from app.services.synthesis_service import OPENAI_COMPAT_MODEL_ID, VoxCPMRuntime, build_voxcpm_meta

router = APIRouter(tags=["system"])


@router.get("/")
def root(runtime: VoxCPMRuntime = Depends(get_runtime)) -> dict[str, str | bool]:
    return {
        "message": "VoxCPM launcher is running.",
        "mode": "api",
        "model": runtime.model_id,
        "device": runtime.status_device,
        "asr_enabled": runtime.asr_enabled,
    }


@router.get("/health")
@router.get("/api/health", include_in_schema=False)
def health(runtime: VoxCPMRuntime = Depends(get_runtime)) -> dict[str, str | bool]:
    return {
        "status": "ok",
        "model": runtime.model_id,
        "device": runtime.status_device,
        "model_loaded": runtime.voxcpm_model is not None,
        "asr_enabled": runtime.asr_enabled,
        "asr_loaded": runtime.asr_model is not None,
        "asr_model_source": runtime.asr_model_source,
        "denoiser_enabled": runtime.load_denoiser,
    }


@router.get("/v1/models")
def list_models(runtime: VoxCPMRuntime = Depends(get_runtime)) -> dict[str, object]:
    data: list[dict[str, object]] = []
    for model_id in served_model_aliases(runtime):
        entry: dict[str, object] = {
            "id": model_id,
            "object": "model",
            "owned_by": "openbmb" if model_id == runtime.model_id else "local",
        }
        if model_id != runtime.model_id:
            entry["root_model"] = runtime.model_id
        if model_id == OPENAI_COMPAT_MODEL_ID:
            entry["alias_type"] = "openai_compat"
        elif model_id.lower() in {"voxcpm2", "openbmb/voxcpm2"}:
            entry["alias_type"] = "vllm_omni_compat"
        data.append(entry)

    return {
        "object": "list",
        "data": data,
    }


@router.get("/voxcpm/meta")
def voxcpm_meta(
    runtime: VoxCPMRuntime = Depends(get_runtime),
    registry: VoiceRegistry = Depends(get_voice_registry),
) -> dict[str, object]:
    return build_voxcpm_meta(runtime, registry)
