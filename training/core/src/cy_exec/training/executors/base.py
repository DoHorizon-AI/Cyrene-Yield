"""Executor protocol. Concrete executors must not leak into TrainingLaunchSpec."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/base.py
# │ Module: training/core/src/cy_exec/training/executors/base
# │ Role: Product execution port shared by Platform-backed adapters.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from ..contracts import TrainingLaunchSpec


class ProcessState(StrEnum):
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
    stdout_path: str | None = None
    stderr_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class TrainingExecutor(Protocol):
    def start(self, launch: TrainingLaunchSpec) -> ProcessHandle: ...

    def poll(self, handle: ProcessHandle) -> int | None: ...

    def wait(self, handle: ProcessHandle, timeout: float | None = None) -> int | None: ...

    def cancel(self, handle: ProcessHandle, timeout: float = 15.0) -> CancelOutcome: ...

    def read_new_output(self, handle: ProcessHandle) -> Sequence[str]: ...


class ExecutionControlError(RuntimeError):
    """Platform execution could not start, observe, cancel, or confirm cleanup."""

    def __init__(self, message: str, *, lost: bool = False, cleanup_attempted: bool = False) -> None:
        super().__init__(message)
        self.lost = lost
        self.cleanup_attempted = cleanup_attempted
