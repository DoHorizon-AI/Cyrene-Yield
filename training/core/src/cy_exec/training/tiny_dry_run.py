"""Product-level bounded execution gate using the normal training runtime path.

使用正常训练 runtime 路径执行 Product 级有界执行门禁。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/tiny_dry_run.py
# │ 中文:文件:training/core/src/cy_exec/training/tiny_dry_run.py
# │ Module: training/core/src/cy_exec/training/tiny_dry_run
# │ 模块:training/core/src/cy_exec/training/tiny_dry_run
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责:规范 Yield 训练 runtime,拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from cy_artifacts import ArtifactKind, ArtifactRef
from cyrene_yield_contracts import YieldArtifactKind
from cyrene_preflight import HardwareFacts, PreflightIssue, PreflightResult, PreflightSeverity, PreflightStatus

from .checkpoint import CheckpointManager
from .contracts import TrainingSpec, TrainingStatus
from .preflight import TrainingPreflight
from .runtime import TrainingRuntime, TrainingSession


class TinyDryRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class TinyDryRunGateError(RuntimeError):
    """Raised when a full product training run has not passed the dry-run gate.

    当完整 Product 训练 run 尚未通过 dry-run 门禁时抛出。
    """


@dataclass
class TinyDryRunResult:
    status: TinyDryRunStatus
    environment_lock_digest: Optional[str]
    input_artifacts: Tuple[ArtifactRef, ...] = ()
    observed_device_facts: Optional[HardwareFacts] = None
    peak_memory_bytes: Optional[int] = None
    checkpoint_write_result: Optional[bool] = None
    checkpoint_resume_result: Optional[bool] = None
    issues: Tuple[PreflightIssue, ...] = ()
    diagnostic_artifact: Optional[ArtifactRef] = None
    output_artifacts: Dict[str, ArtifactRef] = field(default_factory=dict)
    timestamps: Dict[str, str] = field(default_factory=dict)
    session_id: Optional[str] = None
    bounded_samples: int = 0
    bounded_steps: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status.value,
            "environment_lock_digest": self.environment_lock_digest,
            "input_artifacts": [item.to_dict() for item in self.input_artifacts],
            "observed_device_facts": None if self.observed_device_facts is None else self.observed_device_facts.to_dict(),
            "peak_memory_bytes": self.peak_memory_bytes,
            "checkpoint_write_result": self.checkpoint_write_result,
            "checkpoint_resume_result": self.checkpoint_resume_result,
            "issues": [item.to_dict() for item in self.issues],
            "diagnostic_artifact": None if self.diagnostic_artifact is None else self.diagnostic_artifact.to_dict(),
            "output_artifacts": {name: item.to_dict() for name, item in self.output_artifacts.items()},
            "timestamps": dict(self.timestamps),
            "session_id": self.session_id,
            "bounded_samples": self.bounded_samples,
            "bounded_steps": self.bounded_steps,
        }


# ════════════════════════════════════════════════════════════════════════
# 🔧 CLASS: TinyDryRun
# 🔧 类:TinyDryRun
#
#   Executes the minimal training gate that validates the selected engine and
#   执行最小训练门禁,验证所选引擎和
#   workload path before full training is admitted.
#   工作负载路径,然后才允许完整训练。
#
#   执行最小训练门禁，在准入完整训练前验证选定引擎与工作负载路径。
#
# ════════════════════════════════════════════════════════════════════════
class TinyDryRun:
    """Runs a bounded product attempt through the same adapter and executor as a full run.

    通过与完整 run 相同的适配器和 executor 执行有界 attempt。
    """

    def __init__(self, runtime: TrainingRuntime, preflight: Optional[TrainingPreflight] = None) -> None:
        self._runtime = runtime
        self._preflight = preflight or TrainingPreflight()

    @staticmethod
    def bounded_spec(spec: TrainingSpec) -> TrainingSpec:
        """Use the same bounded trainer settings in a durable Product attempt.

        在持久化 Product attempt 中使用相同的有界 trainer 配置。
        """
        return _bounded_spec(spec, samples=128, steps=1)

    def run(
            self,
            spec: TrainingSpec,
            *,
            samples: int = 128,
            steps: int = 1,
            timeout: Optional[float] = None,
    ) -> TinyDryRunResult:
        if not 50 <= samples <= 500:
            raise ValueError("tiny dry run samples must be between 50 and 500")
        if not 1 <= steps <= 3:
            raise ValueError("tiny dry run steps must be between 1 and 3")
        started = _timestamp()
        lock, resolution_issue = self._resolve_lock(spec)
        preflight = self._preflight.evaluate(spec, lock, self._runtime.hardware_facts)
        if resolution_issue is not None:
            preflight = _with_issue(preflight, resolution_issue)
        if preflight.status is PreflightStatus.BLOCKED:
            return self._gate_result(
                TinyDryRunStatus.BLOCKED,
                preflight,
                started,
                samples,
                steps,
                _input_artifacts(spec),
            )
        if preflight.status is PreflightStatus.UNKNOWN and not self._preflight.can_safely_resolve_with_tiny_dry_run(
                preflight):
            return self._gate_result(
                TinyDryRunStatus.UNKNOWN,
                preflight,
                started,
                samples,
                steps,
                _input_artifacts(spec),
            )

        bounded_spec = _bounded_spec(spec, samples=samples, steps=steps)
        session = self._runtime.submit(bounded_spec)
        if session.status in (TrainingStatus.QUEUED, TrainingStatus.RUNNING, TrainingStatus.CANCELLING):
            session = self._runtime.wait(session.session_id, timeout=timeout)
        return self._result_from_session(session, preflight, started, samples, steps)

    def cancel(self, session_id: str, timeout: float = 15.0) -> TrainingSession:
        """Reuse runtime cancellation; terminal cancellation still needs tree cleanup.

        复用 runtime 取消流程;进入终态前仍需清理进程树。
        """

        return self._runtime.cancel(session_id, timeout=timeout)

    def submit_full(self, spec: TrainingSpec, dry_run: TinyDryRunResult) -> TrainingSession:
        if dry_run.status is not TinyDryRunStatus.SUCCEEDED:
            raise TinyDryRunGateError(
                f"full TrainingRun is gated by tiny dry run status {dry_run.status.value}"
            )
        return self._runtime.submit(spec)

    def _resolve_lock(self, spec: TrainingSpec):
        try:
            return self._runtime.resolve_environment_lock(spec), None
        except ValueError as exc:
            return None, PreflightIssue(
                code="environment.resolution.blocked",
                severity=PreflightSeverity.BLOCKED,
                message=str(exc),
                source="environment-resolver",
                remediation="Resolve a compatible EnvironmentLock before execution.",
            )

    def _gate_result(
            self,
            status: TinyDryRunStatus,
            preflight: PreflightResult,
            started: str,
            samples: int,
            steps: int,
            input_artifacts: Tuple[ArtifactRef, ...],
    ) -> TinyDryRunResult:
        return TinyDryRunResult(
            status=status,
            environment_lock_digest=preflight.resolved_environment_identity,
            input_artifacts=input_artifacts,
            observed_device_facts=preflight.hardware,
            issues=preflight.issues,
            timestamps={"started_at": started, "finished_at": _timestamp()},
            bounded_samples=samples,
            bounded_steps=steps,
        )

    def _result_from_session(
            self,
            session: TrainingSession,
            preflight: PreflightResult,
            started: str,
            samples: int,
            steps: int,
    ) -> TinyDryRunResult:
        result = session.result
        artifacts = dict(result.artifacts) if result is not None else {}
        checkpoint_write, checkpoint_resume = _checkpoint_outcomes(session.spec.output_dir)
        status = _status_from_training(session.status)
        peak = _peak_memory(session.events)
        diagnostic, metrics = self._publish_diagnostics(session, preflight, status, started, peak)
        if diagnostic is not None:
            artifacts["tiny-dry-run-diagnostic"] = diagnostic
        if metrics is not None:
            artifacts["tiny-dry-run-metrics"] = metrics
        lock_digest = None
        if session.launch and session.launch.environment_lock:
            lock_digest = session.launch.environment_lock.environment_digest
        return TinyDryRunResult(
            status=status,
            environment_lock_digest=lock_digest or preflight.resolved_environment_identity,
            input_artifacts=_input_artifacts(session.spec),
            observed_device_facts=preflight.hardware,
            peak_memory_bytes=peak,
            checkpoint_write_result=checkpoint_write,
            checkpoint_resume_result=checkpoint_resume,
            issues=preflight.issues,
            diagnostic_artifact=diagnostic,
            output_artifacts=artifacts,
            timestamps={"started_at": started, "finished_at": _timestamp()},
            session_id=session.session_id,
            bounded_samples=samples,
            bounded_steps=steps,
        )

    def _publish_diagnostics(
            self,
            session: TrainingSession,
            preflight: PreflightResult,
            status: TinyDryRunStatus,
            started: str,
            peak: Optional[int],
    ) -> tuple[Optional[ArtifactRef], Optional[ArtifactRef]]:
        output_dir = Path(session.spec.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": "tiny-dry-run",
            "status": status.value,
            "preflight": preflight.to_dict(),
            "events": [event.to_dict() for event in session.events],
            "peak_memory_bytes": peak,
            "started_at": started,
            "finished_at": _timestamp(),
        }
        diagnostic_path = output_dir / "tiny-dry-run-diagnostic.json"
        diagnostic_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        metrics_path = output_dir / "metrics.json"
        metrics_path.write_text(
            json.dumps({"events": payload["events"], "peak_memory_bytes": peak}, sort_keys=True),
            encoding="utf-8",
        )
        provider = self._runtime.artifact_provider_for(session.spec)
        diagnostic = provider.publish(str(diagnostic_path), kind=ArtifactKind(YieldArtifactKind.REPORT),
                                      producer="cyrene-yield.tiny-dry-run")
        metrics = provider.publish(str(metrics_path), kind=ArtifactKind(YieldArtifactKind.METRICS), producer="cyrene-yield.tiny-dry-run")
        return diagnostic, metrics


def _bounded_spec(spec: TrainingSpec, *, samples: int, steps: int) -> TrainingSpec:
    bounded = copy.deepcopy(spec)
    bounded.job_id = f"{spec.job_id or 'training'}:tiny"
    bounded.output_dir = str(Path(spec.output_dir) / "tiny-dry-run")
    bounded.checkpoint.output_dir = bounded.output_dir
    bounded.checkpoint.save_steps = 1
    bounded.checkpoint.save_total_limit = 1
    bounded.checkpoint.resume_from = None
    bounded.hyperparams.num_train_epochs = min(bounded.hyperparams.num_train_epochs, 1.0)
    bounded.hyperparams.logging_steps = 1
    bounded.extra = dict(bounded.extra)
    bounded.extra.update({"max_steps": steps, "max_train_samples": samples, "tiny_dry_run": True})
    llama_args = dict(bounded.extra.get("llamafactory_args") or {})
    llama_args.update({"max_steps": steps, "max_samples": samples})
    bounded.extra["llamafactory_args"] = llama_args
    return bounded


def _with_issue(result: PreflightResult, issue: PreflightIssue) -> PreflightResult:
    issues = tuple(result.issues) + (issue,)
    return PreflightResult(
        status=PreflightStatus.BLOCKED,
        issues=issues,
        resolved_environment_identity=result.resolved_environment_identity,
        hardware=result.hardware,
        analysis_evidence=result.analysis_evidence,
    )


def _checkpoint_outcomes(output_dir: str) -> tuple[bool, Optional[bool]]:
    manager = CheckpointManager(output_dir)
    checkpoint = manager.find_latest_training_dir()
    if checkpoint is None:
        return False, None
    written = manager.validate_weights_or_metadata(checkpoint)
    if not written:
        return False, None
    return True, manager.load_checkpoint(checkpoint) is not None


def _input_artifacts(spec: TrainingSpec) -> Tuple[ArtifactRef, ...]:
    references = []
    for item in spec.extra.get("input_artifacts") or ():
        if isinstance(item, ArtifactRef):
            references.append(item)
        elif isinstance(item, dict):
            references.append(ArtifactRef.from_dict(item))
    return tuple(references)


def _peak_memory(events: Sequence) -> Optional[int]:
    values = [event.payload.get("peak_memory_bytes") for event in events if event.payload]
    parsed = []
    for value in values:
        try:
            parsed.append(int(value))
        except (TypeError, ValueError):
            pass
    return max(parsed) if parsed else None


def _status_from_training(status: TrainingStatus) -> TinyDryRunStatus:
    if status is TrainingStatus.COMPLETED:
        return TinyDryRunStatus.SUCCEEDED
    if status is TrainingStatus.CANCELLED:
        return TinyDryRunStatus.CANCELLED
    return TinyDryRunStatus.FAILED


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["TinyDryRun", "TinyDryRunGateError", "TinyDryRunResult", "TinyDryRunStatus"]
