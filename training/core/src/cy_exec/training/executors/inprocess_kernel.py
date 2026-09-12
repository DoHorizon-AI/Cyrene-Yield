"""TEST ONLY in-process Kernel port.

This is not production authority. It exists so Windows TCK can exercise
TrainingRun/Attempt mapping without a Unix Kernel daemon. It must not be
the default CyreneKernelExecutor port.

It still follows the develop shape: one Lease containing N GPU Resource
identities. It does not generate CUDA_VISIBLE_DEVICES.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/inprocess_kernel.py
# │ Module: training/core/src/cy_exec/training/executors/inprocess_kernel
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..contracts.launch import ResourceRequest, TrainingLaunchSpec
from .base import CancelOutcome, ProcessHandle
from .kernel_commands import (
    CancelOperationCommand,
    DEFAULT_TRAINING_WORKER_EXECUTION_REF,
    StopWorkerCommand,
    assert_no_legacy_agent_contract,
    assert_start_worker_has_no_launch_argv,
)
from .kernel_events import (
    ExecutionOutputChannel,
    KernelLifecycleEvent,
    KernelLifecycleKind,
    assert_not_kernel_event,
)
from .kernel_mapping import (
    AllocationSet,
    NodeInventory,
    acquire_lease_command,
    require_single_node,
    start_worker_command,
)
from .local_process import LocalProcessExecutor
from .plugin_control import PluginCancel, PluginConfigure, PluginInvoke, WorkloadControlError

# Explicit marker so production code reviews can grep TEST ONLY.
INPROCESS_KERNEL_PORT_TEST_ONLY = True


class InProcessKernelPort:
    """TEST ONLY. Local process tree + one-lease-N-resources projection."""

    def __init__(self, *, node_id: str = "local-node", gpu_count: int = 8) -> None:
        self._inventory = NodeInventory(
            node_id=node_id,
            gpu_count=gpu_count,
            labels={"gpu_count": str(gpu_count), "test_only": "true"},
        )
        self._free_gpus = list(range(gpu_count))
        self._leases: Dict[str, AllocationSet] = {}
        self._process = LocalProcessExecutor()
        self._events: List[KernelLifecycleEvent] = []
        self._output = ExecutionOutputChannel()
        self._ops: Dict[int, Dict[str, object]] = {}
        self.last_commands: List[dict] = []
        self.principal_id = "principal/test"

    def probe_node(self) -> NodeInventory:
        return self._inventory

    def allocate(self, request: ResourceRequest) -> AllocationSet:
        require_single_node(request)
        needed = max(0, request.gpu_count)
        if len(self._free_gpus) < needed:
            raise RuntimeError(f"Not enough GPUs: requested {needed}, free {len(self._free_gpus)}")
        command = acquire_lease_command(request, holder_id="worker/pending")
        payload = command.to_dict()
        assert_no_legacy_agent_contract(payload)
        self.last_commands.append(payload)

        indices = [self._free_gpus.pop(0) for _ in range(needed)]
        resource_ids = [f"GPU-UUID-{index}" for index in indices]
        lease_id = f"lease/{uuid.uuid4()}"
        allocation = AllocationSet(
            node_id=self._inventory.node_id,
            lease_id=lease_id,
            fence_token=1,
            resource_ids=resource_ids,
            lease_generation=1,
            principal_id=self.principal_id,
            holder_id="worker/pending",
        )
        self._leases[lease_id] = allocation
        return allocation

    def start_operation(
        self,
        launch: TrainingLaunchSpec,
        allocation: AllocationSet,
        assigned_env: dict[str, str],
    ) -> ProcessHandle:
        if assigned_env:
            raise ValueError(
                "TEST ONLY InProcess port must not inject CUDA_VISIBLE_DEVICES; "
                "production NVIDIA create_binding owns device visibility"
            )
        worker_id = f"worker/{uuid.uuid4()}"
        execution_ref = str(launch.extra.get("execution_ref") or DEFAULT_TRAINING_WORKER_EXECUTION_REF)
        start = start_worker_command(
            worker_id=worker_id,
            principal_id=self.principal_id,
            allocation=allocation,
            execution_ref=execution_ref,
        )
        start_payload = start.to_dict()
        assert_start_worker_has_no_launch_argv(start_payload)
        self.last_commands.append(start_payload)

        allocation.holder_id = worker_id
        control_dir = str(Path(launch.work_dir) / ".worker-control" / uuid.uuid4().hex)
        Path(control_dir).mkdir(parents=True, exist_ok=True)
        wrapper = TrainingLaunchSpec(
            engine=launch.engine,
            argv=[
                sys.executable,
                "-m",
                "cy_exec.training.worker",
                "--control-dir",
                control_dir,
                "--output-root",
                launch.work_dir,
            ],
            work_dir=launch.work_dir,
            distributed=launch.distributed,
            checkpoint=launch.checkpoint,
            resources=launch.resources,
            output_layout=launch.output_layout,
            spec_artifact_path=launch.spec_artifact_path,
        )
        try:
            import cy_exec

            src_root = str(Path(cy_exec.__file__).resolve().parents[1])
        except Exception:
            src_root = ""
        pythonpath = os.pathsep.join(item for item in (src_root, os.environ.get("PYTHONPATH") or "") if item)
        try:
            handle = self._process.start(
                wrapper,
                assigned_env={
                    "CYRENE_GENERATION": str(allocation.lease_generation),
                    "CYRENE_FENCE_TOKEN": str(allocation.fence_token),
                    "CYRENE_WORKER_ID": worker_id,
                    "PYTHONPATH": pythonpath,
                },
            )
        except Exception:
            self._return_gpus(allocation, cleanup_confirmed=False)
            raise
        operation_id = f"operation/start/{worker_id}"
        handle.extra = {
            "test_only": True,
            "node_id": allocation.node_id,
            "principal_id": self.principal_id,
            "lease_id": allocation.lease_id,
            "fence_token": allocation.fence_token,
            "lease_generation": allocation.lease_generation,
            "resource_ids": list(allocation.resource_ids),
            "worker_id": worker_id,
            "start_operation_id": operation_id,
            "operation_id": operation_id,
            "operations": [{"operation_id": operation_id, "kind": "worker.start", "state": "RUNNING"}],
            "execution_ref": execution_ref,
            "control_dir": control_dir,
            "kernel_commands": list(self.last_commands[-1:]),
            "assigned_env": {},
            "invoke_started": False,
        }
        self._ops[handle.pid] = {
            "allocation": allocation,
            "worker_id": worker_id,
            "operation_id": operation_id,
        }
        self._emit(
            KernelLifecycleKind.WORKER_STARTED,
            operation_id=operation_id,
            worker_id=worker_id,
            message="TEST ONLY launcher worker started",
            payload={
                "pid": handle.pid,
                "lease_id": allocation.lease_id,
                "resource_ids": list(allocation.resource_ids),
            },
        )
        return handle

    def wait_ready(self, handle: ProcessHandle, timeout: float = 15.0) -> None:
        control = Path(str(handle.extra.get("control_dir") or ""))
        ready = control / "ready"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ready.is_file() or any("WORKER_READY" in line for line in self._process.read_new_output(handle)):
                return
            if self._process.poll(handle) is not None:
                raise WorkloadControlError("worker exited before ready", lost=True)
            time.sleep(0.05)
        raise WorkloadControlError("worker ready timeout", lost=True)

    def configure(self, handle: ProcessHandle, envelope: PluginConfigure) -> None:
        payload = envelope.to_dict()
        self.last_commands.append(payload)
        control = Path(str(handle.extra["control_dir"]))
        (control / "configure.json").write_text(json.dumps(payload), encoding="utf-8")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (control / "configure.ack").is_file():
                op_id = f"operation/configure/{handle.extra.get('worker_id')}"
                _append_operation(handle, op_id, "worker.configure", "SUCCEEDED")
                handle.extra["plugin_configure"] = dict(envelope.settings)
                return
            if (control / "configure.err").is_file():
                message = (control / "configure.err").read_text(encoding="utf-8")
                raise WorkloadControlError(f"Configure failed: {message}")
            if self._process.poll(handle) is not None:
                raise WorkloadControlError("worker exited during Configure", lost=True)
            time.sleep(0.05)
        raise WorkloadControlError("Configure timed out", lost=True)

    def invoke(self, handle: ProcessHandle, envelope: PluginInvoke) -> str:
        payload = envelope.to_dict()
        self.last_commands.append(payload)
        control = Path(str(handle.extra["control_dir"]))
        (control / "invoke.json").write_text(json.dumps(payload), encoding="utf-8")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (control / "invoke.ack").is_file():
                request_id = (control / "invoke.ack").read_text(encoding="utf-8").strip()
                op_id = f"operation/invoke/{handle.extra.get('worker_id')}"
                _append_operation(handle, op_id, "worker.invoke", "RUNNING")
                handle.extra["invoke_started"] = True
                handle.extra["invoke_request_id"] = request_id
                return request_id
            if (control / "invoke.err").is_file():
                message = (control / "invoke.err").read_text(encoding="utf-8")
                raise WorkloadControlError(f"Invoke failed: {message}")
            if self._process.poll(handle) is not None:
                raise WorkloadControlError("worker exited during Invoke", lost=True)
            time.sleep(0.05)
        raise WorkloadControlError("Invoke timed out", lost=True)

    def plugin_cancel(self, handle: ProcessHandle, envelope: PluginCancel) -> bool:
        """Record generic plugin Cancel. Receipt is only returned if the worker acks.

        The TEST ONLY wrapper does not multiplex Cancel while the engine child
        is running; physical stop remains StopWorker / process-tree kill.
        """
        self.last_commands.append(envelope.to_dict())
        control = Path(str(handle.extra.get("control_dir") or ""))
        if control.is_dir():
            (control / "cancel.json").write_text(json.dumps(envelope.to_dict()), encoding="utf-8")
        ack = control / "cancel.ack"
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            if ack.is_file():
                return True
            time.sleep(0.05)
        return False

    def poll(self, handle: ProcessHandle) -> Optional[int]:
        meta = self._ops.get(handle.pid, {})
        if meta.get("terminal"):
            return self._process.poll(handle)
        code = self._process.poll(handle)
        if code is None:
            return None
        meta["terminal"] = True
        kind = KernelLifecycleKind.OPERATION_COMPLETED if code == 0 else KernelLifecycleKind.OPERATION_FAILED
        self._emit(
            kind,
            operation_id=str(meta.get("operation_id") or ""),
            worker_id=str(meta.get("worker_id") or ""),
            message=f"operation exited {code}",
            payload={"exit_code": code},
        )
        self._release(handle, cleanup_confirmed=True)
        return code

    def cancel(self, handle: ProcessHandle, timeout: float = 15.0) -> CancelOutcome:
        meta = self._ops.get(handle.pid, {})
        extra = handle.extra or {}
        self.last_commands.append(CancelOperationCommand(operation_id=str(extra.get("operation_id") or "")).to_dict())
        self.last_commands.append(
            StopWorkerCommand(
                worker_id=str(extra.get("worker_id") or ""),
                lease_id=str(extra.get("lease_id") or ""),
                fence_token=int(extra.get("fence_token") or 0),
                grace_period_seconds=timeout,
            ).to_dict()
        )
        outcome = self._process.cancel(handle, timeout=timeout)
        if outcome.stopped:
            meta["terminal"] = True
            self._emit(
                KernelLifecycleKind.CANCELLED,
                operation_id=str(meta.get("operation_id") or ""),
                worker_id=str(meta.get("worker_id") or ""),
                message="TEST ONLY launcher process tree stopped",
                payload={"remaining_pids": list(outcome.remaining_pids)},
            )
            self._release(handle, cleanup_confirmed=True)
            return CancelOutcome(
                stopped=True,
                remaining_pids=(),
                message=outcome.message,
                cleanup_confirmed=True,
                leases_released=True,
            )
        self._emit(
            KernelLifecycleKind.CANCEL_UNCONFIRMED,
            operation_id=str(meta.get("operation_id") or ""),
            worker_id=str(meta.get("worker_id") or ""),
            message=outcome.message,
            payload={"remaining_pids": list(outcome.remaining_pids)},
        )
        self._emit(
            KernelLifecycleKind.WORKER_LOST,
            operation_id=str(meta.get("operation_id") or ""),
            worker_id=str(meta.get("worker_id") or ""),
            message="unable to confirm worker cleanup",
            payload={"remaining_pids": list(outcome.remaining_pids)},
        )
        handle.extra["lost"] = True
        return CancelOutcome(
            stopped=False,
            remaining_pids=outcome.remaining_pids,
            message=outcome.message,
            cleanup_confirmed=False,
            leases_released=False,
        )

    def read_output(self, handle: ProcessHandle) -> Sequence[str]:
        lines = list(self._process.read_new_output(handle))
        self._output.extend(lines)
        return lines

    def lifecycle_events(self) -> List[KernelLifecycleEvent]:
        return list(self._events)

    def output_channel(self) -> ExecutionOutputChannel:
        return self._output

    def leases_released(self, handle: ProcessHandle) -> bool:
        lease_id = str(handle.extra.get("lease_id") or "")
        allocation = self._leases.get(lease_id)
        return bool(allocation and allocation.released)

    def mark_worker_lost(self, handle: ProcessHandle) -> None:
        handle.extra["lost"] = True
        meta = self._ops.get(handle.pid, {})
        self._emit(
            KernelLifecycleKind.WORKER_LOST,
            operation_id=str(meta.get("operation_id") or ""),
            worker_id=str(meta.get("worker_id") or ""),
            message="worker lost",
        )

    def _return_gpus(self, allocation: AllocationSet, *, cleanup_confirmed: bool) -> None:
        if allocation.released:
            return
        allocation.released = True
        allocation.cleanup_confirmed = cleanup_confirmed
        for resource_id in allocation.resource_ids:
            index = _index_from_test_uuid(resource_id)
            if index is not None and index not in self._free_gpus:
                self._free_gpus.append(index)
        self._free_gpus.sort()

    def _release(self, handle: ProcessHandle, *, cleanup_confirmed: bool) -> None:
        meta = self._ops.get(handle.pid) or {}
        allocation = meta.get("allocation")
        if not isinstance(allocation, AllocationSet):
            return
        if not cleanup_confirmed or allocation.released:
            return
        allocation.released = True
        allocation.cleanup_confirmed = True
        for resource_id in allocation.resource_ids:
            index = _index_from_test_uuid(resource_id)
            if index is not None:
                self._free_gpus.append(index)
        self._free_gpus.sort()
        self._emit(
            KernelLifecycleKind.LEASE_RELEASED,
            operation_id=str(meta.get("operation_id") or ""),
            worker_id=str(meta.get("worker_id") or ""),
            message="lease released after cleanup",
            payload={
                "lease_id": allocation.lease_id,
                "resource_ids": list(allocation.resource_ids),
            },
        )

    def _emit(
        self,
        kind: KernelLifecycleKind,
        *,
        operation_id: str,
        worker_id: str,
        message: str,
        payload: Optional[dict] = None,
    ) -> None:
        body = payload or {}
        assert_not_kernel_event(body)
        self._events.append(
            KernelLifecycleEvent(
                kind=kind,
                operation_id=operation_id,
                worker_id=worker_id,
                message=message,
                payload=body,
            )
        )


def _index_from_test_uuid(resource_id: str) -> Optional[int]:
    prefix = "GPU-UUID-"
    if not resource_id.startswith(prefix):
        return None
    try:
        return int(resource_id[len(prefix) :])
    except ValueError:
        return None


def _append_operation(handle: ProcessHandle, operation_id: str, kind: str, state: str) -> None:
    ops = list(handle.extra.get("operations") or [])
    ops.append({"operation_id": operation_id, "kind": kind, "state": state})
    handle.extra["operations"] = ops
