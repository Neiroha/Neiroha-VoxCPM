from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

PRESET_MODELS = {
    "default": "OpenBMB/VoxCPM2",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download explicit VoxCPM backend assets.")
    parser.add_argument("--preset", default="default", choices=sorted(PRESET_MODELS))
    parser.add_argument("--model-id", default="", help="Override the model id for the selected preset.")
    parser.add_argument("--include-asr", action="store_true", help="Also download the optional SenseVoice ASR model.")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def run_download(model_id: str, *, force: bool) -> None:
    command = [
        sys.executable,
        str(WORKSPACE_ROOT / "scripts" / "download_modelscope_model.py"),
        "--model-id",
        model_id,
    ]
    if force:
        command.append("--force")
    subprocess.check_call(command, cwd=WORKSPACE_ROOT)


def main() -> int:
    args = parse_args()
    model_id = args.model_id.strip() or PRESET_MODELS[args.preset]
    run_download(model_id, force=args.force)
    if args.include_asr:
        run_download("iic/SenseVoiceSmall", force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
