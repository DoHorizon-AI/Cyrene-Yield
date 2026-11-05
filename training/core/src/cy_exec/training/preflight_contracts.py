# ╔══════════════════════════════════════════════════════════════════════╗
# ║ 📄 File: training/core/src/cy_exec/training/preflight_contracts.py
# ║ 文件:training/core/src/cy_exec/training/preflight_contracts.py
# ║ Module: Cyrene Yield
# ║ 模块:Cyrene Yield
# ║ Role: Product-owned model analysis and training compatibility ports.
# ║ 职责:Product 所有的模型分析与训练兼容性端口。
# ║
# ║ 模块：Cyrene Yield
# ║ 职责：由产品拥有的模型分析与训练兼容性端口。
# ╚══════════════════════════════════════════════════════════════════════╝
"""Product-owned preflight data and replaceable capability ports.

Product 所有的 preflight 数据与可替换能力端口。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, Sequence, Tuple

from cyrene_preflight import HardwareFacts, PreflightIssue, PreflightResult, status_from_issues


class ModelAnalyzer(Protocol):
    def analyze(self, request: "ModelAnalysisRequest") -> "ModelFacts": ...


class CompatibilityEvaluator(Protocol):
    def evaluate(self, request: "CompatibilityRequest") -> "CompatibilityAnalysis": ...


@dataclass(frozen=True)
class ModelAnalysisRequest:
    model_id: str
    precision: str
    execution_kind: str
    parameter_count: Optional[int] = None
    context_length: Optional[int] = None
    activation_memory_bytes: Optional[int] = None
    accelerator_memory_bytes: Optional[int] = None


@dataclass(frozen=True)
class VramEstimate:
    lower_bytes: int
    upper_bytes: int
    confidence: str = "estimated"
    uncertainty: Optional[str] = None

    def __post_init__(self) -> None:
        if self.lower_bytes < 0 or self.upper_bytes < self.lower_bytes:
            raise ValueError("VRAM estimates must be a non-negative range")

    def to_dict(self) -> dict[str, Any]:
        return {
            "lower_bytes": self.lower_bytes,
            "upper_bytes": self.upper_bytes,
            "confidence": self.confidence,
            "uncertainty": self.uncertainty,
        }


@dataclass(frozen=True)
class ModelFacts:
    model_id: str
    model_family: Optional[str]
    parameter_count: Optional[int]
    precision: str
    vram_estimate: Optional[VramEstimate]
    tensor_parallelism_recommendation: Optional[int] = None
    evidence: Tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_family": self.model_family,
            "parameter_count": self.parameter_count,
            "precision": self.precision,
            "vram_estimate": None if self.vram_estimate is None else self.vram_estimate.to_dict(),
            "tensor_parallelism_recommendation": self.tensor_parallelism_recommendation,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class EnvironmentCompatibility:
    identity: Optional[str]
    accelerator_runtime: Optional[str] = None
    minimum_driver: Optional[str] = None
    framework_versions: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CompatibilityRequest:
    model: ModelFacts
    environment: EnvironmentCompatibility
    hardware: Optional[HardwareFacts]
    execution_kind: str


@dataclass(frozen=True)
class CompatibilityAnalysis:
    issues: Tuple[PreflightIssue, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_result(
        self,
        *,
        environment_identity: Optional[str],
        hardware: Optional[HardwareFacts],
        extra_issues: Sequence[PreflightIssue] = (),
    ) -> PreflightResult:
        issues = tuple(extra_issues) + tuple(self.issues)
        return PreflightResult(
            status=status_from_issues(issues),
            issues=issues,
            resolved_environment_identity=environment_identity,
            hardware=hardware,
            analysis_evidence=self.evidence,
        )


__all__ = [
    "CompatibilityAnalysis",
    "CompatibilityEvaluator",
    "CompatibilityRequest",
    "EnvironmentCompatibility",
    "ModelAnalysisRequest",
    "ModelAnalyzer",
    "ModelFacts",
    "VramEstimate",
]
