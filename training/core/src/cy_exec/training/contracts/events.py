"""Training events and results reported to the product runtime.

上报给 Product runtime 的训练事件与结果。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/events.py
# │ 中文:文件:training/core/src/cy_exec/training/contracts/events.py
# │ Module: training/core/src/cy_exec/training/contracts/events
# │ 模块:training/core/src/cy_exec/training/contracts/events
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责:规范 Yield 训练 runtime,拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from cy_artifacts import ArtifactRef
from .errors import TrainingError
from .status import TrainingStatus


class TrainingEventKind(str, Enum):
    LOG = "log"
    PROGRESS = "progress"
    CHECKPOINT = "checkpoint"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TrainingEvent:
    kind: TrainingEventKind
    message: str = ""
    step: Optional[int] = None
    total_steps: Optional[int] = None
    epoch: Optional[float] = None
    loss: Optional[float] = None
    learning_rate: Optional[float] = None
    raw: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            self.kind = TrainingEventKind(self.kind)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "step": self.step,
            "total_steps": self.total_steps,
            "epoch": self.epoch,
            "loss": self.loss,
            "learning_rate": self.learning_rate,
            "raw": self.raw,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }


@dataclass
class TrainingResult:
    status: TrainingStatus
    output_dir: str = ""
    checkpoint_path: Optional[str] = None
    checkpoint_digest: str = ""
    checkpoint_size_bytes: int = 0
    exit_code: Optional[int] = None
    error: Optional[TrainingError] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, ArtifactRef] = field(default_factory=dict)
    message: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = TrainingStatus(self.status)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "output_dir": self.output_dir,
            "checkpoint_path": self.checkpoint_path,
            "checkpoint_digest": self.checkpoint_digest,
            "checkpoint_size_bytes": self.checkpoint_size_bytes,
            "exit_code": self.exit_code,
            "error": None if self.error is None else self.error.to_dict(),
            "metrics": dict(self.metrics),
            "artifacts": {key: value.to_dict() for key, value in self.artifacts.items()},
            "message": self.message,
        }
