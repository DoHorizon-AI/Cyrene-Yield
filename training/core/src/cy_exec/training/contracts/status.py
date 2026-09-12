"""Product-level training lifecycle states.

Engine adapters must not treat these as their own job-state authority.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/status.py
# │ Module: training/core/src/cy_exec/training/contracts/status
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

from enum import Enum


class TrainingStatus(str, Enum):
    """Canonical product job states owned by TrainingRuntime.

    Attempt-level status may include LOST. A Lost attempt must not be
    rewritten as a successful TrainingRun. Controller decides retry.
    """

    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST = "lost"
    AWAITING_RETRY = "awaiting_retry"


class EngineKind(str, Enum):
    """Plugins-owned training backends exposed to Yield."""

    LLAMA_FACTORY = "llamafactory"


class DistributedStrategy(str, Enum):
    """Training strategy chosen by an Engine, not by the Executor."""

    SINGLE = "single"
    DDP = "ddp"
    FSDP = "fsdp"
    DEEPSPEED = "deepspeed"
    TORCHRUN = "torchrun"


class LaunchKind(str, Enum):
    """How the compiled command should be started.

    This is still a training-engine decision (direct python vs torchrun
    wrapper). The Executor only starts the resulting argv/process tree.
    """

    DIRECT = "direct"
    TORCHRUN = "torchrun"
