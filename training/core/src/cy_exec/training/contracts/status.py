"""Product-level training lifecycle states.

Engine adapters must not treat these as their own job-state authority.

Product 级训练生命周期状态。

引擎适配器不得将这些状态当成自己的作业状态权威。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/status.py
# │ 中文：文件：training/core/src/cy_exec/training/contracts/status.py
# │ Module: training/core/src/cy_exec/training/contracts/status
# │ 模块：training/core/src/cy_exec/training/contracts/status
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责：规范 Yield 训练 runtime，拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

from enum import Enum


class TrainingStatus(str, Enum):
    """Canonical product job states owned by TrainingRuntime.

    Attempt-level status may include LOST. A Lost attempt must not be
    rewritten as a successful TrainingRun. Controller decides retry.

    由 TrainingRuntime 拥有的规范 Product 作业状态。

    Attempt 状态可以包含 LOST。丢失的 Attempt 不得改写为成功的 TrainingRun；是否重试由 controller 决定。
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
    """Plugins-owned training backends exposed to Yield.

    向 Yield 暴露的 Plugins 所有训练后端。
    """

    LLAMA_FACTORY = "llamafactory"


class DistributedStrategy(str, Enum):
    """Training strategy chosen by an Engine, not by the Executor.

    由 Engine 选择的训练策略，不由 Executor 选择。
    """

    SINGLE = "single"
    DDP = "ddp"
    FSDP = "fsdp"
    DEEPSPEED = "deepspeed"
    TORCHRUN = "torchrun"


class LaunchKind(str, Enum):
    """How the compiled command should be started.

    This is still a training-engine decision (direct python vs torchrun
    wrapper). The Executor only starts the resulting argv/process tree.

    编译后的命令应如何启动。

    这仍由训练引擎决定（直接运行 Python，还是使用 torchrun wrapper）。Executor 只负责启动生成的 argv/进程树。
    """

    DIRECT = "direct"
    TORCHRUN = "torchrun"
