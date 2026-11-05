"""Immutable workload config identity. Not a TrainingSpec and not a local path.

Configure.settings may only carry this ref plus worker-visible staging pointers.
TrainingSpec remains the Product source of truth.

不可变工作负载配置身份。它不是 TrainingSpec,也不是本地路径。

Configure.settings 只可携带此引用以及 worker 可见的暂存指针。TrainingSpec 仍是 Product 的事实来源。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/workload.py
# │ 中文:文件:training/core/src/cy_exec/training/contracts/workload.py
# │ Module: training/core/src/cy_exec/training/contracts/workload
# │ 模块:training/core/src/cy_exec/training/contracts/workload
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责:规范 Yield 训练 runtime,拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from cy_artifacts import ArtifactKind, ArtifactRef
from cyrene_yield_contracts import YieldArtifactKind

TRAINING_SPEC_SCHEMA = "cyrene.training.spec"
TRAINING_SPEC_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class WorkloadConfigRef:
    uri: str
    digest: str
    schema: str = TRAINING_SPEC_SCHEMA
    schema_version: str = TRAINING_SPEC_SCHEMA_VERSION
    size_bytes: Optional[int] = None
    kind: str = YieldArtifactKind.GENERIC.value
    manifest_digest: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "uri": self.uri,
            "digest": self.digest,
            "schema": self.schema,
            "schema_version": self.schema_version,
        }
        if self.size_bytes is not None:
            payload["size_bytes"] = self.size_bytes
        payload["kind"] = self.kind
        if self.manifest_digest is not None:
            payload["manifest_digest"] = self.manifest_digest
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkloadConfigRef":
        return cls(
            uri=str(data["uri"]),
            digest=str(data["digest"]),
            schema=str(data.get("schema") or TRAINING_SPEC_SCHEMA),
            schema_version=str(data.get("schema_version") or TRAINING_SPEC_SCHEMA_VERSION),
            size_bytes=data.get("size_bytes"),
            kind=str(data.get("kind") or YieldArtifactKind.GENERIC.value),
            manifest_digest=data.get("manifest_digest"),
        )

    @classmethod
    def from_artifact_ref(cls, artifact_ref: ArtifactRef) -> "WorkloadConfigRef":
        return cls(
            uri=artifact_ref.uri,
            digest=artifact_ref.digest,
            size_bytes=artifact_ref.size_bytes,
            kind=artifact_ref.kind.value,
            manifest_digest=artifact_ref.manifest_digest,
        )

    def to_artifact_ref(self) -> ArtifactRef:
        return ArtifactRef(
            uri=self.uri,
            digest=self.digest,
            size_bytes=int(self.size_bytes or 0),
            kind=ArtifactKind(self.kind),
            manifest_digest=self.manifest_digest,
        )


@dataclass
class StagedWorkload:
    """Local staging result. control_plane_path must never be sent to a Worker.

    本地暂存结果。control_plane_path 绝不能发送给 Worker。
    """

    config_ref: WorkloadConfigRef
    control_plane_path: str
    worker_visible_path: str

    @property
    def artifact_ref(self) -> ArtifactRef:
        return self.config_ref.to_artifact_ref()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_ref": self.config_ref.to_dict(),
            "control_plane_path": self.control_plane_path,
            "worker_visible_path": self.worker_visible_path,
        }


@dataclass(frozen=True)
class WorkloadConfigureSettings:
    """Generic plugin Configure.settings. Not the TrainingSpec document.

    通用 Plugin Configure.settings,不是 TrainingSpec 文档。
    """

    workload_config_ref: WorkloadConfigRef
    worker_config_path: str
    output_root: str
    attempt_id: str
    execution_id: str

    def to_settings_map(self) -> Dict[str, str]:
        return {
            "workload_config_ref": self.workload_config_ref.to_json(),
            "worker_config_path": self.worker_config_path,
            "output_root": self.output_root,
            "attempt_id": self.attempt_id,
            "execution_id": self.execution_id,
        }

    @classmethod
    def from_settings_map(cls, settings: Dict[str, str]) -> "WorkloadConfigureSettings":
        ref = WorkloadConfigRef.from_dict(json.loads(settings["workload_config_ref"]))
        return cls(
            workload_config_ref=ref,
            worker_config_path=settings["worker_config_path"],
            output_root=settings["output_root"],
            attempt_id=settings["attempt_id"],
            execution_id=settings["execution_id"],
        )


def assert_configure_is_not_training_spec(settings: Dict[str, str]) -> None:
    forbidden = (
        "model",
        "dataset",
        "lora",
        "learning_rate",
        "batch",
        "hyperparams",
        "control_plane_path",
    )
    leaked = [key for key in forbidden if key in settings]
    if leaked:
        raise ValueError(f"Configure.settings must not carry TrainingSpec fields: {leaked}")
    if "workload_config_ref" not in settings:
        raise ValueError("Configure.settings requires workload_config_ref")
    ref = json.loads(settings["workload_config_ref"])
    if not isinstance(ref, dict) or "digest" not in ref or "uri" not in ref:
        raise ValueError("workload_config_ref must be a WorkloadConfigRef document")
