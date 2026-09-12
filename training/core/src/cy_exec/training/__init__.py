"""Unified Training architecture.

Single product call chain:

    TrainingSpec
      -> TrainingRuntime / TrainingAttempt
        -> TrainingEngineAdapter (Plugins-owned LLaMA Factory)
          -> Executor (LocalProcess | CyreneKernel)
"""

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
from .engines import available_engines, get_engine
from .executors import CyreneKernelExecutor, LocalProcessExecutor, TrainingExecutor
from .runtime import TrainingRuntime, TrainingSession, get_training_runtime
from .preflight import TrainingPreflight
from .tiny_dry_run import TinyDryRun, TinyDryRunGateError, TinyDryRunResult, TinyDryRunStatus
from .control_plane import TrainingControlPlane, TrainingPlanCompiler, TrainingStateRecoveryError
from .capability_seam import (
    YieldTrainingRuntimeAdapter,
    YieldTrainingRuntimeResolver,
    YIELD_TRAINING_RUNTIME_CAPABILITY,
    YIELD_TRAINING_RUNTIME_INTERFACE_VERSION,
    YIELD_TRAINING_RUNTIME_REQUIREMENT,
    TrainingRuntimeRequirement,
)

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
    "CyreneKernelExecutor",
    "LocalProcessExecutor",
    "TrainingExecutor",
    "TrainingRuntime",
    "TrainingSession",
    "get_training_runtime",
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
