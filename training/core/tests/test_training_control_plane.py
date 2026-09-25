# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_training_control_plane.py
# │ 中文:文件:training/core/tests/test_training_control_plane.py
# │ Module: training/core/tests/test_training_control_plane
# │ 模块:training/core/tests/test_training_control_plane
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │ 职责:Yield 核心测试模块,验证统一训练 runtime 与契约。
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import json
import platform
from dataclasses import replace
from pathlib import Path

import pytest

from cy_exec.training.lifecycle import AttemptStatus, DesiredState, PlanStatus
from cyrene_preflight import AcceleratorFacts, HardwareFacts
from cy_exec.training import TrainingControlPlane, TrainingRuntime, TrainingStateRecoveryError
from cy_exec.training.capability_seam import (
    YieldTrainingRuntimeResolver,
    YIELD_TRAINING_RUNTIME_CAPABILITY,
    YIELD_TRAINING_RUNTIME_REQUIREMENT,
)
from cy_exec.training.control_plane import ENVIRONMENT_LOCK_METADATA, TRAINING_SPEC_METADATA
from cy_exec.training.executors.base import CancelOutcome, ProcessHandle
from training_tck_helpers import make_spec

GiB = 1024**3


def _hardware(memory_bytes=24 * GiB):
    return HardwareFacts.from_node_resource_inventory(
        node_id="control-node",
        inventory_generation=4,
        architecture=platform.machine().lower(),
        accelerators=(
            AcceleratorFacts(
                device_id="gpu-0",
                kind="gpu",
                vendor="nvidia",
                total_memory_bytes=memory_bytes,
                allocatable_memory_bytes=memory_bytes,
                features=("precision:int4", "precision:bf16", "precision:fp16"),
            ),
        ),
    )


class CompletedExecutor:
    def __init__(self):
        self.launches = []

    def start(self, launch):
        self.launches.append(launch)
        checkpoint = Path(launch.work_dir) / "checkpoint-1"
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "model.safetensors").write_bytes(b"checkpoint")
        (checkpoint / "checkpoint_info.json").write_text(
            json.dumps(
                {
                    "path": str(checkpoint),
                    "step": 1,
                    "epoch": 1.0,
                    "loss": 0.1,
                    "timestamp": "2026-01-01T00:00:00",
                    "is_valid": True,
                }
            ),
            encoding="utf-8",
        )
        return ProcessHandle(pid=321, argv=list(launch.argv), work_dir=launch.work_dir)

    def poll(self, _handle):
        return 0

    def read_new_output(self, _handle):
        return ()

    def cancel(self, _handle, timeout=15.0):
        return CancelOutcome(stopped=True, cleanup_confirmed=True)


class FailingExecutor(CompletedExecutor):
    def poll(self, _handle):
        return 1


class ArtifactProducingExecutor(CompletedExecutor):
    def start(self, launch):
        handle = super().start(launch)
        model = Path(launch.work_dir) / "model"
        model.mkdir(parents=True, exist_ok=True)
        (model / "adapter.safetensors").write_bytes(b"adapter")
        return handle


class RecordingTrainingResolver:
    def __init__(self, runtime):
        self._reference = YieldTrainingRuntimeResolver(runtime)
        self.requirements = []

    def resolve(self, requirement):
        self.requirements.append(requirement)
        return self._reference.resolve(requirement)


class MismatchedSessionResolver:
    def __init__(self, runtime, operation):
        reference = YieldTrainingRuntimeResolver(runtime)
        self._engine = reference.resolve(YIELD_TRAINING_RUNTIME_REQUIREMENT)
        self._operation = operation

    def resolve(self, requirement):
        if requirement != YIELD_TRAINING_RUNTIME_REQUIREMENT:
            raise ValueError(f"Unsupported training capability requirement: {requirement}")
        return self

    def submit(self, spec):
        return self._engine.submit(spec)

    def poll(self, session_id):
        session = self._engine.poll(session_id)
        if self._operation == "poll":
            return replace(session, session_id=f"mismatched-{session_id}")
        return session

    def cancel(self, session_id):
        session = self._engine.cancel(session_id)
        if self._operation == "cancel":
            return replace(session, session_id=f"mismatched-{session_id}")
        return session


def _spec(tmp_path, *, parameters=1_000_000):
    spec = make_spec(tmp_path, "llamafactory")
    spec.model.extra["parameter_count"] = parameters
    return spec


def _advance(control, run_id, count):
    run = None
    for _ in range(count):
        run = control.reconcile_once(run_id)
    return run


def test_training_spec_compiles_deterministically_to_explicit_phase_plan(tmp_path):
    control = TrainingControlPlane(
        TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware()), tmp_path / "state.json"
    )
    first = control.submit(_spec(tmp_path), idempotency_key="same-intent")
    second = control.submit(_spec(tmp_path), idempotency_key="same-intent")

    assert first.run_id == second.run_id
    plan = control._control.load_plan(first.plan_id)
    assert [step.step_id for step in plan.ordered_steps()] == [
        "training-preflight",
        "training-tiny-dry-run",
        "training-execution",
    ]


def test_preflight_blocked_prevents_plan_advancement_and_execution(tmp_path):
    executor = CompletedExecutor()
    control = TrainingControlPlane(TrainingRuntime(executor, hardware_facts=_hardware(1)), tmp_path / "state.json")
    run = control.submit(_spec(tmp_path, parameters=7_000_000_000))

    _advance(control, run.run_id, 2)

    assert control.load(run.run_id).observed_status is PlanStatus.BLOCKED
    assert executor.launches == []


def test_tiny_dry_run_failure_prevents_real_training_step(tmp_path):
    executor = FailingExecutor()
    control = TrainingControlPlane(TrainingRuntime(executor, hardware_facts=_hardware()), tmp_path / "state.json")
    run = control.submit(_spec(tmp_path))

    _advance(control, run.run_id, 3)

    assert control.load(run.run_id).observed_status is PlanStatus.FAILED
    assert len(executor.launches) == 1


def test_successful_dry_run_advances_to_same_real_training_runtime_path(tmp_path):
    executor = CompletedExecutor()
    control = TrainingControlPlane(TrainingRuntime(executor, hardware_facts=_hardware()), tmp_path / "state.json")
    run = control.submit(_spec(tmp_path))

    _advance(control, run.run_id, 5)

    final = control.load(run.run_id)
    assert final.observed_status is PlanStatus.SUCCEEDED
    assert len(executor.launches) == 2
    assert final.attempts[-1].execution_references


def test_real_training_step_resolves_yield_runtime_before_existing_implementation(tmp_path):
    executor = CompletedExecutor()
    runtime = TrainingRuntime(executor, hardware_facts=_hardware())
    resolver = RecordingTrainingResolver(runtime)
    control = TrainingControlPlane(
        runtime,
        tmp_path / "state.json",
        capability_resolver=resolver,
    )
    run = control.submit(_spec(tmp_path), idempotency_key="capability-seam")
    plan = control._control._store.load_plan(run.plan_id)

    assert plan.step("training-execution").capability == YIELD_TRAINING_RUNTIME_CAPABILITY
    _advance(control, run.run_id, 5)
    assert control.load(run.run_id).observed_status is PlanStatus.SUCCEEDED
    assert resolver.requirements
    assert all(requirement == YIELD_TRAINING_RUNTIME_REQUIREMENT for requirement in resolver.requirements)


def test_restart_restores_product_spec_and_environment_before_first_attempt(tmp_path):
    state_path = tmp_path / "state.json"
    initial = TrainingControlPlane(
        TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware()),
        state_path,
    )
    run = initial.submit(_spec(tmp_path), idempotency_key="restart-before-attempt")

    restarted_executor = CompletedExecutor()
    restarted = TrainingControlPlane(
        TrainingRuntime(restarted_executor, hardware_facts=_hardware()),
        state_path,
    )
    observed = restarted.reconcile_once(run.run_id)

    assert observed.attempts[-1].step_id == "training-preflight"
    assert observed.attempts[-1].status is AttemptStatus.SUCCEEDED
    assert restarted_executor.launches == []


def test_restart_rejects_spec_metadata_that_changes_immutable_plan_intent(tmp_path):
    state_path = tmp_path / "state.json"
    initial = TrainingControlPlane(
        TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware()),
        state_path,
    )
    run = initial.submit(_spec(tmp_path), idempotency_key="tampered-restart")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    stored_run = state["runs"][run.run_id]
    stored_spec = json.loads(stored_run["metadata"][TRAINING_SPEC_METADATA])
    stored_spec["model"]["extra"]["parameter_count"] = 2_000_000
    stored_run["metadata"][TRAINING_SPEC_METADATA] = json.dumps(stored_spec)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    restarted = TrainingControlPlane(
        TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware()),
        state_path,
    )

    with pytest.raises(TrainingStateRecoveryError, match="immutable plan intent"):
        restarted.reconcile_once(run.run_id)
    assert restarted.load(run.run_id).attempts == ()


def test_restart_rejects_environment_lock_with_invalid_content_digest(tmp_path):
    state_path = tmp_path / "state.json"
    initial = TrainingControlPlane(
        TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware()),
        state_path,
    )
    run = initial.submit(_spec(tmp_path), idempotency_key="tampered-environment")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    stored_run = state["runs"][run.run_id]
    stored_lock = json.loads(stored_run["metadata"][ENVIRONMENT_LOCK_METADATA])
    stored_lock["python_version"] = "0.0.0"
    stored_run["metadata"][ENVIRONMENT_LOCK_METADATA] = json.dumps(stored_lock)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    restarted = TrainingControlPlane(
        TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware()),
        state_path,
    )

    with pytest.raises(TrainingStateRecoveryError, match="invalid EnvironmentLock"):
        restarted.reconcile_once(run.run_id)
    assert restarted.load(run.run_id).attempts == ()


def test_restart_quarantines_unobservable_execution_without_retry(tmp_path):
    state_path = tmp_path / "state.json"
    initial_executor = CompletedExecutor()
    initial = TrainingControlPlane(
        TrainingRuntime(initial_executor, hardware_facts=_hardware()),
        state_path,
    )
    run = initial.submit(_spec(tmp_path), idempotency_key="restart-active")
    running = _advance(initial, run.run_id, 3)
    assert running.attempts[-1].status is AttemptStatus.RUNNING

    restarted_executor = CompletedExecutor()
    restarted = TrainingControlPlane(
        TrainingRuntime(restarted_executor, hardware_facts=_hardware()),
        state_path,
    )
    quarantined = restarted.reconcile_once(run.run_id)

    assert quarantined.desired_state is DesiredState.CANCELLED
    assert quarantined.observed_status is PlanStatus.CANCELLING
    assert quarantined.attempts[-1].status is AttemptStatus.CANCELLING
    assert quarantined.attempts[-1].cleanup_confirmed is False
    assert "EXECUTION_RECOVERY_UNAVAILABLE" in quarantined.attempts[-1].error
    assert len(quarantined.attempts) == len(running.attempts)
    assert restarted_executor.launches == []


def test_poll_quarantines_mismatched_session_without_rebinding_attempt(tmp_path):
    runtime = TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware())
    control = TrainingControlPlane(
        runtime,
        tmp_path / "state.json",
        capability_resolver=MismatchedSessionResolver(runtime, "poll"),
    )
    run = control.submit(_spec(tmp_path), idempotency_key="mismatched-poll")
    running = _advance(control, run.run_id, 3)
    expected_reference = running.attempts[-1].execution_references

    quarantined = control.reconcile_once(run.run_id)

    assert quarantined.observed_status is PlanStatus.CANCELLING
    assert quarantined.attempts[-1].status is AttemptStatus.CANCELLING
    assert quarantined.attempts[-1].execution_references == expected_reference
    assert "mismatched session" in quarantined.attempts[-1].error


def test_cancel_refuses_cleanup_confirmation_from_mismatched_session(tmp_path):
    runtime = TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware())
    control = TrainingControlPlane(
        runtime,
        tmp_path / "state.json",
        capability_resolver=MismatchedSessionResolver(runtime, "cancel"),
    )
    run = control.submit(_spec(tmp_path), idempotency_key="mismatched-cancel")
    running = _advance(control, run.run_id, 3)
    expected_reference = running.attempts[-1].execution_references
    control.request_cancel(run.run_id)

    cancelling = control.reconcile_once(run.run_id)

    assert cancelling.observed_status is PlanStatus.CANCELLING
    assert cancelling.attempts[-1].status is AttemptStatus.CANCELLING
    assert cancelling.attempts[-1].cleanup_confirmed is False
    assert cancelling.attempts[-1].execution_references == expected_reference
    assert "mismatched session" in cancelling.attempts[-1].error


def test_cancel_after_restart_never_fabricates_cleanup_confirmation(tmp_path):
    state_path = tmp_path / "state.json"
    initial = TrainingControlPlane(
        TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware()),
        state_path,
    )
    run = initial.submit(_spec(tmp_path), idempotency_key="restart-cancel")
    _advance(initial, run.run_id, 3)

    restarted = TrainingControlPlane(
        TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware()),
        state_path,
    )
    restarted.request_cancel(run.run_id)
    cancelling = restarted.reconcile_once(run.run_id)
    stable_generation = cancelling.generation
    repeated = restarted.reconcile_once(run.run_id)

    assert cancelling.observed_status is PlanStatus.CANCELLING
    assert cancelling.attempts[-1].status is AttemptStatus.CANCELLING
    assert cancelling.attempts[-1].cleanup_confirmed is False
    assert repeated.generation == stable_generation
    assert repeated.terminal is False


def test_result_artifacts_are_durable_and_readable_after_restart(tmp_path):
    state_path = tmp_path / "state.json"
    control = TrainingControlPlane(
        TrainingRuntime(ArtifactProducingExecutor(), hardware_facts=_hardware()),
        state_path,
    )
    run = control.submit(_spec(tmp_path), idempotency_key="durable-artifacts")
    final = _advance(control, run.run_id, 5)
    artifacts = control.output_artifacts(run.run_id)

    assert final.observed_status is PlanStatus.SUCCEEDED
    assert artifacts["model"].uri.startswith("artifact://sha256/")

    restarted = TrainingControlPlane(
        TrainingRuntime(CompletedExecutor(), hardware_facts=_hardware()),
        state_path,
    )
    restored = restarted.output_artifacts(run.run_id)
    assert restored == artifacts
