"""Training-side output candidates.

The Artifact Plane lives in ``cy_artifacts``. These candidates retain the
producer path until a Training controller publishes them.

训练侧输出候选项。

Artifact Plane 位于 cy_artifacts 中。在 Training controller 发布这些候选项前,它们保留生产者路径。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/artifacts.py
# │ 中文:文件:training/core/src/cy_exec/training/contracts/artifacts.py
# │ Module: training/core/src/cy_exec/training/contracts/artifacts
# │ 模块:training/core/src/cy_exec/training/contracts/artifacts
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责:规范 Yield 训练 runtime,拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from cy_artifacts import ArtifactRef


@dataclass
class ArtifactCandidate:
    path: str
    kind: str
    digest: str = ""
    size_bytes: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)
    artifact_ref: Optional[ArtifactRef] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "extra": dict(self.extra),
            "artifact_ref": None if self.artifact_ref is None else self.artifact_ref.to_dict(),
        }


@dataclass
class OutputDescriptor:
    output_root: str
    model_dir: str
    checkpoint_dir: str
    metrics_path: str
    manifest_path: str
    artifacts: List[ArtifactCandidate] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output_root": self.output_root,
            "model_dir": self.model_dir,
            "checkpoint_dir": self.checkpoint_dir,
            "metrics_path": self.metrics_path,
            "manifest_path": self.manifest_path,
            "artifacts": [item.to_dict() for item in self.artifacts],
        }


def layout_paths(work_dir: str, layout: Any) -> OutputDescriptor:
    from pathlib import Path

    root = Path(work_dir) / layout.root
    return OutputDescriptor(
        output_root=str(root),
        model_dir=str(root / layout.model),
        checkpoint_dir=str(root / layout.checkpoints),
        metrics_path=str(root / layout.metrics),
        manifest_path=str(root / layout.manifest),
    )
