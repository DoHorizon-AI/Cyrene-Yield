"""Training-specific orchestration over Platform resource facts and Product policy."""

from __future__ import annotations

import os
from typing import Optional

from cyrene_preflight import HardwareFacts, PreflightIssue, PreflightResult, PreflightSeverity, PreflightStatus

from .contracts import TrainingSpec
from .environment import EnvironmentLock
from .preflight_contracts import (
    CompatibilityEvaluator,
    CompatibilityRequest,
    EnvironmentCompatibility,
    ModelAnalysisRequest,
    ModelAnalyzer,
)
from .plugin_preflight import (
    COMPATIBILITY_EVALUATOR_CAPABILITY,
    MODEL_ANALYZER_CAPABILITY,
    DirectPluginCompatibilityEvaluator,
    DirectPluginModelAnalyzer,
    PreflightCapabilityFailure,
)

_SAFE_DRY_RUN_UNKNOWN_CODES = frozenset({"model.vram.unknown"})
_MODEL_ANALYZER_CONNECTION_ENV = "CYRENE_MODEL_ANALYZER_CONNECTION_REF"
_COMPATIBILITY_EVALUATOR_CONNECTION_ENV = "CYRENE_COMPATIBILITY_EVALUATOR_CONNECTION_REF"


class TrainingPreflight:
    """Combines training intent with resource facts and replaceable Product policy."""

    def __init__(
        self,
        model_analyzer: Optional[ModelAnalyzer] = None,
        compatibility_evaluator: Optional[CompatibilityEvaluator] = None,
    ) -> None:
        self._model_analyzer = model_analyzer
        self._compatibility_evaluator = compatibility_evaluator
        self._model_analyzer_ref = os.environ.get(_MODEL_ANALYZER_CONNECTION_ENV, "").strip()
        self._compatibility_evaluator_ref = os.environ.get(_COMPATIBILITY_EVALUATOR_CONNECTION_ENV, "").strip()

    def evaluate(
        self,
        spec: TrainingSpec,
        environment_lock: Optional[EnvironmentLock],
        hardware: Optional[HardwareFacts],
    ) -> PreflightResult:
        if environment_lock is None:
            extra_issues = (
                PreflightIssue(
                    code="environment.lock.missing",
                    severity=PreflightSeverity.UNKNOWN,
                    message="Training did not resolve an EnvironmentLock.",
                    source="training-preflight",
                    remediation="Resolve the training EnvironmentSpec before execution.",
                ),
            )
            environment = EnvironmentCompatibility(identity=None)
            identity = None
        else:
            environment = EnvironmentCompatibility(
                identity=environment_lock.environment_digest,
                accelerator_runtime=environment_lock.accelerator_runtime,
                minimum_driver=environment_lock.minimum_driver,
                framework_versions=environment_lock.framework_versions,
            )
            identity = environment_lock.environment_digest
            extra_issues = ()
        try:
            model = self._resolved_model_analyzer().analyze(
                ModelAnalysisRequest(
                    model_id=spec.model.name or spec.model.path,
                    parameter_count=_parameter_count(spec),
                    precision=_precision(spec),
                    execution_kind="train",
                    context_length=spec.hyperparams.max_seq_length,
                    accelerator_memory_bytes=(None if hardware is None else hardware.largest_accelerator_memory_bytes),
                )
            )
        except PreflightCapabilityFailure as exc:
            return _capability_failure_result(exc, identity, hardware, extra_issues)
        try:
            analysis = self._resolved_compatibility_evaluator().evaluate(
                CompatibilityRequest(
                    model=model,
                    environment=environment,
                    hardware=hardware,
                    execution_kind="train",
                )
            )
        except PreflightCapabilityFailure as exc:
            return _capability_failure_result(exc, identity, hardware, extra_issues)
        return analysis.to_result(
            environment_identity=identity,
            hardware=hardware,
            extra_issues=extra_issues,
        )

    def _resolved_model_analyzer(self) -> ModelAnalyzer:
        if self._model_analyzer is None:
            if not self._model_analyzer_ref:
                raise PreflightCapabilityFailure(
                    MODEL_ANALYZER_CAPABILITY,
                    f"set {_MODEL_ANALYZER_CONNECTION_ENV} to the resolved direct endpoint",
                )
            self._model_analyzer = DirectPluginModelAnalyzer(self._model_analyzer_ref)
        return self._model_analyzer

    def _resolved_compatibility_evaluator(self) -> CompatibilityEvaluator:
        if self._compatibility_evaluator is None:
            if not self._compatibility_evaluator_ref:
                raise PreflightCapabilityFailure(
                    COMPATIBILITY_EVALUATOR_CAPABILITY,
                    f"set {_COMPATIBILITY_EVALUATOR_CONNECTION_ENV} to the resolved direct endpoint",
                )
            self._compatibility_evaluator = DirectPluginCompatibilityEvaluator(self._compatibility_evaluator_ref)
        return self._compatibility_evaluator

    @staticmethod
    def can_safely_resolve_with_tiny_dry_run(result: PreflightResult) -> bool:
        if result.status is not PreflightStatus.UNKNOWN or result.hardware is None:
            return result.status in (PreflightStatus.READY, PreflightStatus.WARNING)
        unknown_codes = {issue.code for issue in result.issues if issue.severity is PreflightSeverity.UNKNOWN}
        return bool(unknown_codes) and unknown_codes.issubset(_SAFE_DRY_RUN_UNKNOWN_CODES)


def _parameter_count(spec: TrainingSpec) -> Optional[int]:
    value = spec.model.extra.get("parameter_count")
    try:
        parsed = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return parsed if parsed and parsed > 0 else None


def _precision(spec: TrainingSpec) -> str:
    if spec.quantization.use_4bit:
        return "int4"
    return str(spec.extra.get("precision") or spec.quantization.bnb_4bit_compute_dtype or "fp16").lower()


def _capability_failure_result(
    failure: PreflightCapabilityFailure,
    environment_identity: Optional[str],
    hardware: Optional[HardwareFacts],
    extra_issues: tuple[PreflightIssue, ...],
) -> PreflightResult:
    capability_code = failure.capability.removesuffix(".v1").replace(".", "_")
    issue = PreflightIssue(
        code=f"{capability_code}.binding.unavailable",
        severity=PreflightSeverity.BLOCKED,
        message=f"Required capability {failure.capability} is unavailable: {failure}",
        source=failure.capability,
        remediation="Resolve and activate the Plugins capability, then provide its connection_ref to Yield.",
    )
    issues = extra_issues + (issue,)
    return PreflightResult(
        status=PreflightStatus.BLOCKED,
        issues=issues,
        resolved_environment_identity=environment_identity,
        hardware=hardware,
        analysis_evidence={"required_capability": failure.capability},
    )


__all__ = ["TrainingPreflight"]
