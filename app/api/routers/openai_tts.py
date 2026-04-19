from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.common import audio_response, ensure_served_model, ensure_wav_only, openai_error
from app.api.dependencies import get_runtime, get_voice_registry
from app.core.registry import VoiceRegistry
from app.core.schemas import OpenAITTSSpeechRequest
from app.services.synthesis_service import VoxCPMRuntime, build_openai_request

LOGGER = logging.getLogger("voxcpm.launcher")
router = APIRouter(tags=["openai"])


@router.get("/v1/audio/voices")
@router.get("/v1/audio/speakers", include_in_schema=False)
def list_voices(
    registry: VoiceRegistry = Depends(get_voice_registry),
) -> dict[str, object]:
    data = [
        {
            "id": "default",
            "name": "default",
            "object": "voice",
            "description": "Fallback entry for ad-hoc requests without a registered voice profile.",
        }
    ]

    for profile in registry.list_profiles():
        data.append(
            {
                "id": profile.id,
                "name": profile.display_name,
                "object": "voice",
                "description": profile.instruction or f"Registered local voice profile ({profile.mode_hint or 'auto'}).",
                "mode_hint": profile.mode_hint,
                "language": profile.language,
                "model": profile.model,
            }
        )

    return {"object": "list", "data": data}


@router.get("/speakers")
def speakers(registry: VoiceRegistry = Depends(get_voice_registry)) -> list[dict[str, str]]:
    data = [{"name": "default", "voice_id": "default"}]
    for profile in registry.list_profiles():
        data.append({"name": profile.display_name, "voice_id": profile.id})
    return data


@router.post("/v1/audio/speech", summary="Generate speech (OpenAI compatible)")
def openai_audio_speech(
    payload: OpenAITTSSpeechRequest,
    runtime: VoxCPMRuntime = Depends(get_runtime),
    registry: VoiceRegistry = Depends(get_voice_registry),
):
    try:
        ensure_served_model(payload.model, runtime)
        ensure_wav_only(payload.response_format or payload.format or "wav")
        request = build_openai_request(payload, runtime, registry)
        sample_rate, wav = runtime.synthesize(request)
    except FileNotFoundError as exc:
        return openai_error(str(exc), status_code=404)
    except HTTPException as exc:
        return openai_error(str(exc.detail), status_code=exc.status_code)
    except (ValueError, RuntimeError) as exc:
        return openai_error(str(exc), status_code=400)
    except Exception as exc:
        LOGGER.exception("OpenAI-compatible synthesis failed")
        return openai_error(str(exc), status_code=500, error_type="server_error")

    return audio_response(sample_rate=sample_rate, wav=wav, model_id=runtime.model_id)
