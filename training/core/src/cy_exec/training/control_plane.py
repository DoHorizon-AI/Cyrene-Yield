"""Yield-owned training lifecycle and execution adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from cy_artifacts import ArtifactRef
from .lifecycle import (
    Attempt,
    AttemptStatus,
    DesiredState,
    ExecutionPlan,
    IdempotencyKey,
    JsonFileControlPlaneStore,
    PlanStatus,
    PlanStep,
    ProductControlPlane,
    ProductRun,
    ReconcileActionKind,
    RetryPolicy,
    StepDependency,
)
from cyrene_preflight import PreflightStatus

from .contracts import TrainingSpec, TrainingStatus
from .contracts.checkpoint import CheckpointSpec
from .contracts.events import TrainingEvent
from .environment import EnvironmentLock
from .preflight import TrainingPreflight
from .runtime import TrainingRuntime
from .tiny_dry_run import TinyDryRun, TinyDryRunStatus
from .capability_seam import (
    YieldTrainingRuntimeResolver,
    YIELD_TRAINING_RUNTIME_CAPABILITY,
    YIELD_TRAINING_RUNTIME_REQUIREMENT,
    TrainingRuntimeResolver,
)

TRAINING_PRODUCT_KIND = "cyrene.yield.training"
PREFLIGHT_STEP_ID = "training-preflight"
TINY_DRY_RUN_STEP_ID = "training-tiny-dry-run"
REAL_TRAINING_STEP_ID = "training-execution"
TRAINING_SPEC_METADATA = "cyrene.yield.training_spec.v1"
ENVIRONMENT_LOCK_METADATA = "cyrene.yield.environment_lock.v1"
RESULT_ARTIFACTS_METADATA = "cyrene.yield.result_artifacts.v1"
TRAINING_EVENTS_METADATA = "cyrene.yield.training_events.v1"
EXECUTION_RECOVERY_UNAVAILABLE = "EXECUTION_RECOVERY_UNAVAILABLE"


class TrainingStateRecoveryError(RuntimeError):
    """Persisted Product state cannot be restored without changing intent."""


class TrainingPlanCompiler:
    """Compiles TrainingSpec into generic PlanSteps without changing engine execution."""

    def compile(self, spec: TrainingSpec, environment_lock: EnvironmentLock) -> ExecutionPlan:
        inputs = _input_artifacts(spec)
        payload_ref = f"sha256:{_digest(spec.to_dict())}"
        environment_identity = environment_lock.environment_digest
        resource_reference = f"resource-request:gpus={spec.distributed.gpu_count}"
        real_attempts = _positive_int(spec.extra.get("max_product_attempts"), default=1)
        return ExecutionPlan.create(
            (
                PlanStep(
                    step_id=PREFLIGHT_STEP_ID,
                    capability="capability.preflight.evaluate",
                    inputs=inputs,
                    outputs=("preflight-report",),
                    environment_identity=environment_identity,
                    resource_reference=resource_reference,
                    retry_policy=RetryPolicy(max_attempts=1),
                    execution_payload_ref=payload_ref,
                ),
                PlanStep(
                    step_id=TINY_DRY_RUN_STEP_ID,
                    capability="capability.execution.dry-run",
                    inputs=inputs,
                    outputs=("dry-run-report", "dry-run-checkpoint"),
                    environment_identity=environment_identity,
                    resource_reference=resource_reference,
                    dependencies=(StepDependency(PREFLIGHT_STEP_ID),),
                    retry_policy=RetryPolicy(max_attempts=1),
                    execution_payload_ref=payload_ref,
                ),
                PlanStep(
                    step_id=REAL_TRAINING_STEP_ID,
                    capability=YIELD_TRAINING_RUNTIME_CAPABILITY,
                    inputs=inputs,
                    outputs=("product-result",),
                    environment_identity=environment_identity,
                    resource_reference=resource_reference,
                    dependencies=(StepDependency(TINY_DRY_RUN_STEP_ID),),
                    retry_policy=RetryPolicy(max_attempts=real_attempts),
                    execution_payload_ref=payload_ref,
                ),
            ),
            metadata={"resolved_intent": payload_ref},
            provenance={"compiler": "cyrene-yield.training"},
        )


class TrainingControlPlane:
    """Drives Product phases while reusing TrainingRuntime's real execution path."""

    def __init__(
        self,
        runtime: TrainingRuntime,
        state_path: str | Path,
        *,
        compiler: Optional[TrainingPlanCompiler] = None,
        preflight: Optional[TrainingPreflight] = None,
        tiny_dry_run: Optional[TinyDryRun] = None,
        capability_resolver: Optional[TrainingRuntimeResolver] = None,
        durable_tiny_attempt: bool = False,
    ) -> None:
        self._runtime = runtime
        self._compiler = compiler or TrainingPlanCompiler()
        self._preflight = preflight or TrainingPreflight()
        self._tiny_dry_run = tiny_dry_run or TinyDryRun(runtime, self._preflight)
        self._capability_resolver = capability_resolver or YieldTrainingRuntimeResolver(runtime)
        self._control = ProductControlPlane(JsonFileControlPlaneStore(state_path))
        self._specs: Dict[str, TrainingSpec] = {}
        self._locks: Dict[str, EnvironmentLock] = {}
        self._execution_sessions: Dict[str, str] = {}
        self._resume_checkpoints: Dict[str, str] = {}
        self._durable_tiny_attempt = durable_tiny_attempt

    def submit(self, spec: TrainingSpec, *, idempotency_key: Optional[str] = None) -> ProductRun:
        lock = self._runtime.resolve_environment_lock(spec)
        self._capability_resolver.resolve(YIELD_TRAINING_RUNTIME_REQUIREMENT)
        plan = self._compiler.compile(spec, lock)
        spec_payload = _normalized(spec.to_dict())
        spec_digest = _digest(spec_payload)
        key = IdempotencyKey(idempotency_key or f"training:{spec_digest}:{lock.environment_digest}")
        run = self._control.submit(
            plan,
            product_kind=TRAINING_PRODUCT_KIND,
            idempotency_key=key,
            metadata={
                "training_spec_digest": spec_digest,
                TRAINING_SPEC_METADATA: _canonical_json(spec_payload),
                ENVIRONMENT_LOCK_METADATA: _canonical_json(lock.to_dict()),
            },
        )
        self._specs[run.run_id] = spec
        self._locks[run.run_id] = lock
        return run

    def load(self, run_id: str) -> ProductRun:
        return self._control.load(run_id)

    def spec(self, run_id: str) -> TrainingSpec:
        """Read the immutable validated intent for one ProductRun."""

        return self._require_spec(run_id)

    def environment_lock(self, run_id: str) -> EnvironmentLock:
        """Read the immutable resolved environment identity for one ProductRun."""

        return self._require_lock(run_id)

    def preflight_result(self, run_id: str):
        """Evaluate the configured preflight ports for one ProductRun."""

        return self._preflight.evaluate(
            self._require_spec(run_id),
            self._require_lock(run_id),
            self._runtime.hardware_facts,
        )

    def session_events(self, attempt_id: str):
        """Return the in-process events observed for one durable Attempt."""

        session = self._runtime.get(str(attempt_id))
        return tuple(session.events) if session is not None else ()

    def persisted_session_events(self, run_id: str, attempt_id: str):
        """Return the redacted event snapshot saved with an Attempt."""

        attempt = self._require_attempt(run_id, attempt_id)
        raw = attempt.metadata.get(TRAINING_EVENTS_METADATA)
        if not isinstance(raw, str):
            return ()
        try:
            documents = json.loads(raw)
        except json.JSONDecodeError:
            return ()
        if not isinstance(documents, list):
            return ()
        events = []
        for document in documents:
            if not isinstance(document, dict):
                continue
            try:
                events.append(TrainingEvent(**document))
            except (TypeError, ValueError):
                continue
        return tuple(events)

    def resume(self, run_id: str, *, checkpoint_path: str, step_id: str = REAL_TRAINING_STEP_ID) -> ProductRun:
        """Resume a stopped ProductRun from a complete checkpoint as a new Attempt."""

        if not checkpoint_path or not Path(checkpoint_path).exists():
            raise ValueError("YIELD_RESUME_CHECKPOINT_MISSING: stage a complete checkpoint before resume")
        attempt = self._control.resume_attempt(run_id, step_id)
        self._resume_checkpoints[str(attempt.attempt_id)] = checkpoint_path
        return self._execute_step(run_id, attempt)

    def request_cancel(self, run_id: str) -> ProductRun:
        return self._control.request_cancel(run_id)

    def output_artifacts(self, run_id: str) -> Dict[str, ArtifactRef]:
        """Return the latest durable result ArtifactRefs for the real training step."""

        run = self._control.load(run_id)
        for attempt in reversed(run.attempts):
            if attempt.step_id == REAL_TRAINING_STEP_ID:
                return _attempt_artifacts(attempt.metadata)
        return {}

    def checkpoint_artifacts(self, run_id: str) -> Dict[str, ArtifactRef]:
        """Return checkpoint artifacts from the most recent real Attempt.

        Checkpoint identity is read from the persisted Attempt metadata rather
        than from a private output path, so a resume request can be validated
        after the control process has restarted.
        """

        artifacts = self.output_artifacts(run_id)
        return {
            name: reference
            for name, reference in artifacts.items()
            if name.startswith("checkpoint") or reference.kind == "checkpoint"
        }

    def reconcile_once(self, run_id: str) -> ProductRun:
        """Perform one Product action; callers decide polling cadence."""

        action = self._control.next_action(run_id)
        if action.kind in {
            ReconcileActionKind.FINALIZE_SUCCEEDED,
            ReconcileActionKind.FINALIZE_FAILED,
            ReconcileActionKind.FINALIZE_BLOCKED,
            ReconcileActionKind.FINALIZE_CANCELLED,
        }:
            return self._control.apply_terminal_action(run_id)
        if action.kind is ReconcileActionKind.NOOP:
            return self._control.load(run_id)
        if action.kind is ReconcileActionKind.WAIT:
            return self._observe_execution_if_present(run_id, action.attempt_id)
        if action.kind is ReconcileActionKind.REQUEST_CANCELLATION:
            return self._cancel_execution(run_id, action.attempt_id)
        self._require_spec(run_id)
        self._require_lock(run_id)
        attempt = self._control.start_next_attempt(run_id)
        return self._execute_step(run_id, attempt)

    def _execute_step(self, run_id: str, attempt: Attempt) -> ProductRun:
        spec = self._require_spec(run_id)
        lock = self._require_lock(run_id)
        if attempt.step_id == PREFLIGHT_STEP_ID:
            result = self._preflight.evaluate(spec, lock, self._runtime.hardware_facts)
            if result.status is PreflightStatus.BLOCKED:
                return self._control.observe_attempt(
                    run_id, attempt.attempt_id, AttemptStatus.BLOCKED, error=_issues_text(result)
                )
            if result.status is PreflightStatus.UNKNOWN and not self._preflight.can_safely_resolve_with_tiny_dry_run(
                result
            ):
                return self._control.observe_attempt(
                    run_id, attempt.attempt_id, AttemptStatus.BLOCKED, error=_issues_text(result)
                )
            return self._control.observe_attempt(run_id, attempt.attempt_id, AttemptStatus.SUCCEEDED)
        if attempt.step_id == TINY_DRY_RUN_STEP_ID:
            if self._durable_tiny_attempt:
                # Preflight is already committed as the preceding plan step.
                # Persist this real bounded execution exactly like full training.
                engine = self._capability_resolver.resolve(YIELD_TRAINING_RUNTIME_REQUIREMENT)
                bounded = TinyDryRun.bounded_spec(spec)
                bounded.job_id = str(attempt.attempt_id)
                session = engine.submit(bounded)
                self._execution_sessions[str(attempt.attempt_id)] = session.session_id
                return self._observe_training_session(run_id, attempt, session)
            result = self._tiny_dry_run.run(spec)
            status = {
                TinyDryRunStatus.SUCCEEDED: AttemptStatus.SUCCEEDED,
                TinyDryRunStatus.BLOCKED: AttemptStatus.BLOCKED,
                TinyDryRunStatus.UNKNOWN: AttemptStatus.BLOCKED,
                TinyDryRunStatus.CANCELLED: AttemptStatus.CANCELLED,
                TinyDryRunStatus.FAILED: AttemptStatus.FAILED,
            }[result.status]
            references = [result.session_id] if result.session_id else ()
            return self._control.observe_attempt(
                run_id,
                attempt.attempt_id,
                status,
                execution_references=references,
                cleanup_confirmed=result.status is TinyDryRunStatus.CANCELLED,
                error="; ".join(issue.message for issue in result.issues) or None,
                metadata=_result_metadata(result.output_artifacts, attempt.metadata),
            )
        if attempt.step_id == REAL_TRAINING_STEP_ID:
            engine = self._capability_resolver.resolve(YIELD_TRAINING_RUNTIME_REQUIREMENT)
            execution_spec = TrainingSpec.from_dict(spec.to_dict())
            execution_spec.job_id = str(attempt.attempt_id)
            resume_from = self._resume_checkpoints.pop(str(attempt.attempt_id), None)
            if resume_from:
                checkpoint = execution_spec.checkpoint.to_dict()
                checkpoint["resume_from"] = resume_from
                execution_spec.checkpoint = CheckpointSpec.from_dict(checkpoint)
            session = engine.submit(execution_spec)
            self._execution_sessions[str(attempt.attempt_id)] = session.session_id
            return self._observe_training_session(run_id, attempt, session)
        raise ValueError(f"Unknown Yield PlanStep: {attempt.step_id}")

    def _observe_execution_if_present(self, run_id: str, attempt_id) -> ProductRun:
        if attempt_id is None:
            return self._control.load(run_id)
        attempt = self._require_attempt(run_id, attempt_id)
        session_id = self._execution_session_id(attempt)
        if session_id is None:
            return self._quarantine_unknown_execution(
                run_id,
                attempt,
                "active Attempt has no durable execution reference",
            )
        engine = self._capability_resolver.resolve(YIELD_TRAINING_RUNTIME_REQUIREMENT)
        try:
            session = engine.poll(session_id)
        except KeyError:
            return self._quarantine_unknown_execution(
                run_id,
                attempt,
                f"execution reference {session_id!r} cannot be observed after controller restart",
            )
        return self._observe_training_session(
            run_id,
            attempt,
            session,
            expected_session_id=session_id,
        )

    def _cancel_execution(self, run_id: str, attempt_id) -> ProductRun:
        if attempt_id is None:
            return self._control.load(run_id)
        attempt = self._require_attempt(run_id, attempt_id)
        session_id = self._execution_session_id(attempt)
        if session_id is None:
            return self._record_unconfirmed_cancellation(
                run_id,
                attempt,
                "active Attempt has no durable execution reference; cleanup is unconfirmed",
            )
        engine = self._capability_resolver.resolve(YIELD_TRAINING_RUNTIME_REQUIREMENT)
        try:
            session = engine.cancel(session_id)
        except KeyError:
            return self._record_unconfirmed_cancellation(
                run_id,
                attempt,
                f"execution reference {session_id!r} cannot be cancelled after controller restart; cleanup is unconfirmed",
            )
        if session.session_id != session_id:
            return self._record_unconfirmed_cancellation(
                run_id,
                attempt,
                (
                    f"execution reference {session_id!r} returned mismatched session "
                    f"{session.session_id!r}; cleanup is unconfirmed"
                ),
            )
        status = _attempt_status(session.status)
        if status is not AttemptStatus.CANCELLED:
            return self._record_unconfirmed_cancellation(
                run_id,
                attempt,
                session.error or "execution adapter did not confirm cancellation cleanup",
            )
        return self._control.observe_attempt(
            run_id,
            attempt_id,
            status,
            execution_references=(session_id,),
            cleanup_confirmed=True,
            error=session.error or None,
            metadata=_result_metadata(
                {} if session.result is None else session.result.artifacts,
                attempt.metadata,
                session.events,
            ),
        )

    def _observe_training_session(
        self,
        run_id: str,
        attempt: Attempt,
        session,
        *,
        expected_session_id: Optional[str] = None,
    ) -> ProductRun:
        if expected_session_id is not None and session.session_id != expected_session_id:
            return self._quarantine_unknown_execution(
                run_id,
                attempt,
                (f"execution reference {expected_session_id!r} returned mismatched session {session.session_id!r}"),
            )
        return self._control.observe_attempt(
            run_id,
            attempt.attempt_id,
            _attempt_status(session.status),
            execution_references=(session.session_id,),
            error=session.error or None,
            metadata=_result_metadata(
                {} if session.result is None else session.result.artifacts,
                attempt.metadata,
                session.events,
            ),
        )

    def _quarantine_unknown_execution(self, run_id: str, attempt: Attempt, detail: str) -> ProductRun:
        run = self._control.load(run_id)
        if run.desired_state is not DesiredState.CANCELLED:
            self._control.request_cancel(run_id)
        return self._control.observe_attempt(
            run_id,
            attempt.attempt_id,
            AttemptStatus.CANCELLING,
            execution_references=attempt.execution_references,
            cleanup_confirmed=False,
            error=(
                f"{EXECUTION_RECOVERY_UNAVAILABLE}: {detail}; automatic retry is quarantined until cleanup is confirmed"
            ),
        )

    def _record_unconfirmed_cancellation(
        self,
        run_id: str,
        attempt: Attempt,
        detail: str,
    ) -> ProductRun:
        error = f"{EXECUTION_RECOVERY_UNAVAILABLE}: {detail}"
        if attempt.status is AttemptStatus.CANCELLING and not attempt.cleanup_confirmed and attempt.error == error:
            return self._control.load(run_id)
        return self._control.observe_attempt(
            run_id,
            attempt.attempt_id,
            AttemptStatus.CANCELLING,
            execution_references=attempt.execution_references,
            cleanup_confirmed=False,
            error=error,
        )

    def _execution_session_id(self, attempt: Attempt) -> Optional[str]:
        cached = self._execution_sessions.get(str(attempt.attempt_id))
        if cached is not None:
            return cached
        if not attempt.execution_references:
            return None
        session_id = attempt.execution_references[0]
        self._execution_sessions[str(attempt.attempt_id)] = session_id
        return session_id

    def _require_attempt(self, run_id: str, attempt_id) -> Attempt:
        run = self._control.load(run_id)
        attempt = next((item for item in run.attempts if item.attempt_id == attempt_id), None)
        if attempt is None:
            raise KeyError(f"Unknown Attempt: {attempt_id}")
        return attempt

    def _require_spec(self, run_id: str) -> TrainingSpec:
        cached = self._specs.get(run_id)
        if cached is not None:
            return cached
        run = self._control.load(run_id)
        payload = _metadata_mapping(run.metadata, TRAINING_SPEC_METADATA, run_id)
        try:
            spec = TrainingSpec.from_dict(dict(payload))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise TrainingStateRecoveryError(f"ProductRun {run_id} contains an invalid TrainingSpec") from exc
        plan = self._control.load_plan(run.plan_id)
        expected = str(plan.metadata.get("resolved_intent") or "")
        actual = f"sha256:{_digest(spec.to_dict())}"
        if actual != expected:
            raise TrainingStateRecoveryError(
                f"TrainingSpec for {run_id} does not match immutable plan intent {expected!r}"
            )
        self._specs[run_id] = spec
        return spec

    def _require_lock(self, run_id: str) -> EnvironmentLock:
        cached = self._locks.get(run_id)
        if cached is not None:
            return cached
        run = self._control.load(run_id)
        payload = _metadata_mapping(run.metadata, ENVIRONMENT_LOCK_METADATA, run_id)
        try:
            lock = EnvironmentLock.from_dict(payload)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise TrainingStateRecoveryError(f"ProductRun {run_id} contains an invalid EnvironmentLock") from exc
        plan = self._control.load_plan(run.plan_id)
        expected = {step.environment_identity for step in plan.steps}
        if expected != {lock.environment_digest}:
            raise TrainingStateRecoveryError(f"EnvironmentLock for {run_id} does not match immutable plan identity")
        self._locks[run_id] = lock
        return lock


def _input_artifacts(spec: TrainingSpec) -> Tuple[ArtifactRef, ...]:
    references = []
    for item in spec.extra.get("input_artifacts") or ():
        if isinstance(item, ArtifactRef):
            references.append(item)
        elif isinstance(item, dict):
            references.append(ArtifactRef.from_dict(item))
    return tuple(references)


def _digest(value) -> str:
    encoded = json.dumps(_normalized(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json(value) -> str:
    return json.dumps(_normalized(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _metadata_mapping(metadata: Mapping, key: str, run_id: str) -> Mapping:
    raw = metadata.get(key)
    if not isinstance(raw, str):
        raise TrainingStateRecoveryError(f"ProductRun {run_id} is missing durable metadata {key!r}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TrainingStateRecoveryError(f"ProductRun {run_id} contains invalid durable metadata {key!r}") from exc
    if not isinstance(value, dict):
        raise TrainingStateRecoveryError(f"ProductRun {run_id} durable metadata {key!r} must be an object")
    return value


def _result_metadata(
    artifacts: Mapping[str, ArtifactRef],
    existing: Mapping,
    events=(),
) -> Optional[Dict]:
    if not artifacts and not events:
        return None
    metadata = dict(existing)
    if artifacts:
        metadata[RESULT_ARTIFACTS_METADATA] = _canonical_json(
            {name: reference.to_dict() for name, reference in artifacts.items()}
        )
    if events:
        metadata[TRAINING_EVENTS_METADATA] = _canonical_json(
            [
                {
                    "kind": event.kind.value,
                    "step": event.step,
                    "total_steps": event.total_steps,
                    "epoch": event.epoch,
                    "loss": event.loss,
                    "learning_rate": event.learning_rate,
                    "timestamp": event.timestamp,
                }
                for event in events
            ]
        )
    return metadata


def _attempt_artifacts(metadata: Mapping) -> Dict[str, ArtifactRef]:
    raw = metadata.get(RESULT_ARTIFACTS_METADATA)
    if raw is None:
        return {}
    if not isinstance(raw, str):
        raise TrainingStateRecoveryError("Attempt result Artifact metadata must be canonical JSON")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TrainingStateRecoveryError("Attempt result Artifact metadata is invalid") from exc
    if not isinstance(payload, dict):
        raise TrainingStateRecoveryError("Attempt result Artifact metadata must be an object")
    if any(not isinstance(value, dict) for value in payload.values()):
        raise TrainingStateRecoveryError("Attempt result ArtifactRef must be an object")
    try:
        return {str(name): ArtifactRef.from_dict(value) for name, value in payload.items()}
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TrainingStateRecoveryError("Attempt result ArtifactRef is invalid") from exc


def _normalized(value):
    if isinstance(value, dict):
        return {str(key): _normalized(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalized(item) for item in value]
    if hasattr(value, "to_dict"):
        return _normalized(value.to_dict())
    return value


def _positive_int(value, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _issues_text(result) -> str:
    return "; ".join(issue.message for issue in result.issues) or result.status.value


def _attempt_status(status: TrainingStatus) -> AttemptStatus:
    return {
        TrainingStatus.QUEUED: AttemptStatus.PENDING,
        TrainingStatus.RUNNING: AttemptStatus.RUNNING,
        TrainingStatus.CANCELLING: AttemptStatus.CANCELLING,
        TrainingStatus.COMPLETED: AttemptStatus.SUCCEEDED,
        TrainingStatus.FAILED: AttemptStatus.FAILED,
        TrainingStatus.CANCELLED: AttemptStatus.CANCELLED,
        TrainingStatus.LOST: AttemptStatus.LOST,
        TrainingStatus.AWAITING_RETRY: AttemptStatus.LOST,
    }[status]


__all__ = ["TrainingControlPlane", "TrainingPlanCompiler", "TrainingStateRecoveryError"]
