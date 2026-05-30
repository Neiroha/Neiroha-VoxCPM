from __future__ import annotations

import hashlib
import json
import os
import re
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


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if value is None:
        value = ""
    return json.dumps(str(value), ensure_ascii=False)


def write_toml_mapping(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    nested: list[tuple[str, dict[str, Any]]] = []
    for key, value in payload.items():
        if isinstance(value, dict):
            nested.append((key, value))
        else:
            lines.append(f"{key} = {toml_value(value)}")
    for table, values in nested:
        lines.append("")
        lines.append(f"[{table}]")
        for key, value in values.items():
            lines.append(f"{key} = {toml_value(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def safe_filename_part(value: Any, fallback: str = "speech") -> str:
    text = strip_text(value) or fallback
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", "_", text).strip("._ ")
    return text or fallback


def safe_ascii_filename_part(value: Any, fallback: str = "speech") -> str:
    raw = strip_text(value) or fallback
    text = safe_filename_part(raw, fallback=fallback)
    ascii_text = text.encode("ascii", errors="ignore").decode("ascii")
    ascii_text = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_text)
    ascii_text = re.sub(r"_+", "_", ascii_text).strip("._-")
    if ascii_text:
        return ascii_text[:80]
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{fallback}_{digest}"


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


def copy_model(instance: Any, **updates: Any) -> Any:
    if hasattr(instance, "model_copy"):
        return instance.model_copy(update=updates)
    return instance.copy(update=updates)
