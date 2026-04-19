from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Iterable

from app.core.config import VOICES_ROOT, WORKSPACE_ROOT
from app.core.schemas import VoiceProfile, VoiceProfileCreateRequest
from app.core.utils import dump_model, first_non_empty, resolve_local_path, strip_text, utc_now_iso

LOGGER = logging.getLogger("voxcpm.voice_registry")
VOICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _handle_rmtree_error(func, path: str, exc_info) -> None:
    Path(path).chmod(0o666)
    func(path)


class VoiceRegistry:
    def __init__(self, root: Path = VOICES_ROOT) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _normalize_voice_id(self, voice_id: str) -> str:
        normalized = strip_text(voice_id).replace(" ", "_")
        if not normalized:
            raise ValueError("voice id is required.")
        if not VOICE_ID_PATTERN.match(normalized):
            raise ValueError("voice id may only contain letters, numbers, dot, dash, and underscore.")
        return normalized

    def _voice_dir(self, voice_id: str) -> Path:
        return (self.root / self._normalize_voice_id(voice_id)).resolve()

    def _meta_file(self, voice_id: str) -> Path:
        return self._voice_dir(voice_id) / "meta.json"

    def _ensure_voice_dir_is_safe(self, voice_dir: Path) -> None:
        root = self.root.resolve()
        if voice_dir != root and root not in voice_dir.parents:
            raise ValueError(f"voice directory escapes registry root: {voice_dir}")

    def _serialize_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(WORKSPACE_ROOT.resolve())
            return relative.as_posix()
        except ValueError:
            return str(resolved)

    def resolve_audio_path(self, path_value: str | None) -> str | None:
        candidate = resolve_local_path(path_value)
        if candidate is None:
            return None
        if candidate.is_absolute():
            return str(candidate.resolve())
        workspace_candidate = (WORKSPACE_ROOT / candidate)
        if workspace_candidate.exists():
            return str(workspace_candidate.resolve())
        return str(candidate.resolve())

    def _prepare_audio_path(
        self,
        path_value: str | None,
        *,
        voice_dir: Path,
        filename_stem: str,
        copy_audio: bool,
    ) -> str | None:
        resolved = self.resolve_audio_path(path_value)
        if resolved is None:
            return None

        source_path = Path(resolved)
        if not source_path.exists():
            raise FileNotFoundError(f"{filename_stem} does not exist: {source_path}")
        if not source_path.is_file():
            raise FileNotFoundError(f"{filename_stem} is not a file: {source_path}")

        if copy_audio:
            target = voice_dir / f"{filename_stem}{source_path.suffix or '.wav'}"
            shutil.copy2(source_path, target)
            return self._serialize_path(target)

        return self._serialize_path(source_path)

    @staticmethod
    def _fields_set(payload: VoiceProfileCreateRequest) -> set[str]:
        fields = getattr(payload, "model_fields_set", None)
        if fields is not None:
            return set(fields)
        return set(getattr(payload, "__fields_set__", set()))

    @staticmethod
    def _infer_sample_rate(*paths: str | None) -> int | None:
        try:
            import soundfile as sf
        except ModuleNotFoundError:
            return None

        for candidate in paths:
            if not candidate:
                continue
            try:
                info = sf.info(candidate)
                return int(info.samplerate)
            except Exception:
                continue
        return None

    def list_profiles(self) -> list[VoiceProfile]:
        profiles: list[VoiceProfile] = []
        for meta_file in sorted(self.root.glob("*/meta.json")):
            try:
                payload = json.loads(meta_file.read_text(encoding="utf-8"))
                if payload.get("deleted"):
                    continue
                profiles.append(VoiceProfile(**payload))
            except Exception as exc:
                LOGGER.warning("Failed to load voice profile %s: %s", meta_file, exc)
        return profiles

    def exists(self, voice_id: str) -> bool:
        return self._meta_file(voice_id).exists()

    def get_profile(self, voice_id: str) -> VoiceProfile:
        meta_file = self._meta_file(voice_id)
        if not meta_file.exists():
            raise FileNotFoundError(f"Voice profile not found: {voice_id}")
        payload = json.loads(meta_file.read_text(encoding="utf-8"))
        if payload.get("deleted"):
            raise FileNotFoundError(f"Voice profile not found: {voice_id}")
        return VoiceProfile(**payload)

    def get_optional_profile(self, voice_id: str) -> VoiceProfile | None:
        try:
            return self.get_profile(voice_id)
        except FileNotFoundError:
            return None

    def save_profile(self, payload: VoiceProfileCreateRequest, *, default_model: str) -> tuple[VoiceProfile, bool]:
        voice_id = self._normalize_voice_id(payload.id)
        voice_dir = self._voice_dir(voice_id)
        self._ensure_voice_dir_is_safe(voice_dir)
        voice_dir.mkdir(parents=True, exist_ok=True)

        existing = self.get_optional_profile(voice_id)
        created = existing is None
        fields_set = self._fields_set(payload)

        def field_provided(*names: str) -> bool:
            return any(name in fields_set for name in names)

        def text_value(name: str, fallback: str) -> str:
            if name in fields_set:
                return strip_text(getattr(payload, name))
            return fallback

        def optional_text_value(name: str, fallback: str | None) -> str | None:
            if name in fields_set:
                value = strip_text(getattr(payload, name))
                return value or None
            return fallback

        reference_source = existing.audio_path if existing else None
        if field_provided("audio_path", "reference_audio_path"):
            reference_source = first_non_empty(payload.audio_path, payload.reference_audio_path) or None

        prompt_source = existing.prompt_audio_path if existing else None
        if "prompt_audio_path" in fields_set:
            prompt_source = strip_text(payload.prompt_audio_path) or None

        reference_audio_path = self._prepare_audio_path(
            reference_source,
            voice_dir=voice_dir,
            filename_stem="reference",
            copy_audio=payload.copy_audio_to_registry,
        )
        prompt_audio_path = self._prepare_audio_path(
            prompt_source,
            voice_dir=voice_dir,
            filename_stem="prompt",
            copy_audio=payload.copy_audio_to_registry,
        )

        now = utc_now_iso()
        resolved_audio_paths: Iterable[str | None] = (
            self.resolve_audio_path(reference_audio_path),
            self.resolve_audio_path(prompt_audio_path),
        )
        sample_rate = (
            payload.sample_rate
            if "sample_rate" in fields_set and payload.sample_rate is not None
            else self._infer_sample_rate(*resolved_audio_paths) or (existing.sample_rate if existing else None)
        )

        profile = VoiceProfile(
            id=voice_id,
            display_name=text_value("display_name", existing.display_name if existing else voice_id) or voice_id,
            engine=text_value("engine", existing.engine if existing else "torch_native") or "torch_native",
            model=text_value("model", existing.model if existing else default_model) or default_model,
            mode_hint=optional_text_value("mode_hint", existing.mode_hint if existing else None),
            audio_path=reference_audio_path,
            prompt_audio_path=prompt_audio_path,
            prompt_text=text_value("prompt_text", existing.prompt_text if existing else ""),
            instruction=text_value("instruction", existing.instruction if existing else ""),
            language=text_value("language", existing.language if existing else ""),
            sample_rate=sample_rate,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )

        meta_file = voice_dir / "meta.json"
        meta_file.write_text(json.dumps(dump_model(profile), ensure_ascii=False, indent=2), encoding="utf-8")
        return profile, created

    def delete_profile(self, voice_id: str) -> None:
        voice_dir = self._voice_dir(voice_id)
        self._ensure_voice_dir_is_safe(voice_dir)
        if not voice_dir.exists():
            raise FileNotFoundError(f"Voice profile not found: {voice_id}")
        meta_file = self._meta_file(voice_id)
        if meta_file.exists():
            try:
                payload = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                payload = {"id": self._normalize_voice_id(voice_id)}
            if payload.get("deleted"):
                raise FileNotFoundError(f"Voice profile not found: {voice_id}")
            payload["deleted"] = True
            payload["deleted_at"] = utc_now_iso()
            meta_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            shutil.rmtree(voice_dir, onerror=_handle_rmtree_error)
        except OSError as exc:
            LOGGER.debug("Voice profile directory could not be fully removed yet: %s", exc)
