from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = WORKSPACE_ROOT / "runtime"
TEMP_DIR = RUNTIME_ROOT / "temp"
MODELS_ROOT = WORKSPACE_ROOT / "models"
CACHE_ROOT = MODELS_ROOT / "_modelscope_cache"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
MODELS_ROOT.mkdir(parents=True, exist_ok=True)
CACHE_ROOT.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("TMPDIR", str(TEMP_DIR))
os.environ.setdefault("TEMP", str(TEMP_DIR))
os.environ.setdefault("TMP", str(TEMP_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download VoxCPM weights from ModelScope into the local runtime/models directory.",
    )
    parser.add_argument(
        "--model-id",
        default="OpenBMB/VoxCPM2",
        help="ModelScope model id, for example OpenBMB/VoxCPM2 or OpenBMB/VoxCPM1.5.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=MODELS_ROOT,
        help="Root directory that stores downloaded models, defaulting to ./models.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=CACHE_ROOT,
        help="Project-local ModelScope cache/lock directory. This avoids using the system default cache path.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload even if the target directory already looks complete.",
    )
    return parser.parse_args()


def sanitize_model_id(model_id: str) -> str:
    return model_id.replace("\\", "__").replace("/", "__").replace(":", "_")


def format_bytes(size: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{size} B"


def dir_size_bytes(path: Path) -> int:
    total = 0
    for file_path in path.rglob("*"):
        if file_path.is_file():
            total += file_path.stat().st_size
    return total


def read_architecture(model_dir: Path) -> str | None:
    config_path = model_dir / "config.json"
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    architecture = config.get("architecture")
    return str(architecture) if architecture else None


def looks_like_downloaded_model(model_dir: Path) -> bool:
    required_markers = [
        model_dir / "config.json",
        model_dir / "configuration.json",
        model_dir / "model.safetensors",
        model_dir / "model.pt",
    ]
    return model_dir.exists() and any(path.exists() for path in required_markers)


def main() -> None:
    from modelscope import snapshot_download

    args = parse_args()
    output_root = args.output_root.resolve()
    cache_dir = args.cache_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    model_id = args.model_id.strip()
    target_dir = output_root / sanitize_model_id(model_id)

    looks_complete = looks_like_downloaded_model(target_dir)
    if looks_complete and not args.force:
        print(f"Model already exists, skipping download: {target_dir}")
    else:
        print(f"Downloading from ModelScope: {model_id}")
        print(f"Target directory: {target_dir}")
        print(f"Cache directory: {cache_dir}")
        snapshot_download(
            model_id,
            local_dir=str(target_dir),
            cache_dir=str(cache_dir),
        )
        print("Download finished.")

    total_size = dir_size_bytes(target_dir)
    architecture = read_architecture(target_dir) or "unknown"
    file_count = sum(1 for path in target_dir.rglob("*") if path.is_file())

    print("")
    print("Model summary")
    print(f"Model ID: {model_id}")
    print(f"Local path: {target_dir}")
    print(f"Cache path: {cache_dir}")
    print(f"Architecture: {architecture}")
    print(f"Files: {file_count}")
    print(f"Size: {format_bytes(total_size)} ({total_size} bytes)")


if __name__ == "__main__":
    main()
