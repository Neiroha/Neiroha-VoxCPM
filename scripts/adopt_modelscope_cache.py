from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
MODELS_ROOT = WORKSPACE_ROOT / "models"
DEFAULT_MODELSCOPE_CACHE_ROOT = Path.home() / ".cache" / "modelscope" / "hub" / "models"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move or copy a model that was already downloaded by ModelScope into the local ./models directory.",
    )
    parser.add_argument(
        "--model-id",
        required=True,
        help="ModelScope model id, for example iic/SenseVoiceSmall.",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_MODELSCOPE_CACHE_ROOT,
        help="Root directory of the existing ModelScope cache, defaulting to ~/.cache/modelscope/hub/models.",
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=MODELS_ROOT,
        help="Root directory that stores local project models, defaulting to ./models.",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy instead of moving. Default behavior is move.",
    )
    return parser.parse_args()


def sanitize_model_id(model_id: str) -> str:
    return model_id.replace("\\", "__").replace("/", "__").replace(":", "_")


def modelscope_cache_path(model_id: str, source_root: Path) -> Path:
    parts = [segment for segment in re.split(r"[\\/]+", model_id.strip()) if segment]
    if len(parts) < 2:
        raise ValueError(f"Expected a namespaced model id like 'org/name', got: {model_id}")
    return source_root.joinpath(*parts)


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


def main() -> None:
    args = parse_args()
    source_root = args.source_root.resolve()
    target_root = args.target_root.resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    model_id = args.model_id.strip()
    source_dir = modelscope_cache_path(model_id, source_root)
    target_dir = target_root / sanitize_model_id(model_id)

    if not source_dir.exists():
        raise FileNotFoundError(f"ModelScope cache model not found: {source_dir}")

    if target_dir.exists():
        file_count = sum(1 for path in target_dir.rglob("*") if path.is_file())
        total_size = dir_size_bytes(target_dir)
        print(f"Model already exists in project directory: {target_dir}")
        print(f"Files: {file_count}")
        print(f"Size: {format_bytes(total_size)} ({total_size} bytes)")
        return

    action = "Copying" if args.copy else "Moving"
    print(f"{action} ModelScope cache model")
    print(f"Model ID: {model_id}")
    print(f"Source: {source_dir}")
    print(f"Target: {target_dir}")

    if args.copy:
        shutil.copytree(source_dir, target_dir)
    else:
        shutil.move(str(source_dir), str(target_dir))

    file_count = sum(1 for path in target_dir.rglob("*") if path.is_file())
    total_size = dir_size_bytes(target_dir)

    print("")
    print("Model summary")
    print(f"Local path: {target_dir}")
    print(f"Files: {file_count}")
    print(f"Size: {format_bytes(total_size)} ({total_size} bytes)")
    print(f"Source still exists: {source_dir.exists()}")


if __name__ == "__main__":
    main()
