from __future__ import annotations

import argparse
import contextlib
import importlib.util
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Iterator

import uvicorn

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from app.api.main import create_api_app
from app.admin.voxcpm_admin import create_admin_blocks
from app.core.config import prepare_runtime_environment
from app.core.registry import VoiceRegistry
from app.core.runtime_log import RUNTIME_EVENTS
from app.services.synthesis_service import VoxCPMRuntime

prepare_runtime_environment()

LOGGER = logging.getLogger("voxcpm.launcher")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch VoxCPM with REST API, Neiroha Admin, or the official VoxCPM WebUI.",
    )
    parser.add_argument(
        "--mode",
        choices=["webui", "admin", "api", "api-preload", "combined", "api-admin", "api-admin-preload"],
        default=None,
        help="Compatibility launch mode. If omitted, configs/server.toml [startup].surface is used.",
    )
    parser.add_argument(
        "--surface",
        choices=["api", "admin", "both", "webui", "combined"],
        default=None,
        help="Override configs/server.toml [startup].surface without changing preload or preset settings.",
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
        default=None,
        help="Local model path or Hugging Face repo id served by this launcher. Defaults to configs/model-presets/default.toml.",
    )
    parser.add_argument("--host", type=str, default=None, help="Server host to bind. Defaults to configs/server.toml.")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Server port override. Defaults come from configs/server.toml.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Runtime device: auto, cpu, cuda, or cuda:N. Defaults to the active model preset.",
    )
    parser.add_argument("--optimize", action="store_true", help="Enable model optimization even if the preset disables it.")
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


def normalize_mode(args: argparse.Namespace, startup_config: dict[str, object] | None = None) -> str:
    startup_config = startup_config or {}
    if args.surface:
        surface = args.surface
    elif args.mode is None:
        surface = str(startup_config.get("surface") or "both")
    else:
        surface = ""

    if surface:
        normalized_surface = surface.strip().lower().replace("_", "-")
        if normalized_surface == "both":
            return "api-admin"
        if normalized_surface in {"api", "admin", "webui", "combined"}:
            return normalized_surface
        raise ValueError(f"Unsupported startup surface: {surface}")

    if args.mode in {"api-preload"}:
        args.preload_model = True
        return "api"
    if args.mode == "api-admin-preload":
        args.preload_model = True
        return "api-admin"
    return args.mode


def _config_section(config: dict[str, object], name: str) -> dict[str, object]:
    section = config.get(name, {})
    return section if isinstance(section, dict) else {}


def _configured_bool(section: dict[str, object], key: str, default: bool = False) -> bool:
    if key not in section:
        return default
    return bool(section[key])


def resolve_launch_settings(args: argparse.Namespace, registry: VoiceRegistry) -> argparse.Namespace:
    server_config = registry.server_config()
    api_config = _config_section(server_config, "api")
    admin_config = _config_section(server_config, "admin")
    startup_config = _config_section(server_config, "startup")

    args.mode = normalize_mode(args, startup_config)
    preset = registry.get_model_preset(registry.active_model_preset_id())

    api_host = str(api_config.get("host") or "127.0.0.1")
    api_port = int(api_config.get("port") or 8000)
    admin_host = str(admin_config.get("host") or "127.0.0.1")
    admin_port = int(admin_config.get("port") or 7860)
    admin_share = bool(admin_config.get("share", False))

    if args.mode == "api":
        configured_host = api_host
        configured_port = api_port
    else:
        configured_host = admin_host
        configured_port = admin_port

    args.host = args.host or configured_host
    args.port = args.port if args.port is not None else configured_port
    args.api_host = args.host if args.mode == "api" else api_host
    args.api_port = args.port if args.mode == "api" else api_port
    args.admin_host = args.host if args.mode != "api" else admin_host
    args.admin_port = args.port if args.mode != "api" else admin_port
    args.admin_share = admin_share
    args.model_id = args.model_id or preset.model_id
    args.device = args.device or preset.device
    args.optimize = True if args.optimize else bool(preset.optimize)
    if args.no_optimize:
        args.optimize = False
    args.load_denoiser = bool(args.load_denoiser or preset.load_denoiser)
    args.enable_asr = bool(args.enable_asr or preset.enable_asr)
    args.asr_model_id = args.asr_model_id or preset.asr_model_id
    args.preload_model = bool(
        args.preload_model
        or (
            args.mode in {"api", "api-admin"}
            and (
                _configured_bool(startup_config, "preload_model")
                or _configured_bool(api_config, "preload_model")
            )
        )
    )
    args.model_preset_id = preset.id
    return args


def _bind_host(host: str) -> str:
    return "" if host in {"0.0.0.0", "::"} else host


def select_available_port(host: str, requested_port: int, *, service: str) -> tuple[int, bool]:
    bind_host = _bind_host(host)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((bind_host, requested_port))
        return requested_port, False
    except OSError as exc:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((bind_host, 0))
            selected = int(probe.getsockname()[1])
        RUNTIME_EVENTS.append(
            "port_fallback",
            service=service,
            requested_port=requested_port,
            selected_port=selected,
            reason=str(exc),
        )
        return selected, True


def public_url(host: str, port: int) -> str:
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    return f"http://{display_host}:{port}"


def validate_args(args: argparse.Namespace) -> None:
    if not args.repo_dir.exists():
        raise FileNotFoundError(f"VoxCPM repo directory does not exist: {args.repo_dir}")
    if args.mode in {"webui", "combined"} and not (args.repo_dir / "app.py").exists():
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
    registry: VoiceRegistry,
    launch_info: dict[str, object],
    repo_dir: Path,
    host: str,
    port: int,
    queue_size: int,
    mount_path: str,
    log_level: str,
) -> None:
    import gradio as gr

    api_app = create_api_app(runtime, registry, launch_info=launch_info)
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


def run_api_server_in_thread(
    *,
    runtime: VoxCPMRuntime,
    registry: VoiceRegistry,
    launch_info: dict[str, object],
    host: str,
    port: int,
    log_level: str,
) -> uvicorn.Server:
    app = create_api_app(runtime, registry, launch_info=launch_info)
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="voxcpm-api", daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    RUNTIME_EVENTS.append("api_thread_start", host=host, port=port, started=server.started)
    return server


def launch_admin(
    *,
    api_url: str,
    admin_url: str,
    registry: VoiceRegistry,
    host: str,
    port: int,
    share: bool,
    queue_size: int,
) -> None:
    blocks = create_admin_blocks(
        api_url=api_url,
        admin_url=admin_url,
        registry=registry,
        queue_size=queue_size,
    )
    blocks.launch(
        server_name=host,
        server_port=port,
        share=share,
        show_error=True,
    )


def main() -> None:
    configure_logging()
    args = parse_args()
    RUNTIME_EVENTS.reset_for_launch()
    registry = VoiceRegistry()
    args = resolve_launch_settings(args, registry)
    args.repo_dir = args.repo_dir.resolve()
    validate_args(args)
    api_port_fallback = False
    admin_port_fallback = False
    if args.mode == "api":
        args.api_port, api_port_fallback = select_available_port(args.api_host, args.api_port, service="FastAPI")
        args.port = args.api_port
    elif args.mode == "api-admin":
        args.api_port, api_port_fallback = select_available_port(args.api_host, args.api_port, service="FastAPI")
        args.admin_port, admin_port_fallback = select_available_port(args.admin_host, args.admin_port, service="Admin")
        args.port = args.admin_port
    else:
        args.admin_port, admin_port_fallback = select_available_port(args.admin_host, args.admin_port, service="Gradio")
        args.port = args.admin_port

    official_app = load_official_app_module(args.repo_dir) if args.mode in {"webui", "combined"} else None
    runtime = VoxCPMRuntime(
        model_id=args.model_id,
        device=args.device,
        optimize=args.optimize,
        load_denoiser=args.load_denoiser,
        enable_asr=args.enable_asr,
        asr_model_id=args.asr_model_id,
    )
    if args.mode == "combined":
        api_url = public_url(args.admin_host, args.admin_port)
    else:
        api_url = public_url(args.api_host, args.api_port)
    launch_info = {
        "api_url": api_url,
        "admin_url": public_url(args.admin_host, args.admin_port) if args.mode in {"admin", "api-admin", "webui", "combined"} else "",
        "port_fallback": bool(api_port_fallback or admin_port_fallback),
        "api_port_fallback": api_port_fallback,
        "admin_port_fallback": admin_port_fallback,
        "model_preset": args.model_preset_id,
    }

    if args.preload_model:
        runtime.get_or_load_voxcpm()

    LOGGER.info(
        "Starting VoxCPM launcher mode=%s repo=%s preset=%s model=%s host=%s port=%s asr_enabled=%s asr_source=%s",
        args.mode,
        args.repo_dir,
        args.model_preset_id,
        args.model_id,
        args.api_host if args.mode in {"api", "api-admin"} else args.admin_host,
        args.api_port if args.mode == "api" else args.admin_port,
        runtime.asr_enabled,
        runtime.asr_model_source,
    )
    RUNTIME_EVENTS.append(
        "launcher_start",
        mode=args.mode,
        model_preset=args.model_preset_id,
        model=args.model_id,
        api_url=launch_info["api_url"],
        admin_url=launch_info["admin_url"],
        optimize=args.optimize,
        preload=args.preload_model,
    )

    if args.mode == "webui":
        if official_app is None:
            raise RuntimeError("Official VoxCPM WebUI module is required for --mode webui.")
        launch_webui(
            official_app=official_app,
            runtime=runtime,
            repo_dir=args.repo_dir,
            host=args.admin_host,
            port=args.admin_port,
            queue_size=args.queue_size,
        )
        return

    if args.mode == "api":
        app = create_api_app(runtime, registry, launch_info=launch_info)
        uvicorn.run(app, host=args.api_host, port=args.api_port, log_level=args.log_level)
        return

    if args.mode == "admin":
        launch_admin(
            api_url=str(launch_info["api_url"]),
            admin_url=str(launch_info["admin_url"]),
            registry=registry,
            host=args.admin_host,
            port=args.admin_port,
            share=args.admin_share,
            queue_size=args.queue_size,
        )
        return

    if args.mode == "api-admin":
        run_api_server_in_thread(
            runtime=runtime,
            registry=registry,
            launch_info=launch_info,
            host=args.api_host,
            port=args.api_port,
            log_level=args.log_level,
        )
        launch_admin(
            api_url=str(launch_info["api_url"]),
            admin_url=str(launch_info["admin_url"]),
            registry=registry,
            host=args.admin_host,
            port=args.admin_port,
            share=args.admin_share,
            queue_size=args.queue_size,
        )
        return

    if official_app is None:
        raise RuntimeError("Official VoxCPM WebUI module is required for --mode combined.")

    launch_combined(
        official_app=official_app,
        runtime=runtime,
        registry=registry,
        launch_info=launch_info,
        repo_dir=args.repo_dir,
        host=args.admin_host,
        port=args.admin_port,
        queue_size=args.queue_size,
        mount_path=args.gradio_path,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
