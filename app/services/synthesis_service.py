from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.config import LOCAL_ASR_MODEL_DIR
from app.core.registry import VoiceRegistry
from app.core.schemas import NativeSpeechRequest, OpenAITTSSpeechRequest, PreparedSynthesisRequest
from app.core.utils import extract_voice_name, first_non_empty, require_existing_file, strip_text

LOGGER = logging.getLogger("voxcpm.launcher")
OPENAI_COMPAT_MODEL_ID = "voxcpm-openai-tts"

MODE_ALIASES = {
    "design": "design",
    "voice_design": "design",
    "voice-design": "design",
    "tts": "design",
    "clone": "clone",
    "reference": "clone",
    "reference_only": "clone",
    "reference-only": "clone",
    "controllable_clone": "clone",
    "controllable-clone": "clone",
    "controllable_cloning": "clone",
    "preset_voice": "clone",
    "preset-voice": "clone",
    "cross_lingual": "clone",
    "cross-lingual": "clone",
    "instruction": "clone",
    "ultimate_clone": "ultimate_clone",
    "ultimate-clone": "ultimate_clone",
    "continuation": "ultimate_clone",
    "reference_with_text": "ultimate_clone",
    "reference-with-text": "ultimate_clone",
    "prompt_clone": "ultimate_clone",
    "prompt-clone": "ultimate_clone",
    "clone_with_prompt": "ultimate_clone",
    "clone-with-prompt": "ultimate_clone",
}


class VoxCPMRuntime:
    def __init__(
        self,
        *,
        model_id: str,
        device: str = "auto",
        optimize: bool = True,
        load_denoiser: bool = False,
        enable_asr: bool = False,
        asr_model_id: Optional[str] = None,
    ) -> None:
        self.model_id = model_id
        self.requested_device = device
        self.optimize = optimize
        self.load_denoiser = load_denoiser
        self.asr_enabled = enable_asr
        self._runtime_device: Optional[str] = None
        self.voxcpm_model = None
        self.asr_model = None
        self.asr_model_source = asr_model_id or self._default_asr_source()

    @staticmethod
    def _resolve_runtime_device(device: str) -> str:
        if device and device != "auto":
            return device

        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"

    @property
    def runtime_device(self) -> str:
        if self._runtime_device is None:
            self._runtime_device = self._resolve_runtime_device(self.requested_device)
        return self._runtime_device

    @property
    def status_device(self) -> str:
        if self._runtime_device is not None:
            return self._runtime_device
        requested = strip_text(self.requested_device)
        return requested or "auto"

    @staticmethod
    def _default_asr_source() -> str:
        if (LOCAL_ASR_MODEL_DIR / "model.pt").exists():
            return str(LOCAL_ASR_MODEL_DIR)
        return "iic/SenseVoiceSmall"

    def get_or_load_voxcpm(self):
        import voxcpm

        if self.voxcpm_model is not None:
            return self.voxcpm_model

        LOGGER.info(
            "Loading VoxCPM model '%s' with device=%s optimize=%s load_denoiser=%s",
            self.model_id,
            self.requested_device,
            self.optimize,
            self.load_denoiser,
        )
        self.voxcpm_model = voxcpm.VoxCPM.from_pretrained(
            hf_model_id=self.model_id,
            load_denoiser=self.load_denoiser,
            optimize=self.optimize,
            device=self.requested_device,
        )
        return self.voxcpm_model

    def get_or_load_asr(self):
        if not self.asr_enabled:
            raise RuntimeError(
                "ASR is disabled. Provide prompt_text manually, or restart the launcher with --enable-asr."
            )

        if self.asr_model is not None:
            return self.asr_model

        from funasr import AutoModel

        resolved_device = self.runtime_device
        LOGGER.info("Loading ASR model '%s' on %s", self.asr_model_source, resolved_device)
        self.asr_model = AutoModel(
            model=self.asr_model_source,
            disable_update=True,
            log_level="DEBUG",
            device=resolved_device if resolved_device.startswith("cuda") else "cpu",
        )
        return self.asr_model

    def transcribe_audio(self, audio_path: str) -> str:
        if not audio_path:
            raise ValueError("audio_path is required for ASR transcription.")

        asr_model = self.get_or_load_asr()
        result = asr_model.generate(input=audio_path, language="auto", use_itn=True)
        return result[0]["text"].split("|>")[-1]

    def prompt_wav_recognition(self, prompt_wav: Optional[str]) -> str:
        if prompt_wav is None:
            return ""
        if not self.asr_enabled:
            LOGGER.info("ASR is disabled; returning an empty transcript so prompt_text can be typed manually.")
            return ""
        return self.transcribe_audio(prompt_wav)

    def _normalize_mode_name(
        self,
        *,
        mode: Optional[str],
        reference_audio: Optional[str],
        prompt_audio: Optional[str],
        prompt_text: str,
    ) -> str:
        mode_name = strip_text(mode).lower().replace(" ", "_")
        normalized = MODE_ALIASES.get(mode_name) if mode_name else None

        if normalized is None:
            if prompt_text:
                return "ultimate_clone"
            if reference_audio or prompt_audio:
                return "clone"
            return "design"

        if normalized == "clone" and prompt_text:
            return "ultimate_clone"
        return normalized

    def prepare_synthesis_request(
        self,
        *,
        text_input: str,
        mode: Optional[str] = None,
        control_instruction: str = "",
        reference_wav_path_input: Optional[str] = None,
        prompt_wav_path_input: Optional[str] = None,
        prompt_text: str = "",
        auto_asr: bool = False,
        response_format: str = "wav",
        cfg_value_input: float = 2.0,
        do_normalize: bool = False,
        denoise: bool = False,
        inference_timesteps: int = 10,
        speed: float = 1.0,
        voice_name: str = "",
    ) -> PreparedSynthesisRequest:
        text = strip_text(text_input)
        if not text:
            raise ValueError("Please input text to synthesize.")

        control = strip_text(control_instruction)
        reference_audio = require_existing_file(
            strip_text(reference_wav_path_input) or None,
            field_name="reference_audio",
        )
        prompt_audio = require_existing_file(
            strip_text(prompt_wav_path_input) or None,
            field_name="prompt_audio",
        )
        prompt_text_clean = strip_text(prompt_text)
        response_format_clean = strip_text(response_format or "wav").lower() or "wav"

        normalized_mode = self._normalize_mode_name(
            mode=mode,
            reference_audio=reference_audio,
            prompt_audio=prompt_audio,
            prompt_text=prompt_text_clean,
        )

        if prompt_text_clean and control:
            raise ValueError(
                "Ultimate clone does not support control/instruction. Provide prompt_text manually and leave control empty."
            )

        if normalized_mode == "design":
            if reference_audio or prompt_audio or prompt_text_clean:
                raise ValueError("Design mode does not accept reference audio or prompt_text.")

        elif normalized_mode == "clone":
            if not reference_audio and prompt_audio:
                reference_audio = prompt_audio
            prompt_audio = None
            prompt_text_clean = ""
            if not reference_audio:
                raise ValueError("Clone mode requires reference_audio or prompt_audio.")

        elif normalized_mode == "ultimate_clone":
            primary_audio = prompt_audio or reference_audio
            if not primary_audio:
                raise ValueError("Ultimate clone requires prompt_audio or reference_audio.")
            if not prompt_audio:
                prompt_audio = primary_audio
            if not reference_audio:
                reference_audio = primary_audio
            if not prompt_text_clean:
                if auto_asr:
                    prompt_text_clean = self.transcribe_audio(prompt_audio)
                else:
                    raise ValueError(
                        "Ultimate clone requires prompt_text by default. Set auto_asr=true and start the launcher with --enable-asr if you want automatic transcription."
                    )

        else:
            raise ValueError(f"Unsupported mode: {normalized_mode}")

        return PreparedSynthesisRequest(
            text_input=text,
            mode=normalized_mode,
            control_instruction=control,
            reference_audio_path=reference_audio,
            prompt_audio_path=prompt_audio,
            prompt_text=prompt_text_clean,
            response_format=response_format_clean,
            cfg_value=float(cfg_value_input),
            inference_timesteps=int(inference_timesteps),
            normalize=bool(do_normalize),
            denoise=bool(denoise),
            speed=float(speed),
            voice_name=voice_name,
        )

    def generate_tts_audio(
        self,
        *,
        text_input: str,
        control_instruction: str = "",
        reference_wav_path_input: Optional[str] = None,
        prompt_wav_path_input: Optional[str] = None,
        prompt_text: str = "",
        cfg_value_input: float = 2.0,
        do_normalize: bool = False,
        denoise: bool = False,
        inference_timesteps: int = 10,
    ) -> tuple[int, Any]:
        request = self.prepare_synthesis_request(
            text_input=text_input,
            control_instruction=control_instruction,
            reference_wav_path_input=reference_wav_path_input,
            prompt_wav_path_input=prompt_wav_path_input,
            prompt_text=prompt_text,
            cfg_value_input=cfg_value_input,
            do_normalize=do_normalize,
            denoise=denoise,
            inference_timesteps=inference_timesteps,
        )
        return self.synthesize(request)

    def synthesize(self, request: PreparedSynthesisRequest) -> tuple[int, Any]:
        current_model = self.get_or_load_voxcpm()

        final_text = (
            f"({request.control_instruction}){request.text_input}"
            if request.control_instruction
            else request.text_input
        )

        generate_kwargs = {
            "text": final_text,
            "reference_wav_path": request.reference_audio_path,
            "cfg_value": request.cfg_value,
            "inference_timesteps": request.inference_timesteps,
            "normalize": request.normalize,
            "denoise": request.denoise,
        }

        if request.prompt_audio_path and request.prompt_text:
            generate_kwargs["prompt_wav_path"] = request.prompt_audio_path
            generate_kwargs["prompt_text"] = request.prompt_text

        LOGGER.info(
            "Synthesizing mode=%s voice=%s ref=%s prompt=%s prompt_text=%s text_len=%s",
            request.mode,
            request.voice_name or "default",
            bool(request.reference_audio_path),
            bool(request.prompt_audio_path),
            bool(request.prompt_text),
            len(request.text_input),
        )
        wav = current_model.generate(**generate_kwargs)
        return current_model.tts_model.sample_rate, wav


def _apply_registered_voice(
    *,
    voice_name: str,
    registry: VoiceRegistry,
    mode: Optional[str],
    control_instruction: str,
    reference_wav_path_input: Optional[str],
    prompt_wav_path_input: Optional[str],
    prompt_text: str,
) -> dict[str, Any]:
    normalized_voice = strip_text(voice_name)
    resolved_mode = strip_text(mode).lower().replace(" ", "_")
    if not normalized_voice or normalized_voice == "default":
        return {
            "mode": mode,
            "control_instruction": control_instruction,
            "reference_wav_path_input": reference_wav_path_input,
            "prompt_wav_path_input": prompt_wav_path_input,
            "prompt_text": prompt_text,
            "voice_name": normalized_voice,
        }

    profile = registry.get_optional_profile(normalized_voice)
    if profile is None:
        if resolved_mode in {"preset_voice", "preset-voice"}:
            raise ValueError(f"voice_id '{normalized_voice}' is not registered.")
        return {
            "mode": mode,
            "control_instruction": control_instruction,
            "reference_wav_path_input": reference_wav_path_input,
            "prompt_wav_path_input": prompt_wav_path_input,
            "prompt_text": prompt_text,
            "voice_name": normalized_voice,
        }

    return {
        "mode": first_non_empty(mode, profile.mode_hint),
        "control_instruction": first_non_empty(control_instruction, profile.instruction),
        "reference_wav_path_input": first_non_empty(reference_wav_path_input, registry.resolve_audio_path(profile.audio_path)),
        "prompt_wav_path_input": first_non_empty(
            prompt_wav_path_input,
            registry.resolve_audio_path(profile.prompt_audio_path),
        ),
        "prompt_text": first_non_empty(prompt_text, profile.prompt_text),
        "voice_name": profile.id,
    }


def build_openai_request(
    payload: OpenAITTSSpeechRequest,
    runtime: VoxCPMRuntime,
    registry: VoiceRegistry,
) -> PreparedSynthesisRequest:
    voice_name = extract_voice_name(payload.voice)
    voice_inputs = _apply_registered_voice(
        voice_name=voice_name,
        registry=registry,
        mode=payload.mode,
        control_instruction=first_non_empty(payload.instructions, payload.instruction, payload.control, payload.instruct_text),
        reference_wav_path_input=first_non_empty(
            payload.reference_audio,
            payload.reference_audio_path,
            payload.reference_wav_path,
        ),
        prompt_wav_path_input=first_non_empty(
            payload.prompt_audio,
            payload.prompt_audio_path,
            payload.prompt_wav_path,
        ),
        prompt_text=first_non_empty(payload.prompt_text, payload.reference_text, payload.transcript),
    )

    return runtime.prepare_synthesis_request(
        text_input=first_non_empty(payload.input, payload.text),
        mode=voice_inputs["mode"],
        control_instruction=voice_inputs["control_instruction"],
        reference_wav_path_input=voice_inputs["reference_wav_path_input"],
        prompt_wav_path_input=voice_inputs["prompt_wav_path_input"],
        prompt_text=voice_inputs["prompt_text"],
        auto_asr=payload.auto_asr,
        response_format=first_non_empty(payload.response_format, payload.format, "wav"),
        cfg_value_input=payload.cfg_value,
        do_normalize=payload.normalize,
        denoise=payload.denoise,
        inference_timesteps=payload.inference_timesteps,
        speed=payload.speed,
        voice_name=voice_inputs["voice_name"],
    )


def build_native_request(
    payload: NativeSpeechRequest,
    runtime: VoxCPMRuntime,
    registry: VoiceRegistry,
) -> PreparedSynthesisRequest:
    voice_name = first_non_empty(
        payload.voice_id,
        payload.profile,
        payload.character_name,
        payload.speaker,
        extract_voice_name(payload.voice),
    )
    voice_inputs = _apply_registered_voice(
        voice_name=voice_name,
        registry=registry,
        mode=payload.mode,
        control_instruction=first_non_empty(payload.instructions, payload.instruction, payload.control, payload.instruct_text),
        reference_wav_path_input=first_non_empty(
            payload.reference_audio,
            payload.reference_audio_path,
            payload.reference_wav_path,
        ),
        prompt_wav_path_input=first_non_empty(
            payload.prompt_audio,
            payload.prompt_audio_path,
            payload.prompt_wav_path,
        ),
        prompt_text=first_non_empty(payload.prompt_text, payload.reference_text, payload.transcript),
    )

    return runtime.prepare_synthesis_request(
        text_input=first_non_empty(payload.text, payload.input),
        mode=voice_inputs["mode"],
        control_instruction=voice_inputs["control_instruction"],
        reference_wav_path_input=voice_inputs["reference_wav_path_input"],
        prompt_wav_path_input=voice_inputs["prompt_wav_path_input"],
        prompt_text=voice_inputs["prompt_text"],
        auto_asr=payload.auto_asr,
        response_format=first_non_empty(payload.response_format, payload.format, "wav"),
        cfg_value_input=payload.cfg_value,
        do_normalize=payload.normalize,
        denoise=payload.denoise,
        inference_timesteps=payload.inference_timesteps,
        speed=payload.speed,
        voice_name=voice_inputs["voice_name"],
    )


def build_voxcpm_meta(runtime: VoxCPMRuntime, registry: VoiceRegistry) -> dict[str, Any]:
    registered_voices = registry.list_profiles()
    return {
        "provider": "voxcpm",
        "model": runtime.model_id,
        "openai_model_alias": OPENAI_COMPAT_MODEL_ID,
        "asr_enabled": runtime.asr_enabled,
        "asr_model_source": runtime.asr_model_source,
        "supported_modes": [
            {
                "name": "design",
                "aliases": ["voice_design", "tts"],
                "required_fields": ["text"],
                "description": "Pure TTS or voice design without reference audio.",
            },
            {
                "name": "clone",
                "aliases": ["reference", "controllable_clone", "preset_voice", "cross_lingual", "instruction"],
                "required_fields": ["text", "reference_audio|voice_id"],
                "description": "Reference-audio cloning, voice-profile cloning, or instruction cloning.",
            },
            {
                "name": "ultimate_clone",
                "aliases": ["reference_with_text", "clone_with_prompt"],
                "required_fields": ["text", "prompt_text", "prompt_audio|reference_audio|voice_id"],
                "description": "Prompt-text-guided continuation cloning. A single audio path can be reused as both reference and prompt.",
            },
        ],
        "paths": {
            "health": "/health",
            "openai_models": "/v1/models",
            "openai_voices": "/v1/audio/voices",
            "openai_speech": "/v1/audio/speech",
            "native_json": "/voxcpm/speech",
            "native_upload": "/voxcpm/speech/upload",
            "voice_registry": "/voxcpm/voices",
            "meta": "/voxcpm/meta",
        },
        "voice_registry": {
            "root": "runtime/voices",
            "count": len(registered_voices),
            "ids": [profile.id for profile in registered_voices],
        },
    }
