"""Kernel control port used by CyreneKernelExecutor.

Production implementation talks to origin/develop KernelAuthorityService.
InProcessKernelPort is TEST ONLY and must not be treated as authority.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/kernel_port.py
# │ Module: training/core/src/cy_exec/training/executors/kernel_port
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from typing import List, Optional, Protocol, Sequence

from ..contracts.launch import ResourceRequest, TrainingLaunchSpec
from .base import CancelOutcome, ProcessHandle
from .kernel_events import ExecutionOutputChannel, KernelLifecycleEvent
from .kernel_mapping import AllocationSet, NodeInventory
from .plugin_control import PluginCancel, PluginConfigure, PluginInvoke


class KernelControlPort(Protocol):
    def probe_node(self) -> NodeInventory:
        ...

    def allocate(self, request: ResourceRequest) -> AllocationSet:
        ...

    def start_operation(
        self,
        launch: TrainingLaunchSpec,
        allocation: AllocationSet,
        assigned_env: dict[str, str],
    ) -> ProcessHandle:
        ...

    def wait_ready(self, handle: ProcessHandle, timeout: float = 15.0) -> None:
        ...

    def configure(self, handle: ProcessHandle, envelope: PluginConfigure) -> None:
        ...

    def invoke(self, handle: ProcessHandle, envelope: PluginInvoke) -> str:
        ...

    def plugin_cancel(self, handle: ProcessHandle, envelope: PluginCancel) -> bool:
        ...

    def poll(self, handle: ProcessHandle) -> Optional[int]:
        ...

    def cancel(self, handle: ProcessHandle, timeout: float = 15.0) -> CancelOutcome:
        ...

    def read_output(self, handle: ProcessHandle) -> Sequence[str]:
        ...

    def lifecycle_events(self) -> List[KernelLifecycleEvent]:
        ...

    def output_channel(self) -> ExecutionOutputChannel:
        ...

    def leases_released(self, handle: ProcessHandle) -> bool:
        ...
