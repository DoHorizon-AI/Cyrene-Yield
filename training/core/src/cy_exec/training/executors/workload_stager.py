"""Training adapter over the provider-neutral Artifact Plane.

Separates:
- artifact identity (WorkloadConfigRef)
- Control Plane local path
- Worker mounted/visible path
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/workload_stager.py
# │ Module: training/core/src/cy_exec/training/executors/workload_stager
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Optional, Union

from cy_artifacts import (
    ArtifactKind,
    ArtifactProvider,
    LocalArtifactProvider,
    LocalArtifactStager,
    ResolvedArtifact,
    StagedArtifact,
    sha256_bytes,
)
from cyrene_yield_contracts import YieldArtifactKind
from ..contracts.spec import TrainingSpec
from ..contracts.workload import (
    TRAINING_SPEC_SCHEMA,
    TRAINING_SPEC_SCHEMA_VERSION,
    StagedWorkload,
    WorkloadConfigRef,
)

WORKER_CONFIG_FILENAME = "training-spec.json"
DEFAULT_WORKER_VISIBLE_DIR = "/input/config"


class MinimalWorkloadStager:
    """Compatibility adapter that publishes config before staging it."""

    def __init__(self, provider: Optional[ArtifactProvider] = None) -> None:
        self._provider = provider

    def _provider_for(self, staging_dir: str) -> ArtifactProvider:
        return self._provider or LocalArtifactProvider(Path(staging_dir) / ".artifact-store")

    @staticmethod
    def _kind_for_schema(schema: str) -> ArtifactKind:
        if schema == TRAINING_SPEC_SCHEMA:
            return ArtifactKind(YieldArtifactKind.TRAINING_SPEC)
        return ArtifactKind(YieldArtifactKind.GENERIC)

    @staticmethod
    def _local_worker_path(staging_dir: str, worker_visible_dir: str) -> Path:
        parts = [
            part
            for part in PurePosixPath(worker_visible_dir.replace("\\", "/")).parts
            if part not in ("", "/")
        ]
        return Path(staging_dir).joinpath(*parts, WORKER_CONFIG_FILENAME)

    @staticmethod
    def _worker_visible_path(worker_visible_dir: str) -> str:
        return f"{worker_visible_dir.rstrip('/')}/{WORKER_CONFIG_FILENAME}"

    def stage_bytes(
        self,
        payload: bytes,
        *,
        staging_dir: str,
        worker_visible_dir: str = DEFAULT_WORKER_VISIBLE_DIR,
        schema: str = TRAINING_SPEC_SCHEMA,
        schema_version: str = TRAINING_SPEC_SCHEMA_VERSION,
        materialize_worker_copy: bool = True,
    ) -> StagedWorkload:
        staging = Path(staging_dir)
        staging.mkdir(parents=True, exist_ok=True)
        provider = self._provider_for(staging_dir)
        ref = provider.publish_bytes(
            payload,
            kind=self._kind_for_schema(schema),
            producer="cyrene-yield.training",
            schema=schema,
        )
        resolved: ResolvedArtifact = provider.resolve(ref)
        worker_visible_path = self._worker_visible_path(worker_visible_dir)
        if materialize_worker_copy:
            staged: StagedArtifact = LocalArtifactStager(provider).stage(
                ref,
                self._local_worker_path(staging_dir, worker_visible_dir),
            )
            worker_visible_path = staged.worker_visible_path
        config_ref = WorkloadConfigRef.from_artifact_ref(ref)
        config_ref = WorkloadConfigRef(
            uri=config_ref.uri,
            digest=config_ref.digest,
            schema=schema,
            schema_version=schema_version,
            size_bytes=config_ref.size_bytes,
            kind=config_ref.kind,
            manifest_digest=config_ref.manifest_digest,
        )
        return StagedWorkload(
            config_ref=config_ref,
            control_plane_path=str(resolved.location),
            worker_visible_path=worker_visible_path,
        )

    def stage_spec(
        self,
        spec: TrainingSpec,
        *,
        staging_dir: str,
        worker_visible_dir: str = DEFAULT_WORKER_VISIBLE_DIR,
        materialize_worker_copy: bool = True,
    ) -> StagedWorkload:
        payload = json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.stage_bytes(
            payload,
            staging_dir=staging_dir,
            worker_visible_dir=worker_visible_dir,
            materialize_worker_copy=materialize_worker_copy,
        )

    def stage_path(
        self,
        source: Union[str, Path],
        *,
        staging_dir: str,
        schema: str,
        schema_version: str = "1",
        worker_visible_dir: str = DEFAULT_WORKER_VISIBLE_DIR,
        materialize_worker_copy: bool = True,
    ) -> StagedWorkload:
        payload = Path(source).read_bytes()
        return self.stage_bytes(
            payload,
            staging_dir=staging_dir,
            worker_visible_dir=worker_visible_dir,
            schema=schema,
            schema_version=schema_version,
            materialize_worker_copy=materialize_worker_copy,
        )


def verify_worker_config(path: str, expected: WorkloadConfigRef) -> bytes:
    payload = Path(path).read_bytes()
    digest = sha256_bytes(payload)
    if digest != expected.to_artifact_ref().digest:
        raise ValueError(
            f"worker-visible config digest mismatch: got {digest}, expected {expected.digest}"
        )
    if expected.size_bytes is not None and len(payload) != expected.size_bytes:
        raise ValueError("worker-visible config size mismatch")
    return payload
