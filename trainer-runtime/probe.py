"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: trainer_runtime.probe                                     │
│  Role: Validate CUDA, package versions and Kernel protocol inputs.  │
│                                                                     │
│  模块职责：校验 CUDA、训练依赖版本与 Kernel 协议兼容性。                  │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from google.protobuf import descriptor_pb2
from packaging.specifiers import SpecifierSet

PROFILE = "CYRENE_YIELD_TRAINER_V1_CUDA128"
REQUIREMENTS = {
    "grpcio": "==1.83.0",
    "protobuf": "==7.36.0",
    "torch": "==2.8.0",
}


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package, requirement in REQUIREMENTS.items():
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError(f"TRAINER_PACKAGE_MISSING:{package}") from exc
        if version not in SpecifierSet(requirement):
            raise ValueError(f"TRAINER_PACKAGE_INCOMPATIBLE:{package}")
        versions[package] = version
    return versions


def _protocol(repository: Path) -> dict[str, Any]:
    descriptor = repository / "training/core/src/cy_exec/training/executors/kernel.desc"
    metadata = repository / "training/core/src/cy_exec/training/executors/kernel-descriptor.json"
    worker = repository / "training/core/src/cy_exec/training/executors/training_worker.py"
    if not descriptor.is_file() or not metadata.is_file() or not worker.is_file():
        raise ValueError("TRAINER_PROTOCOL_INPUT_MISSING")
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    descriptor_set.ParseFromString(descriptor.read_bytes())
    services = {f"{file.package}.{service.name}" for file in descriptor_set.file for service in file.service}
    required = {
        "cyrene.core.v1.KernelAuthorityService",
        "cyrene.core.v1.KernelService",
        "cyrene.core.v1.WorkerControlService",
    }
    if not required.issubset(services):
        raise ValueError("TRAINER_PROTOCOL_INCOMPATIBLE")
    compile_result = subprocess.run(
        [os.sys.executable, "-m", "py_compile", str(worker)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
    )
    if compile_result.returncode:
        raise ValueError("TRAINER_WORKER_INCOMPATIBLE")
    return {
        "descriptorDigest": _sha256(descriptor),
        "serviceCount": len(services),
    }


def probe(repository: Path, *, require_cuda: bool = True) -> dict[str, Any]:
    """Validate the installed runtime without loading a model or allocating VRAM.

    验证已安装的 runtime,不加载模型或分配 VRAM。
    """

    versions = _versions()
    import torch

    cuda_available = bool(torch.cuda.is_available())
    if require_cuda and not cuda_available:
        raise ValueError("TRAINER_CUDA_UNAVAILABLE")
    cuda = {
        "available": cuda_available,
        "runtime": torch.version.cuda,
        "deviceCount": torch.cuda.device_count() if cuda_available else 0,
    }
    if require_cuda and (not cuda["runtime"] or int(cuda["deviceCount"]) < 1):
        raise ValueError("TRAINER_CUDA_INCOMPATIBLE")
    return {
        "schemaVersion": 1,
        "profile": PROFILE,
        "status": "READY",
        "python": os.sys.executable,
        "packages": versions,
        "cuda": cuda,
        "protocol": _protocol(repository),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the Cyrene Yield trainer runtime")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-no-cuda", action="store_true")
    args = parser.parse_args()
    try:
        result = probe(args.repository.resolve(), require_cuda=not args.allow_no_cuda)
        if args.output:
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            args.output.chmod(0o600)
        public = {key: result[key] for key in ("schemaVersion", "profile", "status", "packages", "cuda", "protocol")}
        print(json.dumps(public, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        code = str(exc).split(":", 1)[0]
        print(json.dumps({"status": "FAILED", "code": code}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
