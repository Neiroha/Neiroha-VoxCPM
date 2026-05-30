from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.core.config import CACHE_ROOT, LOGS_ROOT, WORKSPACE_ROOT
from app.core.registry import DEFAULT_MODEL_PRESET_ID, DEFAULT_VOICE_SET_ID, ModelPreset, VoiceRegistry, VoiceSet
from app.core.runtime_log import LOG_SOURCES, RUNTIME_EVENTS, read_log_source
from app.core.schemas import VoiceProfileCreateRequest
from app.core.utils import dump_model, first_non_empty, strip_text


TEXT = {
    "zh": {
        "title": "Neiroha VoxCPM Admin",
        "home": "状态",
        "try": "试音",
        "voice_config": "克隆配置",
        "voice_sets": "Voice Sets",
        "model_presets": "Model Presets",
        "download": "下载",
        "logs": "运行日志",
        "settings": "设置",
        "refresh": "刷新",
        "save": "保存",
        "generate": "生成",
        "load": "加载",
        "unload": "卸载",
        "reload": "重载",
    },
    "en": {
        "title": "Neiroha VoxCPM Admin",
        "home": "Status",
        "try": "Synthesis Test",
        "voice_config": "Voice Profiles",
        "voice_sets": "Voice Sets",
        "model_presets": "Model Presets",
        "download": "Downloads",
        "logs": "Runtime Logs",
        "settings": "Settings",
        "refresh": "Refresh",
        "save": "Save",
        "generate": "Generate",
        "load": "Load",
        "unload": "Unload",
        "reload": "Reload",
    },
}


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _json_request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    api_key: str = "",
) -> Any:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(
        _join_url(base_url, path),
        data=data,
        method=method,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read()
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def _audio_request(base_url: str, payload: dict[str, Any], *, api_key: str = "") -> tuple[bytes, dict[str, str]]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(
        _join_url(base_url, "/v1/audio/speech"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        return response.read(), headers


def _api_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        return f"HTTP {exc.code}: {detail or exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"API offline: {exc.reason}"
    return str(exc)


def _read_ui_language(registry: VoiceRegistry) -> str:
    env_lang = strip_text(os.environ.get("NEIROHA_VOXCPM_UI_LANG")).lower()
    if env_lang in TEXT:
        return env_lang
    ui_config = registry.server_config().get("ui", {})
    if isinstance(ui_config, dict):
        lang = strip_text(ui_config.get("default_language")).lower()
        if lang in TEXT:
            return lang
    return "zh"


def _read_ui_title(registry: VoiceRegistry, lang: str) -> str:
    ui_config = registry.server_config().get("ui", {})
    if isinstance(ui_config, dict):
        title = strip_text(ui_config.get("title"))
        if title:
            return title
    return TEXT[lang]["title"]


def _resolve_output_path(path_text: str) -> str:
    text = strip_text(path_text)
    if not text:
        return ""
    path = Path(text)
    if not path.is_absolute():
        path = WORKSPACE_ROOT / path
    return str(path.resolve()) if path.exists() else ""


def _voice_choices(registry: VoiceRegistry, voice_set_id: str = "") -> list[str]:
    return [profile.id for profile in registry.list_profiles(voice_set_id)]


def _voice_set_choices(registry: VoiceRegistry) -> list[str]:
    return [voice_set.id for voice_set in registry.list_voice_sets()]


def _preset_choices(registry: VoiceRegistry) -> list[str]:
    return [preset.id for preset in registry.list_model_presets()]


def _split_csv(text: str) -> list[str]:
    values: list[str] = []
    for chunk in strip_text(text).replace("\n", ",").split(","):
        value = strip_text(chunk)
        if value:
            values.append(value)
    return values


def _sanitize_model_id(model_id: str) -> str:
    return strip_text(model_id).replace("\\", "__").replace("/", "__").replace(":", "_")


def create_admin_blocks(
    *,
    api_url: str,
    admin_url: str,
    registry: VoiceRegistry,
    queue_size: int = 10,
):
    import gradio as gr

    lang = _read_ui_language(registry)
    text = TEXT[lang]
    title = _read_ui_title(registry, lang)

    def admin_api_key() -> str:
        security = registry.server_config().get("security", {})
        if not isinstance(security, dict):
            return ""
        return strip_text(security.get("api_key"))

    def home_status() -> str:
        health: dict[str, Any] = {}
        online = False
        try:
            health = _json_request(api_url, "GET", "/health", api_key=admin_api_key())
            online = True
        except Exception:
            online = False
        profiles = registry.list_profiles()
        presets = registry.list_model_presets()
        voice_sets = registry.list_voice_sets()
        lines = [
            f"### {title}",
            f"- API: `{'online' if online else 'offline'}`",
            f"- API URL: `{api_url}`",
            f"- Admin URL: `{admin_url}`",
            f"- Port fallback: `{health.get('port_fallback', False)}`",
            f"- Active model preset: `{registry.active_model_preset_id()}`",
            f"- Active voice set: `{registry.active_voice_set_id()}`",
            f"- Default voice: `{registry.default_voice_id()}`",
            f"- Model loaded: `{health.get('model_loaded', False)}`",
            f"- Device: `{health.get('device', 'auto')}`",
            f"- ASR enabled: `{health.get('asr_enabled', False)}`",
            f"- Voice count: `{len(profiles)}`",
            f"- Voice sets: `{len(voice_sets)}`",
            f"- Model presets: `{len(presets)}`",
        ]
        return "\n".join(lines)

    def api_action(action: str) -> str:
        try:
            result = _json_request(api_url, "POST", f"/api/voxcpm/{action}", api_key=admin_api_key())
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as exc:
            return _api_error(exc)

    def refresh_try_choices(model_id: str = ""):
        model_choices = _voice_set_choices(registry)
        selected_model = strip_text(model_id) or registry.active_voice_set_id()
        if selected_model not in model_choices and model_choices:
            selected_model = model_choices[0]
        voices = _voice_choices(registry, selected_model)
        selected_voice = registry.default_voice_id() if registry.default_voice_id() in voices else (voices[0] if voices else "")
        return gr.update(choices=model_choices, value=selected_model), gr.update(choices=voices, value=selected_voice)

    def run_try_voice(
        model_id: str,
        voice_id: str,
        text_input: str,
        mode: str,
        instruction: str,
        reference_audio_path: str,
        uploaded_reference: str | None,
        prompt_text: str,
        speed: float,
    ):
        reference_audio = first_non_empty(uploaded_reference, reference_audio_path)
        payload = {
            "model": strip_text(model_id) or registry.active_voice_set_id(),
            "voice": strip_text(voice_id) or registry.default_voice_id(),
            "input": strip_text(text_input),
            "response_format": "wav",
            "speed": float(speed or 1.0),
        }
        if strip_text(mode):
            payload["mode"] = strip_text(mode)
        if strip_text(instruction):
            payload["instruction"] = strip_text(instruction)
        if reference_audio:
            payload["reference_audio"] = reference_audio
        if strip_text(prompt_text):
            payload["prompt_text"] = strip_text(prompt_text)
        try:
            content, headers = _audio_request(api_url, payload, api_key=admin_api_key())
        except Exception as exc:
            return None, _api_error(exc)
        output_path = _resolve_output_path(headers.get("x-neiroha-output-path", ""))
        if not output_path:
            output_path = str((WORKSPACE_ROOT / "runtime" / "outputs" / "admin_preview.wav").resolve())
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(content)
        status = "\n".join(
            [
                f"Output: {output_path}",
                f"Audio seconds: {headers.get('x-neiroha-audio-seconds', '')}",
                f"Elapsed seconds: {headers.get('x-neiroha-elapsed-seconds', '')}",
                f"RTF: {headers.get('x-neiroha-rtf', '')}",
            ]
        )
        return output_path, status

    def load_voice(voice_id: str):
        voice_id = strip_text(voice_id)
        if not voice_id:
            voices = _voice_choices(registry)
            voice_id = voices[0] if voices else ""
        if not voice_id:
            return [""] * 14
        profile = registry.get_profile(voice_id)
        return [
            profile.id,
            profile.display_name,
            profile.description,
            profile.voice_set,
            profile.model_preset,
            profile.mode_hint or profile.mode,
            profile.reference_audio or "",
            profile.prompt_audio or "",
            profile.prompt_text,
            profile.text_lang,
            profile.prompt_lang,
            profile.instruction,
            profile.speed,
            json.dumps(profile.engine_options, ensure_ascii=False, indent=2),
        ]

    def save_voice(
        voice_id: str,
        name: str,
        description: str,
        voice_set: str,
        model_preset: str,
        mode: str,
        reference_audio_path: str,
        uploaded_reference: str | None,
        prompt_audio_path: str,
        uploaded_prompt: str | None,
        prompt_text: str,
        text_lang: str,
        prompt_lang: str,
        instruction: str,
        speed: float,
        engine_options_text: str,
    ):
        mode = strip_text(mode) or "design"
        reference_audio = first_non_empty(uploaded_reference, reference_audio_path)
        prompt_audio = first_non_empty(uploaded_prompt, prompt_audio_path)
        if mode != "design" and not reference_audio and not prompt_audio:
            return "reference audio is required", gr.update()
        if mode == "ultimate_clone" and reference_audio and not prompt_audio:
            prompt_audio = reference_audio
        try:
            engine_options = json.loads(engine_options_text or "{}")
            if not isinstance(engine_options, dict):
                raise ValueError("engine_options must be a JSON object.")
            profile, _ = registry.save_profile(
                VoiceProfileCreateRequest(
                    id=voice_id,
                    name=name,
                    description=description,
                    voice_set=voice_set,
                    model_preset=model_preset,
                    mode=mode,
                    reference_audio=reference_audio,
                    prompt_audio=prompt_audio,
                    prompt_text=prompt_text,
                    text_lang=text_lang,
                    prompt_lang=prompt_lang,
                    instruction=instruction,
                    speed=float(speed or 1.0),
                    engine_options=engine_options,
                    copy_audio_to_registry=bool(uploaded_reference or uploaded_prompt),
                ),
                default_model=registry.active_voice_set_id(),
            )
        except Exception as exc:
            return str(exc), gr.update()
        voices = _voice_choices(registry)
        status = f"Saved voice: {profile.id}\nReference audio: {profile.reference_audio or ''}"
        return status, gr.update(choices=voices, value=profile.id)

    def refresh_voice_config_choices():
        voices = _voice_choices(registry)
        value = registry.default_voice_id() if registry.default_voice_id() in voices else (voices[0] if voices else "")
        return gr.update(choices=voices, value=value)

    def load_voice_set(set_id: str):
        voice_set = registry.get_voice_set(set_id) or registry.get_voice_set(registry.active_voice_set_id())
        if voice_set is None:
            return "", "", "", ""
        return voice_set.id, voice_set.name, voice_set.description, ", ".join(voice_set.voices or [])

    def save_voice_set(set_id: str, name: str, description: str, voices_csv: str):
        try:
            voice_set = registry.save_voice_set(
                VoiceSet(
                    id=set_id,
                    name=name,
                    description=description,
                    voices=_split_csv(voices_csv),
                )
            )
        except Exception as exc:
            return str(exc), gr.update()
        return f"Saved voice set: {voice_set.id}", gr.update(choices=_voice_set_choices(registry), value=voice_set.id)

    def activate_voice_set(set_id: str, default_voice: str):
        registry.update_runtime_state(active_voice_set=set_id, default_voice=default_voice)
        return f"Activated voice set: {registry.active_voice_set_id()}"

    def load_model_preset(preset_id: str):
        preset = registry.get_model_preset(preset_id)
        return (
            preset.id,
            preset.name,
            preset.model_id,
            preset.device,
            preset.optimize,
            preset.load_denoiser,
            preset.enable_asr,
            preset.asr_model_id,
        )

    def save_model_preset(
        preset_id: str,
        name: str,
        model_id: str,
        device: str,
        optimize: bool,
        load_denoiser: bool,
        enable_asr: bool,
        asr_model_id: str,
    ):
        try:
            preset = registry.save_model_preset(
                ModelPreset(
                    id=preset_id,
                    name=name,
                    model_id=model_id,
                    device=device,
                    optimize=optimize,
                    load_denoiser=load_denoiser,
                    enable_asr=enable_asr,
                    asr_model_id=asr_model_id,
                )
            )
        except Exception as exc:
            return str(exc), gr.update()
        return f"Saved model preset: {preset.id}", gr.update(choices=_preset_choices(registry), value=preset.id)

    def activate_model_preset(preset_id: str):
        registry.update_runtime_state(active_model_preset=preset_id)
        return f"Activated model preset: {registry.active_model_preset_id()}"

    def start_download(model_id: str, force: bool) -> str:
        model_id = strip_text(model_id) or "OpenBMB/VoxCPM2"
        LOGS_ROOT.mkdir(parents=True, exist_ok=True)
        out_path = LOGS_ROOT / "download.out.log"
        err_path = LOGS_ROOT / "download.err.log"
        command = [sys.executable, str(WORKSPACE_ROOT / "scripts" / "download_modelscope_model.py"), "--model-id", model_id]
        if force:
            command.append("--force")
        out_file = out_path.open("w", encoding="utf-8", errors="replace")
        err_file = err_path.open("w", encoding="utf-8", errors="replace")
        process = subprocess.Popen(command, cwd=WORKSPACE_ROOT, stdout=out_file, stderr=err_file)
        RUNTIME_EVENTS.append("download_start", model_id=model_id, pid=process.pid)
        return f"Download started: pid={process.pid}\nstdout={out_path}\nstderr={err_path}"

    def download_info(model_id: str, force: bool) -> str:
        model_id = strip_text(model_id) or "OpenBMB/VoxCPM2"
        target_path = WORKSPACE_ROOT / "models" / _sanitize_model_id(model_id)
        cache_path = CACHE_ROOT / "modelscope"
        lines = [
            f"Source: {model_id}",
            f"Target: {target_path}",
            f"Cache: {cache_path}",
            "Expected size: unknown",
            f"Overwrite existing assets: {bool(force)}",
        ]
        return "\n".join(lines)

    def refresh_log(source: str, limit: int, newest_first: bool) -> str:
        return read_log_source(source, limit=int(limit or 160), newest_first=bool(newest_first))

    def run_smoke_test(include_synthesis: bool) -> str:
        command = [
            sys.executable,
            str(WORKSPACE_ROOT / "scripts" / "smoke_test_api.py"),
            "--base-url",
            api_url,
        ]
        api_key = admin_api_key()
        if api_key:
            command.extend(["--api-key", api_key])
        if include_synthesis:
            command.append("--synthesize")
        try:
            completed = subprocess.run(
                command,
                cwd=WORKSPACE_ROOT,
                capture_output=True,
                text=True,
                timeout=900 if include_synthesis else 90,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            return str(exc)
        output = (completed.stdout or "").strip()
        error = (completed.stderr or "").strip()
        lines = [f"Exit code: {completed.returncode}"]
        if output:
            lines.append(output)
        if error:
            lines.append(error)
        return "\n\n".join(lines)

    def load_settings():
        config = registry.server_config()
        api = config.get("api") if isinstance(config.get("api"), dict) else {}
        admin = config.get("admin") if isinstance(config.get("admin"), dict) else {}
        startup = config.get("startup") if isinstance(config.get("startup"), dict) else {}
        security = config.get("security") if isinstance(config.get("security"), dict) else {}
        ui = config.get("ui") if isinstance(config.get("ui"), dict) else {}
        return (
            str(api.get("host") or "127.0.0.1"),
            int(api.get("port") or 8000),
            str(admin.get("host") or "127.0.0.1"),
            int(admin.get("port") or 7860),
            bool(admin.get("share", False)),
            str(startup.get("surface") or "both"),
            bool(startup.get("preload_model", False)),
            str(startup.get("default_model_preset") or registry.active_model_preset_id()),
            str(security.get("api_key") or ""),
            str(ui.get("title") or title),
            str(ui.get("default_language") or lang),
        )

    def restart_plan() -> str:
        config = registry.server_config()
        startup = config.get("startup") if isinstance(config.get("startup"), dict) else {}
        api = config.get("api") if isinstance(config.get("api"), dict) else {}
        admin = config.get("admin") if isinstance(config.get("admin"), dict) else {}
        lines = [
            "Command: pixi run serve",
            f"Config: {WORKSPACE_ROOT / 'configs' / 'server.toml'}",
            f"Surface: {strip_text(startup.get('surface')) or 'both'}",
            f"Preload model: {bool(startup.get('preload_model', False))}",
            f"Default preset: {strip_text(startup.get('default_model_preset')) or registry.active_model_preset_id()}",
            f"API: {strip_text(api.get('host')) or '127.0.0.1'}:{int(api.get('port') or 8000)}",
            f"Admin: {strip_text(admin.get('host')) or '127.0.0.1'}:{int(admin.get('port') or 7860)}",
            "Stop: close the current launcher process before starting the command again.",
        ]
        return "\n".join(lines)

    def save_settings(
        api_host: str,
        api_port: int,
        admin_host: str,
        admin_port: int,
        admin_share: bool,
        startup_surface: str,
        preload_model: bool,
        default_model_preset: str,
        api_key: str,
        ui_title: str,
        ui_language: str,
    ) -> str:
        config = dict(registry.server_config())
        config["api"] = {
            "host": strip_text(api_host) or "127.0.0.1",
            "port": int(api_port or 8000),
            "reload": bool(config.get("api", {}).get("reload", False)) if isinstance(config.get("api"), dict) else False,
        }
        config["admin"] = {
            "enabled": True,
            "host": strip_text(admin_host) or "127.0.0.1",
            "port": int(admin_port or 7860),
            "share": bool(admin_share),
        }
        config["startup"] = {
            "surface": strip_text(startup_surface) or "both",
            "preload_model": bool(preload_model),
            "default_model_preset": strip_text(default_model_preset) or DEFAULT_MODEL_PRESET_ID,
        }
        config["security"] = {"api_key": strip_text(api_key)}
        config["ui"] = {
            "title": strip_text(ui_title) or title,
            "default_language": strip_text(ui_language) or lang,
        }
        registry.save_server_config(config)
        return "Saved settings. Restart the service for launch settings to take effect."

    with gr.Blocks(title=title) as demo:
        gr.Markdown(f"# {title}")
        with gr.Tab(text["home"]):
            home_box = gr.Markdown(value=home_status())
            with gr.Row():
                refresh_home = gr.Button(text["refresh"])
                load_button = gr.Button(text["load"])
                unload_button = gr.Button(text["unload"])
                reload_button = gr.Button(text["reload"])
            model_action_box = gr.Code(label="Model action", language="json")
            refresh_home.click(home_status, outputs=home_box)
            load_button.click(lambda: api_action("load"), outputs=model_action_box)
            unload_button.click(lambda: api_action("unload"), outputs=model_action_box)
            reload_button.click(lambda: api_action("reload"), outputs=model_action_box)

        with gr.Tab(text["model_presets"]):
            preset_select = gr.Dropdown(label="Model Preset", choices=_preset_choices(registry), value=registry.active_model_preset_id())
            load_preset = gr.Button(text["load"])
            preset_id = gr.Textbox(label="ID")
            preset_name = gr.Textbox(label="Name")
            preset_model_id = gr.Textbox(label="Model path / repository id")
            preset_device = gr.Textbox(label="Device", value="auto")
            with gr.Row():
                preset_optimize = gr.Checkbox(label="Optimize")
                preset_denoiser = gr.Checkbox(label="Load denoiser")
                preset_asr = gr.Checkbox(label="Enable ASR")
            preset_asr_model = gr.Textbox(label="ASR model path / id")
            with gr.Row():
                save_preset = gr.Button(text["save"], variant="primary")
                activate_preset = gr.Button("Activate")
            preset_status = gr.Textbox(label="Status", lines=2)
            load_preset.click(
                load_model_preset,
                inputs=preset_select,
                outputs=[preset_id, preset_name, preset_model_id, preset_device, preset_optimize, preset_denoiser, preset_asr, preset_asr_model],
            )
            save_preset.click(
                save_model_preset,
                inputs=[preset_id, preset_name, preset_model_id, preset_device, preset_optimize, preset_denoiser, preset_asr, preset_asr_model],
                outputs=[preset_status, preset_select],
            )
            activate_preset.click(activate_model_preset, inputs=preset_id, outputs=preset_status)

        with gr.Tab(text["voice_sets"]):
            set_select = gr.Dropdown(label="Voice Set", choices=_voice_set_choices(registry), value=registry.active_voice_set_id())
            load_set = gr.Button(text["load"])
            set_id = gr.Textbox(label="ID")
            set_name = gr.Textbox(label="Name")
            set_description = gr.Textbox(label="Description", lines=2)
            set_voices = gr.Textbox(label="Voices", lines=5)
            with gr.Row():
                save_set = gr.Button(text["save"], variant="primary")
                activate_set = gr.Button("Activate")
            set_status = gr.Textbox(label="Status", lines=2)

            voice_select = gr.Dropdown(label="Voice", choices=_voice_choices(registry), value=registry.default_voice_id())
            with gr.Row():
                refresh_voices = gr.Button(text["refresh"])
                load_voice_button = gr.Button(text["load"])
            with gr.Row():
                voice_id = gr.Textbox(label="Voice ID")
                voice_name = gr.Textbox(label="Name")
            voice_description = gr.Textbox(label="Description", lines=2)
            with gr.Row():
                voice_set_id = gr.Dropdown(label="Voice Set", choices=_voice_set_choices(registry), value=registry.active_voice_set_id())
                voice_preset = gr.Dropdown(label="Model Preset", choices=_preset_choices(registry), value=registry.active_model_preset_id())
                voice_mode = gr.Dropdown(label="Mode", choices=["design", "clone", "ultimate_clone"], value="design")
            with gr.Row():
                voice_ref_path = gr.Textbox(label="Reference audio path")
                voice_ref_upload = gr.Audio(label="Upload reference", sources=["upload"], type="filepath")
            with gr.Row():
                voice_prompt_path = gr.Textbox(label="Prompt audio path")
                voice_prompt_upload = gr.Audio(label="Upload prompt", sources=["upload"], type="filepath")
            voice_prompt_text = gr.Textbox(label="Prompt text", lines=3)
            with gr.Row():
                voice_text_lang = gr.Textbox(label="Text lang", value="auto")
                voice_prompt_lang = gr.Textbox(label="Prompt lang", value="auto")
                voice_speed = gr.Slider(label="Speed", minimum=0.5, maximum=2.0, step=0.05, value=1.0)
            voice_instruction = gr.Textbox(label="Instruction", lines=2)
            voice_engine_options = gr.Code(label="Engine options JSON", language="json", value="{}")
            save_voice_button = gr.Button(text["save"], variant="primary")
            voice_status = gr.Textbox(label="Status", lines=3)

            load_set.click(load_voice_set, inputs=set_select, outputs=[set_id, set_name, set_description, set_voices])
            save_set.click(save_voice_set, inputs=[set_id, set_name, set_description, set_voices], outputs=[set_status, set_select])
            activate_set.click(activate_voice_set, inputs=[set_id, voice_select], outputs=set_status)
            load_voice_button.click(
                load_voice,
                inputs=voice_select,
                outputs=[
                    voice_id,
                    voice_name,
                    voice_description,
                    voice_set_id,
                    voice_preset,
                    voice_mode,
                    voice_ref_path,
                    voice_prompt_path,
                    voice_prompt_text,
                    voice_text_lang,
                    voice_prompt_lang,
                    voice_instruction,
                    voice_speed,
                    voice_engine_options,
                ],
            )
            refresh_voices.click(refresh_voice_config_choices, outputs=voice_select)
            save_voice_button.click(
                save_voice,
                inputs=[
                    voice_id,
                    voice_name,
                    voice_description,
                    voice_set_id,
                    voice_preset,
                    voice_mode,
                    voice_ref_path,
                    voice_ref_upload,
                    voice_prompt_path,
                    voice_prompt_upload,
                    voice_prompt_text,
                    voice_text_lang,
                    voice_prompt_lang,
                    voice_instruction,
                    voice_speed,
                    voice_engine_options,
                ],
                outputs=[voice_status, voice_select],
            )

        with gr.Tab(text["try"]):
            with gr.Row():
                try_model = gr.Dropdown(label="Model / Voice Set", choices=_voice_set_choices(registry), value=registry.active_voice_set_id())
                try_voice = gr.Dropdown(label="Voice", choices=_voice_choices(registry, registry.active_voice_set_id()), value=registry.default_voice_id())
                try_mode = gr.Dropdown(label="Mode override", choices=["", "design", "clone", "ultimate_clone"], value="")
            try_text = gr.Textbox(label="Text", lines=4, value="你好，这是 VoxCPM2 的 Admin 试音。")
            try_instruction = gr.Textbox(label="Instruction", lines=2)
            with gr.Row():
                try_ref_path = gr.Textbox(label="Reference audio path")
                try_ref_upload = gr.Audio(label="Upload reference", sources=["upload"], type="filepath")
            try_prompt_text = gr.Textbox(label="Prompt text", lines=2)
            try_speed = gr.Slider(label="Speed", minimum=0.5, maximum=2.0, step=0.05, value=1.0)
            try_run = gr.Button(text["generate"], variant="primary")
            try_audio = gr.Audio(label="Output", type="filepath")
            try_status = gr.Textbox(label="Status", lines=4)
            try_model.change(refresh_try_choices, inputs=try_model, outputs=[try_model, try_voice])
            try_run.click(
                run_try_voice,
                inputs=[try_model, try_voice, try_text, try_mode, try_instruction, try_ref_path, try_ref_upload, try_prompt_text, try_speed],
                outputs=[try_audio, try_status],
            )

        with gr.Tab(text["download"]):
            download_model = gr.Textbox(label="ModelScope model id", value="OpenBMB/VoxCPM2")
            download_force = gr.Checkbox(label="Force redownload", value=False)
            download_details = gr.Textbox(label="Download details", lines=5, value=download_info("OpenBMB/VoxCPM2", False))
            download_start = gr.Button("Start download", variant="primary")
            download_status = gr.Textbox(label="Status", lines=4)
            download_log = gr.Code(label="download.out.log", language=None, lines=18)
            download_model.change(download_info, inputs=[download_model, download_force], outputs=download_details)
            download_force.change(download_info, inputs=[download_model, download_force], outputs=download_details)
            download_start.click(start_download, inputs=[download_model, download_force], outputs=download_status)
            download_start.click(lambda: read_log_source("download.out.log", limit=120), outputs=download_log)

        with gr.Tab(text["logs"]):
            with gr.Row():
                log_source = gr.Dropdown(label="Source", choices=sorted(LOG_SOURCES), value="backend.log")
                log_limit = gr.Slider(label="Lines", minimum=40, maximum=500, step=20, value=160)
                newest_first = gr.Checkbox(label="Newest first", value=True)
            log_refresh = gr.Button(text["refresh"])
            log_box = gr.Code(label="Log", language=None, lines=24, value=refresh_log("backend.log", 160, True))
            log_refresh.click(refresh_log, inputs=[log_source, log_limit, newest_first], outputs=log_box)
            with gr.Row():
                smoke_synthesis = gr.Checkbox(label="Include synthesis", value=False)
                smoke_run = gr.Button("Run smoke")
            smoke_output = gr.Code(label="Smoke output", language=None, lines=10)
            smoke_run.click(run_smoke_test, inputs=smoke_synthesis, outputs=smoke_output)

        with gr.Tab(text["settings"]):
            initial_settings = load_settings()
            with gr.Row():
                api_host = gr.Textbox(label="API host", value=initial_settings[0])
                api_port = gr.Number(label="API port", value=initial_settings[1], precision=0)
            with gr.Row():
                admin_host = gr.Textbox(label="Admin host", value=initial_settings[2])
                admin_port = gr.Number(label="Admin port", value=initial_settings[3], precision=0)
                admin_share = gr.Checkbox(label="Admin share", value=initial_settings[4])
            with gr.Row():
                startup_surface = gr.Dropdown(label="Startup surface", choices=["api", "admin", "both", "webui", "combined"], value=initial_settings[5])
                startup_preload = gr.Checkbox(label="Preload model", value=initial_settings[6])
                startup_preset = gr.Dropdown(label="Default model preset", choices=_preset_choices(registry), value=initial_settings[7])
            api_key = gr.Textbox(label="API key", value=initial_settings[8], type="password")
            with gr.Row():
                ui_title = gr.Textbox(label="UI title", value=initial_settings[9])
                ui_language = gr.Dropdown(label="UI language", choices=sorted(TEXT), value=initial_settings[10])
            with gr.Row():
                refresh_settings = gr.Button(text["refresh"])
                save_settings_button = gr.Button(text["save"], variant="primary")
            settings_status = gr.Textbox(label="Status", lines=2)
            restart_box = gr.Code(label="Restart plan", language=None, lines=8, value=restart_plan())
            refresh_restart = gr.Button("Refresh restart plan")
            setting_outputs = [
                api_host,
                api_port,
                admin_host,
                admin_port,
                admin_share,
                startup_surface,
                startup_preload,
                startup_preset,
                api_key,
                ui_title,
                ui_language,
            ]
            refresh_settings.click(load_settings, outputs=setting_outputs)
            save_settings_button.click(
                save_settings,
                inputs=setting_outputs,
                outputs=settings_status,
            )
            refresh_restart.click(restart_plan, outputs=restart_box)

    return demo.queue(max_size=queue_size, default_concurrency_limit=1)
