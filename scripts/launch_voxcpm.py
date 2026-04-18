from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator, Optional

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
MODELS_ROOT = WORKSPACE_ROOT / "models"
RUNTIME_ROOT = WORKSPACE_ROOT / "runtime"
LOCAL_TEMP_DIR = RUNTIME_ROOT / "temp"
UPLOAD_TEMP_DIR = LOCAL_TEMP_DIR / "uploads"
MODELSCOPE_CACHE_ROOT = MODELS_ROOT / "_modelscope_cache"
LOCAL_ASR_MODEL_DIR = MODELS_ROOT / "iic__SenseVoiceSmall"

LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
MODELSCOPE_CACHE_ROOT.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("TMPDIR", str(LOCAL_TEMP_DIR))
os.environ.setdefault("TEMP", str(LOCAL_TEMP_DIR))
os.environ.setdefault("TMP", str(LOCAL_TEMP_DIR))
os.environ.setdefault("GRADIO_TEMP_DIR", str(LOCAL_TEMP_DIR / "gradio"))
os.environ.setdefault("MODELSCOPE_CACHE", str(MODELSCOPE_CACHE_ROOT))
os.environ.setdefault("MODELSCOPE_MODULES_CACHE", str(MODELSCOPE_CACHE_ROOT / "modules"))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import gradio as gr
import soundfile as sf
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

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


def require_existing_file(path: Optional[str], *, field_name: str) -> Optional[str]:
    if path is None:
        return None
    candidate = Path(path).expanduser()
    if not candidate.exists():
        raise FileNotFoundError(f"{field_name} does not exist: {candidate}")
    if not candidate.is_file():
        raise FileNotFoundError(f"{field_name} is not a file: {candidate}")
    return str(candidate.resolve())


def json_response(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status_code)


def openai_error(
    message: str,
    *,
    status_code: int = 400,
    error_type: str = "invalid_request_error",
) -> JSONResponse:
    return json_response(
        {
            "error": {
                "message": message,
                "type": error_type,
            }
        },
        status_code=status_code,
    )


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


class OpenAITTSSpeechRequest(BaseModel):
    model: Optional[str] = Field(
        default=None,
        description="Optional model id. Accepts the local model path or voxcpm-openai-tts.",
    )
    input: Optional[str] = Field(default=None, description="Text to synthesize.")
    text: Optional[str] = Field(default=None, description="Alias of input.")
    voice: str | dict[str, Any] | None = Field(
        default="default",
        description="Reserved for a future local voice registry. Currently accepted for compatibility.",
    )
    speed: float = Field(
        default=1.0,
        description="Compatibility field. VoxCPM does not currently expose an explicit speed control here.",
    )
    response_format: str = Field(default="wav", description="Only `wav` is currently supported.")
    format: str = Field(default="", description="Alias of response_format.")
    mode: str | None = Field(default=None, description="Optional mode override: design, clone, ultimate_clone.")
    instruction: str = Field(default="", description="Optional style instruction.")
    instructions: str = Field(default="", description="Alias of instruction.")
    control: str = Field(default="", description="Alias of instruction.")
    instruct_text: str = Field(default="", description="Alias of instruction.")
    reference_audio: Optional[str] = Field(default=None, description="Local reference audio path.")
    reference_audio_path: Optional[str] = Field(default=None, description="Alias of reference_audio.")
    reference_wav_path: Optional[str] = Field(default=None, description="Alias of reference_audio.")
    prompt_audio: Optional[str] = Field(default=None, description="Local prompt audio path for ultimate clone.")
    prompt_audio_path: Optional[str] = Field(default=None, description="Alias of prompt_audio.")
    prompt_wav_path: Optional[str] = Field(default=None, description="Alias of prompt_audio.")
    prompt_text: str = Field(default="", description="Transcript that matches prompt_audio.")
    reference_text: str = Field(default="", description="Alias of prompt_text.")
    transcript: str = Field(default="", description="Alias of prompt_text.")
    auto_asr: bool = Field(
        default=False,
        description="If true and prompt_text is empty, attempt ASR on the prompt/reference audio. Server ASR is disabled by default.",
    )
    cfg_value: float = Field(default=2.0)
    inference_timesteps: int = Field(default=10)
    normalize: bool = Field(default=False)
    denoise: bool = Field(default=False)


class NativeSpeechRequest(BaseModel):
    model: Optional[str] = Field(
        default=None,
        description="Optional model id. Accepts the local model path or voxcpm-openai-tts.",
    )
    text: Optional[str] = Field(default=None, description="Text to synthesize.")
    input: Optional[str] = Field(default=None, description="Alias of text.")
    mode: str | None = Field(default=None, description="design | clone | ultimate_clone")
    profile: str | None = Field(default=None, description="Compatibility field for a future local preset registry.")
    character_name: str | None = Field(default=None, description="Alias of profile.")
    speaker: str | None = Field(default=None, description="Alias of profile.")
    voice: str | dict[str, Any] | None = Field(default=None, description="Alias of profile.")
    instruction: str = Field(default="", description="Optional style instruction.")
    instructions: str = Field(default="", description="Alias of instruction.")
    control: str = Field(default="", description="Alias of instruction.")
    instruct_text: str = Field(default="", description="Alias of instruction.")
    reference_audio: Optional[str] = Field(default=None, description="Local reference audio path.")
    reference_audio_path: Optional[str] = Field(default=None, description="Alias of reference_audio.")
    reference_wav_path: Optional[str] = Field(default=None, description="Alias of reference_audio.")
    prompt_audio: Optional[str] = Field(default=None, description="Local prompt audio path.")
    prompt_audio_path: Optional[str] = Field(default=None, description="Alias of prompt_audio.")
    prompt_wav_path: Optional[str] = Field(default=None, description="Alias of prompt_audio.")
    prompt_text: str = Field(default="", description="Transcript that matches prompt_audio.")
    reference_text: str = Field(default="", description="Alias of prompt_text.")
    transcript: str = Field(default="", description="Alias of prompt_text.")
    auto_asr: bool = Field(
        default=False,
        description="If true and prompt_text is empty, attempt ASR on the prompt/reference audio. Server ASR is disabled by default.",
    )
    speed: float = Field(default=1.0, description="Compatibility field, currently informational only.")
    response_format: str = Field(default="wav", description="Only `wav` is currently supported.")
    format: str = Field(default="", description="Alias of response_format.")
    cfg_value: float = Field(default=2.0)
    inference_timesteps: int = Field(default=10)
    normalize: bool = Field(default=False)
    denoise: bool = Field(default=False)


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
            raise ValueError("Ultimate clone does not support control/instruction. Provide prompt_text manually and leave control empty.")

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch VoxCPM with Gradio WebUI, REST API, or both from the outer pixi workspace.",
    )
    parser.add_argument(
        "--mode",
        choices=["webui", "api", "combined"],
        default="combined",
        help="Run Gradio only, REST API only, or a combined server.",
    )
    parser.add_argument(
        "--repo-dir",
        type=Path,
        default=WORKSPACE_ROOT / "VoxCPM",
        help="Path to the cloned official VoxCPM repository.",
    )
    parser.add_argument(
        "--model-id",
        type=str,
        default="openbmb/VoxCPM2",
        help="Local model path or Hugging Face repo id served by this launcher.",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Server host to bind.")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Server port. Defaults to 7860 for webui/combined and 8000 for api.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="Runtime device: auto, cpu, cuda, or cuda:N.",
    )
    parser.add_argument("--no-optimize", action="store_true", help="Disable model optimization during load.")
    parser.add_argument(
        "--load-denoiser",
        action="store_true",
        help="Load ZipEnhancer during model init so denoise requests can be executed.",
    )
    parser.add_argument(
        "--enable-asr",
        action="store_true",
        help="Enable optional ASR for ultimate clone. Default is disabled so prompt_text must be typed manually.",
    )
    parser.add_argument(
        "--asr-model-id",
        type=str,
        default=None,
        help="Optional local ASR model path or remote model id. Defaults to models/iic__SenseVoiceSmall if present.",
    )
    parser.add_argument(
        "--preload-model",
        action="store_true",
        help="Load the TTS model at startup instead of on first request.",
    )
    parser.add_argument("--queue-size", type=int, default=10, help="Gradio queue max size.")
    parser.add_argument(
        "--gradio-path",
        type=str,
        default="/",
        help="Mount path for Gradio when --mode combined is used.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Uvicorn logging level for API/combined mode.",
    )
    return parser.parse_args()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def resolve_port(args: argparse.Namespace) -> int:
    if args.port is not None:
        return args.port
    return 8000 if args.mode == "api" else 7860


def validate_args(args: argparse.Namespace) -> None:
    if not args.repo_dir.exists():
        raise FileNotFoundError(f"VoxCPM repo directory does not exist: {args.repo_dir}")
    if args.mode != "api" and not (args.repo_dir / "app.py").exists():
        raise FileNotFoundError(f"Cannot find official app.py under: {args.repo_dir}")
    if args.mode == "combined" and not args.gradio_path.startswith("/"):
        raise ValueError("--gradio-path must start with '/'.")


def load_official_app_module(repo_dir: Path) -> ModuleType:
    app_file = repo_dir / "app.py"
    spec = importlib.util.spec_from_file_location("voxcpm_official_app", app_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load official app module from {app_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def pushd(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def build_gradio_blocks(
    *,
    official_app: ModuleType,
    runtime: VoxCPMRuntime,
    repo_dir: Path,
    queue_size: int,
):
    with pushd(repo_dir):
        blocks = official_app.create_demo_interface(runtime)
    return blocks.queue(max_size=queue_size, default_concurrency_limit=1)


def audio_response(*, sample_rate: int, wav, model_id: str, filename: str = "speech.wav") -> Response:
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


def ensure_served_model(requested_model: Optional[str], runtime: VoxCPMRuntime) -> None:
    requested = strip_text(requested_model)
    if requested and requested not in {runtime.model_id, OPENAI_COMPAT_MODEL_ID}:
        raise HTTPException(
            status_code=400,
            detail=f"This launcher currently serves {runtime.model_id} and the alias {OPENAI_COMPAT_MODEL_ID}.",
        )


def ensure_wav_only(response_format: str) -> None:
    if strip_text(response_format).lower() != "wav":
        raise HTTPException(
            status_code=400,
            detail="Only response_format='wav' is currently supported by this launcher.",
        )


def save_uploaded_audio(uploaded_audio: Optional[UploadFile], *, prefix: str) -> Optional[str]:
    if uploaded_audio is None or not uploaded_audio.filename:
        return None
    suffix = Path(uploaded_audio.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=UPLOAD_TEMP_DIR,
        prefix=f"{prefix}_",
        suffix=suffix,
    ) as tmp:
        tmp.write(uploaded_audio.file.read())
        return tmp.name


def cleanup_temp_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def build_openai_request(payload: OpenAITTSSpeechRequest, runtime: VoxCPMRuntime) -> PreparedSynthesisRequest:
    return runtime.prepare_synthesis_request(
        text_input=first_non_empty(payload.input, payload.text),
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
        auto_asr=payload.auto_asr,
        response_format=first_non_empty(payload.response_format, payload.format, "wav"),
        cfg_value_input=payload.cfg_value,
        do_normalize=payload.normalize,
        denoise=payload.denoise,
        inference_timesteps=payload.inference_timesteps,
        speed=payload.speed,
        voice_name=extract_voice_name(payload.voice),
    )


def build_native_request(payload: NativeSpeechRequest, runtime: VoxCPMRuntime) -> PreparedSynthesisRequest:
    return runtime.prepare_synthesis_request(
        text_input=first_non_empty(payload.text, payload.input),
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
        auto_asr=payload.auto_asr,
        response_format=first_non_empty(payload.response_format, payload.format, "wav"),
        cfg_value_input=payload.cfg_value,
        do_normalize=payload.normalize,
        denoise=payload.denoise,
        inference_timesteps=payload.inference_timesteps,
        speed=payload.speed,
        voice_name=first_non_empty(
            payload.profile,
            payload.character_name,
            payload.speaker,
            extract_voice_name(payload.voice),
        ),
    )


def build_voxcpm_meta(runtime: VoxCPMRuntime) -> dict[str, Any]:
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
                "aliases": ["reference", "controllable_clone"],
                "required_fields": ["text", "reference_audio"],
                "description": "Reference-audio cloning with optional control instruction.",
            },
            {
                "name": "ultimate_clone",
                "aliases": ["reference_with_text", "clone_with_prompt"],
                "required_fields": ["text", "prompt_text", "prompt_audio|reference_audio"],
                "description": "Prompt-text-guided continuation cloning. Uses the same audio as both reference and prompt when only one path is supplied.",
            },
        ],
        "paths": {
            "health": "/health",
            "openai_speech": "/v1/audio/speech",
            "native_json": "/voxcpm/speech",
            "native_upload": "/voxcpm/speech/upload",
            "meta": "/voxcpm/meta",
        },
    }


def create_api_app(runtime: VoxCPMRuntime) -> FastAPI:
    app = FastAPI(
        title="VoxCPM Local Launcher",
        version="0.2.0",
        description="FastAPI wrapper around the official VoxCPM runtime with native and OpenAI-compatible routes.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root():
        return {
            "message": "VoxCPM launcher is running.",
            "mode": "api",
            "model": runtime.model_id,
            "device": runtime.status_device,
            "asr_enabled": runtime.asr_enabled,
        }

    @app.get("/health")
    @app.get("/api/health", include_in_schema=False)
    def health():
        return {
            "status": "ok",
            "model": runtime.model_id,
            "device": runtime.status_device,
            "model_loaded": runtime.voxcpm_model is not None,
            "asr_enabled": runtime.asr_enabled,
            "asr_loaded": runtime.asr_model is not None,
            "asr_model_source": runtime.asr_model_source,
            "denoiser_enabled": runtime.load_denoiser,
        }

    @app.get("/v1/models")
    def list_models():
        return {
            "object": "list",
            "data": [
                {
                    "id": OPENAI_COMPAT_MODEL_ID,
                    "object": "model",
                    "owned_by": "local",
                    "root_model": runtime.model_id,
                },
                {
                    "id": runtime.model_id,
                    "object": "model",
                    "owned_by": "openbmb",
                },
            ],
        }

    @app.get("/v1/audio/voices")
    @app.get("/v1/audio/speakers", include_in_schema=False)
    def list_voices():
        return {
            "object": "list",
            "data": [
                {
                    "id": "default",
                    "name": "default",
                    "object": "voice",
                    "description": "Placeholder voice entry. Native reference-audio paths are supplied per request.",
                }
            ],
        }

    @app.get("/speakers")
    def speakers():
        return [{"name": "default", "voice_id": "default"}]

    @app.get("/voxcpm/meta")
    def voxcpm_meta():
        return build_voxcpm_meta(runtime)

    @app.post("/v1/audio/speech", summary="Generate speech (OpenAI compatible)")
    def openai_audio_speech(payload: OpenAITTSSpeechRequest):
        ensure_served_model(payload.model, runtime)
        ensure_wav_only(payload.response_format)

        try:
            request = build_openai_request(payload, runtime)
            sample_rate, wav = runtime.synthesize(request)
        except FileNotFoundError as exc:
            return openai_error(str(exc), status_code=404)
        except (ValueError, RuntimeError) as exc:
            return openai_error(str(exc), status_code=400)
        except Exception as exc:
            LOGGER.exception("OpenAI-compatible synthesis failed")
            return openai_error(str(exc), status_code=500, error_type="server_error")

        return audio_response(sample_rate=sample_rate, wav=wav, model_id=runtime.model_id)

    @app.post("/voxcpm/speech", summary="Generate speech with native VoxCPM JSON API")
    @app.post("/voxcpm/generate", include_in_schema=False)
    def native_generate(payload: NativeSpeechRequest):
        ensure_served_model(payload.model, runtime)
        ensure_wav_only(payload.response_format)

        try:
            request = build_native_request(payload, runtime)
            sample_rate, wav = runtime.synthesize(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            LOGGER.exception("Native synthesis failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return audio_response(sample_rate=sample_rate, wav=wav, model_id=runtime.model_id)

    @app.post("/voxcpm/speech/upload", summary="Generate speech with uploaded reference/prompt audio")
    def native_generate_upload(
        text: str = Form(...),
        mode: str | None = Form(None),
        profile: str | None = Form(None),
        character_name: str | None = Form(None),
        speaker: str | None = Form(None),
        voice: str | None = Form(None),
        instruction: str | None = Form(None),
        instructions: str | None = Form(None),
        control: str | None = Form(None),
        reference_audio_path: str | None = Form(None),
        prompt_audio_path: str | None = Form(None),
        reference_audio: UploadFile | None = File(None),
        prompt_audio: UploadFile | None = File(None),
        prompt_text: str | None = Form(None),
        reference_text: str | None = Form(None),
        transcript: str | None = Form(None),
        auto_asr: bool = Form(False),
        speed: float = Form(1.0),
        response_format: str = Form("wav"),
        cfg_value: float = Form(2.0),
        inference_timesteps: int = Form(10),
        normalize: bool = Form(False),
        denoise: bool = Form(False),
    ):
        temp_reference_audio = None
        temp_prompt_audio = None

        try:
            temp_reference_audio = save_uploaded_audio(reference_audio, prefix="reference")
            temp_prompt_audio = save_uploaded_audio(prompt_audio, prefix="prompt")

            payload = NativeSpeechRequest(
                text=text,
                input=None,
                mode=mode,
                profile=profile,
                character_name=character_name,
                speaker=speaker,
                voice=voice,
                instruction=instruction or "",
                instructions=instructions or "",
                control=control or "",
                instruct_text="",
                reference_audio=temp_reference_audio or reference_audio_path,
                reference_audio_path=None,
                reference_wav_path=None,
                prompt_audio=temp_prompt_audio or prompt_audio_path,
                prompt_audio_path=None,
                prompt_wav_path=None,
                prompt_text=prompt_text or "",
                reference_text=reference_text or "",
                transcript=transcript or "",
                auto_asr=auto_asr,
                speed=speed,
                response_format=response_format,
                format="",
                cfg_value=cfg_value,
                inference_timesteps=inference_timesteps,
                normalize=normalize,
                denoise=denoise,
            )
            request = build_native_request(payload, runtime)
            sample_rate, wav = runtime.synthesize(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            LOGGER.exception("Native upload synthesis failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            cleanup_temp_file(temp_reference_audio)
            cleanup_temp_file(temp_prompt_audio)

        return audio_response(sample_rate=sample_rate, wav=wav, model_id=runtime.model_id)

    @app.post("/api/v1/tts/voxcpm", include_in_schema=False)
    @app.post("/api/tts/voxcpm", include_in_schema=False)
    @app.post("/api/tts", include_in_schema=False)
    def legacy_native_generate(payload: NativeSpeechRequest):
        return native_generate(payload)

    return app


def launch_webui(
    *,
    official_app: ModuleType,
    runtime: VoxCPMRuntime,
    repo_dir: Path,
    host: str,
    port: int,
    queue_size: int,
) -> None:
    blocks = build_gradio_blocks(
        official_app=official_app,
        runtime=runtime,
        repo_dir=repo_dir,
        queue_size=queue_size,
    )
    blocks.launch(
        server_name=host,
        server_port=port,
        show_error=True,
        i18n=official_app.I18N,
        theme=official_app._APP_THEME,
        css=official_app._CUSTOM_CSS,
        footer_links=["api", "gradio", "settings"],
    )


def launch_combined(
    *,
    official_app: ModuleType,
    runtime: VoxCPMRuntime,
    repo_dir: Path,
    host: str,
    port: int,
    queue_size: int,
    mount_path: str,
    log_level: str,
) -> None:
    api_app = create_api_app(runtime)
    blocks = build_gradio_blocks(
        official_app=official_app,
        runtime=runtime,
        repo_dir=repo_dir,
        queue_size=queue_size,
    )
    app = gr.mount_gradio_app(
        app=api_app,
        blocks=blocks,
        path=mount_path,
        show_error=True,
        footer_links=["api", "gradio", "settings"],
        allowed_paths=[str((repo_dir / "assets").resolve())],
        i18n=official_app.I18N,
        theme=official_app._APP_THEME,
        css=official_app._CUSTOM_CSS,
    )
    uvicorn.run(app, host=host, port=port, log_level=log_level)


def main() -> None:
    configure_logging()
    args = parse_args()
    args.repo_dir = args.repo_dir.resolve()
    args.port = resolve_port(args)
    validate_args(args)

    official_app = load_official_app_module(args.repo_dir) if args.mode != "api" else None
    runtime = VoxCPMRuntime(
        model_id=args.model_id,
        device=args.device,
        optimize=not args.no_optimize,
        load_denoiser=args.load_denoiser,
        enable_asr=args.enable_asr,
        asr_model_id=args.asr_model_id,
    )

    if args.preload_model:
        runtime.get_or_load_voxcpm()

    LOGGER.info(
        "Starting VoxCPM launcher mode=%s repo=%s model=%s host=%s port=%s asr_enabled=%s asr_source=%s",
        args.mode,
        args.repo_dir,
        args.model_id,
        args.host,
        args.port,
        runtime.asr_enabled,
        runtime.asr_model_source,
    )

    if args.mode == "webui":
        if official_app is None:
            raise RuntimeError("Official VoxCPM WebUI module is required for --mode webui.")
        launch_webui(
            official_app=official_app,
            runtime=runtime,
            repo_dir=args.repo_dir,
            host=args.host,
            port=args.port,
            queue_size=args.queue_size,
        )
        return

    if args.mode == "api":
        app = create_api_app(runtime)
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
        return

    if official_app is None:
        raise RuntimeError("Official VoxCPM WebUI module is required for --mode combined.")

    launch_combined(
        official_app=official_app,
        runtime=runtime,
        repo_dir=args.repo_dir,
        host=args.host,
        port=args.port,
        queue_size=args.queue_size,
        mount_path=args.gradio_path,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
