"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.product_service                            │
│  Role: Explicit drafts over existing training and Artifact engines.│
│  模块职责：接收产品引用，显式启动训练并发布结果；不自动部署或启用路由。     │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from cy_artifacts import LocalArtifactProvider
from cyrene_preflight import HardwareFacts, PreflightSeverity, PreflightStatus

from .contracts import DatasetRef, EngineKind, HyperparamSpec, LoRASpec, ModelRef, QuantizationSpec, TrainingSpec
from .contracts.events import TrainingEvent, TrainingEventKind
from .control_plane import REAL_TRAINING_STEP_ID, TrainingControlPlane
from .lifecycle import Attempt, PlanStatus
from .llama_factory_yaml import parse_llama_factory_yaml, render_llama_factory_yaml
from .model_registry import ModelRegistryPort
from .product_models import (
    ArtifactRef,
    CreateTrainingDraft,
    DiagnosticRecord,
    DiagnosticsPage,
    GatewayRouteDraftReceipt,
    HandoffReceipt,
    ImportLlamaFactoryYaml,
    LlamaFactoryPrefill,
    PreflightItem,
    PreflightReport,
    PrepareTrainingDraft,
    ProducedArtifact,
    ProducedKind,
    ProductFailure,
    PublicTrainingSpec,
    ResourceRef,
    ResumeTrainingRun,
    RunState,
    SendTrainingResultToExchange,
    TrainingAttemptResource,
    TrainingDraft,
    TrainingEventResource,
    TrainingEventsPage,
    TrainingParameters,
    TrainingResultResource,
    TrainingRunPage,
    TrainingRunResource,
)
from .product_results import compose_result
from .product_store import ProductStore

_RESUMABLE_STATES = frozenset({PlanStatus.FAILED, PlanStatus.CANCELLED, PlanStatus.AWAITING_RETRY})
_TERMINAL_RUN_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
# One diagnostics page is capped by both record count and serialized size, so a
# 每个诊断分页同时受记录数和序列化字节数限制，因此
# console poll can never pull an unbounded payload.
# 控制台轮询不会获取无界 payload。
DIAGNOSTICS_PAGE_LIMIT = 500
DIAGNOSTICS_PAGE_MAX_BYTES = 1024 * 1024
_REDACTED = "[redacted]"
_TOKEN_PATTERNS = (
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bcyk_[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
)
_MIN_FREE_DISK_BYTES = 1024**3
_WARN_FREE_DISK_BYTES = 5 * 1024**3
_MODEL_VERSION_ID = re.compile(r"^model-version://sha256/[0-9a-f]{64}$")


def _now() -> datetime:
    return datetime.now(UTC)


def _ref(kind: str, identifier: UUID, version: int = 1) -> ResourceRef:
    return ResourceRef(uri=f"cyrene://yield/{kind}/{identifier}", id=identifier, resource_version=version)


def _json(resource: Any) -> dict[str, Any]:
    return resource.model_dump(mode="json", by_alias=True, exclude_none=True)


class YieldService:
    """Yield owns drafts/results; TrainingControlPlane remains the run state store.

    Yield 拥有 drafts 与 results；TrainingControlPlane 仍是 run 状态存储。
    """

    def __init__(
        self,
        *,
        store: ProductStore,
        control: TrainingControlPlane,
        artifacts: LocalArtifactProvider,
        state_directory: Path,
        binding_id: str,
        reactor_url: str | None = None,
        reactor_bearer_token: str | None = None,
        exchange_url: str | None = None,
        exchange_bearer_token: str | None = None,
        exchange_endpoint_id: str | None = None,
        exchange_target_binding_id: str | None = None,
        model_registry: ModelRegistryPort | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.store, self.control, self.artifacts = store, control, artifacts
        self.state_directory, self.binding_id = state_directory, binding_id
        self.reactor_url = reactor_url.rstrip("/") if reactor_url else None
        self.exchange_url = exchange_url.rstrip("/") if exchange_url else None
        self.exchange_bearer_token = exchange_bearer_token
        self.exchange_endpoint_id = exchange_endpoint_id
        self.exchange_target_binding_id = exchange_target_binding_id
        self.model_registry = model_registry
        self._http = http_client or httpx.Client(timeout=30, trust_env=False)
        self.reactor_bearer_token = reactor_bearer_token
        self._lock = RLock()

    def create_draft(self, command: CreateTrainingDraft, key: str | None = None) -> TrainingDraft:
        """Persist only references; importing never allocates compute or starts work.

        只持久化引用；导入不会分配计算资源或启动工作。
        """
        identifier = uuid4()
        draft = TrainingDraft(
            id=identifier,
            resource_ref=_ref("training-drafts", identifier),
            state="DRAFT",
            name=command.name,
            dataset_version=command.dataset_version,
            imported_parameters=command.imported_parameters,
            workspace_id=command.workspace_id,
            created_at=_now(),
        )
        source = command.dataset_version
        idempotency_key = (
            key or "dataset:" + hashlib.sha256(f"{source.uri}:{source.resource_version}".encode()).hexdigest()
        )
        return TrainingDraft.model_validate(self.store.create_draft(idempotency_key, _json(command), _json(draft)))

    def get_draft(self, identifier: UUID) -> TrainingDraft:
        return TrainingDraft.model_validate(self.store.get("draft", str(identifier)))

    def list_drafts(self) -> list[TrainingDraft]:
        return [TrainingDraft.model_validate(item) for item in self.store.list("draft")]

    def list_runs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        workspace_id: str | None = None,
    ) -> TrainingRunPage:
        """Return a deterministic offset page without exposing executor state.

        返回确定性的 offset 分页，不暴露 executor 状态。
        """

        if not 0 <= offset:
            raise ValueError("YIELD_PAGINATION_INVALID: offset must be non-negative")
        if not 1 <= limit <= 100:
            raise ValueError("YIELD_PAGINATION_INVALID: limit must be between 1 and 100")
        drafts = [draft for draft in self.list_drafts() if draft.training_run is not None]
        if workspace_id is not None:
            drafts = [draft for draft in drafts if draft.workspace_id == workspace_id]
        drafts.sort(key=lambda draft: (draft.created_at, str(draft.id)), reverse=True)
        total = len(drafts)
        selected = drafts[offset : offset + limit]
        items = [self.get_run(draft.training_run.id) for draft in selected if draft.training_run is not None]
        next_offset = offset + len(items) if offset + len(items) < total else None
        return TrainingRunPage(items=items, offset=offset, limit=limit, total=total, next_offset=next_offset)

    def import_llama_factory_yaml(
        self,
        command: ImportLlamaFactoryYaml,
        key: str | None = None,
    ) -> TrainingDraft:
        """Import only admitted LLaMA Factory fields into a DRAFT resource.

        只将获准的 LLaMA Factory 字段导入 DRAFT 资源。
        """

        prefill = parse_llama_factory_yaml(command.yaml_text)
        draft_command = CreateTrainingDraft(
            name=command.name,
            dataset_version=command.dataset_version,
            workspace_id=command.workspace_id,
            imported_parameters=prefill,
        )
        return self.create_draft(draft_command, key)

    def export_llama_factory_yaml(self, identifier: UUID) -> str:
        """Export a draft's canonical parameters as LLaMA Factory YAML.

        将 draft 的规范参数导出为 LLaMA Factory YAML。
        """

        return render_llama_factory_yaml(**self._yaml_values(self.get_draft(identifier)))

    def export_result_llama_factory_yaml(self, identifier: UUID) -> str:
        """Export the immutable result's source draft parameters as YAML.

        将不可变结果的来源 draft 参数导出为 YAML。
        """

        result = self.get_result(identifier)
        draft = self._draft_for_run(result.training_run.id)
        return render_llama_factory_yaml(**self._yaml_values(draft))

    def _yaml_values(self, draft: TrainingDraft) -> dict[str, Any]:
        if draft.configuration is not None:
            return {
                "model_name_or_path": draft.configuration.base_model.source.repository,
                "dataset": draft.imported_parameters.dataset
                if draft.imported_parameters and draft.imported_parameters.dataset
                else draft.dataset_version.uri,
                "parameters": draft.configuration.parameters,
            }
        imported = draft.imported_parameters
        return {
            "model_name_or_path": imported.model_name_or_path if imported else None,
            "dataset": imported.dataset if imported and imported.dataset else draft.dataset_version.uri,
            "parameters": imported.parameters if imported else TrainingParameters(),
        }

    def prepare(self, identifier: UUID, command: PrepareTrainingDraft) -> TrainingDraft:
        with self._lock:
            draft = self.get_draft(identifier)
            if draft.training_run is not None:
                raise ValueError("YIELD_DRAFT_ALREADY_STARTED: create another draft to change training intent")
            self.artifacts.verify(command.base_model.artifact.platform())
            self.artifacts.verify(draft.dataset_version.artifact.platform())
            if draft.imported_parameters is not None and "parameters" not in command.model_fields_set:
                command = command.model_copy(update={"parameters": draft.imported_parameters.parameters})
            draft.configuration, draft.state = command, "PREPARED"
            self.store.save("draft", str(identifier), _json(draft))
            return draft

    def start(self, identifier: UUID) -> TrainingRunResource:
        """The explicit start is the only action that submits a TrainingRun.

        只有显式 start 操作会提交 TrainingRun。
        """
        with self._lock:
            draft = self.get_draft(identifier)
            if draft.training_run is not None:
                return self.get_run(draft.training_run.id)
            if draft.configuration is None:
                raise ValueError("YIELD_DRAFT_NOT_PREPARED: select a base model and training parameters")
            spec = self._stage_spec(draft)
            try:
                run = self.control.submit(spec, idempotency_key="product-draft:" + str(identifier))
            except ValueError as exc:
                raise ValueError(
                    "YIELD_ENVIRONMENT_UNAVAILABLE: resolve the configured training environment and host facts"
                ) from exc
            run_id = UUID(run.run_id.removeprefix("run-"))
            draft.training_run, draft.state = _ref("training-runs", run_id), "STARTED"
            self.store.save("draft", str(identifier), _json(draft))
            return self.get_run(run_id)

    def _stage_spec(self, draft: TrainingDraft) -> TrainingSpec:
        configuration = draft.configuration
        assert configuration is not None
        root = self.state_directory / "training" / str(draft.id)
        inputs = root / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        dataset = inputs / "train.jsonl"
        base = inputs / "base"
        self.artifacts.stage(draft.dataset_version.artifact.platform(), dataset)
        self.artifacts.stage(configuration.base_model.artifact.platform(), base)
        params = configuration.parameters
        return TrainingSpec(
            engine=EngineKind.LLAMA_FACTORY,
            job_id=str(draft.id),
            model=ModelRef(name=configuration.base_model.source.repository, path=str(base), trust_remote_code=False),
            dataset=DatasetRef(path=str(dataset), format="jsonl", schema="instruction", name="instruction"),
            output_dir=str(root / "result"),
            finetuning_type="lora",
            stage="sft",
            lora=LoRASpec(r=params.lora_rank, lora_alpha=params.lora_alpha, lora_dropout=params.lora_dropout),
            quantization=QuantizationSpec(use_4bit=False),
            hyperparams=HyperparamSpec(
                num_train_epochs=params.epochs,
                per_device_batch_size=params.per_device_batch_size,
                gradient_accumulation_steps=params.gradient_accumulation_steps,
                learning_rate=params.learning_rate,
                max_seq_length=params.max_sequence_length,
                logging_steps=1,
            ),
            extra={
                "precision": "fp32",
                "base_source": _json(configuration.base_model.source),
                "input_artifacts": [
                    draft.dataset_version.artifact.platform().to_dict(),
                    configuration.base_model.artifact.platform().to_dict(),
                ],
                "max_steps": params.max_steps,
                "llamafactory_args": {
                    "template": params.template,
                    "bf16": False,
                    "fp16": False,
                    "lora_dropout": params.lora_dropout,
                },
            },
        )

    def _draft_for_run(self, identifier: UUID) -> TrainingDraft:
        for draft in self.list_drafts():
            if draft.training_run is not None and draft.training_run.id == identifier:
                return draft
        raise KeyError(str(identifier))

    def get_run(self, identifier: UUID) -> TrainingRunResource:
        draft = self._draft_for_run(identifier)
        configuration = draft.configuration
        assert configuration is not None
        run = self.control.load("run-" + str(identifier))
        states: dict[PlanStatus, RunState] = {
            PlanStatus.PENDING: "QUEUED",
            PlanStatus.RUNNING: "RUNNING",
            PlanStatus.SUCCEEDED: "COMPLETED",
            PlanStatus.FAILED: "FAILED",
            PlanStatus.BLOCKED: "FAILED",
            PlanStatus.CANCEL_REQUESTED: "CANCELLING",
            PlanStatus.CANCELLING: "CANCELLING",
            PlanStatus.CANCELLED: "CANCELLED",
            PlanStatus.AWAITING_RETRY: "AWAITING_RETRY",
        }
        state = states[run.observed_status]
        artifacts = self.control.output_artifacts(run.run_id)
        result = self._result(draft, artifacts) if state == "COMPLETED" else None
        lineage = [configuration.base_model.artifact.digest, draft.dataset_version.artifact.digest]
        kinds: dict[str, ProducedKind] = {
            "model": "MODEL_ADAPTER",
            "checkpoint": "MODEL_CHECKPOINT",
            "metrics": "METRICS",
            "report": "TRAINING_MANIFEST",
        }
        produced = [
            ProducedArtifact(
                kind=kinds.get(name, "MODEL_CHECKPOINT"),
                artifact=ArtifactRef.model_validate(ref.to_dict()),
                derived_from_digests=lineage,
            )
            for name, ref in artifacts.items()
        ]
        parameters = _json(configuration.parameters)
        public_parameters = {
            key: parameters[key]
            for key in (
                "epochs",
                "perDeviceBatchSize",
                "gradientAccumulationSteps",
                "learningRate",
                "maxSequenceLength",
            )
        }
        source = draft.dataset_version
        spec = PublicTrainingSpec(
            model_artifact=configuration.base_model.artifact,
            dataset_version={
                "uri": source.uri,
                "id": str(source.id),
                "resourceVersion": source.resource_version,
                "artifact": source.artifact.platform().to_dict(),
            },
            parameters=public_parameters,
            extensions={"cyrene.text-lifecycle.v1": {"dataset": _json(source), "configuration": _json(configuration)}},
        )
        failures = [attempt.error for attempt in run.attempts if attempt.error]
        return TrainingRunResource(
            id=identifier,
            resource_ref=_ref("training-runs", identifier, max(1, int(run.generation))),
            draft_ref=draft.resource_ref,
            state=state,
            spec=spec,
            engine_binding_id=self.binding_id,
            attempt_count=sum(attempt.step_id == REAL_TRAINING_STEP_ID for attempt in run.attempts),
            output_artifacts=produced,
            created_at=datetime.fromisoformat(run.created_at),
            updated_at=datetime.fromisoformat(run.updated_at),
            resource_version=max(1, int(run.generation)),
            result=result,
            cancellation_requested_at=draft.cancellation_requested_at,
            failure=ProductFailure(
                code="YIELD_TRAINING_FAILED",
                message="Training or preflight did not complete; inspect attempt diagnostics.",
            )
            if state == "FAILED" or failures
            else None,
        )

    def preflight(self, identifier: UUID) -> PreflightReport:
        """Run the existing Product preflight and add local operational checks.

        运行现有 Product preflight 并增加本地运维检查。
        """

        self._draft_for_run(identifier)
        run_id = "run-" + str(identifier)
        result = self.control.preflight_result(run_id)
        items = [
            PreflightItem(
                id=issue.code,
                status=_preflight_item_status(issue.severity),
                message=issue.message,
                remediation=issue.remediation,
            )
            for issue in result.issues
        ]
        spec = self.control.spec(run_id)
        lock = self.control.environment_lock(run_id)
        accelerator_runtime = (lock.accelerator_runtime or "").lower()
        items.extend(_filesystem_preflight(spec.output_dir))
        items.append(
            PreflightItem(
                id="cuda-runtime",
                status="PASS" if accelerator_runtime == "cuda" else "FAIL",
                message=(
                    "The resolved environment uses CUDA."
                    if accelerator_runtime == "cuda"
                    else "The resolved training environment is not CUDA."
                ),
                remediation="Select a CUDA training environment on an NVIDIA node.",
            )
        )
        hardware = result.hardware
        if hardware is None:
            items.append(
                PreflightItem(
                    id="gpu-inventory",
                    status="UNKNOWN",
                    message="GPU inventory is not available from the Platform preflight.",
                    remediation="Refresh node resource inventory before starting training.",
                )
            )
        else:
            accelerators = tuple(getattr(hardware, "accelerators", ()) or ())
            total_vram = sum(int(getattr(item, "total_memory_bytes", 0) or 0) for item in accelerators)
            items.append(
                PreflightItem(
                    id="gpu-inventory",
                    status="PASS" if accelerators else "FAIL",
                    message=(
                        f"{len(accelerators)} GPU(s) and {total_vram} bytes of VRAM are reported."
                        if accelerators
                        else "No GPU was reported by the Platform inventory."
                    ),
                    remediation="Register an NVIDIA GPU with current VRAM facts before training."
                    if not accelerators
                    else None,
                )
            )
        statuses = {item.status for item in items}
        report_status: Literal["PASS", "WARN", "FAIL"] = (
            "FAIL" if "FAIL" in statuses else "WARN" if statuses.intersection({"WARN", "UNKNOWN"}) else "PASS"
        )
        return PreflightReport(status=report_status, items=items, checked_at=_now())

    def events(self, identifier: UUID, *, after_sequence: int = 0, limit: int = 5000) -> TrainingEventsPage:
        """Harvest runtime events and return a durable ordered slice.

        采集 runtime 事件，并返回持久化的有序切片。
        """

        if after_sequence < 0:
            raise ValueError("YIELD_EVENT_SEQUENCE_INVALID: after_sequence must be non-negative")
        self._draft_for_run(identifier)
        self._harvest_events(identifier)
        run = self.get_run(identifier)
        records = self.store.list_events(str(identifier), after_sequence, limit)
        values = [TrainingEventResource.model_validate(record) for record in records]
        next_sequence = values[-1].sequence if values else after_sequence
        return TrainingEventsPage(
            events=values,
            after_sequence=after_sequence,
            next_sequence=next_sequence,
            terminal=run.state in _TERMINAL_RUN_STATES,
            state=run.state,
        )

    def diagnostics(
        self, identifier: UUID, *, after_sequence: int = 0, limit: int = 200
    ) -> DiagnosticsPage:
        """Harvest trainer output and return a durable, redacted page.

        采集 trainer 输出，并返回持久化且已脱敏的分页。
        """

        if after_sequence < 0:
            raise ValueError("YIELD_DIAGNOSTICS_SEQUENCE_INVALID: after_sequence must be non-negative")
        self._draft_for_run(identifier)
        self._harvest_diagnostics(identifier)
        run = self.get_run(identifier)
        records = self.store.list_diagnostics(str(identifier), after_sequence, DIAGNOSTICS_PAGE_LIMIT)
        items = [DiagnosticRecord.model_validate(record) for record in records]
        items, dropped = _bounded_diagnostics(items)
        next_sequence = items[-1].sequence if items else after_sequence
        return DiagnosticsPage(
            resource_id=str(identifier),
            items=items,
            next_sequence=next_sequence,
            terminal=run.state in _TERMINAL_RUN_STATES,
            diagnostics_degraded=(
                self._diagnostics_degraded(identifier, run) or dropped
            ),
        )

    def _harvest_diagnostics(self, identifier: UUID) -> None:
        """Persist only the new prefix of each attempt's raw output.

        仅持久化每个 attempt 原始输出的新增前缀。
        """

        run_id = "run-" + str(identifier)
        run = self.control.load(run_id)
        try:
            spec = self.control.spec(run_id)
        except (KeyError, RuntimeError, ValueError):
            spec = None
        private_paths = _private_paths(spec, self.state_directory)
        for attempt in run.attempts:
            observed = self.control.session_diagnostics(str(attempt.attempt_id))
            persisted = self.store.diagnostics_count(str(identifier), str(attempt.attempt_id))
            fresh = observed[persisted:]
            if not fresh:
                continue
            documents = [
                _diagnostic_document(identifier, attempt, record, private_paths) for record in fresh
            ]
            self.store.append_diagnostics(str(identifier), str(attempt.attempt_id), documents)

    def _diagnostics_degraded(self, identifier: UUID, run: Any) -> bool:
        """True when any attempt lost output or the budget was exhausted.

        当任一 attempt 丢失输出或达到字节上限时返回 True。
        """

        for attempt in run.attempts:
            if self.control.session_diagnostics_degraded(str(attempt.attempt_id)):
                return True
        return self.store.diagnostics_degraded(str(identifier))

    def _harvest_events(self, identifier: UUID) -> None:
        """Persist only the new prefix of each in-process attempt event stream.

        仅持久化进程内 attempt 事件流的新增前缀。
        """

        self._draft_for_run(identifier)
        run_id = "run-" + str(identifier)
        run = self.control.load(run_id)
        try:
            spec = self.control.spec(run_id)
        except (KeyError, RuntimeError, ValueError):
            spec = None
        private_paths = _private_paths(spec, self.state_directory)
        for attempt in run.attempts:
            observed = self.control.session_events(str(attempt.attempt_id))
            persisted_snapshot = self.control.persisted_session_events(
                run_id, str(attempt.attempt_id)
            )
            if len(persisted_snapshot) > len(observed):
                observed = persisted_snapshot
            persisted = self.store.event_count(str(identifier), str(attempt.attempt_id))
            fresh = observed[persisted:]
            if not fresh:
                continue
            documents = [
                _event_document(identifier, attempt.step_id, attempt.attempt_id, event, private_paths)
                for event in fresh
            ]
            self.store.append_events(str(identifier), str(attempt.attempt_id), documents)

    def resume(
        self,
        identifier: UUID,
        command: ResumeTrainingRun,
        key: str | None = None,
    ) -> TrainingRunResource:
        """Stage a verified checkpoint and append one explicit Attempt.

        暂存已验证的 checkpoint，并追加一个明确的 Attempt。
        """

        with self._lock:
            draft = self._draft_for_run(identifier)
            run_id = "run-" + str(identifier)
            run = self.control.load(run_id)
            if run.observed_status not in _RESUMABLE_STATES:
                raise ValueError("YIELD_RESUME_NOT_ALLOWED: run is not stopped or awaiting retry")
            checkpoints = self.control.checkpoint_artifacts(run_id)
            selected = _select_checkpoint(checkpoints, command)
            if selected is None:
                raise ValueError("YIELD_RESUME_CHECKPOINT_MISSING: no complete checkpoint is attached to the run")
            checkpoint_name, checkpoint = selected
            digest = hashlib.sha256(
                json_bytes({"run": str(identifier), "checkpoint": checkpoint.to_dict(), "name": checkpoint_name})
            ).hexdigest()
            receipt_key = key or f"resume:{identifier}:{checkpoint.digest}"
            if self.store.recall_receipt(receipt_key, digest) is not None:
                return self.get_run(identifier)
            self.artifacts.verify(checkpoint)
            target = self.state_directory / "training" / str(draft.id) / "resume" / checkpoint.digest.removeprefix("sha256:")
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            self.artifacts.stage(checkpoint, target)
            if not target.exists() or not any(target.rglob("*")):
                raise ValueError("YIELD_RESUME_CHECKPOINT_INCOMPLETE: staged checkpoint is empty")
            self.control.resume(run_id, checkpoint_path=str(target))
            self.store.save_receipt(
                receipt_key,
                digest,
                {"runId": str(identifier), "checkpointDigest": checkpoint.digest},
            )
        return self.get_run(identifier)

    def send_to_exchange(
        self,
        identifier: UUID,
        command: SendTrainingResultToExchange,
        key: str | None = None,
    ) -> GatewayRouteDraftReceipt:
        """Create, but never confirm, an Exchange Route Draft for a result.

        为一个结果创建 Exchange Route Draft，但绝不确认该 draft。
        """

        result = self.get_result(identifier)
        if self.exchange_url is None:
            raise ValueError("YIELD_EXCHANGE_NOT_CONNECTED: configure the Exchange Product URL")
        endpoint_id = command.gateway_endpoint_id or self.exchange_endpoint_id
        target_binding_id = command.target_binding_id or self.exchange_target_binding_id
        if not endpoint_id or not target_binding_id:
            raise ValueError("YIELD_EXCHANGE_NOT_CONFIGURED: configure the gateway endpoint and target binding")
        source_endpoint, deployment = self._inspect_reactor_endpoint(command.endpoint_url, result)
        target_model = command.target_model or source_endpoint["model"]
        if target_model != source_endpoint["model"]:
            raise ValueError("YIELD_EXCHANGE_SOURCE_MISMATCH: target model differs from Reactor Endpoint")
        model_pattern = command.model_pattern or command.model_alias
        source = {
            "product": "reactor",
            "resourceUri": command.endpoint_url,
            "resourceVersion": source_endpoint["resourceVersion"],
            "artifactDigest": deployment["modelArtifact"]["digest"],
        }
        source["modelVersionId"] = deployment["modelVersion"]["id"]
        payload = {
            "endpointId": str(endpoint_id),
            "modelPattern": model_pattern,
            "targetBindingId": target_binding_id,
            "targetModel": target_model,
            "priority": command.priority,
            "source": source,
        }
        digest = hashlib.sha256(json_bytes(payload)).hexdigest()
        receipt_key = key or f"send-to-exchange:{identifier}"
        saved = self.store.recall_receipt(receipt_key, digest)
        if saved is not None:
            return GatewayRouteDraftReceipt.model_validate(saved)
        headers = {"Idempotency-Key": receipt_key}
        if self.exchange_bearer_token:
            headers["Authorization"] = "Bearer " + self.exchange_bearer_token
        response = self._http.post(
            self.exchange_url + "/api/v1/gateway-route-drafts",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        document = response.json()
        route_id = UUID(str(document["id"]))
        receipt = GatewayRouteDraftReceipt(
            route_id=route_id,
            draft_url=self.exchange_url + "/api/v1/gateway-route-drafts/" + str(route_id),
        )
        self.store.save_receipt(receipt_key, digest, _json(receipt))
        return receipt

    def _inspect_reactor_endpoint(
        self, endpoint_url: str, result: TrainingResultResource
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Read the Reactor source before sending its versioned reference to Exchange.

        将 Reactor 来源读取后，再向 Exchange 发送其版本化引用。
        """

        if self.reactor_url is None:
            raise ValueError("YIELD_REACTOR_NOT_CONNECTED: configure the Reactor Product URL")
        source = urlsplit(endpoint_url)
        reactor = urlsplit(self.reactor_url)
        endpoint_match = re.fullmatch(r"/api/v1/endpoints/([0-9a-f-]{36})", source.path)
        if (
            endpoint_match is None
            or source.scheme != reactor.scheme
            or source.netloc != reactor.netloc
            or source.query
            or source.fragment
            or reactor.path not in {"", "/"}
        ):
            raise ValueError("YIELD_EXCHANGE_SOURCE_INVALID: endpoint_url must be a Reactor Endpoint URI")
        headers = (
            {"Authorization": "Bearer " + self.reactor_bearer_token}
            if self.reactor_bearer_token
            else {}
        )
        endpoint_response = self._http.get(endpoint_url, headers=headers)
        endpoint_response.raise_for_status()
        endpoint = endpoint_response.json()
        if (
            not isinstance(endpoint, dict)
            or str(endpoint.get("id")) != endpoint_match.group(1)
            or endpoint.get("state") != "READY"
            or endpoint.get("protocol") != "openai.chat.v1"
            or not isinstance(endpoint.get("model"), str)
            or not isinstance(endpoint.get("resourceVersion"), int)
            or isinstance(endpoint.get("resourceVersion"), bool)
        ):
            raise ValueError("YIELD_EXCHANGE_SOURCE_INVALID: Reactor Endpoint is not ready")
        deployment_id = endpoint.get("deploymentId")
        try:
            deployment_uuid = UUID(str(deployment_id))
        except (ValueError, TypeError) as exc:
            raise ValueError("YIELD_EXCHANGE_SOURCE_INVALID: Reactor deployment identity is invalid") from exc
        deployment_response = self._http.get(
            self.reactor_url + "/api/v1/deployments/" + str(deployment_uuid),
            headers=headers,
        )
        deployment_response.raise_for_status()
        deployment = deployment_response.json()
        model_artifact = deployment.get("modelArtifact") if isinstance(deployment, dict) else None
        model_version = deployment.get("modelVersion") if isinstance(deployment, dict) else None
        result_model_version = result.model_version.get("id")
        if (
            not isinstance(deployment, dict)
            or not isinstance(model_artifact, dict)
            or not isinstance(model_artifact.get("digest"), str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", model_artifact["digest"])
            or not isinstance(model_version, dict)
            or not isinstance(model_version.get("id"), str)
            or not _MODEL_VERSION_ID.fullmatch(model_version["id"])
            or model_version["id"] != result_model_version
        ):
            raise ValueError("YIELD_EXCHANGE_SOURCE_MISMATCH: Reactor deployment is not this training result")
        return endpoint, deployment

    def _result(self, draft: TrainingDraft, artifacts: dict[str, Any]) -> TrainingResultResource:
        assert draft.training_run is not None and draft.configuration is not None
        identifier = uuid5(NAMESPACE_URL, draft.training_run.uri + "/result")
        try:
            result = TrainingResultResource.model_validate(self.store.get("result", str(identifier)))
        except KeyError:
            pass
        else:
            self._register_model_version(result)
            return result
        adapter = artifacts.get("model")
        if adapter is None:
            raise ValueError("YIELD_RESULT_INCOMPLETE: no published adapter Artifact")
        self.artifacts.verify(adapter)
        source = draft.dataset_version
        model = compose_result(
            run_ref=draft.training_run.uri,
            dataset_ref=source.uri,
            base_model=_json(draft.configuration.base_model),
            adapter=adapter,
            dataset_artifacts=[source.artifact.platform()],
            tokenizer={"mode": "INHERIT"},
            chat_template={"mode": "INHERIT"},
        )
        result = TrainingResultResource(
            id=identifier,
            resource_ref=_ref("training-results", identifier),
            training_run=draft.training_run,
            dataset_version=ResourceRef(uri=source.uri, id=source.id, resource_version=source.resource_version),
            adapter_artifact=ArtifactRef.model_validate(adapter.to_dict()),
            checkpoint_artifacts=[
                ArtifactRef.model_validate(value.to_dict())
                for name, value in artifacts.items()
                if name.startswith("checkpoint")
            ],
            model_version=model.to_dict(),
            created_at=_now(),
        )
        created = TrainingResultResource.model_validate(self.store.create_result(_json(result)))
        self._register_model_version(created)
        return created

    def _register_model_version(self, result: TrainingResultResource) -> None:
        """Publish once when configured; Artifact bytes remain in the Artifact Plane.

        配置后只发布一次；Artifact 字节仍留在 Artifact Plane。
        """
        if self.model_registry is None:
            return
        model_version_id = result.model_version.get("id")
        if not isinstance(model_version_id, str) or not _MODEL_VERSION_ID.fullmatch(model_version_id):
            raise ValueError("YIELD_MODEL_VERSION_INVALID: result does not contain an immutable ModelVersion")
        request = {
            "modelVersion": result.model_version,
            "sourceRef": result.resource_ref.uri,
        }
        digest = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        key = "model-registry:" + model_version_id
        if self.store.recall_receipt(key, digest) is not None:
            return
        registration = self.model_registry.register(
            result.model_version,
            source_ref=result.resource_ref.uri,
        )
        self.store.save_receipt(key, digest, registration.to_dict())

    def get_result(self, identifier: UUID) -> TrainingResultResource:
        result = TrainingResultResource.model_validate(self.store.get("result", str(identifier)))
        self._register_model_version(result)
        return result

    def list_attempts(self, identifier: UUID) -> list[TrainingAttemptResource]:
        """Expose stable phase diagnostics without leaking host paths or raw logs.

        暴露稳定的阶段诊断，不泄漏主机路径或原始日志。
        """
        self._draft_for_run(identifier)
        run = self.control.load("run-" + str(identifier))
        return [
            TrainingAttemptResource(
                id=uuid5(NAMESPACE_URL, _ref("training-runs", identifier).uri + "/attempts/" + str(attempt.attempt_id)),
                training_run_id=identifier,
                phase=attempt.step_id,
                state=attempt.status.value,
                failure=ProductFailure(
                    code=_failure_code(attempt.error),
                    message=(
                        "The phase did not complete. Check host readiness, input format "
                        "and the selected trainer profile."
                    ),
                )
                if attempt.error
                else None,
            )
            for attempt in run.attempts
        ]

    def cancel(self, identifier: UUID) -> TrainingRunResource:
        with self._lock:
            draft = self._draft_for_run(identifier)
            if draft.cancellation_requested_at is None:
                draft.cancellation_requested_at = _now()
                self.store.save("draft", str(draft.id), _json(draft))
            self.control.request_cancel("run-" + str(identifier))
        return self.get_run(identifier)

    def advance(self) -> None:
        """Reconcile only runs explicitly started by a user, using the existing controller.

        只使用现有 controller 对用户明确启动的 run 执行 reconciliation。
        """
        for draft in self.list_drafts():
            if draft.training_run is None:
                continue
            self.control.reconcile_once("run-" + str(draft.training_run.id))
            self._harvest_events(draft.training_run.id)
            self.get_run(draft.training_run.id)

    def send_to_reactor(self, identifier: UUID) -> HandoffReceipt:
        result = self.get_result(identifier)
        if self.reactor_url is None:
            raise ValueError("YIELD_REACTOR_NOT_CONNECTED: configure the Reactor Product URL")
        response = self._http.post(
            self.reactor_url + "/api/v1/deployment-drafts",
            headers={
                "Idempotency-Key": "yield-result:" + str(identifier),
                **(
                    {"Authorization": "Bearer " + self.reactor_bearer_token}
                    if self.reactor_bearer_token
                    else {}
                ),
            },
            json={"sourceRef": _json(result.resource_ref), "modelVersion": result.model_version},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("state") not in {"DRAFT", "STARTED"}:
            raise ValueError("YIELD_HANDOFF_INVALID: Reactor did not return a deployment draft")
        target = ResourceRef.model_validate(payload["resourceRef"])
        return HandoffReceipt(
            target_resource=target,
            status=payload["state"],
            open_in=self.reactor_url + "/api/v1/deployment-drafts/" + str(target.id),
        )


def _failure_code(detail: str | None) -> str:
    code = (detail or "").split(":", 1)[0]
    return code if code.startswith("YIELD_") and code.replace("_", "").isalnum() else "YIELD_TRAINING_PHASE_FAILED"


def json_bytes(value: Any) -> bytes:
    """Encode an idempotency payload deterministically.

    以确定性方式编码幂等 payload。
    """

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _preflight_item_status(severity: PreflightSeverity) -> Literal["PASS", "WARN", "FAIL", "UNKNOWN"]:
    if severity is PreflightSeverity.BLOCKED:
        return "FAIL"
    if severity is PreflightSeverity.UNKNOWN:
        return "UNKNOWN"
    return "WARN"


def _filesystem_preflight(output_dir: str) -> list[PreflightItem]:
    """Check the output parent without returning its private path.

    检查输出目录的父级，但不返回其私有路径。
    """

    target = Path(output_dir)
    parent = target if target.exists() else target.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    items: list[PreflightItem] = []
    writable = parent.exists() and os.access(parent, os.W_OK)
    items.append(
        PreflightItem(
            id="output-write-permission",
            status="PASS" if writable else "FAIL",
            message="The training output location is writable." if writable else "The training output location is not writable.",
            remediation="Choose a writable output volume for the training result." if not writable else None,
        )
    )
    if parent.exists():
        free = shutil.disk_usage(parent).free
        disk_status: Literal["PASS", "WARN", "FAIL"] = (
            "FAIL" if free < _MIN_FREE_DISK_BYTES else "WARN" if free < _WARN_FREE_DISK_BYTES else "PASS"
        )
        items.append(
            PreflightItem(
                id="disk-space",
                status=disk_status,
                message="The output volume has sufficient free space."
                if disk_status == "PASS"
                else "The output volume has limited free space.",
                remediation="Free at least 1 GiB on the output volume before training."
                if disk_status != "PASS"
                else None,
            )
        )
    else:
        items.append(
            PreflightItem(
                id="disk-space",
                status="UNKNOWN",
                message="The output volume could not be inspected.",
                remediation="Create or mount the configured output volume before training.",
            )
        )
    return items


def _private_paths(spec: TrainingSpec | None, state_directory: Path) -> tuple[str, ...]:
    if spec is None:
        return (str(state_directory),)
    return tuple(
        path
        for path in (
            str(state_directory),
            spec.model.path,
            spec.dataset.path,
            spec.output_dir,
            spec.checkpoint.output_dir,
        )
        if path
    )


def _bounded_diagnostics(items: list[DiagnosticRecord]) -> tuple[list[DiagnosticRecord], bool]:
    """Trim a page to the serialized byte budget; report whether it was trimmed.

    将分页裁剪到序列化字节上限，并报告是否发生裁剪。
    """

    if not items:
        return items, False
    kept = list(items)
    while kept and len(json.dumps([item.model_dump(by_alias=True) for item in kept])) > DIAGNOSTICS_PAGE_MAX_BYTES:
        kept.pop()
    return kept, len(kept) < len(items)


def _diagnostic_document(
    run_id: UUID,
    attempt: Any,
    record: dict[str, Any],
    private_paths: tuple[str, ...],
) -> dict[str, Any]:
    """Map one raw worker record onto the public DiagnosticRecord shape.

    将一条原始 worker 记录映射为公开 DiagnosticRecord 形状。
    """

    message = _redact_text(str(record.get("message", ""))[:8192], private_paths)
    attempt_id = str(attempt.attempt_id)
    metadata = attempt.metadata if isinstance(getattr(attempt, "metadata", None), dict) else {}
    operation_id = metadata.get("operationId") or metadata.get("operation_id")
    resource_ids = metadata.get("resourceIds") or metadata.get("resource_ids")
    return {
        "sequence": record.get("sequence", 0),
        "timestamp": str(record.get("timestamp") or ""),
        "level": str(record.get("level") or "info"),
        "source": "trainer",
        "stream": str(record.get("stream") or "combined"),
        "code": record.get("code"),
        "message": message,
        "request_id": record.get("requestId"),
        "operation_id": str(operation_id) if operation_id else None,
        "resource_id": str(resource_ids[0]) if resource_ids else None,
        "attempt_id": attempt_id,
        "truncated": bool(record.get("truncated", False)),
    }


def _event_document(
    run_id: UUID,
    phase: str,
    attempt_id: Any,
    event: TrainingEvent,
    private_paths: tuple[str, ...],
) -> dict[str, Any]:
    payload = _redact_value(event.payload, private_paths)
    checkpoint = None
    if event.kind is TrainingEventKind.CHECKPOINT:
        checkpoint = {
            key: payload[key]
            for key in ("name", "step", "epoch", "digest", "size_bytes")
            if key in payload
        }
        if not checkpoint and event.message:
            checkpoint = {"name": Path(event.message).name}
    return _json(
        TrainingEventResource(
            sequence=1,
            training_run_id=run_id,
            attempt_id=str(attempt_id),
            phase=phase,
            kind=event.kind.value,
            message=_redact_text(event.message, private_paths),
            step=event.step,
            total_steps=event.total_steps,
            epoch=event.epoch,
            loss=event.loss,
            learning_rate=event.learning_rate,
            throughput=_number(payload.get("throughput")),
            eta_seconds=_number(payload.get("eta_seconds") or payload.get("eta")),
            checkpoint=checkpoint,
            payload=payload if isinstance(payload, dict) else {},
            timestamp=event.timestamp,
        )
    )


def _redact_value(value: Any, private_paths: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_value(item, private_paths) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, private_paths) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item, private_paths) for item in value]
    return _redact_text(value, private_paths) if isinstance(value, str) else value


def _redact_text(value: str, private_paths: tuple[str, ...]) -> str:
    redacted = value
    for private_path in sorted((item for item in private_paths if item), key=len, reverse=True):
        redacted = redacted.replace(private_path, "<private>")
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(1) + " " + _REDACTED if match.lastindex else _REDACTED, redacted)
    return redacted


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _select_checkpoint(
    checkpoints: dict[str, Any], command: ResumeTrainingRun
) -> tuple[str, Any] | None:
    if command.checkpoint_artifact is not None:
        for name, reference in checkpoints.items():
            if reference.digest == command.checkpoint_artifact.digest:
                return name, reference
        raise ValueError("YIELD_RESUME_CHECKPOINT_NOT_ATTACHED: checkpoint is not an output of this run")
    if command.checkpoint_name:
        reference = checkpoints.get(command.checkpoint_name)
        return (command.checkpoint_name, reference) if reference is not None else None
    return next(reversed(checkpoints.items()), None) if checkpoints else None
