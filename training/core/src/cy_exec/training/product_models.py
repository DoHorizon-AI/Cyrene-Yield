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
from pydantic import AliasChoices, BaseModel as PydanticModel
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
    lora_dropout: float = Field(default=0.05, ge=0, le=1)
    template: str = Field(default="default", pattern=r"^[A-Za-z0-9_-]{1,100}$")


class LlamaFactoryPrefill(ContractModel):
    """Mapped LLaMA Factory fields kept on a draft before preparation."""

    model_name_or_path: str | None = Field(
        default=None, min_length=1, max_length=4096, exclude_if=lambda value: value is None
    )
    dataset: str | None = Field(
        default=None, min_length=1, max_length=4096, exclude_if=lambda value: value is None
    )
    parameters: TrainingParameters = Field(default_factory=TrainingParameters)


class CreateTrainingDraft(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    dataset_version: DatasetVersionRef
    workspace_id: str = Field(default="default", min_length=1, max_length=200)
    imported_parameters: LlamaFactoryPrefill | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ImportLlamaFactoryYaml(ContractModel):
    """Create a draft while importing a strict LLaMA Factory YAML document."""

    name: str = Field(min_length=1, max_length=200)
    dataset_version: DatasetVersionRef
    workspace_id: str = Field(default="default", min_length=1, max_length=200)
    yaml_text: str = Field(
        min_length=1,
        max_length=1_000_000,
        validation_alias=AliasChoices("yaml", "yamlText", "content"),
        serialization_alias="yaml",
    )


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
    imported_parameters: LlamaFactoryPrefill | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    workspace_id: str = "default"
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


class TrainingRunPage(ContractModel):
    """Stable offset page for the training-run collection."""

    items: list[TrainingRunResource]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)


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


class TrainingEventResource(ContractModel):
    """Durable, ordered, redacted training event. | 持久化有序脱敏训练事件。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")
    sequence: int = Field(ge=1)
    training_run_id: UUID
    attempt_id: str
    phase: str
    kind: str
    message: str = ""
    step: int | None = Field(default=None, ge=0)
    total_steps: int | None = Field(default=None, ge=0)
    epoch: float | None = None
    loss: float | None = None
    learning_rate: float | None = None
    throughput: float | None = None
    eta_seconds: float | None = None
    checkpoint: dict[str, Any] | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str


class TrainingEventsPage(ContractModel):
    """Durable event page used by polling clients before opening SSE."""

    events: list[TrainingEventResource]
    after_sequence: int = Field(ge=0)
    next_sequence: int = Field(ge=0)
    terminal: bool = False
    state: RunState


DiagnosticSource = Literal["product", "trainer", "runtime", "platform"]
DiagnosticStream = Literal["stdout", "stderr", "combined"]
DiagnosticLevel = Literal["debug", "info", "warn", "error"]


class DiagnosticRecord(ContractModel):
    """One redacted diagnostic line a console may show verbatim.

    Raw trainer output never reaches the browser: the message is redacted on the
    way in, and the page carries no path, credential, or environment content.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")
    sequence: int = Field(ge=1)
    timestamp: str
    level: DiagnosticLevel = "info"
    source: DiagnosticSource = "trainer"
    stream: DiagnosticStream = "combined"
    code: str | None = Field(default=None, max_length=200)
    message: str = Field(default="", max_length=8192)
    request_id: str | None = Field(default=None, max_length=200)
    operation_id: str | None = Field(default=None, max_length=200)
    resource_id: str | None = Field(default=None, max_length=200)
    attempt_id: str | None = Field(default=None, max_length=200)
    truncated: bool = False


class DiagnosticsPage(ContractModel):
    """One page of diagnostics for a single resource. | 单个资源的诊断分页。"""

    resource_id: str
    items: list[DiagnosticRecord] = Field(default_factory=list)
    next_sequence: int = Field(ge=0)
    terminal: bool = False
    diagnostics_degraded: bool = False


PreflightItemStatus = Literal["PASS", "WARN", "FAIL", "UNKNOWN"]


class PreflightItem(ContractModel):
    """One preflight observation with a user-facing reason. | 单项预检结果。"""

    id: str = Field(min_length=1, max_length=200)
    status: PreflightItemStatus
    message: str = Field(min_length=1, max_length=2000)
    remediation: str | None = Field(
        default=None, max_length=2000, exclude_if=lambda value: value is None
    )


class PreflightReport(ContractModel):
    """Aggregated preflight outcome for one TrainingRun. | 训练预检报告。"""

    status: Literal["PASS", "WARN", "FAIL"]
    items: list[PreflightItem]
    checked_at: datetime


class ResumeTrainingRun(ContractModel):
    """Explicit manual resume from a complete checkpoint. | 显式 checkpoint 恢复请求。"""

    checkpoint_artifact: ArtifactRef | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    checkpoint_name: str | None = Field(
        default=None, min_length=1, max_length=200, exclude_if=lambda value: value is None
    )


class GatewayRouteDraftReceipt(ContractModel):
    """Exchange route draft created from a training result. | 训练结果的路由草稿回执。"""

    route_id: UUID
    draft_url: str = Field(min_length=1, max_length=2000)


class SendTrainingResultToExchange(ContractModel):
    """Explicit Send using a verified Reactor Endpoint URI. | 使用已校验 Reactor 端点发送。"""

    model_alias: str = Field(min_length=1, max_length=200)
    endpoint_url: str = Field(pattern=r"^https?://", max_length=2000)
    target_model: str | None = Field(default=None, min_length=1, max_length=200)
    gateway_endpoint_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)
    target_binding_id: str | None = Field(default=None, min_length=1, max_length=300)
    model_pattern: str | None = Field(default=None, min_length=1, max_length=200)
    priority: int = Field(default=100, ge=0, le=10_000)
