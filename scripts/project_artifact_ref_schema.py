"""Project the pinned Platform ArtifactRef schema into Yield's contract tree.

Platform owns the generic reference shape. Yield owns model and training
semantics and consumes an immutable, provenance-recorded projection.

Platform 维护通用引用结构；Yield 只维护模型与训练语义，并保留可复核的精确投影。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

PLATFORM_REPOSITORY = "DoHorizon-AI/Cyrene-Platform"
PLATFORM_REVISION = "c59be6f2bd82489fbe933dadff84fc589e00afd9"
PLATFORM_SCHEMA = "contracts/schemas/manifests/artifact_ref.schema.json"
TRAINING_RUN_SCHEMA = "contracts/product/v1/training-run.schema.json"


def _git_show(repository: Path, revision: str, path: str) -> bytes:
    """Read one immutable source object without modifying Platform. | 读取精确对象。"""

    return subprocess.check_output(["git", "-C", str(repository), "show", f"{revision}:{path}"])


def main() -> None:
    """Write or verify the generated schema and provenance. | 写入或校验投影。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-repository", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    source = _git_show(args.platform_repository, PLATFORM_REVISION, PLATFORM_SCHEMA)
    json.loads(source)
    root = Path(__file__).resolve().parents[1]
    training_run_path = root / TRAINING_RUN_SCHEMA
    training_run = json.loads(training_run_path.read_text(encoding="utf-8"))
    training_run["$defs"]["artifactRef"] = json.loads(source)
    training_run_bytes = (json.dumps(training_run, indent=2) + "\n").encode()

    provenance = (
        json.dumps(
            {
                "repository": PLATFORM_REPOSITORY,
                "revision": PLATFORM_REVISION,
                "sha256": {
                    PLATFORM_SCHEMA: hashlib.sha256(source).hexdigest(),
                    f"{TRAINING_RUN_SCHEMA}#/$defs/artifactRef": hashlib.sha256(source).hexdigest(),
                },
            },
            indent=2,
        )
        + "\n"
    ).encode()

    output = root / "contracts/product/v1/generated/platform"
    outputs = {
        output / "artifact-ref.schema.json": source,
        output / "lifecycle-sources.json": provenance,
        training_run_path: training_run_bytes,
    }
    for path, content in outputs.items():
        if args.check:
            if not path.is_file() or path.read_bytes() != content:
                raise RuntimeError(f"generated Platform projection differs: {path.name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    print(json.dumps({"platformRevision": PLATFORM_REVISION, "artifactRefVerified": True}))


if __name__ == "__main__":
    main()
