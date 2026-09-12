"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.product_cli                                │
│  Role: Start the standalone Yield Product HTTP service.             │
│  模块职责：以明确的运维参数启动独立 Yield 产品服务。                     │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import uvicorn

from .executors.kernel_training import KernelTrainingConfiguration
from .product_api import create_app

PLATFORM_RUNTIME_PROFILE = "CYRENE_PLATFORM_RUNTIME_V1_LOCAL_GPU"
TRAINER_PROFILE = "CYRENE_YIELD_TRAINER_V1_CUDA128"


def _private_manifest(path: Path, profile: str) -> dict[str, Any]:
    """Read one private READY manifest and enforce its profile boundary."""

    if path.stat().st_mode & 0o077:
        raise ValueError("RUNTIME_CONFIG_PERMISSIONS: expected mode 0600")
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != 1
        or document.get("profile") != profile
        or document.get("status") != "READY"
    ):
        raise ValueError("RUNTIME_CONFIG_INVALID: expected a compatible READY manifest")
    return document


def _runtime_from_manifests(
    *, state_directory: Path, runtime_config: Path, trainer_runtime_config: Path
) -> tuple[Path, KernelTrainingConfiguration]:
    """Resolve all Kernel topology and trainer paths from canonical manifests."""

    runtime = _private_manifest(runtime_config, PLATFORM_RUNTIME_PROFILE)
    trainer = _private_manifest(trainer_runtime_config, TRAINER_PROFILE)
    if any(
        value.get("status") != "READY" for value in runtime.get("components", {}).values() if isinstance(value, dict)
    ):
        raise ValueError("RUNTIME_COMPONENT_UNAVAILABLE: bootstrap Platform again")
    kernel = runtime.get("kernel")
    if not isinstance(kernel, dict):
        raise ValueError("RUNTIME_CONFIG_INVALID: Kernel projection is missing")
    artifact_root = Path(str(runtime.get("artifactRoot", "")))
    installations = Path(str(runtime.get("installationsRoot", "")))
    signing_key = Path(str(runtime.get("signingKeyFile", "")))
    socket = Path(str(kernel.get("socket", "")))
    python = Path(str(trainer.get("python", "")))
    if (
        not artifact_root.is_absolute()
        or not artifact_root.is_dir()
        or not installations.is_absolute()
        or not installations.is_dir()
        or not socket.is_absolute()
        or not socket.is_socket()
        or not signing_key.is_absolute()
        or not signing_key.is_file()
        or signing_key.stat().st_mode & 0o077
        or signing_key.stat().st_size != 32
        or not python.is_absolute()
        or not python.is_file()
        or not os.access(python, os.X_OK)
    ):
        raise ValueError("RUNTIME_CONFIG_UNAVAILABLE: bootstrap runtime components again")
    host = runtime.get("host")
    allow_wsl = (
        runtime.get("runtimeMode") == "WSL_DEV_PROFILE"
        and isinstance(host, dict)
        and host.get("gpuRuntime") == "WSL2_CUDA"
        and host.get("hardIsolation") is False
    )
    return artifact_root, KernelTrainingConfiguration(
        socket=socket,
        installations=installations,
        signing_key_file=signing_key,
        python=python,
        state_directory=state_directory,
        allow_wsl_shared_device=allow_wsl,
    )


def main() -> None:
    """Expose documented public APIs; operator paths never enter resource identities."""
    parser = argparse.ArgumentParser(description="Cyrene Yield Text Model Lifecycle V1")
    parser.add_argument("--state-directory", required=True, type=Path)
    parser.add_argument("--runtime-config", type=Path)
    parser.add_argument("--trainer-runtime-config", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--kernel-socket", type=Path)
    parser.add_argument("--installations", type=Path)
    parser.add_argument("--signing-key-file", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--allow-wsl-shared-device", action="store_true")
    parser.add_argument("--reactor-url")
    parser.add_argument("--reactor-token-env", help="Name of the Reactor Product credential variable")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8092)
    args = parser.parse_args()
    token = os.environ.get(args.reactor_token_env) if args.reactor_token_env else None
    if args.reactor_token_env and not token:
        parser.error("The configured Reactor credential variable is empty")
    kernel: KernelTrainingConfiguration | None = None
    if args.runtime_config or args.trainer_runtime_config:
        if not args.runtime_config or not args.trainer_runtime_config:
            parser.error("--runtime-config and --trainer-runtime-config are required together")
        if (
            any(
                value is not None
                for value in (
                    args.artifact_root,
                    args.kernel_socket,
                    args.installations,
                    args.signing_key_file,
                    args.python,
                )
            )
            or args.allow_wsl_shared_device
        ):
            parser.error("Runtime manifests cannot be combined with individual topology paths")
        try:
            artifact_root, kernel = _runtime_from_manifests(
                state_directory=args.state_directory,
                runtime_config=args.runtime_config,
                trainer_runtime_config=args.trainer_runtime_config,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
    else:
        if args.artifact_root is None:
            parser.error("--artifact-root or --runtime-config is required")
        artifact_root = args.artifact_root
    if args.kernel_socket and kernel is None:
        if not args.installations or not args.signing_key_file:
            parser.error("--kernel-socket requires --installations and --signing-key-file")
        kernel = KernelTrainingConfiguration(
            socket=args.kernel_socket,
            installations=args.installations,
            signing_key_file=args.signing_key_file,
            python=args.python or Path(sys.executable),
            state_directory=args.state_directory,
            allow_wsl_shared_device=args.allow_wsl_shared_device,
        )
    app = create_app(
        state_directory=args.state_directory,
        artifact_root=artifact_root,
        kernel=kernel,
        reactor_url=args.reactor_url,
        reactor_bearer_token=token,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
