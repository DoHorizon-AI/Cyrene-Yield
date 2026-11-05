"""Closed, browser-safe response projections for private Workspace routes.

私有 Workspace 路由使用闭合且适合浏览器展示的响应投影。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field

from .product_models import (
    ArtifactRef,
    DatasetVersionRef,
    TrainingAttemptResource,
    TrainingDraft,
    TrainingEventResource,
    TrainingEventsPage,
    TrainingParameters,
    TrainingRunResource,
    ContractModel,
)
from .workspace_auth import WorkspaceScope


class WorkspaceArtifactProjection(ContractModel):
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    kind: Literal[
        "generic", "model", "dataset", "checkpoint", "training_spec", "metrics", "merged", "quantized", "report"
    ]
    manifest_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class WorkspaceDatasetVersionProjection(ContractModel):
    id: UUID
    resource_version: int = Field(ge=1)
    artifact: WorkspaceArtifactProjection
    validation_artifact: WorkspaceArtifactProjection | None = None
    format: Literal["ALPACA_JSONL"]


class WorkspaceBaseModelProjection(ContractModel):
    artifact: WorkspaceArtifactProjection
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")


class WorkspaceTrainingConfigurationProjection(ContractModel):
    base_model: WorkspaceBaseModelProjection
    parameters: TrainingParameters


class WorkspaceImportedParametersProjection(ContractModel):
    parameters: TrainingParameters


class WorkspaceTrainingDraftProjection(ContractModel):
    id: UUID
    state: Literal["DRAFT", "PREPARED", "STARTED"]
    name: str = Field(pattern=r"^[^/\\:]{1,200}$")
    resource_version: int = Field(ge=1)
    dataset_version: WorkspaceDatasetVersionProjection
    configuration: WorkspaceTrainingConfigurationProjection | None = None
    imported_parameters: WorkspaceImportedParametersProjection | None = None
    training_run_id: UUID | None = None
    cancellation_requested_at: datetime | None = None
    created_at: datetime


class WorkspaceTrainingParameterProjection(ContractModel):
    epochs: float = Field(gt=0, le=100)
    per_device_batch_size: int = Field(ge=1, le=64)
    gradient_accumulation_steps: int = Field(ge=1, le=1024)
    learning_rate: float = Field(gt=0, le=1)
    max_sequence_length: int = Field(ge=16, le=32768)


class WorkspaceTrainingSpecProjection(ContractModel):
    model_artifact: WorkspaceArtifactProjection
    dataset_version: WorkspaceDatasetVersionProjection
    method: Literal["SFT"]
    finetuning_type: Literal["LORA"]
    parameters: WorkspaceTrainingParameterProjection


class WorkspaceProducedArtifactProjection(ContractModel):
    kind: Literal["MODEL_CHECKPOINT", "MODEL_ADAPTER", "METRICS", "TRAINING_MANIFEST"]
    artifact: WorkspaceArtifactProjection
    derived_from_digests: list[Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]]


class WorkspaceTrainingFailureProjection(ContractModel):
    code: str = Field(pattern=r"^[A-Z0-9_]{1,100}$")
    retryable: bool


class WorkspaceTrainingResultProjection(ContractModel):
    id: UUID
    model_version_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    adapter_artifact: WorkspaceArtifactProjection
    checkpoint_artifacts: list[WorkspaceArtifactProjection]
    created_at: datetime


class WorkspaceTrainingRunProjection(ContractModel):
    id: UUID
    draft_id: UUID
    state: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLING", "CANCELLED", "AWAITING_RETRY"]
    spec: WorkspaceTrainingSpecProjection
    attempt_count: int = Field(ge=0)
    output_artifacts: list[WorkspaceProducedArtifactProjection]
    created_at: datetime
    updated_at: datetime
    resource_version: int = Field(ge=1)
    cancellation_requested_at: datetime | None = None
    result: WorkspaceTrainingResultProjection | None = None
    failure: WorkspaceTrainingFailureProjection | None = None


class WorkspaceScopedTrainingRunProjection(WorkspaceTrainingRunProjection):
    """Run projection bound to the authenticated Workspace and invocation id.

    将任务响应绑定到已认证 Workspace 与 invocation resource id。
    """

    organization_id: str = Field(min_length=1, max_length=200)
    workspace_id: str = Field(min_length=1, max_length=200)
    training_run_id: UUID


class WorkspaceTrainingCheckpointProjection(ContractModel):
    """Closed checkpoint metadata safe to return through Workspace reads.

    可经 Workspace 读取返回的闭合 checkpoint 元数据。
    """

    name: str | None = Field(default=None, max_length=200)
    step: int | None = Field(default=None, ge=0)
    epoch: float | None = None
    digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)


class WorkspaceTrainingEventProjection(ContractModel):
    """Bounded browser-safe event projection without arbitrary payload fields.

    有界浏览器事件投影，不转发任意 payload 字段。
    """

    sequence: int = Field(ge=1)
    training_run_id: UUID
    attempt_id: str = Field(min_length=1, max_length=200)
    phase: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=100)
    message: str = Field(max_length=8192)
    step: int | None = Field(default=None, ge=0)
    total_steps: int | None = Field(default=None, ge=0)
    epoch: float | None = None
    loss: float | None = None
    learning_rate: float | None = None
    throughput: float | None = None
    eta_seconds: float | None = None
    checkpoint: WorkspaceTrainingCheckpointProjection | None = None
    timestamp: datetime


class WorkspaceTrainingEventsPageProjection(ContractModel):
    """Workspace-bound event page whose run identity and cursor travel together.

    Workspace 事件页携带任务身份与游标，避免跨任务拼接序号。
    """

    organization_id: str = Field(min_length=1, max_length=200)
    workspace_id: str = Field(min_length=1, max_length=200)
    training_run_id: UUID
    events: list[WorkspaceTrainingEventProjection] = Field(max_length=100)
    after_sequence: int = Field(ge=0)
    next_sequence: int = Field(ge=0)
    terminal: bool
    state: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLING", "CANCELLED", "AWAITING_RETRY"]


class WorkspaceTrainingAttemptsProjection(ContractModel):
    """Workspace-bound attempt list for one exact training run.

    将阶段尝试列表绑定到一个精确训练任务和 Workspace。
    """

    organization_id: str = Field(min_length=1, max_length=200)
    workspace_id: str = Field(min_length=1, max_length=200)
    training_run_id: UUID
    attempts: list[TrainingAttemptResource] = Field(max_length=100)


def project_workspace_scoped_training_run(
    run: TrainingRunResource,
    scope: WorkspaceScope,
) -> WorkspaceScopedTrainingRunProjection:
    """Bind the owner run projection to the authenticated scope and requested id.

    将 owner run 投影绑定到已认证 scope 和请求中的任务身份。
    """

    return WorkspaceScopedTrainingRunProjection(
        **project_workspace_training_run(run).model_dump(),
        organization_id=scope.organization_id,
        workspace_id=scope.workspace_id,
        training_run_id=run.id,
    )


def project_workspace_run_events(
    page: TrainingEventsPage,
    *,
    run_id: UUID,
    scope: WorkspaceScope,
) -> WorkspaceTrainingEventsPageProjection:
    """Bind a bounded event page and every event to one authorized run.

    将有界事件页及每条事件绑定到同一个已授权任务。
    """

    events: list[WorkspaceTrainingEventProjection] = []
    for event in page.events:
        if event.training_run_id != run_id:
            raise ValueError("YIELD_EVENT_RUN_SCOPE_MISMATCH")
        checkpoint = event.checkpoint or {}
        checkpoint_projection = WorkspaceTrainingCheckpointProjection(
            name=_safe_checkpoint_name(checkpoint.get("name", checkpoint.get("checkpointName"))),
            step=_safe_nonnegative_int(checkpoint.get("step")),
            epoch=_safe_number(checkpoint.get("epoch")),
            digest=_safe_digest(checkpoint.get("digest")),
            size_bytes=_safe_nonnegative_int(checkpoint.get("sizeBytes", checkpoint.get("size_bytes"))),
        )
        safe_checkpoint: WorkspaceTrainingCheckpointProjection | None = (
            checkpoint_projection if checkpoint_projection.model_dump(exclude_none=True) else None
        )
        events.append(
            WorkspaceTrainingEventProjection(
                sequence=event.sequence,
                training_run_id=event.training_run_id,
                attempt_id=event.attempt_id,
                phase=event.phase,
                kind=event.kind,
                message=event.message[:8192],
                step=event.step,
                total_steps=event.total_steps,
                epoch=event.epoch,
                loss=event.loss,
                learning_rate=event.learning_rate,
                throughput=event.throughput,
                eta_seconds=event.eta_seconds,
                checkpoint=safe_checkpoint,
                timestamp=datetime.fromisoformat(event.timestamp.replace("Z", "+00:00")),
            )
        )
    return WorkspaceTrainingEventsPageProjection(
        organization_id=scope.organization_id,
        workspace_id=scope.workspace_id,
        training_run_id=run_id,
        events=events,
        after_sequence=page.after_sequence,
        next_sequence=page.next_sequence,
        terminal=page.terminal,
        state=page.state,
    )


def project_workspace_run_attempts(
    attempts: list[TrainingAttemptResource],
    *,
    run_id: UUID,
    scope: WorkspaceScope,
) -> WorkspaceTrainingAttemptsProjection:
    """Bind every sanitized attempt to the requested Workspace run.

    将脱敏阶段尝试列表绑定到请求中的 Workspace 任务。
    """

    if any(attempt.training_run_id != run_id for attempt in attempts):
        raise ValueError("YIELD_ATTEMPT_RUN_SCOPE_MISMATCH")
    return WorkspaceTrainingAttemptsProjection(
        organization_id=scope.organization_id,
        workspace_id=scope.workspace_id,
        training_run_id=run_id,
        attempts=attempts,
    )


def _safe_checkpoint_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200]


def _safe_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _safe_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _safe_digest(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return value
    return None


_MODEL_VERSION_ID = re.compile(r"^model-version://sha256/([0-9a-f]{64})$")
_SAFE_DISPLAY_LABEL = re.compile(r"^[^/\\:]{1,200}$")


def _artifact_projection(artifact: ArtifactRef) -> WorkspaceArtifactProjection:
    return WorkspaceArtifactProjection(
        digest=artifact.digest,
        size_bytes=artifact.size_bytes,
        kind=artifact.kind,
        manifest_digest=artifact.manifest_digest,
    )


def _dataset_projection(dataset: DatasetVersionRef) -> WorkspaceDatasetVersionProjection:
    return WorkspaceDatasetVersionProjection(
        id=dataset.id,
        resource_version=dataset.resource_version,
        artifact=_artifact_projection(dataset.artifact),
        validation_artifact=(
            _artifact_projection(dataset.validation_artifact) if dataset.validation_artifact is not None else None
        ),
        format=dataset.format,
    )


def _artifact_projection_from_mapping(value: Mapping[str, Any]) -> WorkspaceArtifactProjection:
    size_bytes = value.get("sizeBytes", value.get("size_bytes"))
    manifest_digest = value.get("manifestDigest", value.get("manifest_digest"))
    return WorkspaceArtifactProjection(
        digest=value["digest"],
        size_bytes=size_bytes,
        kind=value["kind"],
        manifest_digest=manifest_digest,
    )


def project_workspace_training_draft(draft: TrainingDraft) -> WorkspaceTrainingDraftProjection:
    configuration = draft.configuration
    imported_parameters = draft.imported_parameters
    name = draft.name if _SAFE_DISPLAY_LABEL.fullmatch(draft.name) else f"Training draft {draft.id}"
    return WorkspaceTrainingDraftProjection(
        id=draft.id,
        state=draft.state,
        name=name,
        resource_version=draft.resource_ref.resource_version,
        dataset_version=_dataset_projection(draft.dataset_version),
        configuration=(
            WorkspaceTrainingConfigurationProjection(
                base_model=WorkspaceBaseModelProjection(
                    artifact=_artifact_projection(configuration.base_model.artifact),
                    source_revision=configuration.base_model.source.revision,
                ),
                parameters=configuration.parameters,
            )
            if configuration is not None
            else None
        ),
        imported_parameters=(
            WorkspaceImportedParametersProjection(parameters=imported_parameters.parameters)
            if imported_parameters is not None
            else None
        ),
        training_run_id=draft.training_run.id if draft.training_run is not None else None,
        cancellation_requested_at=draft.cancellation_requested_at,
        created_at=draft.created_at,
    )


def project_workspace_training_run(run: TrainingRunResource) -> WorkspaceTrainingRunProjection:
    dataset = run.spec.dataset_version
    dataset_projection = WorkspaceDatasetVersionProjection(
        id=UUID(str(dataset["id"])),
        resource_version=int(dataset["resourceVersion"]),
        artifact=_artifact_projection_from_mapping(dataset["artifact"]),
        format="ALPACA_JSONL",
    )
    parameters = run.spec.parameters
    result = run.result
    model_version_digest = None
    if result is not None:
        match = _MODEL_VERSION_ID.fullmatch(str(result.model_version.get("id", "")))
        if match is not None:
            model_version_digest = "sha256:" + match.group(1)
    failure = run.failure
    return WorkspaceTrainingRunProjection(
        id=run.id,
        draft_id=run.draft_ref.id,
        state=run.state,
        spec=WorkspaceTrainingSpecProjection(
            model_artifact=_artifact_projection(run.spec.model_artifact),
            dataset_version=dataset_projection,
            method=run.spec.method,
            finetuning_type=run.spec.finetuning_type,
            parameters=WorkspaceTrainingParameterProjection(
                epochs=float(parameters["epochs"]),
                per_device_batch_size=int(parameters["perDeviceBatchSize"]),
                gradient_accumulation_steps=int(parameters["gradientAccumulationSteps"]),
                learning_rate=float(parameters["learningRate"]),
                max_sequence_length=int(parameters["maxSequenceLength"]),
            ),
        ),
        attempt_count=run.attempt_count,
        output_artifacts=[
            WorkspaceProducedArtifactProjection(
                kind=item.kind,
                artifact=_artifact_projection(item.artifact),
                derived_from_digests=item.derived_from_digests,
            )
            for item in run.output_artifacts
        ],
        created_at=run.created_at,
        updated_at=run.updated_at,
        resource_version=run.resource_version,
        cancellation_requested_at=run.cancellation_requested_at,
        result=(
            WorkspaceTrainingResultProjection(
                id=result.id,
                model_version_digest=model_version_digest,
                adapter_artifact=_artifact_projection(result.adapter_artifact),
                checkpoint_artifacts=[_artifact_projection(item) for item in result.checkpoint_artifacts],
                created_at=result.created_at,
            )
            if result is not None
            else None
        ),
        failure=(
            WorkspaceTrainingFailureProjection(code=failure.code, retryable=failure.retryable)
            if failure is not None
            else None
        ),
    )
