"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.product_service                            │
│  Role: Explicit drafts over existing training and Artifact engines.│
│  模块职责：接收产品引用，显式启动训练并发布结果；不自动部署或启用路由。     │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from cy_artifacts import LocalArtifactProvider

from .contracts import DatasetRef, EngineKind, HyperparamSpec, LoRASpec, ModelRef, QuantizationSpec, TrainingSpec
from .control_plane import REAL_TRAINING_STEP_ID, TrainingControlPlane
from .lifecycle import PlanStatus
from .product_models import (
    ArtifactRef,
    CreateTrainingDraft,
    HandoffReceipt,
    PrepareTrainingDraft,
    ProducedArtifact,
    ProducedKind,
    ProductFailure,
    PublicTrainingSpec,
    ResourceRef,
    RunState,
    TrainingAttemptResource,
    TrainingDraft,
    TrainingResultResource,
    TrainingRunResource,
)
from .product_results import compose_result
from .product_store import ProductStore


def _now() -> datetime:
    return datetime.now(UTC)


def _ref(kind: str, identifier: UUID, version: int = 1) -> ResourceRef:
    return ResourceRef(uri=f"cyrene://yield/{kind}/{identifier}", id=identifier, resource_version=version)


def _json(resource: Any) -> dict[str, Any]:
    return resource.model_dump(mode="json", by_alias=True, exclude_none=True)


class YieldService:
    """Yield owns drafts/results; TrainingControlPlane remains the run state store."""

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
        http_client: httpx.Client | None = None,
    ) -> None:
        self.store, self.control, self.artifacts = store, control, artifacts
        self.state_directory, self.binding_id = state_directory, binding_id
        self.reactor_url = reactor_url.rstrip("/") if reactor_url else None
        self._http = http_client or httpx.Client(timeout=30, trust_env=False)
        if reactor_bearer_token:
            self._http.headers["Authorization"] = "Bearer " + reactor_bearer_token
        self._lock = RLock()

    def create_draft(self, command: CreateTrainingDraft, key: str | None = None) -> TrainingDraft:
        """Persist only references; importing never allocates compute or starts work."""
        identifier = uuid4()
        draft = TrainingDraft(
            id=identifier,
            resource_ref=_ref("training-drafts", identifier),
            state="DRAFT",
            name=command.name,
            dataset_version=command.dataset_version,
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

    def prepare(self, identifier: UUID, command: PrepareTrainingDraft) -> TrainingDraft:
        with self._lock:
            draft = self.get_draft(identifier)
            if draft.training_run is not None:
                raise ValueError("YIELD_DRAFT_ALREADY_STARTED: create another draft to change training intent")
            self.artifacts.verify(command.base_model.artifact.platform())
            self.artifacts.verify(draft.dataset_version.artifact.platform())
            draft.configuration, draft.state = command, "PREPARED"
            self.store.save("draft", str(identifier), _json(draft))
            return draft

    def start(self, identifier: UUID) -> TrainingRunResource:
        """The explicit start is the only action that submits a TrainingRun."""
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
            lora=LoRASpec(r=params.lora_rank, lora_alpha=params.lora_alpha),
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

    def _result(self, draft: TrainingDraft, artifacts: dict[str, Any]) -> TrainingResultResource:
        assert draft.training_run is not None and draft.configuration is not None
        identifier = uuid5(NAMESPACE_URL, draft.training_run.uri + "/result")
        try:
            return TrainingResultResource.model_validate(self.store.get("result", str(identifier)))
        except KeyError:
            pass
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
        return TrainingResultResource.model_validate(self.store.create_result(_json(result)))

    def get_result(self, identifier: UUID) -> TrainingResultResource:
        return TrainingResultResource.model_validate(self.store.get("result", str(identifier)))

    def list_attempts(self, identifier: UUID) -> list[TrainingAttemptResource]:
        """Expose stable phase diagnostics without leaking host paths or raw logs."""
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
        """Reconcile only runs explicitly started by a user, using the existing controller."""
        for draft in self.list_drafts():
            if draft.training_run is None:
                continue
            self.control.reconcile_once("run-" + str(draft.training_run.id))
            self.get_run(draft.training_run.id)

    def send_to_reactor(self, identifier: UUID) -> HandoffReceipt:
        result = self.get_result(identifier)
        if self.reactor_url is None:
            raise ValueError("YIELD_REACTOR_NOT_CONNECTED: configure the Reactor Product URL")
        response = self._http.post(
            self.reactor_url + "/api/v1/deployment-drafts",
            headers={"Idempotency-Key": "yield-result:" + str(identifier)},
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
