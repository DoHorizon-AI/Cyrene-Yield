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
    TrainingDraft,
    TrainingParameters,
    TrainingRunResource,
    ContractModel,
)


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
