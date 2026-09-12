"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.product_models                             │
│  Role: Public draft, run and result projections for Text Lifecycle. │
│  模块职责：Yield 产品引用契约；不暴露执行路径或复制其它产品状态。          │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from cy_artifacts import ArtifactRef as PlatformArtifactRef
from pydantic import BaseModel as PydanticModel
from pydantic import ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class ContractModel(PydanticModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ArtifactRef(ContractModel):
    """Projection of Platform ArtifactRef; identity is validated by its SDK."""

    model_config = ConfigDict(alias_generator=None, populate_by_name=True, extra="forbid")
    uri: str = Field(pattern=r"^artifact://sha256/[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0, strict=True)
    kind: Literal[
        "generic", "model", "dataset", "checkpoint", "training_spec", "metrics", "merged", "quantized", "report"
    ]
    manifest_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_identity(self) -> ArtifactRef:
        self.platform()
        return self

    def platform(self) -> PlatformArtifactRef:
        return PlatformArtifactRef.from_dict(self.model_dump(exclude_none=True))


class ResourceRef(ContractModel):
    """Opaque, versioned identity owned by the source Product."""

    uri: str = Field(pattern=r"^(https?://|cyrene://)[^\s]+$")
    id: UUID
    resource_version: int = Field(ge=1)


class DatasetVersionRef(ResourceRef):
    artifact: ArtifactRef
    validation_artifact: ArtifactRef | None = None
    format: Literal["ALPACA_JSONL"] = "ALPACA_JSONL"
    provenance_refs: list[
        Annotated[str, Field(pattern=r"^(cyrene|https?|artifact|model-version)://[^\s]+$", max_length=2000)]
    ] = Field(default_factory=list, max_length=100)


class BaseSource(ContractModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")


class BaseModel(ContractModel):
    artifact: ArtifactRef
    source: BaseSource

    @model_validator(mode="after")
    def portable_model(self) -> BaseModel:
        if self.artifact.kind != "model" or self.artifact.manifest_digest != self.artifact.digest:
            raise ValueError("A complete portable base model Artifact is required")
        return self


class TrainingParameters(ContractModel):
    epochs: float = Field(default=1, gt=0, le=100)
    per_device_batch_size: int = Field(default=1, ge=1, le=64)
    gradient_accumulation_steps: int = Field(default=1, ge=1, le=1024)
    learning_rate: float = Field(default=0.0002, gt=0, le=1)
    max_sequence_length: int = Field(default=512, ge=16, le=32768)
    max_steps: int | None = Field(default=None, ge=1)
    lora_rank: int = Field(default=8, ge=1, le=512)
    lora_alpha: int = Field(default=16, ge=1)
    template: str = Field(default="default", pattern=r"^[A-Za-z0-9_-]{1,100}$")


class CreateTrainingDraft(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    dataset_version: DatasetVersionRef


class PrepareTrainingDraft(ContractModel):
    base_model: BaseModel
    parameters: TrainingParameters = Field(default_factory=TrainingParameters)


class TrainingDraft(ContractModel):
    id: UUID
    resource_ref: ResourceRef
    state: Literal["DRAFT", "PREPARED", "STARTED"]
    name: str
    dataset_version: DatasetVersionRef
    configuration: PrepareTrainingDraft | None = None
    training_run: ResourceRef | None = None
    cancellation_requested_at: datetime | None = None
    created_at: datetime


class TrainingResultResource(ContractModel):
    id: UUID
    resource_ref: ResourceRef
    training_run: ResourceRef
    dataset_version: ResourceRef
    adapter_artifact: ArtifactRef
    checkpoint_artifacts: list[ArtifactRef]
    model_version: dict[str, Any]
    created_at: datetime


class ProductFailure(ContractModel):
    code: str
    message: str
    retryable: bool = False


class PublicTrainingSpec(ContractModel):
    model_artifact: ArtifactRef
    dataset_version: dict[str, Any]
    method: Literal["SFT"] = "SFT"
    finetuning_type: Literal["LORA"] = "LORA"
    parameters: dict[str, int | float]
    extensions: dict[str, Any]


ProducedKind = Literal["MODEL_CHECKPOINT", "MODEL_ADAPTER", "METRICS", "TRAINING_MANIFEST"]
RunState = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLING", "CANCELLED", "AWAITING_RETRY"]


class ProducedArtifact(ContractModel):
    kind: ProducedKind
    artifact: ArtifactRef
    derived_from_digests: list[str]


class TrainingRunResource(ContractModel):
    id: UUID
    resource_ref: ResourceRef
    draft_ref: ResourceRef
    state: RunState
    spec: PublicTrainingSpec
    engine_binding_id: str
    engine_capability_type: Literal["cyrene.yield.training-runtime.v1"] = "cyrene.yield.training-runtime.v1"
    attempt_count: int
    output_artifacts: list[ProducedArtifact]
    created_at: datetime
    updated_at: datetime
    resource_version: int
    cancellation_requested_at: datetime | None = None
    result: TrainingResultResource | None = None
    failure: ProductFailure | None = None


class HandoffReceipt(ContractModel):
    target_resource: ResourceRef
    status: Literal["DRAFT", "PREPARED", "STARTED"]
    open_in: str


class TrainingAttemptResource(ContractModel):
    """Public diagnostic projection; executor paths stay private."""

    id: UUID
    training_run_id: UUID
    phase: str
    state: str
    failure: ProductFailure | None = None
