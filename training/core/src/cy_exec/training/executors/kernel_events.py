"""Split Kernel lifecycle events from training telemetry.

Kernel Event / RuntimeJournal may only receive Worker/Operation/Lease
lifecycle facts. Loss/step/epoch go to ExecutionOutput (product-adjacent
files such as /output/metrics.jsonl). Do not revive StreamJournal.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/kernel_events.py
# │ Module: training/core/src/cy_exec/training/executors/kernel_events
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List


class KernelLifecycleKind(str, Enum):
    WORKER_STARTED = "WorkerStarted"
    WORKER_LOST = "WorkerLost"
    OPERATION_COMPLETED = "OperationCompleted"
    OPERATION_FAILED = "OperationFailed"
    LEASE_EXPIRED = "LeaseExpired"
    LEASE_RELEASED = "LeaseReleased"
    CANCELLED = "Cancelled"
    CANCEL_UNCONFIRMED = "CancelUnconfirmed"


KERNEL_EVENT_KINDS = {item.value for item in KernelLifecycleKind}

TRAINING_TELEMETRY_KEYS = frozenset(
    {"loss", "step", "epoch", "checkpoint", "throughput", "learning_rate", "metrics"}
)


@dataclass
class KernelLifecycleEvent:
    kind: KernelLifecycleKind
    operation_id: str = ""
    worker_id: str = ""
    message: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "operation_id": self.operation_id,
            "worker_id": self.worker_id,
            "message": self.message,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }


class ExecutionOutputChannel:
    """Training telemetry / stdout. Must not be written to Kernel Event Store."""

    def __init__(self) -> None:
        self.lines: List[str] = []

    def append(self, line: str) -> None:
        if line is not None:
            self.lines.append(line)

    def extend(self, lines: List[str]) -> None:
        self.lines.extend(lines)


def assert_not_kernel_event(payload: Dict[str, Any]) -> None:
    overlap = TRAINING_TELEMETRY_KEYS.intersection(payload)
    if overlap:
        raise ValueError(
            f"Training telemetry keys {sorted(overlap)} must not enter Kernel Event Store"
        )
