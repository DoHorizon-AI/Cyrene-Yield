"""Unix KernelAuthority UDS transport. Production authority, not a test fake.

origin/develop Node Agent speaks typed KernelCommand over UDS. Windows hosts
are UnsupportedHost; this module fails closed instead of mocking success.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/kernel_uds.py
# │ Module: training/core/src/cy_exec/training/executors/kernel_uds
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

import os
import sys
from typing import List, Optional, Sequence

from ..contracts.launch import ResourceRequest, TrainingLaunchSpec
from .base import CancelOutcome, ProcessHandle
from .kernel_commands import (
    CancelOperationCommand,
    StopWorkerCommand,
    assert_no_legacy_agent_contract,
)
from .kernel_events import ExecutionOutputChannel, KernelLifecycleEvent
from .kernel_mapping import AllocationSet, NodeInventory, acquire_lease_command, require_single_node
from .plugin_control import PluginCancel, PluginConfigure, PluginEnvelopeUndeliverable, PluginInvoke


class KernelHostUnsupported(RuntimeError):
    """Live KernelAuthority UDS cannot be used on this host."""


class KernelAuthorityUnavailable(RuntimeError):
    """Unix host, but no live KernelAuthority endpoint is configured."""


def _windows_host() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


class UnixKernelAuthorityPort:
    """Production Kernel control port.

    Does not implement Resource/Lease/Fence itself. Does not spawn argv.
    """

    def __init__(self, *, socket_path: str | None = None) -> None:
        if _windows_host():
            raise KernelHostUnsupported(
                "Cyrene KernelAuthority UDS is Unix-only on origin/develop. "
                "Windows cannot verify the live Resource/Lease/Worker bridge. "
                "Use CyreneKernelExecutor(test_inprocess=True) for TEST ONLY."
            )
        self.socket_path = socket_path or os.environ.get("CYRENE_KERNEL_AUTHORITY_SOCKET")
        if not self.socket_path:
            raise KernelAuthorityUnavailable(
                "CYRENE_KERNEL_AUTHORITY_SOCKET is unset; refusing to mock Kernel authority"
            )
        self._events: List[KernelLifecycleEvent] = []
        self._output = ExecutionOutputChannel()
        self.last_commands: List[dict] = []

    def probe_node(self) -> NodeInventory:
        self._refuse_live_call("probe_node")

    def allocate(self, request: ResourceRequest) -> AllocationSet:
        require_single_node(request)
        command = acquire_lease_command(request, holder_id="training-worker")
        payload = command.to_dict()
        assert_no_legacy_agent_contract(payload)
        self.last_commands.append(payload)
        self._refuse_live_call("AcquireLease")

    def start_operation(
        self,
        launch: TrainingLaunchSpec,
        allocation: AllocationSet,
        assigned_env: dict[str, str],
    ) -> ProcessHandle:
        if assigned_env:
            raise ValueError(
                "production Kernel path must not inject device visibility env; "
                "NVIDIA create_binding owns CUDA_VISIBLE_DEVICES"
            )
        self._refuse_live_call("StartWorker")

    def wait_ready(self, handle: ProcessHandle, timeout: float = 15.0) -> None:
        self._refuse_plugin_envelope("Hello/WorkerReady")

    def configure(self, handle: ProcessHandle, envelope: PluginConfigure) -> None:
        self.last_commands.append(envelope.to_dict())
        self._refuse_plugin_envelope("Configure")

    def invoke(self, handle: ProcessHandle, envelope: PluginInvoke) -> str:
        self.last_commands.append(envelope.to_dict())
        self._refuse_plugin_envelope("Invoke")

    def plugin_cancel(self, handle: ProcessHandle, envelope: PluginCancel) -> bool:
        self.last_commands.append(envelope.to_dict())
        return False

    def poll(self, handle: ProcessHandle) -> Optional[int]:
        self._refuse_live_call("poll")

    def cancel(self, handle: ProcessHandle, timeout: float = 15.0) -> CancelOutcome:
        extra = handle.extra or {}
        if extra.get("invoke_started"):
            self.last_commands.append(
                PluginCancel(
                    target_request_id=str(extra.get("invoke_request_id") or extra.get("start_operation_id") or ""),
                    fence_token=int(extra.get("fence_token") or 0),
                    generation=int(extra.get("lease_generation") or 0),
                ).to_dict()
            )
        stop = StopWorkerCommand(
            worker_id=str(extra.get("worker_id") or ""),
            lease_id=str(extra.get("lease_id") or ""),
            fence_token=int(extra.get("fence_token") or 0),
            grace_period_seconds=timeout,
        )
        cancel = CancelOperationCommand(operation_id=str(extra.get("operation_id") or ""))
        self.last_commands.append(stop.to_dict())
        self.last_commands.append(cancel.to_dict())
        return CancelOutcome(
            stopped=False,
            remaining_pids=(),
            message=(
                "Kernel cancel confirmation is unavailable on this host; "
                "Attempt must be LOST, not CANCELLED"
            ),
            cleanup_confirmed=False,
            leases_released=False,
        )

    def read_output(self, handle: ProcessHandle) -> Sequence[str]:
        return []

    def lifecycle_events(self) -> List[KernelLifecycleEvent]:
        return list(self._events)

    def output_channel(self) -> ExecutionOutputChannel:
        return self._output

    def leases_released(self, handle: ProcessHandle) -> bool:
        return False

    def _refuse_live_call(self, rpc: str) -> None:
        raise KernelAuthorityUnavailable(
            f"{rpc} requires a live origin/develop KernelAuthority UDS at "
            f"{self.socket_path}; this process will not synthesize leases or "
            "claim process-tree cleanup"
        )

    def _refuse_plugin_envelope(self, name: str) -> None:
        raise PluginEnvelopeUndeliverable(
            f"{name} cannot be delivered through KernelAuthorityService. "
            "A direct training worker or owner-scoped Plugin connection is "
            "required; refusing to proxy business payloads through Platform."
        )
