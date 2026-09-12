"""Yield-side projection of Kernel Resource / Lease / Worker / Operation.

AllocationSet is a Product-side view of one Kernel Lease. It must not become
a second Resource/Lease/Fence lifecycle. Canonical objects live on
Cyrene-Platform origin/develop (AuthorityRuntime, cy-kernel-contract).

Persist only Kernel identities:

- one lease_id + fence_token
- N resource_ids (GPU UUID)
- worker identity
- operation identity
- principal identity
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/kernel_mapping.py
# │ Module: training/core/src/cy_exec/training/executors/kernel_mapping
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..contracts.launch import ResourceRequest, TrainingLaunchSpec
from .kernel_commands import (
    AcquireLeaseCommand,
    DEFAULT_TRAINING_WORKER_EXECUTION_REF,
    KernelIdentity,
    ResourceQuery,
    StartWorkerCommand,
    assert_start_worker_has_no_launch_argv,
    plugin_configure_settings,
)


@dataclass
class NodeInventory:
    node_id: str
    gpu_count: int
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class AllocationSet:
    """Product-side projection of exactly one Kernel Lease holding N Resources."""

    node_id: str
    lease_id: str
    fence_token: int = 0
    resource_ids: List[str] = field(default_factory=list)
    lease_generation: int = 0
    principal_id: str = ""
    holder_id: str = ""
    released: bool = False
    cleanup_confirmed: bool = False

    @property
    def lease_ids(self) -> List[str]:
        return [self.lease_id] if self.lease_id else []

    @property
    def gpu_count(self) -> int:
        return len(self.resource_ids)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "lease_id": self.lease_id,
            "fence_token": self.fence_token,
            "resource_ids": list(self.resource_ids),
            "lease_generation": self.lease_generation,
            "principal_id": self.principal_id,
            "holder_id": self.holder_id,
            "released": self.released,
            "cleanup_confirmed": self.cleanup_confirmed,
        }


@dataclass
class KernelWorkerView:
    worker_id: str
    role: str = "launcher"
    pid: Optional[int] = None
    node_id: str = ""
    execution_ref: str = ""


@dataclass
class KernelOperationView:
    operation_id: str
    worker_id: str
    lease_id: str = ""
    kind: str = "worker.start"


def require_single_node(request: ResourceRequest) -> None:
    if request.nnodes > 1:
        raise ValueError(
            "Stage 3 CyreneKernelExecutor only supports 1 node × N GPU; "
            f"got nnodes={request.nnodes}"
        )


def acquire_lease_command(
    request: ResourceRequest,
    *,
    holder_id: str,
) -> AcquireLeaseCommand:
    require_single_node(request)
    return AcquireLeaseCommand(
        holder=KernelIdentity(id=holder_id),
        query=ResourceQuery(count=max(0, request.gpu_count)),
    )


def start_worker_command(
    *,
    worker_id: str,
    principal_id: str,
    allocation: AllocationSet,
    execution_ref: str,
) -> StartWorkerCommand:
    command = StartWorkerCommand(
        worker_id=worker_id,
        principal_id=principal_id,
        lease_id=allocation.lease_id,
        lease_generation=allocation.lease_generation,
        execution_ref=execution_ref or DEFAULT_TRAINING_WORKER_EXECUTION_REF,
    )
    assert_start_worker_has_no_launch_argv(command.to_dict())
    return command


def workload_configure_settings(launch: TrainingLaunchSpec) -> Dict[str, str]:
    """Per-attempt TrainingSpec reaches the worker outside Kernel StartWorker."""

    return plugin_configure_settings(
        spec_artifact_path=launch.spec_artifact_path,
        output_root=launch.work_dir,
    )
