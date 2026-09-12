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


def run(args: argparse.Namespace) -> int:
    """Sync the exact lock into runtime home, then execute the canonical probe."""

    home = _runtime_home(args.runtime_home)
    project = Path(__file__).resolve().parent
    repository = _repository()
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("UV_UNAVAILABLE")
    environment = dict(os.environ)
    environment["UV_PROJECT_ENVIRONMENT"] = str(home / "venv")
    environment["UV_CACHE_DIR"] = str(home / "cache")
    if args.command == "bootstrap":
        result = subprocess.run(
            [
                uv,
                "sync",
                "--project",
                str(project),
                "--locked",
                "--no-dev",
                "--python",
                "3.12",
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
