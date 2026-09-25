"""TrainingRun contains many TrainingAttempts.

A Kernel Worker/Operation Lost maps to Attempt LOST first. The controller
decides whether to retry. It must not be rewritten as TrainingRun success.

One Attempt may have many Kernel Operations (start, configure/invoke, stop).
start_operation_id is the StartWorker operation, not a long-term singleton.

一个 TrainingRun 包含多个 TrainingAttempt。

Kernel Worker/Operation 丢失时,首先映射为 Attempt LOST。是否重试由 controller 决定,不得将其改写成 TrainingRun 成功。

一个 Attempt 可对应多个 Kernel Operation(start、configure/invoke、stop)。start_operation_id 是 StartWorker 操作的 ID,不是长期单例。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/attempt.py
# │ 中文:文件:training/core/src/cy_exec/training/contracts/attempt.py
# │ Module: training/core/src/cy_exec/training/contracts/attempt
# │ 模块:training/core/src/cy_exec/training/contracts/attempt
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责:规范 Yield 训练 runtime,拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .events import TrainingEvent, TrainingResult
from .launch import TrainingLaunchSpec
from .spec import TrainingSpec
from .status import TrainingStatus
from .workload import WorkloadConfigRef


@dataclass
class KernelOperationRef:
    operation_id: str
    kind: str
    state: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "state": self.state,
        }


@dataclass
class KernelBinding:
    """Product-side handles for one TrainingAttempt.

    These are Kernel identities, not a second lease/fence machine.

    一个 TrainingAttempt 的 Product 侧句柄。

    这些是 Kernel 身份,不是第二套 lease/fence 状态机。
    """

    node_id: str = ""
    principal_id: str = ""
    lease_id: str = ""
    fence_token: int = 0
    resource_ids: List[str] = field(default_factory=list)
    worker_id: str = ""
    start_operation_id: str = ""
    operations: List[KernelOperationRef] = field(default_factory=list)
    execution_ref: str = ""
    workload_config_ref: Optional[WorkloadConfigRef] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def operation_id(self) -> str:
        """Compatibility alias for StartWorker operation. Not a Product invariant.

        StartWorker operation 的兼容别名,不是 Product 不变量。
        """
        return self.start_operation_id

    @property
    def lease_ids(self) -> List[str]:
        return [self.lease_id] if self.lease_id else []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "principal_id": self.principal_id,
            "lease_id": self.lease_id,
            "fence_token": self.fence_token,
            "resource_ids": list(self.resource_ids),
            "worker_id": self.worker_id,
            "start_operation_id": self.start_operation_id,
            "operations": [item.to_dict() for item in self.operations],
            "execution_ref": self.execution_ref,
            "workload_config_ref": None
            if self.workload_config_ref is None
            else self.workload_config_ref.to_dict(),
            "extra": dict(self.extra),
        }


@dataclass
class TrainingAttempt:
    attempt_id: str
    run_id: str
    ordinal: int
    spec: TrainingSpec
    status: TrainingStatus = TrainingStatus.QUEUED
    launch: Optional[TrainingLaunchSpec] = None
    binding: KernelBinding = field(default_factory=KernelBinding)
    result: Optional[TrainingResult] = None
    events: List[TrainingEvent] = field(default_factory=list)
    error: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "ordinal": self.ordinal,
            "status": self.status.value,
            "binding": self.binding.to_dict(),
            "environment_lock_digest": (
                None
                if self.launch is None or self.launch.environment_lock is None
                else self.launch.environment_lock.environment_digest
            ),
            "error": self.error,
        }


@dataclass
class TrainingRun:
    run_id: str
    spec: TrainingSpec
    status: TrainingStatus = TrainingStatus.QUEUED
    attempts: List[TrainingAttempt] = field(default_factory=list)
    error: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def current_attempt(self) -> Optional[TrainingAttempt]:
        return self.attempts[-1] if self.attempts else None

    def derive_status(self) -> TrainingStatus:
        attempt = self.current_attempt
        if attempt is None:
            return TrainingStatus.QUEUED
        if attempt.status == TrainingStatus.LOST:
            return TrainingStatus.AWAITING_RETRY
        return attempt.status
