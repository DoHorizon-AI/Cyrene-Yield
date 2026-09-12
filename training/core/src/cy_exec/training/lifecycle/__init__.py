# ╔══════════════════════════════════════════════════════════════════════╗
# ║ 📄 File: training/core/src/cy_exec/training/lifecycle/__init__.py
# ║ Module: Cyrene Yield
# ║ Role: Product-owned training lifecycle implementation.
# ║
# ║ 模块：Cyrene Yield
# ║ 职责：训练产品拥有的生命周期实现。
# ╚══════════════════════════════════════════════════════════════════════╝
"""Yield-owned run, attempt, persistence, and reconciliation state."""

from .contracts import (
    CONTRACT_VERSION,
    Attempt,
    AttemptId,
    AttemptNumber,
    AttemptStatus,
    DesiredState,
    ExecutionPlan,
    Generation,
    IdempotencyKey,
    PlanStatus,
    PlanStep,
    ProductRun,
    RetryPolicy,
    StepDependency,
    StepStatus,
)
from .reconciler import ProductControlPlane, ProductReconciler, ReconcileAction, ReconcileActionKind
from .store import ControlPlaneStore, IdempotencyConflictError, JsonFileControlPlaneStore, StaleGenerationError

__all__ = [
    "CONTRACT_VERSION",
    "Attempt",
    "AttemptId",
    "AttemptNumber",
    "AttemptStatus",
    "ControlPlaneStore",
    "DesiredState",
    "ExecutionPlan",
    "Generation",
    "IdempotencyConflictError",
    "IdempotencyKey",
    "JsonFileControlPlaneStore",
    "PlanStatus",
    "PlanStep",
    "ProductControlPlane",
    "ProductReconciler",
    "ProductRun",
    "ReconcileAction",
    "ReconcileActionKind",
    "RetryPolicy",
    "StaleGenerationError",
    "StepDependency",
    "StepStatus",
]
