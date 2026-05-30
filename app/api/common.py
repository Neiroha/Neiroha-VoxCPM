from __future__ import annotations

import io
import datetime as dt
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

from app.core.config import OUTPUTS_ROOT, WORKSPACE_ROOT
from app.core.registry import VoiceRegistry
from app.core.utils import safe_ascii_filename_part, strip_text
from app.services.synthesis_service import OPENAI_COMPAT_MODEL_ID, VoxCPMRuntime

BACKEND_SLUG = "voxcpm"


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
    add("tts-1")
    add("tts-1-hd")
    add(runtime.model_id)

    runtime_name = Path(runtime.model_id).name.lower()
    if "voxcpm2" in runtime.model_id.lower() or "voxcpm2" in runtime_name:
        add("voxcpm2")
        add("openbmb/VoxCPM2")

    return aliases


def _runtime_model_aliases(runtime: VoxCPMRuntime) -> set[str]:
    return {alias.lower() for alias in served_model_aliases(runtime)}


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
    model_preset_id: str = "",
    voice_id: str = "",
    output_format: str = "wav",
    filename: str = "speech.wav",
    output_stem: str = "speech",
    synthesis_seconds: float | None = None,
) -> Response:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, wav, sample_rate, format="WAV")
    content = buffer.getvalue()
    metrics = audio_metrics(sample_rate=sample_rate, wav=wav, synthesis_seconds=synthesis_seconds)
    output_path = write_runtime_output(content, output_stem, suffix="wav")
    safe_filename = header_safe_value(filename, fallback="speech.wav")

    headers = {
        "X-VoxCPM-Model": header_safe_value(model_id, fallback="model"),
        "X-VoxCPM-Sample-Rate": str(sample_rate),
        "X-VoxCPM-Audio-Seconds": _format_header_float(metrics["audio_seconds"]),
        "X-VoxCPM-Output-Bytes": str(len(content)),
        "X-Neiroha-Backend": BACKEND_SLUG,
        "X-Neiroha-Model-Preset": header_safe_value(model_preset_id, fallback="preset"),
        "X-Neiroha-Voice": header_safe_value(voice_id, fallback="voice"),
        "X-Neiroha-Sample-Rate": str(sample_rate),
        "X-Neiroha-Output-Format": header_safe_value(output_format, fallback="wav"),
        "X-Neiroha-Output-Path": header_safe_path(output_path),
        "X-Neiroha-Audio-Seconds": _format_header_float(metrics["audio_seconds"]),
        "Content-Disposition": f'inline; filename="{safe_filename}"',
    }

    if "synthesis_seconds" in metrics and "rtf" in metrics:
        inference_ms = int(round(float(metrics["synthesis_seconds"]) * 1000))
        headers["X-VoxCPM-Synthesis-Seconds"] = _format_header_float(metrics["synthesis_seconds"])
        headers["X-VoxCPM-RTF"] = _format_header_float(metrics["rtf"])
        headers["X-Neiroha-Inference-Ms"] = str(inference_ms)
        headers["X-Neiroha-Elapsed-Seconds"] = _format_header_float(metrics["synthesis_seconds"])
        headers["X-Neiroha-RTF"] = _format_header_float(metrics["rtf"])

    return Response(
        content=content,
        media_type="audio/wav",
        headers=headers,
    )


def write_runtime_output(content: bytes, stem: Any, *, suffix: str) -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    safe_stem = safe_ascii_filename_part(stem, fallback="speech")
    path = OUTPUTS_ROOT / f"{safe_stem}_{timestamp}.{suffix}"
    counter = 1
    while path.exists():
        path = OUTPUTS_ROOT / f"{safe_stem}_{timestamp}_{counter}.{suffix}"
        counter += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def header_safe_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(WORKSPACE_ROOT.resolve()).as_posix()
    except ValueError:
        text = str(path)
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        return safe_ascii_filename_part(path.name)


def header_safe_value(value: Any, *, fallback: str = "value") -> str:
    text = strip_text(value)
    if not text:
        return fallback
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        return safe_ascii_filename_part(text, fallback=fallback)


def error_payload(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    error_type: str = "invalid_request_error",
) -> dict[str, dict[str, Any]]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "type": error_type,
        }
    }


def error_response(
    code: str,
    message: str,
    *,
    status_code: int = 400,
    details: dict[str, Any] | None = None,
    error_type: str = "invalid_request_error",
) -> JSONResponse:
    return JSONResponse(
        content=error_payload(code, message, details=details, error_type=error_type),
        status_code=status_code,
    )


def error_code_for_status(status_code: int) -> str:
    if status_code == 401:
        return "auth_required"
    if status_code == 404:
        return "voice_not_found"
    if status_code >= 500:
        return "inference_failed"
    return "invalid_request"


def openai_error(
    message: str,
    *,
    status_code: int = 400,
    error_type: str = "invalid_request_error",
    code: str | None = None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return error_response(
        code or error_code_for_status(status_code),
        message,
        status_code=status_code,
        details=details,
        error_type=error_type,
    )


def http_error_detail(code: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details or {}}


def ensure_served_model(
    requested_model: str | None,
    runtime: VoxCPMRuntime,
    registry: VoiceRegistry | None = None,
) -> None:
    requested = strip_text(requested_model)
    accepted = _runtime_model_aliases(runtime)
    if registry is not None:
        accepted.update(voice_set.id.lower() for voice_set in registry.list_voice_sets())
    if requested and requested.lower() not in accepted:
        if registry is not None and registry.has_voice_set(requested):
            return
        raise HTTPException(
            status_code=400,
            detail=http_error_detail(
                "voice_not_found",
                (
                    "This launcher currently serves the following OpenAI model/voice-set ids: "
                    + ", ".join(sorted(accepted))
                    + "."
                ),
                details={"requested_model": requested, "accepted": sorted(accepted)},
            ),
        )


def ensure_wav_only(response_format: str) -> None:
    if strip_text(response_format).lower() != "wav":
        raise HTTPException(
            status_code=400,
            detail=http_error_detail(
                "unsupported_format",
                "Only response_format='wav' is currently supported by this launcher.",
                details={"requested_format": response_format, "supported_formats": ["wav"]},
            ),
        )
