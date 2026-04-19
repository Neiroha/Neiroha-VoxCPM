from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname


def strip_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = strip_text(value)
        if text:
            return text
    return ""


def extract_voice_name(voice_value: Any) -> str:
    if isinstance(voice_value, dict):
        return first_non_empty(voice_value.get("id"), voice_value.get("name"))
    return strip_text(voice_value)


def resolve_local_path(path_value: Any) -> Path | None:
    text = strip_text(path_value)
    if not text:
        return None

    if text.lower().startswith("file://"):
        parsed = urlparse(text)
        path_text = url2pathname(parsed.path or "")
        if parsed.netloc and parsed.netloc not in {"", "localhost"}:
            path_text = f"//{parsed.netloc}{path_text}"
        if os.name == "nt" and path_text.startswith("/") and len(path_text) > 2 and path_text[2] == ":":
            path_text = path_text[1:]
        return Path(path_text).expanduser()

    return Path(text).expanduser()


def require_existing_file(path_value: Any, *, field_name: str) -> str | None:
    candidate = resolve_local_path(path_value)
    if candidate is None:
        return None
    if not candidate.exists():
        raise FileNotFoundError(f"{field_name} does not exist: {candidate}")
    if not candidate.is_file():
        raise FileNotFoundError(f"{field_name} is not a file: {candidate}")
    return str(candidate.resolve())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def dump_model(instance: Any) -> dict[str, Any]:
    if hasattr(instance, "model_dump"):
        return instance.model_dump()
    return instance.dict()
