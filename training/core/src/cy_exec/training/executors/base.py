"""Executor protocol. Concrete executors must not leak into TrainingLaunchSpec."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/base.py
# │ Module: training/core/src/cy_exec/training/executors/base
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Protocol, Sequence

from ..contracts import TrainingLaunchSpec


class ProcessState(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    EXITED = "exited"
    STOPPING = "stopping"
    STOPPED = "stopped"
    LOST = "lost"


@dataclass
class CancelOutcome:
    stopped: bool
    remaining_pids: Sequence[int] = field(default_factory=list)
    message: str = ""
    cleanup_confirmed: bool = False
    leases_released: bool = False

    @property
    def lost(self) -> bool:
        return not self.stopped


@dataclass
class ProcessHandle:
    """Runtime handle for a launched process tree. Not part of the product contract."""

    pid: int
    argv: Sequence[str]
    work_dir: str
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class TrainingExecutor(Protocol):
    def start(self, launch: TrainingLaunchSpec) -> ProcessHandle:
        ...

    def poll(self, handle: ProcessHandle) -> Optional[int]:
        ...

    def wait(self, handle: ProcessHandle, timeout: Optional[float] = None) -> Optional[int]:
        ...

    def cancel(self, handle: ProcessHandle, timeout: float = 15.0) -> CancelOutcome:
        ...

    def read_new_output(self, handle: ProcessHandle) -> Sequence[str]:
        ...
