# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_training_preflight_and_tiny_dry_run.py
# │ 中文：文件：training/core/tests/test_training_preflight_and_tiny_dry_run.py
# │ Module: training/core/tests/test_training_preflight_and_tiny_dry_run
# │ 模块：training/core/tests/test_training_preflight_and_tiny_dry_run
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │ 职责：Yield 核心测试模块，验证统一训练 runtime 与契约。
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest

from cyrene_preflight import AcceleratorFacts, HardwareFacts, PreflightStatus
from cy_exec.training import TinyDryRun, TinyDryRunGateError, TinyDryRunStatus, TrainingPreflight, TrainingRuntime
from cy_exec.training.executors.base import CancelOutcome, ProcessHandle
from training_tck_helpers import make_spec

GiB = 1024**3


def node_hardware(*, memory_bytes: int = 24 * GiB) -> HardwareFacts:
    return HardwareFacts.from_node_resource_inventory(
        node_id="node-test",
        inventory_generation=3,
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
    def __init__(self) -> None:
        self.launches = []

    def start(self, launch):
        self.launches.append(launch)
        output = Path(launch.work_dir)
        checkpoint = output / "checkpoint-1"
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "model.safetensors").write_bytes(b"tiny-checkpoint")
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
        return ProcessHandle(pid=101, argv=list(launch.argv), work_dir=launch.work_dir)

    def poll(self, _handle):
        return 0

    def read_new_output(self, _handle):
        return ['{"loss":0.1,"peak_memory_bytes":1234}']

    def cancel(self, _handle, timeout=15.0):
        return CancelOutcome(stopped=True, cleanup_confirmed=True)


class FailingExecutor(CompletedExecutor):
    def poll(self, _handle):
        return 1


class UncleanCancelExecutor(CompletedExecutor):
    def poll(self, _handle):
        return None

    def cancel(self, _handle, timeout=15.0):
        return CancelOutcome(stopped=False, remaining_pids=(101,), message="child still alive")


def configured_spec(tmp_path, *, parameters: int = 1_000_000):
    spec = make_spec(tmp_path, "llamafactory")
    spec.model.extra["parameter_count"] = parameters
    return spec


def test_training_preflight_fails_closed_without_plugin_bindings(tmp_path, monkeypatch):
    monkeypatch.delenv("CYRENE_MODEL_ANALYZER_CONNECTION_REF", raising=False)
    monkeypatch.delenv("CYRENE_COMPATIBILITY_EVALUATOR_CONNECTION_REF", raising=False)
    spec = configured_spec(tmp_path)

    result = TrainingPreflight().evaluate(spec, None, node_hardware())

    assert result.status is PreflightStatus.BLOCKED
    assert result.issues[-1].source == "model.analyzer.v1"
    assert result.issues[-1].code == "model_analyzer.binding.unavailable"


def test_training_preflight_is_ready_for_supported_node_and_keeps_environment_identity(tmp_path):
    runtime = TrainingRuntime(CompletedExecutor(), hardware_facts=node_hardware())
    spec = configured_spec(tmp_path)
    lock = runtime.resolve_environment_lock(spec)

    result = TinyDryRun(runtime)._preflight.evaluate(spec, lock, node_hardware())

    assert result.status is PreflightStatus.READY
    assert result.resolved_environment_identity == lock.environment_digest
    assert result.hardware_reference.endswith("/3")


def test_blocked_preflight_skips_real_executor(tmp_path):
    executor = CompletedExecutor()
    runtime = TrainingRuntime(executor, hardware_facts=node_hardware(memory_bytes=1))
    dry_run = TinyDryRun(runtime).run(configured_spec(tmp_path, parameters=7_000_000_000))

    assert dry_run.status is TinyDryRunStatus.BLOCKED
    assert executor.launches == []


def test_tiny_dry_run_uses_real_adapter_launch_and_artifact_path(tmp_path):
    executor = CompletedExecutor()
    runtime = TrainingRuntime(executor, hardware_facts=node_hardware())
    result = TinyDryRun(runtime).run(configured_spec(tmp_path), samples=128, steps=1)

    assert result.status is TinyDryRunStatus.SUCCEEDED
    assert len(executor.launches) == 1
    launch = executor.launches[0]
    compiled = json.loads(Path(launch.spec_artifact_path).read_text(encoding="utf-8"))
    assert compiled["max_steps"] == 1
    assert compiled["max_samples"] == 128
    assert result.environment_lock_digest == launch.environment_lock.environment_digest
    assert result.checkpoint_write_result is True
    assert result.checkpoint_resume_result is True
    assert result.peak_memory_bytes == 1234
    assert result.diagnostic_artifact is not None
    assert "tiny-dry-run-metrics" in result.output_artifacts


def test_tiny_dry_run_failure_gates_full_training(tmp_path):
    executor = FailingExecutor()
    runtime = TrainingRuntime(executor, hardware_facts=node_hardware())
    gate = TinyDryRun(runtime)
    spec = configured_spec(tmp_path)
    failed = gate.run(spec)

    assert failed.status is TinyDryRunStatus.FAILED
    with pytest.raises(TinyDryRunGateError):
        gate.submit_full(spec, failed)
    assert len(executor.launches) == 1


def test_tiny_dry_run_cancel_keeps_nonterminal_state_until_cleanup_is_confirmed(tmp_path):
    runtime = TrainingRuntime(UncleanCancelExecutor(), hardware_facts=node_hardware())
    result = TinyDryRun(runtime).run(configured_spec(tmp_path), timeout=0)

    session = TinyDryRun(runtime).cancel(result.session_id)
    assert session.status.value == "awaiting_retry"
