from __future__ import annotations

import json
import logging
import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.core.config import MODEL_PRESETS_DIR, SERVER_CONFIG_PATH, VOICE_SETS_DIR, VOICES_ROOT, WORKSPACE_ROOT
from app.core.schemas import VoiceProfile, VoiceProfileCreateRequest
from app.core.utils import dump_model, first_non_empty, resolve_local_path, strip_text, utc_now_iso, write_toml_mapping

LOGGER = logging.getLogger("voxcpm.voice_registry")
DEFAULT_MODEL_PRESET_ID = "voxcpm2-default"
DEFAULT_VOICE_SET_ID = "default"
DEFAULT_VOICE_ID = "voxcpm2-design"
LEGACY_OPENAI_MODEL_ALIASES = {
    "voxcpm-openai-tts",
    "voxcpm2",
    "openbmb/voxcpm2",
    "tts-1",
    "tts-1-hd",
}


@dataclass
class ModelPreset:
    id: str
    name: str
    engine: str = "voxcpm2"
    model_id: str = "models/OpenBMB__VoxCPM2"
    device: str = "auto"
    optimize: bool = False
    load_denoiser: bool = False
    enable_asr: bool = False
    asr_model_id: str = "models/iic__SenseVoiceSmall"

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ModelPreset":
        voxcpm2 = payload.get("voxcpm2") if isinstance(payload.get("voxcpm2"), dict) else {}
        preset_id = strip_text(payload.get("id")) or DEFAULT_MODEL_PRESET_ID
        return cls(
            id=preset_id,
            name=first_non_empty(payload.get("name"), preset_id),
            engine=strip_text(payload.get("engine")) or "voxcpm2",
            model_id=first_non_empty(voxcpm2.get("model_id"), voxcpm2.get("model_dir"), "models/OpenBMB__VoxCPM2"),
            device=first_non_empty(voxcpm2.get("device"), "auto"),
            optimize=bool(voxcpm2.get("optimize", False)),
            load_denoiser=bool(voxcpm2.get("load_denoiser", False)),
            enable_asr=bool(voxcpm2.get("enable_asr", False)),
            asr_model_id=first_non_empty(voxcpm2.get("asr_model_id"), "models/iic__SenseVoiceSmall"),
        )

    def to_native_model(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "object": "voxcpm.model_preset",
            "name": self.name,
            "engine": self.engine,
            "model_id": self.model_id,
            "device": self.device,
            "optimize": self.optimize,
            "load_denoiser": self.load_denoiser,
            "enable_asr": self.enable_asr,
            "asr_model_id": self.asr_model_id,
        }


@dataclass
class VoiceSet:
    id: str
    name: str
    description: str = ""
    voices: list[str] | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "VoiceSet":
        set_id = first_non_empty(payload.get("id"), payload.get("name"), DEFAULT_VOICE_SET_ID)
        voices = payload.get("voices") if isinstance(payload.get("voices"), list) else []
        return cls(
            id=set_id,
            name=first_non_empty(payload.get("name"), set_id),
            description=strip_text(payload.get("description")),
            voices=[strip_text(item) for item in voices if strip_text(item)],
        )

    def to_openai_model(self, voice_count: int) -> dict[str, Any]:
        return {
            "id": self.id,
            "object": "model",
            "owned_by": "neiroha",
            "name": self.name,
            "description": self.description,
            "voice_count": voice_count,
        }


def _handle_rmtree_error(func, path: str, exc_info) -> None:
    Path(path).chmod(0o666)
    func(path)


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        payload = tomllib.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"TOML file must contain a table: {path}")
    return payload


def _read_mapping_file(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".toml":
        return _read_toml(path)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config file must contain an object/table: {path}")
    return payload


class VoiceRegistry:
    def __init__(
        self,
        root: Path = VOICES_ROOT,
        *,
        server_config_path: Path = SERVER_CONFIG_PATH,
        model_presets_dir: Path = MODEL_PRESETS_DIR,
        voice_sets_dir: Path = VOICE_SETS_DIR,
    ) -> None:
        self.root = root
        self.server_config_path = server_config_path
        self.model_presets_dir = model_presets_dir
        self.voice_sets_dir = voice_sets_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def server_config(self) -> dict[str, Any]:
        if not self.server_config_path.exists():
            return {}
        return _read_toml(self.server_config_path)

    def save_server_config(self, config: dict[str, Any]) -> None:
        write_toml_mapping(self.server_config_path, config)

    def update_runtime_state(
        self,
        *,
        active_model_preset: str | None = None,
        active_voice_set: str | None = None,
        default_voice: str | None = None,
    ) -> None:
        config = self.server_config()
        runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
        runtime = dict(runtime)
        if active_model_preset is not None:
            runtime["active_model_preset"] = strip_text(active_model_preset) or self.active_model_preset_id()
        if active_voice_set is not None:
            runtime["active_voice_set"] = strip_text(active_voice_set) or self.active_voice_set_id()
        if default_voice is not None:
            runtime["default_voice"] = strip_text(default_voice) or self.default_voice_id()
        config["runtime"] = runtime
        self.save_server_config(config)

    def active_state(self) -> dict[str, Any]:
        runtime_config = self.server_config().get("runtime", {})
        return runtime_config if isinstance(runtime_config, dict) else {}

    def startup_config(self) -> dict[str, Any]:
        startup_config = self.server_config().get("startup", {})
        return startup_config if isinstance(startup_config, dict) else {}

    def active_model_preset_id(self) -> str:
        return (
            strip_text(self.active_state().get("active_model_preset"))
            or strip_text(self.startup_config().get("default_model_preset"))
            or DEFAULT_MODEL_PRESET_ID
        )

    def active_voice_set_id(self) -> str:
        return strip_text(self.active_state().get("active_voice_set")) or DEFAULT_VOICE_SET_ID

    def default_voice_id(self) -> str:
        return strip_text(self.active_state().get("default_voice")) or DEFAULT_VOICE_ID

    def _normalize_voice_id(self, voice_id: str) -> str:
        normalized = strip_text(voice_id).replace(" ", "_")
        if not normalized:
            raise ValueError("voice id is required.")
        if normalized in {".", ".."} or any(sep and sep in normalized for sep in ("/", "\\")):
            raise ValueError("voice id must not contain path separators.")
        if re.search(r"[\x00-\x1f<>:\"|?*]", normalized):
            raise ValueError("voice id contains characters that are invalid on Windows paths.")
        return normalized

    def _voice_dir(self, voice_id: str) -> Path:
        return (self.root / self._normalize_voice_id(voice_id)).resolve()

    def _meta_file(self, voice_id: str) -> Path:
        return self._voice_dir(voice_id) / "meta.json"

    def _voice_file(self, voice_id: str) -> Path:
        return self._voice_dir(voice_id) / "voice.toml"

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
        workspace_candidate = WORKSPACE_ROOT / candidate
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

    def list_model_presets(self) -> list[ModelPreset]:
        presets: list[ModelPreset] = []
        if self.model_presets_dir.exists():
            for path in sorted(self.model_presets_dir.glob("*.toml")):
                try:
                    presets.append(ModelPreset.from_mapping(_read_toml(path)))
                except Exception as exc:
                    LOGGER.warning("Failed to load model preset %s: %s", path, exc)
        if not presets:
            presets.append(ModelPreset(id=DEFAULT_MODEL_PRESET_ID, name="VoxCPM2 Default"))
        return presets

    def get_model_preset(self, preset_id: str = "") -> ModelPreset:
        target = strip_text(preset_id) or self.active_model_preset_id()
        for preset in self.list_model_presets():
            if target in {preset.id, preset.name}:
                return preset
        raise ValueError(f"Unknown model preset: {target}")

    def save_model_preset(self, preset: ModelPreset) -> ModelPreset:
        preset_id = strip_text(preset.id)
        if not preset_id:
            raise ValueError("model preset id is required.")
        write_toml_mapping(
            self.model_presets_dir / f"{preset_id}.toml",
            {
                "schema_version": 1,
                "id": preset_id,
                "name": strip_text(preset.name) or preset_id,
                "engine": strip_text(preset.engine) or "voxcpm2",
                "voxcpm2": {
                    "model_id": strip_text(preset.model_id) or "models/OpenBMB__VoxCPM2",
                    "device": strip_text(preset.device) or "auto",
                    "optimize": bool(preset.optimize),
                    "load_denoiser": bool(preset.load_denoiser),
                    "enable_asr": bool(preset.enable_asr),
                    "asr_model_id": strip_text(preset.asr_model_id),
                },
            },
        )
        return self.get_model_preset(preset_id)

    def list_voice_sets(self) -> list[VoiceSet]:
        voice_sets: list[VoiceSet] = []
        if self.voice_sets_dir.exists():
            seen: set[str] = set()
            for path in sorted(self.voice_sets_dir.glob("*.toml")):
                try:
                    voice_set = VoiceSet.from_mapping(_read_toml(path))
                except Exception as exc:
                    LOGGER.warning("Failed to load voice set %s: %s", path, exc)
                    continue
                if voice_set.id in seen:
                    continue
                seen.add(voice_set.id)
                voice_sets.append(voice_set)
        if not voice_sets:
            voices = []
            for meta_file in sorted(self.root.glob("*/meta.json")):
                try:
                    payload = json.loads(meta_file.read_text(encoding="utf-8"))
                    if not payload.get("deleted"):
                        voices.append(strip_text(payload.get("id")))
                except Exception:
                    continue
            voice_sets.append(
                VoiceSet(
                    id=DEFAULT_VOICE_SET_ID,
                    name="Default",
                    description="Default voices exposed as OpenAI TTS models.",
                    voices=[voice for voice in voices if voice],
                )
            )
        return voice_sets

    def normalize_voice_set_id(self, model_id: str = "") -> str:
        model_id = strip_text(model_id)
        if not model_id or model_id.lower() in LEGACY_OPENAI_MODEL_ALIASES:
            return self.active_voice_set_id()
        return model_id

    def get_voice_set(self, model_id: str = "") -> VoiceSet | None:
        target = self.normalize_voice_set_id(model_id)
        for voice_set in self.list_voice_sets():
            if target in {voice_set.id, voice_set.name}:
                return voice_set
        return None

    def has_voice_set(self, model_id: str = "") -> bool:
        return self.get_voice_set(model_id) is not None

    def save_voice_set(self, voice_set: VoiceSet) -> VoiceSet:
        voice_set_id = strip_text(voice_set.id)
        if not voice_set_id:
            raise ValueError("voice set id is required.")
        voices = [strip_text(item) for item in (voice_set.voices or []) if strip_text(item)]
        write_toml_mapping(
            self.voice_sets_dir / f"{voice_set_id}.toml",
            {
                "schema_version": 1,
                "id": voice_set_id,
                "name": strip_text(voice_set.name) or voice_set_id,
                "description": strip_text(voice_set.description),
                "voices": voices,
            },
        )
        found = self.get_voice_set(voice_set_id)
        if found is None:
            raise ValueError(f"Failed to save voice set: {voice_set_id}")
        return found

    def _profile_from_toml(self, voice_id: str, voice_set: VoiceSet) -> VoiceProfile | None:
        voice_path = self.root / voice_id / "voice.toml"
        if not voice_path.exists():
            return None
        payload = _read_toml(voice_path)
        preset_id = strip_text(payload.get("model_preset")) or self.active_model_preset_id()
        preset = self.get_model_preset(preset_id)
        mode = first_non_empty(payload.get("mode"), payload.get("mode_hint"), "design")
        reference_audio = first_non_empty(
            payload.get("reference_audio"),
            payload.get("audio_path"),
            payload.get("ref_audio_path"),
        )
        prompt_audio = first_non_empty(payload.get("prompt_audio"), payload.get("prompt_audio_path"))
        profile_id = first_non_empty(payload.get("id"), voice_id)
        return VoiceProfile(
            id=profile_id,
            display_name=first_non_empty(payload.get("name"), payload.get("display_name"), profile_id),
            engine=first_non_empty(payload.get("engine"), preset.engine, "torch_native"),
            model=voice_set.id,
            voice_set=voice_set.id,
            model_preset=preset.id,
            mode_hint=mode,
            mode=mode,
            audio_path=reference_audio or None,
            reference_audio=reference_audio or None,
            prompt_audio_path=prompt_audio or None,
            prompt_audio=prompt_audio or None,
            prompt_text=strip_text(payload.get("prompt_text")),
            instruction=strip_text(payload.get("instruction")),
            language=first_non_empty(payload.get("language"), payload.get("text_lang")),
            text_lang=strip_text(payload.get("text_lang")),
            prompt_lang=strip_text(payload.get("prompt_lang")),
            description=strip_text(payload.get("description")),
            speed=float(payload.get("speed") or 1.0),
            cfg_value=float(payload.get("cfg_value") or 2.0),
            inference_timesteps=int(payload.get("inference_timesteps") or 10),
            normalize=bool(payload.get("normalize", False)),
            denoise=bool(payload.get("denoise", False)),
            engine_options=payload.get("engine_options") if isinstance(payload.get("engine_options"), dict) else {},
        )

    def _profile_from_meta_json(self, meta_file: Path) -> VoiceProfile | None:
        payload = json.loads(meta_file.read_text(encoding="utf-8"))
        if payload.get("deleted"):
            return None
        profile = VoiceProfile(**payload)
        if not profile.voice_set:
            profile.voice_set = self.active_voice_set_id()
        if not profile.model:
            profile.model = profile.voice_set
        return profile

    def list_profiles(self, model_id: str = "") -> list[VoiceProfile]:
        profiles: list[VoiceProfile] = []
        target_set_id = self.normalize_voice_set_id(model_id) if strip_text(model_id) else ""

        if self.voice_sets_dir.exists() or any(self.root.glob("*/voice.toml")):
            for voice_set in self.list_voice_sets():
                if target_set_id and voice_set.id != target_set_id:
                    continue
                for voice_id in voice_set.voices or []:
                    try:
                        profile = self._profile_from_toml(voice_id, voice_set)
                    except Exception as exc:
                        LOGGER.warning("Failed to load voice profile %s: %s", voice_id, exc)
                        continue
                    if profile is not None:
                        profiles.append(profile)
            return profiles

        for meta_file in sorted(self.root.glob("*/meta.json")):
            try:
                profile = self._profile_from_meta_json(meta_file)
                if profile is not None:
                    profiles.append(profile)
            except Exception as exc:
                LOGGER.warning("Failed to load voice profile %s: %s", meta_file, exc)
        return profiles

    def exists(self, voice_id: str) -> bool:
        return self._voice_file(voice_id).exists() or self._meta_file(voice_id).exists()

    def get_profile(self, voice_id: str, *, model_id: str = "") -> VoiceProfile:
        target = self._normalize_voice_id(voice_id)
        for profile in self.list_profiles(model_id):
            if target in {profile.id, profile.display_name}:
                return profile
        raise FileNotFoundError(f"Voice profile not found: {voice_id}")

    def get_optional_profile(self, voice_id: str, *, model_id: str = "") -> VoiceProfile | None:
        try:
            return self.get_profile(voice_id, model_id=model_id)
        except FileNotFoundError:
            return None

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

    def _update_voice_set(self, voice_set_id: str, voice_id: str) -> None:
        voice_set = self.get_voice_set(voice_set_id) or VoiceSet(
            id=voice_set_id,
            name=voice_set_id,
            description="User voice set.",
            voices=[],
        )
        voices = list(voice_set.voices or [])
        if voice_id not in voices:
            voices.append(voice_id)
        write_toml_mapping(
            self.voice_sets_dir / f"{voice_set.id}.toml",
            {
                "schema_version": 1,
                "id": voice_set.id,
                "name": voice_set.name,
                "description": voice_set.description,
                "voices": voices,
            },
        )

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

        def text_value(names: tuple[str, ...], fallback: str = "") -> str:
            for name in names:
                if name in fields_set:
                    return strip_text(getattr(payload, name))
            return fallback

        def bool_value(name: str, fallback: bool) -> bool:
            return bool(getattr(payload, name)) if name in fields_set else fallback

        def float_value(name: str, fallback: float) -> float:
            return float(getattr(payload, name)) if name in fields_set else fallback

        def int_value(name: str, fallback: int) -> int:
            return int(getattr(payload, name)) if name in fields_set else fallback

        reference_source = existing.audio_path if existing else None
        if field_provided("audio_path", "reference_audio", "reference_audio_path"):
            reference_source = first_non_empty(payload.audio_path, payload.reference_audio, payload.reference_audio_path) or None

        prompt_source = existing.prompt_audio_path if existing else None
        if field_provided("prompt_audio", "prompt_audio_path"):
            prompt_source = first_non_empty(payload.prompt_audio, payload.prompt_audio_path) or None

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
        voice_set_id = text_value(("voice_set", "model"), existing.voice_set if existing else default_model) or default_model
        mode = text_value(("mode", "mode_hint"), existing.mode_hint if existing else "design") or "design"
        model_preset = text_value(
            ("model_preset",),
            existing.model_preset if existing else self.active_model_preset_id(),
        ) or self.active_model_preset_id()
        display_name = text_value(
            ("display_name", "name"),
            existing.display_name if existing else voice_id,
        ) or voice_id

        profile = VoiceProfile(
            id=voice_id,
            display_name=display_name,
            engine=text_value(("engine",), existing.engine if existing else "torch_native") or "torch_native",
            model=voice_set_id,
            voice_set=voice_set_id,
            model_preset=model_preset,
            mode_hint=mode,
            mode=mode,
            audio_path=reference_audio_path,
            reference_audio=reference_audio_path,
            prompt_audio_path=prompt_audio_path,
            prompt_audio=prompt_audio_path,
            prompt_text=text_value(("prompt_text",), existing.prompt_text if existing else ""),
            instruction=text_value(("instruction",), existing.instruction if existing else ""),
            language=text_value(("language",), existing.language if existing else ""),
            text_lang=text_value(("text_lang",), existing.text_lang if existing else ""),
            prompt_lang=text_value(("prompt_lang",), existing.prompt_lang if existing else ""),
            description=text_value(("description",), existing.description if existing else ""),
            speed=float_value("speed", existing.speed if existing else 1.0),
            cfg_value=float_value("cfg_value", existing.cfg_value if existing else 2.0),
            inference_timesteps=int_value("inference_timesteps", existing.inference_timesteps if existing else 10),
            normalize=bool_value("normalize", existing.normalize if existing else False),
            denoise=bool_value("denoise", existing.denoise if existing else False),
            engine_options=payload.engine_options if "engine_options" in fields_set else (existing.engine_options if existing else {}),
            sample_rate=sample_rate,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )

        write_toml_mapping(
            voice_dir / "voice.toml",
            {
                "schema_version": 1,
                "id": profile.id,
                "name": profile.display_name,
                "description": profile.description,
                "mode": profile.mode_hint or profile.mode,
                "model_preset": profile.model_preset,
                "reference_audio": profile.reference_audio or "",
                "prompt_audio": profile.prompt_audio or "",
                "prompt_text": profile.prompt_text,
                "text_lang": profile.text_lang,
                "prompt_lang": profile.prompt_lang,
                "instruction": profile.instruction,
                "language": profile.language,
                "speed": profile.speed,
                "cfg_value": profile.cfg_value,
                "inference_timesteps": profile.inference_timesteps,
                "normalize": profile.normalize,
                "denoise": profile.denoise,
                "engine_options": profile.engine_options,
            },
        )
        self._update_voice_set(voice_set_id, voice_id)
        return profile, created

    def delete_profile(self, voice_id: str) -> None:
        voice_dir = self._voice_dir(voice_id)
        self._ensure_voice_dir_is_safe(voice_dir)
        if not voice_dir.exists():
            raise FileNotFoundError(f"Voice profile not found: {voice_id}")
        try:
            shutil.rmtree(voice_dir, onerror=_handle_rmtree_error)
        except OSError as exc:
            LOGGER.debug("Voice profile directory could not be fully removed yet: %s", exc)
