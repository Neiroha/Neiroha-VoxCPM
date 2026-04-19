from __future__ import annotations

import argparse
import contextlib
import importlib.util
import logging
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterator

import uvicorn

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from app.api.main import create_api_app
from app.core.config import prepare_runtime_environment
from app.services.synthesis_service import VoxCPMRuntime

prepare_runtime_environment()

LOGGER = logging.getLogger("voxcpm.launcher")


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
    import gradio as gr

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
