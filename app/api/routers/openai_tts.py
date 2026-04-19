from __future__ import annotations

import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException

from app.api.common import audio_metrics, audio_response, ensure_served_model, ensure_wav_only, openai_error
from app.api.dependencies import get_runtime, get_voice_registry
from app.core.registry import VoiceRegistry
from app.core.schemas import OpenAITTSSpeechRequest
from app.core.utils import copy_model, first_non_empty
from app.services.audio_sources import materialize_audio_sources
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
    synthesis_seconds = None
    try:
        reference_audio = first_non_empty(
            payload.reference_audio,
            payload.reference_audio_path,
            payload.reference_wav_path,
            payload.ref_audio,
        )
        prompt_audio = first_non_empty(
            payload.prompt_audio,
            payload.prompt_audio_path,
            payload.prompt_wav_path,
        )
        with materialize_audio_sources(
            reference_audio=reference_audio,
            prompt_audio=prompt_audio,
            reference_prefix="openai_reference",
            prompt_prefix="openai_prompt",
        ) as materialized:
            request_payload = copy_model(
                payload,
                ref_audio=None,
                reference_audio=materialized.reference_audio,
                reference_audio_path=None,
                reference_wav_path=None,
                prompt_audio=materialized.prompt_audio,
                prompt_audio_path=None,
                prompt_wav_path=None,
            )
            ensure_served_model(request_payload.model, runtime)
            ensure_wav_only(request_payload.response_format or request_payload.format or "wav")
            request = build_openai_request(request_payload, runtime, registry)
            started_at = perf_counter()
            sample_rate, wav = runtime.synthesize(request)
            synthesis_seconds = perf_counter() - started_at
    except FileNotFoundError as exc:
        return openai_error(str(exc), status_code=404)
    except HTTPException as exc:
        return openai_error(str(exc.detail), status_code=exc.status_code)
    except (ValueError, RuntimeError) as exc:
        return openai_error(str(exc), status_code=400)
    except Exception as exc:
        LOGGER.exception("OpenAI-compatible synthesis failed")
        return openai_error(str(exc), status_code=500, error_type="server_error")

    metrics = audio_metrics(sample_rate=sample_rate, wav=wav, synthesis_seconds=synthesis_seconds)
    LOGGER.info(
        "Synthesis completed | synth_seconds=%.2fs | audio_seconds=%.2fs | RTF=%.4f",
        metrics.get("synthesis_seconds", 0.0),
        metrics["audio_seconds"],
        metrics.get("rtf", 0.0),
    )

    return audio_response(
        sample_rate=sample_rate,
        wav=wav,
        model_id=runtime.model_id,
        synthesis_seconds=synthesis_seconds,
    )
