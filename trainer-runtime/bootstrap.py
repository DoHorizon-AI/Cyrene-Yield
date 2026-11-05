"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: trainer_runtime.bootstrap                                 │
│  Role: Materialize the locked CUDA trainer environment.            │
│                                                                     │
│  模块职责：部署锁定的 CUDA 训练环境，并以 probe 结果作为 READY 依据。       │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def _runtime_home(value: Path | None) -> Path:
    if value is None or not value.expanduser().is_absolute():
        raise ValueError("TRAINER_RUNTIME_HOME_REQUIRED")
    home = value.expanduser().resolve()
    if home == Path(home.anchor):
        raise ValueError("TRAINER_RUNTIME_HOME_INVALID")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    home.chmod(0o700)
    return home


def _repository() -> Path:
    return Path(__file__).resolve().parents[1]


def _verified_tool_version(command: list[str], expected: str, code: str) -> None:
    """Require one explicitly selected build tool to match its signed release descriptor.

    要求显式选定的构建工具与签名发布描述中的版本一致。
    """

    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    output = (result.stdout + result.stderr).strip().split()
    if result.returncode or len(output) < 2 or output[1] != expected:
        raise ValueError(code)


def run(args: argparse.Namespace) -> int:
    """Sync the exact lock into runtime home, then execute the canonical probe.

    将精确锁定的依赖同步到 runtime home,然后执行规范探测。
    """

    home = _runtime_home(args.runtime_home)
    project = Path(__file__).resolve().parent
    repository = _repository()
    uv = args.uv_executable or shutil.which("uv")
    if uv is None:
        raise ValueError("UV_UNAVAILABLE")
    uv_path = Path(uv).expanduser().resolve()
    if not uv_path.is_file() or not os.access(uv_path, os.X_OK):
        raise ValueError("UV_UNAVAILABLE")
    if args.uv_version:
        _verified_tool_version([str(uv_path), "--version"], args.uv_version, "UV_VERSION_MISMATCH")

    python_argument = "3.12"
    if args.python_executable:
        python_path = Path(args.python_executable).expanduser().resolve()
        if not python_path.is_file() or not os.access(python_path, os.X_OK):
            raise ValueError("PYTHON_RUNTIME_UNAVAILABLE")
        if args.python_version:
            _verified_tool_version([str(python_path), "--version"], args.python_version, "PYTHON_VERSION_MISMATCH")
        python_argument = str(python_path)
    elif args.python_version:
        raise ValueError("PYTHON_RUNTIME_DESCRIPTOR_INCOMPLETE")

    repository = args.repository.expanduser().resolve() if args.repository else _repository()
    environment = dict(os.environ)
    environment["UV_PROJECT_ENVIRONMENT"] = str(home / "venv")
    environment["UV_CACHE_DIR"] = str(home / "cache")
    if args.command == "bootstrap":
        result = subprocess.run(
            [
                str(uv_path),
                "sync",
                "--project",
                str(project),
                "--locked",
                "--no-dev",
                "--python",
                python_argument,
            ],
            check=False,
            env=environment,
            timeout=3600,
        )
        if result.returncode:
            raise ValueError("TRAINER_SYNC_FAILED")
    python = home / "venv" / "bin" / "python"
    if not python.is_file():
        raise ValueError("TRAINER_ENVIRONMENT_MISSING")
    command = [
        str(python),
        "-I",
        str(project / "probe.py"),
        "--repository",
        str(repository),
        "--output",
        str(home / "runtime.json"),
    ]
    if args.allow_no_cuda:
        command.append("--allow-no-cuda")
    return subprocess.run(command, check=False, timeout=180).returncode


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Cyrene Yield trainer runtime")
    value.add_argument("command", choices=("bootstrap", "status"))
    value.add_argument(
        "--runtime-home",
        type=Path,
        default=Path(os.environ["CYRENE_TRAINER_RUNTIME_HOME"])
        if os.environ.get("CYRENE_TRAINER_RUNTIME_HOME")
        else None,
    )
    value.add_argument("--repository", type=Path, help="Verified execution-runtime source root")
    value.add_argument("--python-executable", help="Pinned base CPython executable from the bundle descriptor")
    value.add_argument("--python-version", help="Exact base CPython version from the bundle descriptor")
    value.add_argument("--uv-executable", help="Pinned uv executable from the bundle descriptor")
    value.add_argument("--uv-version", help="Exact uv version from the bundle descriptor")
    value.add_argument(
        "--allow-no-cuda",
        action="store_true",
        help="Hosted lock/protocol validation only; never produces canonical GPU evidence",
    )
    return value


def main() -> int:
    try:
        return run(parser().parse_args())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAILED", "code": str(exc).split(":", 1)[0]}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
