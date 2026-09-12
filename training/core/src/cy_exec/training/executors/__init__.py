# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/__init__.py
# │ Module: training/core/src/cy_exec/training/executors/__init__
# │ Role: Public execution ports and the Platform-backed adapter.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

"""Yield execution ports and the single Platform-backed adapter."""

from .base import CancelOutcome, ExecutionControlError, ProcessHandle, ProcessState, TrainingExecutor
from .kernel_training import KernelTrainingConfiguration, KernelTrainingExecutor

__all__ = [
    "CancelOutcome",
    "ExecutionControlError",
    "KernelTrainingConfiguration",
    "KernelTrainingExecutor",
    "ProcessHandle",
    "ProcessState",
    "TrainingExecutor",
]
