"""Unified Training architecture.

Single product call chain:

    TrainingSpec
      -> TrainingRuntime / TrainingAttempt
        -> TrainingEngineAdapter (Plugins-owned LLaMA Factory)
          -> explicit Platform-backed execution adapter

统一训练架构。

单一 Product 调用链：

    TrainingSpec
      -> TrainingRuntime / TrainingAttempt
        -> TrainingEngineAdapter（Plugins 所有的 LLaMA Factory）
          -> 显式的 Platform 执行适配器
"""

from .capability_seam import (
    YIELD_TRAINING_RUNTIME_CAPABILITY,
    YIELD_TRAINING_RUNTIME_INTERFACE_VERSION,
    YIELD_TRAINING_RUNTIME_REQUIREMENT,
    TrainingRuntimeRequirement,
    YieldTrainingRuntimeAdapter,
    YieldTrainingRuntimeResolver,
)
from .contracts import (
    CheckpointSpec,
    DistributedSpec,
    EngineKind,
    EngineValidation,
    TrainingAttempt,
    TrainingEvent,
    TrainingEventKind,
    TrainingLaunchSpec,
    TrainingResult,
    TrainingRun,
    TrainingSpec,
    TrainingStatus,
)
from .control_plane import TrainingControlPlane, TrainingPlanCompiler, TrainingStateRecoveryError
from .engines import available_engines, get_engine
from .executors import KernelTrainingConfiguration, KernelTrainingExecutor, TrainingExecutor
from .preflight import TrainingPreflight
from .runtime import TrainingRuntime, TrainingSession
from .tiny_dry_run import TinyDryRun, TinyDryRunGateError, TinyDryRunResult, TinyDryRunStatus

__all__ = [
    "CheckpointSpec",
    "DistributedSpec",
    "EngineKind",
    "EngineValidation",
    "TrainingAttempt",
    "TrainingEvent",
    "TrainingEventKind",
    "TrainingLaunchSpec",
    "TrainingResult",
    "TrainingRun",
    "TrainingSpec",
    "TrainingStatus",
    "available_engines",
    "get_engine",
    "KernelTrainingConfiguration",
    "KernelTrainingExecutor",
    "TrainingExecutor",
    "TrainingRuntime",
    "TrainingSession",
    "TrainingPreflight",
    "TinyDryRun",
    "TinyDryRunGateError",
    "TinyDryRunResult",
    "TinyDryRunStatus",
    "TrainingControlPlane",
    "TrainingPlanCompiler",
    "TrainingStateRecoveryError",
    "YieldTrainingRuntimeAdapter",
    "YieldTrainingRuntimeResolver",
    "YIELD_TRAINING_RUNTIME_CAPABILITY",
    "YIELD_TRAINING_RUNTIME_INTERFACE_VERSION",
    "YIELD_TRAINING_RUNTIME_REQUIREMENT",
    "TrainingRuntimeRequirement",
]
