"""Product training runtime over an explicitly configured Platform executor.

Yield owns Product run and attempt projections. It never starts a local
process tree when the Platform execution adapter is absent; missing execution
authority is a stable, fail-closed Product outcome.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/runtime.py
# │ Module: training/core/src/cy_exec/training/runtime
# │ Role: Product training coordination over explicit Platform execution.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import sys
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from cy_artifacts import ArtifactError, ArtifactProvider, LocalArtifactProvider
from cyrene_preflight import HardwareFacts

from .artifacts import publish_training_outputs
from .contracts import (
    KernelBinding,
    KernelOperationRef,
    TrainingAttempt,
    TrainingEvent,
    TrainingLaunchSpec,
    TrainingResult,
    TrainingRun,
    TrainingSpec,
    TrainingStatus,
    WorkloadConfigRef,
)
from .engines import get_engine
from .environment import (
    EnvironmentCandidate,
    EnvironmentResolutionStatus,
    EnvironmentResolver,
    EnvironmentSpec,
    HardwareRuntimeFacts,
    local_environment_candidate,
)
from .executors import CancelOutcome, ExecutionControlError, ProcessHandle
from .executors.base import TrainingExecutor
from .product_results import publish_adapter


@dataclass
class TrainingSession:
    """Product-facing handle around a TrainingRun and its attempts."""

    session_id: str
    spec: TrainingSpec
    status: TrainingStatus = TrainingStatus.QUEUED
    launch: TrainingLaunchSpec | None = None
    handle: ProcessHandle | None = None
    result: TrainingResult | None = None
    events: list[TrainingEvent] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    diagnostics_degraded: bool = False
    error: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    run: TrainingRun | None = None

    @property
    def current_attempt(self) -> TrainingAttempt | None:
        return self.run.current_attempt if self.run is not None else None


# ════════════════════════════════════════════════════════════════════════
# 🔧 CLASS: TrainingRuntime
#
#   Coordinates product training attempts, engine adapters, executors, event
#   handling, retry decisions, and checkpoint collection.
#
#   协调产品训练尝试、引擎适配器、执行器、事件处理、重试决策与检查点收集。
#
# ════════════════════════════════════════════════════════════════════════
class TrainingRuntime:
    """Owns in-process execution sessions for every engine and executor."""

    def __init__(
        self,
        executor: TrainingExecutor | None = None,
        artifact_provider: ArtifactProvider | None = None,
        environment_resolver: EnvironmentResolver | None = None,
        environment_catalog: Sequence[EnvironmentCandidate] | None = None,
        hardware_facts: HardwareFacts | None = None,
    ) -> None:
        self._executor = executor
        self._artifact_provider = artifact_provider
        self._environment_resolver = environment_resolver or EnvironmentResolver()
        self._environment_catalog = tuple(
            environment_catalog if environment_catalog is not None else (local_environment_candidate(),)
        )
        self._hardware_facts = hardware_facts
        self._sessions: dict[str, TrainingSession] = {}
        self._lock = threading.Lock()

    def submit(self, spec: TrainingSpec) -> TrainingSession:
        adapter = get_engine(spec.engine)
        validation = adapter.validate(spec)
        session_id = spec.job_id or str(uuid.uuid4())
        spec.job_id = session_id
        run = TrainingRun(run_id=session_id, spec=spec)
        session = TrainingSession(session_id=session_id, spec=spec, run=run)
        if not validation.ok:
            session.status = TrainingStatus.FAILED
            run.status = TrainingStatus.FAILED
            session.error = "; ".join(issue.message for issue in validation.issues)
            session.result = TrainingResult(
                status=TrainingStatus.FAILED,
                output_dir=spec.output_dir,
                message=session.error,
            )
            with self._lock:
                self._sessions[session_id] = session
            return session

        try:
            environment_lock = self._resolve_environment_lock(spec)
        except ValueError as exc:
            session.status = TrainingStatus.FAILED
            run.status = TrainingStatus.FAILED
            session.error = str(exc)
            session.result = TrainingResult(
                status=TrainingStatus.FAILED,
                output_dir=spec.output_dir,
                message=session.error,
            )
            with self._lock:
                self._sessions[session_id] = session
            return session
        launch = adapter.compile(spec)
        launch.environment_lock = environment_lock
        launch.assert_executor_agnostic()
        self._start_attempt(session, launch)
        with self._lock:
            self._sessions[session_id] = session
        return session

    def retry(self, session_id: str) -> TrainingSession:
        session = self._require(session_id)
        attempt = session.current_attempt
        if session.status not in (
            TrainingStatus.AWAITING_RETRY,
            TrainingStatus.LOST,
            TrainingStatus.FAILED,
        ):
            raise ValueError(f"Cannot retry session {session_id} in status {session.status.value}")
        if attempt is not None and attempt.status not in (
            TrainingStatus.LOST,
            TrainingStatus.FAILED,
        ):
            raise ValueError(f"Cannot retry attempt {attempt.attempt_id} in status {attempt.status.value}")
        adapter = get_engine(session.spec.engine)
        launch = adapter.compile(session.spec)
        launch.environment_lock = self._resolve_environment_lock(session.spec)
        launch.assert_executor_agnostic()
        self._start_attempt(session, launch)
        return session

    def get(self, session_id: str) -> TrainingSession | None:
        return self._sessions.get(session_id)

    def list_sessions(self, status: TrainingStatus | None = None, limit: int = 100) -> list[TrainingSession]:
        sessions = list(self._sessions.values())
        if status is not None:
            sessions = [item for item in sessions if item.status == status]
        sessions.sort(key=lambda item: item.created_at, reverse=True)
        return sessions[:limit]

    def poll(self, session_id: str) -> TrainingSession:
        session = self._require(session_id)
        if session.status not in (TrainingStatus.QUEUED, TrainingStatus.RUNNING):
            return session
        if session.handle is None or session.launch is None:
            return session
        adapter = get_engine(session.spec.engine)
        attempt = session.current_attempt
        executor = self._require_executor()
        for line in executor.read_new_output(session.handle):
            event = adapter.parse_event(line)
            if event is not None:
                session.events.append(event)
                if attempt is not None:
                    if attempt.events is not session.events:
                        attempt.events.append(event)
        # Diagnostics ride alongside events: the raw stream is a separate copy
        # and never replaces the business event stream.
        reader = getattr(executor, "read_new_diagnostics", None)
        if reader is not None:
            session.diagnostics.extend(reader(session.handle))
        degraded = getattr(executor, "diagnostics_degraded", None)
        if degraded is not None and degraded(session.handle):
            session.diagnostics_degraded = True
        if session.handle.extra.get("lost"):
            self._mark_attempt_lost(session, "worker/operation lost")
            return session
        code = executor.poll(session.handle)
        if code is None:
            return session
        status = TrainingStatus.COMPLETED if code == 0 else TrainingStatus.FAILED
        session.status = status
        if session.run is not None:
            session.run.status = status
        if attempt is not None:
            attempt.status = status
        session.result = adapter.collect_result(session.spec, session.launch, code, status)
        try:
            session.result.artifacts = publish_training_outputs(
                self._provider_for(session.spec),
                session.launch,
            )
            source = session.spec.extra.get("base_source")
            if status is TrainingStatus.COMPLETED and isinstance(source, dict):
                session.result.artifacts["model"] = publish_adapter(
                    self._provider_for(session.spec),
                    Path(session.spec.output_dir),
                    base_source=source,
                    staged_base=session.spec.model.path,
                )
        except (ArtifactError, OSError, ValueError) as exc:
            # A zero exit without publishable weights is a failed Product result.
            session.status = TrainingStatus.FAILED
            session.result.status = TrainingStatus.FAILED
            session.error = str(exc).split(":", 1)[0]
            if session.run is not None:
                session.run.status = TrainingStatus.FAILED
            if attempt is not None:
                attempt.status = TrainingStatus.FAILED
        if attempt is not None:
            attempt.result = session.result
        session.updated_at = datetime.now()
        if session.run is not None:
            session.run.updated_at = session.updated_at
        return session

    def restore_session(self, launch: TrainingLaunchSpec, handle: ProcessHandle) -> TrainingSession:
        """Restore a Kernel execution receipt without submitting or retrying work."""
        spec = TrainingSpec.from_dict(launch.extra["product_spec"])
        session_id = str(spec.job_id)
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            run = TrainingRun(run_id=session_id, spec=spec, status=TrainingStatus.RUNNING)
            attempt = TrainingAttempt(
                attempt_id=str(launch.extra["attempt_id"]),
                run_id=session_id,
                ordinal=1,
                spec=spec,
                status=TrainingStatus.RUNNING,
                launch=launch,
                binding=_binding_from_handle(handle),
            )
            run.attempts.append(attempt)
            session = TrainingSession(
                session_id=session_id,
                spec=spec,
                status=TrainingStatus.RUNNING,
                launch=launch,
                handle=handle,
                run=run,
            )
            self._sessions[session_id] = session
            return session

    def _provider_for(self, spec: TrainingSpec) -> ArtifactProvider:
        if self._artifact_provider is not None:
            return self._artifact_provider
        return LocalArtifactProvider(Path(spec.output_dir).parent / ".cyrene-artifacts")

    @property
    def hardware_facts(self) -> HardwareFacts | None:
        """Canonical Node inventory projection supplied by the runtime host."""

        return self._hardware_facts

    def update_hardware_facts(self, facts: HardwareFacts) -> None:
        """Refresh canonical host observations before a new Product preflight."""
        self._hardware_facts = facts

    def artifact_provider_for(self, spec: TrainingSpec) -> ArtifactProvider:
        """Publish product reports through the same Artifact Plane provider."""

        return self._provider_for(spec)

    def resolve_environment_lock(self, spec: TrainingSpec):
        """Resolve once for Product orchestration without moving resolution into an engine."""

        return self._resolve_environment_lock(spec)

    def _resolve_environment_lock(self, spec: TrainingSpec):
        environment_spec = spec.environment
        if environment_spec is None:
            environment_spec = EnvironmentSpec(
                runtime_profile="local",
                python_version_constraint=f"=={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            )
            catalog = (local_environment_candidate(),)
        else:
            catalog = self._environment_catalog
        resolution = self._environment_resolver.resolve(
            environment_spec,
            catalog,
            _environment_hardware_facts(self._hardware_facts),
        )
        if resolution.status != EnvironmentResolutionStatus.COMPATIBLE:
            reasons = "; ".join(resolution.reasons) or resolution.status.value
            raise ValueError(f"environment resolution {resolution.status.value}: {reasons}")
        return resolution.require_lock()

    def wait(self, session_id: str, timeout: float | None = None, poll_interval: float = 0.2) -> TrainingSession:
        deadline = None if timeout is None else time.time() + timeout
        while True:
            session = self.poll(session_id)
            if session.status not in (TrainingStatus.QUEUED, TrainingStatus.RUNNING, TrainingStatus.CANCELLING):
                return session
            if deadline is not None and time.time() >= deadline:
                return session
            time.sleep(poll_interval)

    def cancel(self, session_id: str, timeout: float = 15.0) -> TrainingSession:
        session = self._require(session_id)
        if session.status in (
            TrainingStatus.COMPLETED,
            TrainingStatus.FAILED,
            TrainingStatus.CANCELLED,
            TrainingStatus.AWAITING_RETRY,
        ):
            return session
        if session.status == TrainingStatus.LOST:
            session.status = TrainingStatus.AWAITING_RETRY
            if session.run is not None:
                session.run.status = TrainingStatus.AWAITING_RETRY
            return session
        if session.handle is None:
            session.status = TrainingStatus.CANCELLED
            if session.run is not None:
                session.run.status = TrainingStatus.CANCELLED
            session.updated_at = datetime.now()
            session.result = TrainingResult(
                status=TrainingStatus.CANCELLED,
                output_dir=session.spec.output_dir,
                message="cancelled before process start",
            )
            return session

        session.status = TrainingStatus.CANCELLING
        if session.run is not None:
            session.run.status = TrainingStatus.CANCELLING
        attempt = session.current_attempt
        if attempt is not None:
            attempt.status = TrainingStatus.CANCELLING

        outcome: CancelOutcome = self._require_executor().cancel(session.handle, timeout=timeout)
        adapter = get_engine(session.spec.engine)
        launch = session.launch or _empty_launch(session.spec)
        cleanup_ok = bool(outcome.stopped and outcome.cleanup_confirmed and not outcome.remaining_pids)
        if cleanup_ok:
            session.status = TrainingStatus.CANCELLED
            if session.run is not None:
                session.run.status = TrainingStatus.CANCELLED
            if attempt is not None:
                attempt.status = TrainingStatus.CANCELLED
            session.result = adapter.collect_result(
                session.spec,
                launch,
                None,
                TrainingStatus.CANCELLED,
            )
            session.result.message = outcome.message or session.result.message
            if attempt is not None:
                attempt.result = session.result
        else:
            message = outcome.message or "unable to confirm process-tree cleanup"
            self._mark_attempt_lost(session, message)
            session.result = adapter.collect_result(
                session.spec,
                launch,
                None,
                TrainingStatus.LOST,
            )
            session.result.message = message
            if attempt is not None:
                attempt.result = session.result
                attempt.error = message
        session.updated_at = datetime.now()
        if session.run is not None:
            session.run.updated_at = session.updated_at
        return session

    def _start_attempt(self, session: TrainingSession, launch: TrainingLaunchSpec) -> None:
        run = session.run
        if run is None:
            run = TrainingRun(run_id=session.session_id, spec=session.spec)
            session.run = run
        ordinal = len(run.attempts) + 1
        attempt = TrainingAttempt(
            attempt_id=f"{session.session_id}:{ordinal}",
            run_id=run.run_id,
            ordinal=ordinal,
            spec=session.spec,
            status=TrainingStatus.QUEUED,
            launch=launch,
        )
        launch.extra = dict(launch.extra or {})
        launch.extra["product_spec"] = session.spec.to_dict()
        launch.extra["attempt_id"] = attempt.attempt_id
        try:
            handle = self._require_executor().start(launch)
        except ExecutionControlError as exc:
            status = TrainingStatus.LOST if exc.lost else TrainingStatus.FAILED
            attempt.status = status
            attempt.error = str(exc)
            attempt.updated_at = datetime.now()
            run.attempts.append(attempt)
            run.status = TrainingStatus.AWAITING_RETRY if exc.lost else status
            run.error = str(exc)
            session.status = run.status
            session.error = str(exc)
            session.updated_at = datetime.now()
            run.updated_at = session.updated_at
            return
        attempt.status = TrainingStatus.RUNNING
        attempt.binding = _binding_from_handle(handle)
        run.attempts.append(attempt)
        run.status = TrainingStatus.RUNNING
        session.launch = launch
        session.handle = handle
        session.status = TrainingStatus.RUNNING
        session.events = attempt.events
        session.error = ""
        session.updated_at = datetime.now()
        run.updated_at = session.updated_at

    def _mark_attempt_lost(self, session: TrainingSession, message: str) -> None:
        attempt = session.current_attempt
        if attempt is not None:
            attempt.status = TrainingStatus.LOST
            attempt.error = message
            attempt.updated_at = datetime.now()
        session.status = TrainingStatus.AWAITING_RETRY
        session.error = message
        session.updated_at = datetime.now()
        if session.run is not None:
            session.run.status = TrainingStatus.AWAITING_RETRY
            session.run.error = message
            session.run.updated_at = session.updated_at

    def _require(self, session_id: str) -> TrainingSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown training session: {session_id}")
        return session

    def _require_executor(self) -> TrainingExecutor:
        """Return the configured Platform adapter or fail closed.

        Returns:
            The explicit execution port supplied by the Product composition root.
        Raises:
            ExecutionControlError: If no Platform execution binding is configured.
        """

        if self._executor is None:
            raise ExecutionControlError("YIELD_EXECUTION_NOT_CONFIGURED: configure the Platform execution adapter")
        return self._executor


def _binding_from_handle(handle: ProcessHandle) -> KernelBinding:
    extra = handle.extra or {}
    resource_ids = extra.get("resource_ids") or []
    operations = []
    for item in extra.get("operations") or []:
        if isinstance(item, dict):
            operations.append(
                KernelOperationRef(
                    operation_id=str(item.get("operation_id") or ""),
                    kind=str(item.get("kind") or ""),
                    state=str(item.get("state") or ""),
                )
            )
    ref_payload = extra.get("workload_config_ref")
    workload_ref = None
    if isinstance(ref_payload, dict) and ref_payload.get("digest"):
        workload_ref = WorkloadConfigRef.from_dict(ref_payload)
    return KernelBinding(
        node_id=str(extra.get("node_id") or extra.get("allocation_node_id") or ""),
        principal_id=str(extra.get("principal_id") or ""),
        lease_id=str(extra.get("lease_id") or ""),
        fence_token=int(extra.get("fence_token") or 0),
        resource_ids=list(resource_ids),
        worker_id=str(extra.get("worker_id") or ""),
        start_operation_id=str(extra.get("start_operation_id") or extra.get("operation_id") or ""),
        operations=operations,
        execution_ref=str(extra.get("execution_ref") or ""),
        workload_config_ref=workload_ref,
        extra={
            "assigned_env": dict(extra.get("assigned_env") or {}),
            "plugin_configure": dict(extra.get("plugin_configure") or {}),
            "worker_visible_path": extra.get("worker_visible_path") or "",
        },
    )


def _empty_launch(spec: TrainingSpec) -> TrainingLaunchSpec:
    from .contracts.launch import ResourceRequest

    return TrainingLaunchSpec(
        engine=spec.engine,
        argv=[],
        work_dir=spec.output_dir,
        distributed=spec.distributed,
        checkpoint=spec.checkpoint,
        resources=ResourceRequest.from_distributed(spec.distributed),
    )


def _environment_hardware_facts(
    facts: HardwareFacts | None,
) -> HardwareRuntimeFacts | None:
    """Map the canonical Node inventory to Environment's smaller generic view."""

    if facts is None:
        return None
    precision = None
    for candidate in ("fp8", "bf16", "fp16", "int8", "int4"):
        if facts.precision_support(candidate) is True:
            precision = candidate
            break
    return HardwareRuntimeFacts(
        architecture=facts.architecture,
        precision=precision,
        driver_version=facts.driver_version,
        accelerator_runtime=facts.accelerator_runtime,
    )
