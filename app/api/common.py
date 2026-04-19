from __future__ import annotations

import io

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

from app.core.utils import strip_text
from app.services.synthesis_service import OPENAI_COMPAT_MODEL_ID, VoxCPMRuntime


def audio_response(*, sample_rate: int, wav, model_id: str, filename: str = "speech.wav") -> Response:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, wav, sample_rate, format="WAV")
    return Response(
        content=buffer.getvalue(),
        media_type="audio/wav",
        headers={
            "X-VoxCPM-Model": model_id,
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )


def openai_error(
    message: str,
    *,
    status_code: int = 400,
    error_type: str = "invalid_request_error",
) -> JSONResponse:
    return JSONResponse(
        content={
            "error": {
                "message": message,
                "type": error_type,
            }
        },
        status_code=status_code,
    )


def ensure_served_model(requested_model: str | None, runtime: VoxCPMRuntime) -> None:
    requested = strip_text(requested_model)
    if requested and requested not in {runtime.model_id, OPENAI_COMPAT_MODEL_ID}:
        raise HTTPException(
            status_code=400,
            detail=f"This launcher currently serves {runtime.model_id} and the alias {OPENAI_COMPAT_MODEL_ID}.",
        )


def ensure_wav_only(response_format: str) -> None:
    if strip_text(response_format).lower() != "wav":
        raise HTTPException(
            status_code=400,
            detail="Only response_format='wav' is currently supported by this launcher.",
        )
