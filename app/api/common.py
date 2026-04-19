from __future__ import annotations

import io
from pathlib import Path
from typing import Any

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


def _audio_frame_count(wav: Any) -> int:
    shape = getattr(wav, "shape", None)
    if shape is not None:
        dims = [max(int(value), 0) for value in shape]
        if not dims:
            return 0
        if len(dims) == 1:
            return dims[0]

        first = dims[0]
        last = dims[-1]
        if first <= 8 < last:
            return last
        if last <= 8 < first:
            return first
        return max(first, last)

    try:
        return max(len(wav), 0)
    except TypeError:
        return 0


def _format_header_float(value: float) -> str:
    return f"{max(float(value), 0.0):.6f}"


def audio_metrics(
    *,
    sample_rate: int,
    wav,
    synthesis_seconds: float | None = None,
) -> dict[str, float | int]:
    audio_seconds = 0.0
    if sample_rate > 0:
        audio_seconds = _audio_frame_count(wav) / sample_rate

    metrics: dict[str, float | int] = {
        "sample_rate": int(sample_rate),
        "audio_seconds": max(float(audio_seconds), 0.0),
    }

    if synthesis_seconds is not None:
        safe_synthesis_seconds = max(float(synthesis_seconds), 0.0)
        metrics["synthesis_seconds"] = safe_synthesis_seconds
        metrics["rtf"] = safe_synthesis_seconds / audio_seconds if audio_seconds > 0 else 0.0

    return metrics


def audio_response(
    *,
    sample_rate: int,
    wav,
    model_id: str,
    filename: str = "speech.wav",
    synthesis_seconds: float | None = None,
) -> Response:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, wav, sample_rate, format="WAV")
    content = buffer.getvalue()
    metrics = audio_metrics(sample_rate=sample_rate, wav=wav, synthesis_seconds=synthesis_seconds)

    headers = {
        "X-VoxCPM-Model": model_id,
        "X-VoxCPM-Sample-Rate": str(sample_rate),
        "X-VoxCPM-Audio-Seconds": _format_header_float(metrics["audio_seconds"]),
        "X-VoxCPM-Output-Bytes": str(len(content)),
        "Content-Disposition": f'inline; filename="{filename}"',
    }

    if "synthesis_seconds" in metrics and "rtf" in metrics:
        headers["X-VoxCPM-Synthesis-Seconds"] = _format_header_float(metrics["synthesis_seconds"])
        headers["X-VoxCPM-RTF"] = _format_header_float(metrics["rtf"])

    return Response(
        content=content,
        media_type="audio/wav",
        headers=headers,
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
