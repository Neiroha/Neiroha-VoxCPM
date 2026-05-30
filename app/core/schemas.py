from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class APIBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


@dataclass
class PreparedSynthesisRequest:
    text_input: str
    mode: str
    control_instruction: str
    reference_audio_path: Optional[str]
    prompt_audio_path: Optional[str]
    prompt_text: str
    response_format: str
    cfg_value: float
    inference_timesteps: int
    normalize: bool
    denoise: bool
    speed: float
    voice_name: str = ""


class OpenAITTSSpeechRequest(APIBaseModel):
    model: Optional[str] = Field(
        default=None,
        description="Optional model id. Accepts the local model path, voxcpm-openai-tts, voxcpm2, or openbmb/VoxCPM2.",
    )
    input: Optional[str] = Field(default=None, description="Text to synthesize.")
    text: Optional[str] = Field(default=None, description="Alias of input.")
    voice: str | dict[str, Any] | None = Field(
        default="default",
        description="Voice registry id or compatibility voice object.",
    )
    speed: float = Field(default=1.0, description="Compatibility field. Currently informational only.")
    response_format: str = Field(default="wav", description="Only `wav` is currently supported.")
    format: str = Field(default="", description="Alias of response_format.")
    mode: str | None = Field(
        default=None,
        description="Optional mode override: design, clone, ultimate_clone, preset_voice, reference, reference_with_text.",
    )
    instruction: str = Field(default="", description="Optional style instruction.")
    instructions: str = Field(default="", description="Alias of instruction.")
    control: str = Field(default="", description="Alias of instruction.")
    instruct_text: str = Field(default="", description="Alias of instruction.")
    ref_audio: Optional[str] = Field(
        default=None,
        description="vLLM-Omni-compatible alias of reference_audio. Accepts local path, file:// URI, http(s) URL, or data URI.",
    )
    reference_audio: Optional[str] = Field(default=None, description="Local reference audio path or file:// URI.")
    reference_audio_path: Optional[str] = Field(default=None, description="Alias of reference_audio.")
    reference_wav_path: Optional[str] = Field(default=None, description="Alias of reference_audio.")
    prompt_audio: Optional[str] = Field(default=None, description="Local prompt audio path or file:// URI.")
    prompt_audio_path: Optional[str] = Field(default=None, description="Alias of prompt_audio.")
    prompt_wav_path: Optional[str] = Field(default=None, description="Alias of prompt_audio.")
    prompt_text: str = Field(default="", description="Transcript that matches prompt_audio.")
    ref_text: str = Field(default="", description="Compatibility alias of prompt_text.")
    reference_text: str = Field(default="", description="Alias of prompt_text.")
    transcript: str = Field(default="", description="Alias of prompt_text.")
    language: str = Field(default="", description="Optional compatibility field.")
    auto_asr: bool = Field(
        default=False,
        description="If true and prompt_text is empty, attempt ASR on the prompt/reference audio.",
    )
    cfg_value: float = Field(default=2.0)
    inference_timesteps: int = Field(default=10)
    normalize: bool = Field(default=False)
    denoise: bool = Field(default=False)


class NativeSpeechRequest(APIBaseModel):
    model: Optional[str] = Field(
        default=None,
        description="Optional model id. Accepts the local model path, voxcpm-openai-tts, voxcpm2, or openbmb/VoxCPM2.",
    )
    text: Optional[str] = Field(default=None, description="Text to synthesize.")
    input: Optional[str] = Field(default=None, description="Alias of text.")
    mode: str | None = Field(
        default=None,
        description="design | clone | ultimate_clone | preset_voice | reference | reference_with_text",
    )
    voice_id: str | None = Field(default=None, description="Registered local voice profile id.")
    profile: str | None = Field(default=None, description="Alias of voice_id.")
    character_name: str | None = Field(default=None, description="Alias of voice_id.")
    speaker: str | None = Field(default=None, description="Alias of voice_id.")
    voice: str | dict[str, Any] | None = Field(default=None, description="Alias of voice_id.")
    instruction: str = Field(default="", description="Optional style instruction.")
    instructions: str = Field(default="", description="Alias of instruction.")
    control: str = Field(default="", description="Alias of instruction.")
    instruct_text: str = Field(default="", description="Alias of instruction.")
    ref_audio: Optional[str] = Field(
        default=None,
        description="Compatibility alias of reference_audio. Accepts local path, file:// URI, http(s) URL, or data URI.",
    )
    reference_audio: Optional[str] = Field(default=None, description="Local reference audio path or file:// URI.")
    reference_audio_path: Optional[str] = Field(default=None, description="Alias of reference_audio.")
    reference_wav_path: Optional[str] = Field(default=None, description="Alias of reference_audio.")
    prompt_audio: Optional[str] = Field(default=None, description="Local prompt audio path or file:// URI.")
    prompt_audio_path: Optional[str] = Field(default=None, description="Alias of prompt_audio.")
    prompt_wav_path: Optional[str] = Field(default=None, description="Alias of prompt_audio.")
    prompt_text: str = Field(default="", description="Transcript that matches prompt_audio.")
    ref_text: str = Field(default="", description="Compatibility alias of prompt_text.")
    reference_text: str = Field(default="", description="Alias of prompt_text.")
    transcript: str = Field(default="", description="Alias of prompt_text.")
    language: str = Field(default="", description="Optional compatibility field.")
    auto_asr: bool = Field(
        default=False,
        description="If true and prompt_text is empty, attempt ASR on the prompt/reference audio.",
    )
    speed: float = Field(default=1.0, description="Compatibility field, currently informational only.")
    response_format: str = Field(default="wav", description="Only `wav` is currently supported.")
    format: str = Field(default="", description="Alias of response_format.")
    cfg_value: float = Field(default=2.0)
    inference_timesteps: int = Field(default=10)
    normalize: bool = Field(default=False)
    denoise: bool = Field(default=False)


class VoiceProfileCreateRequest(APIBaseModel):
    id: str = Field(description="Unique local voice id.")
    name: str | None = Field(default=None, description="Alias of display_name.")
    display_name: str | None = Field(default=None, description="Human-readable voice name.")
    engine: str = Field(default="torch_native", description="Engine hint for future multi-engine support.")
    model: str | None = Field(default=None, description="Model hint for this voice profile.")
    voice_set: str | None = Field(default=None, description="Voice set id exposed as OpenAI model.")
    model_preset: str | None = Field(default=None, description="Underlying VoxCPM model preset id.")
    mode: str | None = Field(default=None, description="Suggested mode, such as design, clone, or ultimate_clone.")
    mode_hint: str | None = Field(default=None, description="Suggested mode, such as preset_voice or reference_with_text.")
    audio_path: str | None = Field(default=None, description="Reference audio path or file:// URI.")
    reference_audio: str | None = Field(default=None, description="Alias of audio_path.")
    reference_audio_path: str | None = Field(default=None, description="Alias of audio_path.")
    prompt_audio: str | None = Field(default=None, description="Alias of prompt_audio_path.")
    prompt_audio_path: str | None = Field(default=None, description="Prompt audio path or file:// URI.")
    prompt_text: str = Field(default="", description="Transcript that matches the prompt audio.")
    instruction: str = Field(default="", description="Default style instruction for this voice.")
    language: str = Field(default="", description="Optional language hint.")
    text_lang: str = Field(default="", description="Text language hint.")
    prompt_lang: str = Field(default="", description="Prompt language hint.")
    description: str = Field(default="", description="Human-readable profile description.")
    speed: float = Field(default=1.0)
    cfg_value: float = Field(default=2.0)
    inference_timesteps: int = Field(default=10)
    normalize: bool = Field(default=False)
    denoise: bool = Field(default=False)
    engine_options: dict[str, Any] = Field(default_factory=dict)
    sample_rate: int | None = Field(default=None, description="Optional sample rate override.")
    copy_audio_to_registry: bool = Field(
        default=False,
        description="Copy referenced audio files into runtime/voices/<id>/ before saving the profile.",
    )


class VoiceProfile(APIBaseModel):
    id: str
    display_name: str
    engine: str = "torch_native"
    model: str = "default"
    voice_set: str = "default"
    model_preset: str = "voxcpm2-default"
    mode_hint: str | None = None
    mode: str = ""
    audio_path: str | None = None
    reference_audio: str | None = None
    prompt_audio_path: str | None = None
    prompt_audio: str | None = None
    prompt_text: str = ""
    instruction: str = ""
    language: str = ""
    text_lang: str = ""
    prompt_lang: str = ""
    description: str = ""
    speed: float = 1.0
    cfg_value: float = 2.0
    inference_timesteps: int = 10
    normalize: bool = False
    denoise: bool = False
    engine_options: dict[str, Any] = Field(default_factory=dict)
    sample_rate: int | None = None
    created_at: str = ""
    updated_at: str = ""
