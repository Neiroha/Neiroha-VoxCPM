from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = ROOT / ".pixi" / "envs" / "default"
PYTHON_EXE = ENV_DIR / "python.exe"
VOXCPM_SRC = ROOT / "VoxCPM" / "src"
MAIN_MODEL = ROOT / "models" / "OpenBMB__VoxCPM2" / "model.safetensors"


def prepend_path_env(name: str, values: list[Path]) -> None:
    existing = os.environ.get(name, "")
    parts = [str(value) for value in values if value]
    if existing:
        parts.append(existing)
    os.environ[name] = os.pathsep.join(parts)


def configure_environment() -> None:
    prepend_path_env(
        "PATH",
        [
            ENV_DIR,
            ENV_DIR / "Scripts",
            ENV_DIR / "Library" / "bin",
            ENV_DIR / "Library" / "usr" / "bin",
        ],
    )
    prepend_path_env("PYTHONPATH", [ROOT, VOXCPM_SRC])

    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("TMP", str(ROOT / "runtime" / "temp"))
    os.environ.setdefault("TEMP", str(ROOT / "runtime" / "temp"))
    os.environ.setdefault("TMPDIR", str(ROOT / "runtime" / "temp"))
    os.environ.setdefault("GRADIO_TEMP_DIR", str(ROOT / "runtime" / "temp" / "gradio"))
    os.environ.setdefault("MODELSCOPE_CACHE", str(ROOT / "runtime" / "cache" / "modelscope"))
    os.environ.setdefault("MODELSCOPE_MODULES_CACHE", str(ROOT / "runtime" / "cache" / "modelscope" / "modules"))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    for directory in (
        ROOT / "runtime" / "temp",
        ROOT / "runtime" / "cache" / "modelscope",
        ROOT / "runtime" / "logs",
        ROOT / "runtime" / "outputs",
    ):
        directory.mkdir(parents=True, exist_ok=True)


def repair_editable_install() -> None:
    site_packages = ENV_DIR / "Lib" / "site-packages"
    for pth_file in site_packages.glob("__editable__.voxcpm*.pth"):
        try:
            pth_file.write_text(str(VOXCPM_SRC), encoding="utf-8")
        except OSError:
            # PYTHONPATH already points at the unpacked VoxCPM source, so this
            # repair is best-effort for copied Pixi environments.
            pass


def check_portable_layout() -> bool:
    ok = True
    if not PYTHON_EXE.exists():
        print("[错误] 找不到便携 Python 环境:")
        print(f"  {PYTHON_EXE}")
        ok = False

    if not (VOXCPM_SRC / "voxcpm" / "__init__.py").exists():
        print("[错误] 找不到 VoxCPM 源码目录:")
        print(f"  {VOXCPM_SRC}")
        ok = False

    if not (ROOT / "scripts" / "launch_engine.py").exists():
        print("[错误] 找不到启动脚本 scripts/launch_engine.py")
        ok = False

    if not MAIN_MODEL.exists():
        print("[警告] 没有找到主模型:")
        print(f"  {MAIN_MODEL}")
        print("如果这是完整离线包，请检查 models 目录是否打包完整。")
        print("如果只是环境包，首次运行前需要先准备模型。")
        print()

    return ok


def launcher_command(*args: str) -> list[str]:
    return [str(PYTHON_EXE), "-B", str(ROOT / "scripts" / "launch_engine.py"), *args]


def run_launcher(*args: str) -> int:
    print()
    try:
        return subprocess.call(launcher_command(*args), cwd=ROOT, env=os.environ.copy())
    except KeyboardInterrupt:
        print()
        print("已收到停止请求。")
        return 130


def wait_for_enter(prompt: str = "按回车返回菜单...") -> None:
    try:
        input(prompt)
    except EOFError:
        pass


def show_menu() -> str:
    print()
    print("========================================")
    print("  Neiroha VoxCPM Portable")
    print("========================================")
    print("  1. 启动 API + 管理页 (推荐)")
    print("  2. 只启动 API")
    print("  3. 只启动管理页 (需要已有 API)")
    print("  4. 启动官方 VoxCPM WebUI")
    print("  5. 查看启动参数帮助")
    print("  0. 退出")
    print("========================================")
    try:
        return input("请输入数字并回车: ").strip()
    except EOFError:
        return "0"


def main() -> int:
    configure_environment()
    repair_editable_install()
    if not check_portable_layout():
        wait_for_enter("按回车退出...")
        return 1

    actions = {
        "1": ("both", "API + 管理页"),
        "2": ("api", "API"),
        "3": ("admin", "管理页"),
        "4": ("webui", "官方 VoxCPM WebUI"),
    }

    while True:
        if sys.stdin.isatty():
            os.system("cls")
        choice = show_menu()
        if choice == "0":
            return 0
        if choice == "5":
            run_launcher("--help")
            wait_for_enter()
            continue
        if choice not in actions:
            print()
            print("输入无效，请重新选择。")
            wait_for_enter()
            continue

        surface, label = actions[choice]
        print()
        print(f"正在启动: {label}")
        print("按 Ctrl+C 可停止服务。")
        exit_code = run_launcher("--surface", surface)
        print()
        print(f"服务已退出，退出码: {exit_code}")
        wait_for_enter()


if __name__ == "__main__":
    raise SystemExit(main())
