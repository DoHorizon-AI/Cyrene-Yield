"""
┌─────────────────────────────────────────────────────────────────────┐
│  📄 generate_kernel_descriptor.py                                  │
│  Module: yield.scripts                                   │
│  Role: Generate the client descriptor from pinned Platform sources.│
│  模块职责：从平台精确提交生成描述符，不新增协议权威或修改平台目录。           │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.resources
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    """Compile canonical bytes and compare or write their provenance. | 编译规范字节,并比较或写入其来源信息。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-repository", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    revision = "c59be6f2bd82489fbe933dadff84fc589e00afd9"

    def git(*command: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(args.platform_repository), *command])

    files = sorted(
        name
        for name in git("ls-tree", "-r", "--name-only", revision, "contracts/proto").decode().splitlines()
        if name.endswith(".proto")
    )
    if not files:
        raise RuntimeError("Pinned Platform revision has no canonical protobuf sources")
    sources = {}
    with tempfile.TemporaryDirectory(prefix="yield-descriptor-") as temporary:
        stage = Path(temporary)
        for name in files:
            data = git("show", revision + ":" + name)
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            sources[name] = hashlib.sha256(data).hexdigest()
        generated = stage / "kernel.desc"
        include = importlib.resources.files("grpc_tools").joinpath("_proto")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "grpc_tools.protoc",
                "-I" + str(stage / "contracts/proto"),
                "-I" + str(include),
                "--include_imports",
                "--descriptor_set_out=" + str(generated),
                *[str(stage / name) for name in files],
            ],
            check=True,
        )
        descriptor = generated.read_bytes()
    evidence = {
        "platformRevision": revision,
        "grpcioToolsVersion": importlib.metadata.version("grpcio-tools"),
        "descriptorSha256": hashlib.sha256(descriptor).hexdigest(),
        "sourceSha256": sources,
    }
    package = root / "training/core/src/cy_exec/training/executors"
    outputs = {
        package / "kernel.desc": descriptor,
        package / "kernel-descriptor.json": (json.dumps(evidence, indent=2) + "\n").encode(),
    }
    for path, data in outputs.items():
        if args.check:
            if path.read_bytes() != data:
                raise RuntimeError("Generated Platform projection differs: " + path.name)
        else:
            path.write_bytes(data)
    print(json.dumps({"platformRevision": revision, "descriptorVerified": True}))


if __name__ == "__main__":
    main()
