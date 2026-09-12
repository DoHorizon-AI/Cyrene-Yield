# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/__init__.py
# │ Module: training/core/src/cy_exec/training/executors/__init__
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from .base import CancelOutcome, ProcessHandle, ProcessState, TrainingExecutor
from .cyrene_kernel import CyreneKernelExecutor
from .kernel_uds import KernelAuthorityUnavailable, KernelHostUnsupported
from .local_process import LocalProcessExecutor
from .plugin_control import PluginEnvelopeUndeliverable, WorkloadControlError

__all__ = [
    "CancelOutcome",
    "CyreneKernelExecutor",
    "KernelAuthorityUnavailable",
    "KernelHostUnsupported",
    "LocalProcessExecutor",
    "PluginEnvelopeUndeliverable",
    "ProcessHandle",
    "ProcessState",
    "TrainingExecutor",
    "WorkloadControlError",
]
