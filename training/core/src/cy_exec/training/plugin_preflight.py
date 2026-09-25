# ╔══════════════════════════════════════════════════════════════════════╗
# ║ 📄 File: training/core/src/cy_exec/training/plugin_preflight.py     ║
# ║ 文件:training/core/src/cy_exec/training/plugin_preflight.py     ║
# ║ Module: Cyrene Yield                                                ║
# ║ 模块:Cyrene Yield                                                ║
# ║ Role: Direct adapters for Plugins-owned preflight capabilities.     ║
# ║ 职责:面向 Plugins 所有 preflight 能力的直连适配器。
# ║                                                                    ║
# ║ 模块：Cyrene Yield                                                  ║
# ║ 职责：连接由 Plugins 实现的前置分析能力，不承载能力实现。                 ║
# ╚══════════════════════════════════════════════════════════════════════╝
"""Typed Product adapters for Plugins-owned preflight capabilities.

针对 Plugins 所有的 preflight 能力的有类型 Product 适配器。
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from cyrene_preflight import PreflightIssue, PreflightSeverity

from .preflight_contracts import (
    CompatibilityAnalysis,
    CompatibilityRequest,
    ModelAnalysisRequest,
    ModelFacts,
    VramEstimate,
)

MODEL_ANALYZER_CAPABILITY = "model.analyzer.v1"
COMPATIBILITY_EVALUATOR_CAPABILITY = "compatibility.evaluator.v1"
PREFLIGHT_INTERFACE_VERSION = "1"


class PreflightCapabilityFailure(RuntimeError):
    """A required Plugins-owned preflight capability could not be used.

    无法使用所需的 Plugins 所有 preflight 能力。
    """

    def __init__(self, capability: str, message: str) -> None:
        super().__init__(message)
        self.capability = capability


class DirectPluginModelAnalyzer:
    """Map Yield model intent to ``model.analyzer.v1`` typed JSON.

    将 Yield 模型意图映射为 model.analyzer.v1 的有类型 JSON。
    """

    def __init__(
        self,
        connection_ref: str,
        *,
        client: Any | None = None,
        deadline_seconds: float = 5.0,
    ) -> None:
        self._client = client or _client_for(connection_ref, MODEL_ANALYZER_CAPABILITY)
        self._deadline_seconds = deadline_seconds

    def analyze(self, request: ModelAnalysisRequest) -> ModelFacts:
        response = _invoke_json(
            self._client,
            capability=MODEL_ANALYZER_CAPABILITY,
            method="analyze",
            request={
                "model_info": {
                    "id": request.model_id,
                    "parameter_count": request.parameter_count,
                    "weight_precision": request.precision,
                    "context_length": request.context_length,
                    "activation_memory_bytes": request.activation_memory_bytes,
                    "accelerator_memory_bytes": request.accelerator_memory_bytes,
                },
                "workload_intent": {"kind": request.execution_kind},
            },
            deadline_seconds=self._deadline_seconds,
        )
        estimate_payload = response.get("vram_estimate")
        estimate = None
        if estimate_payload is not None:
            estimate_data = _mapping(estimate_payload, "vram_estimate", MODEL_ANALYZER_CAPABILITY)
            estimate = VramEstimate(
                lower_bytes=_integer(estimate_data.get("lower_bytes"), "vram_estimate.lower_bytes"),
                upper_bytes=_integer(estimate_data.get("upper_bytes"), "vram_estimate.upper_bytes"),
                confidence=_text(estimate_data.get("confidence", "estimated"), "vram_estimate.confidence"),
                uncertainty=_optional_text(estimate_data.get("uncertainty"), "vram_estimate.uncertainty"),
            )
        parameter_count = _optional_integer(response.get("parameter_count"), "parameter_count")
        recommendation = _optional_integer(
            response.get("tensor_parallelism_recommendation"),
            "tensor_parallelism_recommendation",
        )
        return ModelFacts(
            model_id=_text(response.get("model_id"), "model_id"),
            model_family=_optional_text(response.get("model_family"), "model_family"),
            parameter_count=parameter_count,
            precision=_text(response.get("weight_precision"), "weight_precision"),
            vram_estimate=estimate,
            tensor_parallelism_recommendation=recommendation,
            evidence=_text_tuple(response.get("evidence", ()), "evidence"),
        )


class DirectPluginCompatibilityEvaluator:
    """Map Product preflight facts to ``compatibility.evaluator.v1``.

    将 Product preflight 事实映射为 compatibility.evaluator.v1。
    """

    def __init__(
        self,
        connection_ref: str,
        *,
        client: Any | None = None,
        deadline_seconds: float = 5.0,
    ) -> None:
        self._client = client or _client_for(connection_ref, COMPATIBILITY_EVALUATOR_CAPABILITY)
        self._deadline_seconds = deadline_seconds

    def evaluate(self, request: CompatibilityRequest) -> CompatibilityAnalysis:
        response = _invoke_json(
            self._client,
            capability=COMPATIBILITY_EVALUATOR_CAPABILITY,
            method="evaluate",
            request={
                "hardware_facts": None if request.hardware is None else request.hardware.to_dict(),
                "model_spec": request.model.to_dict(),
                "workload": {
                    "execution_kind": request.execution_kind,
                    "environment": {
                        "identity": request.environment.identity,
                        "accelerator_runtime": request.environment.accelerator_runtime,
                        "minimum_driver": request.environment.minimum_driver,
                        "framework_versions": dict(request.environment.framework_versions),
                    },
                },
            },
            deadline_seconds=self._deadline_seconds,
        )
        issues_payload = response.get("issues", ())
        if not isinstance(issues_payload, list):
            raise _protocol_failure(COMPATIBILITY_EVALUATOR_CAPABILITY, "issues must be an array")
        issues = []
        for index, value in enumerate(issues_payload):
            item = _mapping(value, f"issues[{index}]", COMPATIBILITY_EVALUATOR_CAPABILITY)
            try:
                severity = PreflightSeverity(_text(item.get("severity"), f"issues[{index}].severity"))
            except ValueError as exc:
                raise _protocol_failure(
                    COMPATIBILITY_EVALUATOR_CAPABILITY,
                    f"issues[{index}].severity is unsupported",
                ) from exc
            evidence = item.get("evidence")
            issues.append(
                PreflightIssue(
                    code=_text(item.get("code"), f"issues[{index}].code"),
                    severity=severity,
                    message=_text(item.get("message"), f"issues[{index}].message"),
                    source=_text(item.get("source"), f"issues[{index}].source"),
                    evidence=None if evidence in (None, []) else _text_tuple(evidence, f"issues[{index}].evidence"),
                    remediation=_optional_text(item.get("remediation"), f"issues[{index}].remediation"),
                )
            )
        evidence = _mapping(response.get("evidence", {}), "evidence", COMPATIBILITY_EVALUATOR_CAPABILITY)
        return CompatibilityAnalysis(tuple(issues), dict(evidence))


def _client_for(connection_ref: str, capability: str) -> Any:
    if not isinstance(connection_ref, str) or not connection_ref.strip():
        raise PreflightCapabilityFailure(capability, "connection_ref is not configured")
    try:
        from cyrene_plugin_runtime import DirectPluginClient

        return DirectPluginClient.for_local_connection_ref(connection_ref.strip())
    except ImportError as exc:
        raise PreflightCapabilityFailure(capability, "Plugins direct runtime SDK is not installed") from exc
    except (TypeError, ValueError) as exc:
        raise PreflightCapabilityFailure(capability, f"connection_ref is invalid: {exc}") from exc


def _invoke_json(
    client: Any,
    *,
    capability: str,
    method: str,
    request: Mapping[str, Any],
    deadline_seconds: float,
) -> Mapping[str, Any]:
    request_type = f"type.cyrene.io/{capability}.{method}.request"
    response_type = f"type.cyrene.io/{capability}.{method}.response"
    try:
        from cyrene_plugin_runtime import DirectPayload, DirectPluginError

        response = client.invoke(
            capability=capability,
            interface_version=PREFLIGHT_INTERFACE_VERSION,
            method=method,
            request=DirectPayload(
                type_url=request_type,
                value=json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            ),
            deadline_seconds=deadline_seconds,
        )
    except ImportError as exc:
        raise PreflightCapabilityFailure(capability, "Plugins direct runtime SDK is not installed") from exc
    except DirectPluginError as exc:
        raise PreflightCapabilityFailure(capability, f"direct invocation failed: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise PreflightCapabilityFailure(capability, f"direct invocation is invalid: {exc}") from exc
    if response.type_url != response_type:
        raise _protocol_failure(capability, f"expected {response_type}, received {response.type_url or '<empty>'}")
    try:
        decoded = json.loads(response.value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _protocol_failure(capability, "response is not valid UTF-8 JSON") from exc
    return _mapping(decoded, "response", capability)


def _mapping(value: Any, field: str, capability: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _protocol_failure(capability, f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _protocol_failure("preflight", f"{field} must be non-empty text")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _protocol_failure("preflight", f"{field} must be an integer")
    return value


def _optional_integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _text_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise _protocol_failure("preflight", f"{field} must be an array of text")
    return tuple(value)


def _protocol_failure(capability: str, message: str) -> PreflightCapabilityFailure:
    return PreflightCapabilityFailure(capability, f"invalid typed response: {message}")


__all__ = [
    "COMPATIBILITY_EVALUATOR_CAPABILITY",
    "DirectPluginCompatibilityEvaluator",
    "DirectPluginModelAnalyzer",
    "MODEL_ANALYZER_CAPABILITY",
    "PREFLIGHT_INTERFACE_VERSION",
    "PreflightCapabilityFailure",
]
