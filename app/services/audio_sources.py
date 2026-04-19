from __future__ import annotations

import base64
import binascii
import contextlib
import mimetypes
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse
from urllib.error import URLError
from urllib.request import urlopen

from app.core.config import UPLOAD_TEMP_DIR
from app.core.utils import strip_text

_MIME_SUFFIXES = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
}


@dataclass
class MaterializedAudioSources:
    reference_audio: str | None = None
    prompt_audio: str | None = None
    cleanup_paths: list[str] = field(default_factory=list)


def _suffix_from_source(*, mime_type: str = "", url_path: str = "") -> str:
    normalized_mime = strip_text(mime_type).lower()
    if normalized_mime in _MIME_SUFFIXES:
        return _MIME_SUFFIXES[normalized_mime]

    guessed = mimetypes.guess_extension(normalized_mime or "")
    if guessed:
        return guessed

    suffix = Path(url_path).suffix
    if suffix:
        return suffix
    return ".wav"


def _write_temp_audio(data: bytes, *, prefix: str, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=UPLOAD_TEMP_DIR,
        prefix=f"{prefix}_",
        suffix=suffix or ".wav",
    ) as tmp:
        tmp.write(data)
        return tmp.name


def _materialize_one_audio_source(source: str | None, *, prefix: str) -> tuple[str | None, list[str]]:
    value = strip_text(source)
    if not value:
        return None, []

    lowered = value.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        try:
            with urlopen(value, timeout=60) as response:
                data = response.read()
                content_type = response.headers.get_content_type()
                suffix = _suffix_from_source(
                    mime_type=content_type or "",
                    url_path=urlparse(value).path,
                )
        except URLError as exc:
            raise RuntimeError(f"Failed to fetch audio URL: {value}") from exc
        path = _write_temp_audio(data, prefix=prefix, suffix=suffix)
        return path, [path]

    if lowered.startswith("data:"):
        try:
            header, encoded = value.split(",", 1)
        except ValueError as exc:
            raise ValueError("Invalid data URI for audio input.") from exc
        if ";base64" not in header.lower():
            raise ValueError("Only base64-encoded data URIs are supported for audio input.")

        mime_type = header[5:].split(";", 1)[0] if header.startswith("data:") else ""
        try:
            data = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise ValueError("Invalid base64 audio payload.") from exc

        suffix = _suffix_from_source(mime_type=mime_type, url_path="")
        path = _write_temp_audio(data, prefix=prefix, suffix=suffix)
        return path, [path]

    return value, []


@contextlib.contextmanager
def materialize_audio_sources(
    *,
    reference_audio: str | None = None,
    prompt_audio: str | None = None,
    reference_prefix: str = "reference",
    prompt_prefix: str = "prompt",
) -> Iterator[MaterializedAudioSources]:
    materialized_reference, reference_cleanup = _materialize_one_audio_source(
        reference_audio,
        prefix=reference_prefix,
    )
    materialized_prompt, prompt_cleanup = _materialize_one_audio_source(
        prompt_audio,
        prefix=prompt_prefix,
    )
    result = MaterializedAudioSources(
        reference_audio=materialized_reference,
        prompt_audio=materialized_prompt,
        cleanup_paths=[*reference_cleanup, *prompt_cleanup],
    )
    try:
        yield result
    finally:
        for path in result.cleanup_paths:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
