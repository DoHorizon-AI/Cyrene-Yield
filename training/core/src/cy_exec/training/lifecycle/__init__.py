# ╔══════════════════════════════════════════════════════════════════════╗
# ║ 📄 File: training/core/src/cy_exec/training/lifecycle/__init__.py
# ║ 文件:training/core/src/cy_exec/training/lifecycle/__init__.py
# ║ Module: Cyrene Yield
# ║ 模块:Cyrene Yield
# ║ Role: Product-owned training lifecycle implementation.
# ║ 职责:Product 所有的训练生命周期实现。
# ║
# ║ 模块：Cyrene Yield
# ║ 职责：训练产品拥有的生命周期实现。
# ╚══════════════════════════════════════════════════════════════════════╝
"""Yield-owned run, attempt, persistence, and reconciliation state.

Yield 所有的 run、attempt、持久化与 reconciliation 状态。
"""

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
