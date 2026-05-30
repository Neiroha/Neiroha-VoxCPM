from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.common import served_model_aliases
from app.api.dependencies import get_runtime, get_voice_registry
from app.core.runtime_log import read_log_source
from app.core.registry import VoiceRegistry
from app.services.synthesis_service import OPENAI_COMPAT_MODEL_ID, VoxCPMRuntime, build_voxcpm_meta

router = APIRouter(tags=["system"])


@router.get("/")
def root(
    runtime: VoxCPMRuntime = Depends(get_runtime),
    registry: VoiceRegistry = Depends(get_voice_registry),
) -> dict[str, str | bool]:
    launch_info = getattr(runtime, "launch_info", {})
    return {
        "message": "VoxCPM launcher is running.",
        "mode": "api",
        "model": runtime.model_id,
        "device": runtime.status_device,
        "asr_enabled": runtime.asr_enabled,
        "api_url": launch_info.get("api_url", ""),
        "admin_url": launch_info.get("admin_url", ""),
        "active_model_preset": registry.active_model_preset_id(),
        "active_voice_set": registry.active_voice_set_id(),
        "default_voice": registry.default_voice_id(),
        "capabilities": "/api/voxcpm/capabilities",
        "native_models": "/api/voxcpm/models",
        "logs": "/api/voxcpm/logs",
    }


@router.get("/health")
@router.get("/api/health", include_in_schema=False)
def health(
    runtime: VoxCPMRuntime = Depends(get_runtime),
    registry: VoiceRegistry = Depends(get_voice_registry),
) -> dict[str, str | bool]:
    launch_info = getattr(runtime, "launch_info", {})
    return {
        "status": "ok",
        "model": runtime.model_id,
        "device": runtime.status_device,
        "model_loaded": runtime.voxcpm_model is not None,
        "asr_enabled": runtime.asr_enabled,
        "asr_loaded": runtime.asr_model is not None,
        "asr_model_source": runtime.asr_model_source,
        "denoiser_enabled": runtime.load_denoiser,
        "api_url": launch_info.get("api_url", ""),
        "admin_url": launch_info.get("admin_url", ""),
        "port_fallback": bool(launch_info.get("port_fallback", False)),
        "active_model_preset": registry.active_model_preset_id(),
        "active_voice_set": registry.active_voice_set_id(),
        "default_voice": registry.default_voice_id(),
    }


@router.get("/v1/models")
def list_models(
    runtime: VoxCPMRuntime = Depends(get_runtime),
    registry: VoiceRegistry = Depends(get_voice_registry),
) -> dict[str, object]:
    data = [
        voice_set.to_openai_model(len(registry.list_profiles(voice_set.id)))
        for voice_set in registry.list_voice_sets()
    ]
    return {
        "object": "list",
        "data": data,
        "legacy_model_aliases": served_model_aliases(runtime),
    }


@router.get("/api/voxcpm/meta")
@router.get("/voxcpm/meta", include_in_schema=False)
def voxcpm_meta(
    runtime: VoxCPMRuntime = Depends(get_runtime),
    registry: VoiceRegistry = Depends(get_voice_registry),
) -> dict[str, object]:
    return build_voxcpm_meta(runtime, registry)


@router.get("/api/voxcpm/models")
@router.get("/voxcpm/models", include_in_schema=False)
def voxcpm_models(registry: VoiceRegistry = Depends(get_voice_registry)) -> dict[str, object]:
    return {
        "object": "list",
        "data": [preset.to_native_model() for preset in registry.list_model_presets()],
    }


@router.get("/api/voxcpm/capabilities")
@router.get("/voxcpm/capabilities", include_in_schema=False)
def voxcpm_capabilities(
    runtime: VoxCPMRuntime = Depends(get_runtime),
    registry: VoiceRegistry = Depends(get_voice_registry),
) -> dict[str, object]:
    return {
        "object": "voxcpm.capabilities",
        "engine": "voxcpm2",
        "active_model_preset": registry.active_model_preset_id(),
        "active_voice_set": registry.active_voice_set_id(),
        "default_voice": registry.default_voice_id(),
        "model_loaded": runtime.voxcpm_model is not None,
        "asr_enabled": runtime.asr_enabled,
        "denoiser_enabled": runtime.load_denoiser,
        "supported_modes": [
            {
                "name": "design",
                "aliases": ["voice_design", "tts"],
                "required_fields": ["text"],
            },
            {
                "name": "clone",
                "aliases": ["reference", "controllable_clone", "preset_voice"],
                "required_fields": ["text", "reference_audio|voice_id"],
            },
            {
                "name": "ultimate_clone",
                "aliases": ["reference_with_text", "prompt_clone", "clone_with_prompt"],
                "required_fields": ["text", "prompt_text", "prompt_audio|reference_audio|voice_id"],
            },
        ],
        "routes": {
            "openai_speech": "/v1/audio/speech",
            "openai_models": "/v1/models",
            "openai_voices": "/v1/audio/voices",
            "native_speech": "/api/voxcpm/tts",
            "native_upload": "/api/voxcpm/tts/upload",
            "native_models": "/api/voxcpm/models",
            "native_voices": "/api/voxcpm/voices",
            "meta": "/api/voxcpm/meta",
            "logs": "/api/voxcpm/logs",
            "load": "/api/voxcpm/load",
            "unload": "/api/voxcpm/unload",
            "reload": "/api/voxcpm/reload",
            "legacy_native_speech": "/voxcpm/speech",
            "legacy_native_upload": "/voxcpm/speech/upload",
        },
    }


@router.post("/api/voxcpm/load")
@router.post("/voxcpm/load", include_in_schema=False)
def load_model(runtime: VoxCPMRuntime = Depends(get_runtime)) -> dict[str, object]:
    runtime.get_or_load_voxcpm()
    return {"loaded": True, "model": runtime.model_id, "device": runtime.status_device}


@router.post("/api/voxcpm/unload")
@router.post("/voxcpm/unload", include_in_schema=False)
def unload_model(runtime: VoxCPMRuntime = Depends(get_runtime)) -> dict[str, object]:
    runtime.voxcpm_model = None
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    return {"loaded": False, "model": runtime.model_id}


@router.post("/api/voxcpm/reload")
@router.post("/voxcpm/reload", include_in_schema=False)
def reload_model(runtime: VoxCPMRuntime = Depends(get_runtime)) -> dict[str, object]:
    unload_model(runtime)
    runtime.get_or_load_voxcpm()
    return {"loaded": True, "model": runtime.model_id, "device": runtime.status_device}


@router.get("/api/voxcpm/logs")
@router.get("/voxcpm/logs", include_in_schema=False)
def voxcpm_logs(
    source: str = "backend.log",
    limit: int = 120,
) -> Response:
    limit = max(1, min(int(limit), 1000))
    return Response(
        content=read_log_source(source, limit=limit),
        media_type="text/plain; charset=utf-8",
    )
