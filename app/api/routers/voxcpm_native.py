from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from time import perf_counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.common import audio_metrics, audio_response, ensure_served_model, ensure_wav_only, http_error_detail
from app.api.dependencies import get_runtime, get_voice_registry
from app.core.config import UPLOAD_TEMP_DIR
from app.core.runtime_log import RUNTIME_EVENTS
from app.core.registry import VoiceRegistry
from app.core.schemas import NativeSpeechRequest
from app.core.utils import copy_model, first_non_empty
from app.services.audio_sources import materialize_audio_sources
from app.services.synthesis_service import VoxCPMRuntime, build_native_request

LOGGER = logging.getLogger("voxcpm.launcher")
router = APIRouter(tags=["voxcpm"])


def save_uploaded_audio(uploaded_audio: UploadFile | None, *, prefix: str) -> str | None:
    if uploaded_audio is None or not uploaded_audio.filename:
        return None
    suffix = Path(uploaded_audio.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=UPLOAD_TEMP_DIR,
        prefix=f"{prefix}_",
        suffix=suffix,
    ) as tmp:
        tmp.write(uploaded_audio.file.read())
        return tmp.name


def cleanup_temp_file(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def synthesize_native_payload(
    payload: NativeSpeechRequest,
    *,
    runtime: VoxCPMRuntime,
    registry: VoiceRegistry,
):
    synthesis_seconds = None
    request = None
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
            reference_prefix="native_reference",
            prompt_prefix="native_prompt",
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
            ensure_served_model(request_payload.model, runtime, registry)
            ensure_wav_only(request_payload.response_format or request_payload.format or "wav")
            request = build_native_request(request_payload, runtime, registry)
            started_at = perf_counter()
            sample_rate, wav = runtime.synthesize(request)
            synthesis_seconds = perf_counter() - started_at
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=http_error_detail("invalid_reference_audio", str(exc)),
        ) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=http_error_detail("invalid_request", str(exc)),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=http_error_detail("inference_failed", str(exc)),
        ) from exc
    except Exception as exc:
        LOGGER.exception("Native synthesis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    metrics = audio_metrics(sample_rate=sample_rate, wav=wav, synthesis_seconds=synthesis_seconds)
    LOGGER.info(
        "Synthesis completed | synth_seconds=%.2fs | audio_seconds=%.2fs | RTF=%.4f",
        metrics.get("synthesis_seconds", 0.0),
        metrics["audio_seconds"],
        metrics.get("rtf", 0.0),
    )
    RUNTIME_EVENTS.append(
        "synthesis_complete",
        route="/voxcpm/speech",
        model=payload.model or runtime.model_id,
        voice=request.voice_name if request else "",
        audio_seconds=metrics["audio_seconds"],
        elapsed_seconds=metrics.get("synthesis_seconds", 0.0),
        rtf=metrics.get("rtf", 0.0),
    )

    return audio_response(
        sample_rate=sample_rate,
        wav=wav,
        model_id=runtime.model_id,
        model_preset_id=registry.active_model_preset_id(),
        voice_id=request.voice_name if request and request.voice_name else registry.default_voice_id(),
        output_stem=request.voice_name if request and request.voice_name else "native",
        synthesis_seconds=synthesis_seconds,
    )


@router.post("/api/voxcpm/tts", summary="Generate speech with native VoxCPM JSON API")
@router.post("/api/voxcpm/speech", include_in_schema=False)
@router.post("/voxcpm/speech", include_in_schema=False)
@router.post("/voxcpm/generate", include_in_schema=False)
def native_generate(
    payload: NativeSpeechRequest,
    runtime: VoxCPMRuntime = Depends(get_runtime),
    registry: VoiceRegistry = Depends(get_voice_registry),
):
    return synthesize_native_payload(payload, runtime=runtime, registry=registry)


@router.post("/api/voxcpm/tts/upload", summary="Generate speech with uploaded reference or prompt audio")
@router.post("/api/voxcpm/speech/upload", include_in_schema=False)
@router.post("/voxcpm/speech/upload", include_in_schema=False)
def native_generate_upload(
    model: str | None = Form(None),
    text: str = Form(...),
    input: str | None = Form(None),
    mode: str | None = Form(None),
    voice_id: str | None = Form(None),
    profile: str | None = Form(None),
    character_name: str | None = Form(None),
    speaker: str | None = Form(None),
    voice: str | None = Form(None),
    instruction: str | None = Form(None),
    instructions: str | None = Form(None),
    control: str | None = Form(None),
    ref_audio: str | None = Form(None),
    reference_audio_path: str | None = Form(None),
    prompt_audio_path: str | None = Form(None),
    reference_audio: UploadFile | None = File(None),
    prompt_audio: UploadFile | None = File(None),
    prompt_text: str | None = Form(None),
    ref_text: str | None = Form(None),
    reference_text: str | None = Form(None),
    transcript: str | None = Form(None),
    language: str | None = Form(None),
    auto_asr: bool = Form(False),
    speed: float = Form(1.0),
    response_format: str = Form("wav"),
    cfg_value: float = Form(2.0),
    inference_timesteps: int = Form(10),
    normalize: bool = Form(False),
    denoise: bool = Form(False),
    runtime: VoxCPMRuntime = Depends(get_runtime),
    registry: VoiceRegistry = Depends(get_voice_registry),
):
    temp_reference_audio = None
    temp_prompt_audio = None

    try:
        temp_reference_audio = save_uploaded_audio(reference_audio, prefix="reference")
        temp_prompt_audio = save_uploaded_audio(prompt_audio, prefix="prompt")

        payload = NativeSpeechRequest(
            model=model,
            text=text,
            input=input,
            mode=mode,
            voice_id=voice_id,
            profile=profile,
            character_name=character_name,
            speaker=speaker,
            voice=voice,
            instruction=instruction or "",
            instructions=instructions or "",
            control=control or "",
            instruct_text="",
            ref_audio=ref_audio,
            reference_audio=temp_reference_audio or reference_audio_path,
            reference_audio_path=None,
            reference_wav_path=None,
            prompt_audio=temp_prompt_audio or prompt_audio_path,
            prompt_audio_path=None,
            prompt_wav_path=None,
            prompt_text=prompt_text or "",
            ref_text=ref_text or "",
            reference_text=reference_text or "",
            transcript=transcript or "",
            language=language or "",
            auto_asr=auto_asr,
            speed=speed,
            response_format=response_format,
            format="",
            cfg_value=cfg_value,
            inference_timesteps=inference_timesteps,
            normalize=normalize,
            denoise=denoise,
        )
        return synthesize_native_payload(payload, runtime=runtime, registry=registry)
    finally:
        cleanup_temp_file(temp_reference_audio)
        cleanup_temp_file(temp_prompt_audio)


@router.post("/api/v1/tts/voxcpm", include_in_schema=False)
@router.post("/api/tts/voxcpm", include_in_schema=False)
@router.post("/api/tts", include_in_schema=False)
def legacy_native_generate(
    payload: NativeSpeechRequest,
    runtime: VoxCPMRuntime = Depends(get_runtime),
    registry: VoiceRegistry = Depends(get_voice_registry),
):
    return synthesize_native_payload(payload, runtime=runtime, registry=registry)
