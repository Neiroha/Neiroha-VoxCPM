from __future__ import annotations

import io
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

from app.core.utils import strip_text
from app.services.synthesis_service import OPENAI_COMPAT_MODEL_ID, VoxCPMRuntime


def served_model_aliases(runtime: VoxCPMRuntime) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        text = strip_text(value)
        if not text:
            return
        lowered = text.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        aliases.append(text)

    add(OPENAI_COMPAT_MODEL_ID)
    add(runtime.model_id)

    runtime_name = Path(runtime.model_id).name.lower()
    if "voxcpm2" in runtime.model_id.lower() or "voxcpm2" in runtime_name:
        add("voxcpm2")
        add("openbmb/VoxCPM2")

    return aliases


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
    accepted = {alias.lower() for alias in served_model_aliases(runtime)}
    if requested and requested.lower() not in accepted:
        raise HTTPException(
            status_code=400,
            detail=(
                "This launcher currently serves the following model ids: "
                + ", ".join(served_model_aliases(runtime))
                + "."
            ),
        )


def ensure_wav_only(response_format: str) -> None:
    if strip_text(response_format).lower() != "wav":
        raise HTTPException(
            status_code=400,
            detail="Only response_format='wav' is currently supported by this launcher.",
        )
