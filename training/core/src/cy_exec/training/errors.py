"""
┌─────────────────────────────────────────────────────────────────────┐
│  📄 errors.py                                                       │
│  Module: cy_exec.training.errors                                    │
│  Role: Canonical error catalog and mappings for Cyrene Yield.       │
│                                                                     │
│  模块职责：Yield 训练执行引擎规范错误命名空间与恢复动作映射。               │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import Any

# ════════════════════════════════════════════════════════════════════════
# Canonical Cyrene Yield Error Catalog & Mappings
# 规范 Cyrene Yield 错误目录与映射。
# ════════════════════════════════════════════════════════════════════════
YIELD_ERROR_MAPPINGS: dict[str, dict[str, str]] = {
    "YIELD_RESOURCE_NOT_FOUND": {
        "code": "PRODUCT.YIELD.RESOURCE_NOT_FOUND",
        "cause_kind": "not_found",
        "recovery_action": "user_action_required",
    },
    "YIELD_DEPENDENCY_UNAVAILABLE": {
        "code": "PRODUCT.YIELD.DEPENDENCY_UNAVAILABLE",
        "cause_kind": "infrastructure",
        "recovery_action": "query_state_first",
    },
    "YIELD_HANDOFF_REJECTED": {
        "code": "PRODUCT.YIELD.HANDOFF_REJECTED",
        "cause_kind": "network",
        "recovery_action": "safely_retry",
    },
    "YIELD_ARTIFACT_UNAVAILABLE": {
        "code": "PRODUCT.YIELD.ARTIFACT_UNAVAILABLE",
        "cause_kind": "storage",
        "recovery_action": "query_state_first",
    },
    "YIELD_REQUEST_INVALID": {
        "code": "PRODUCT.YIELD.REQUEST_INVALID",
        "cause_kind": "validation",
        "recovery_action": "fix_configuration",
    },
    "YIELD_CONFLICT": {
        "code": "PRODUCT.YIELD.CONFLICT",
        "cause_kind": "conflict",
        "recovery_action": "safely_retry",
    },
    "YIELD_PREFLIGHT_BLOCKED": {
        "code": "PRODUCT.YIELD.PREFLIGHT_BLOCKED",
        "cause_kind": "environment",
        "recovery_action": "fix_configuration",
    },
    "YIELD_TRAINING_FAILED": {
        "code": "PRODUCT.YIELD.TRAINING_FAILED",
        "cause_kind": "execution",
        "recovery_action": "query_state_first",
    },
    "YIELD_YAML_INVALID": {
        "code": "PRODUCT.YIELD.YAML_INVALID",
        "cause_kind": "validation",
        "recovery_action": "fix_configuration",
    },
}


def map_yield_error(raw_code: str) -> dict[str, str]:
    """Map a raw or legacy Yield error code to canonical PRODUCT.YIELD.<REASON>.

    将原始或旧版 Yield 错误码映射为规范 PRODUCT.YIELD.<REASON>。
    """
    if raw_code in YIELD_ERROR_MAPPINGS:
        return YIELD_ERROR_MAPPINGS[raw_code]
    normalized = raw_code.upper().replace(" ", "_")
    if not normalized.startswith("PRODUCT.YIELD."):
        clean_name = normalized.removeprefix("YIELD_")
        canonical = f"PRODUCT.YIELD.{clean_name}"
    else:
        canonical = normalized
    return {
        "code": canonical,
        "cause_kind": "unknown",
        "recovery_action": "query_state_first",
    }
