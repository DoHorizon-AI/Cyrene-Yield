"""Unified Training Engine contracts.

TrainingSpec is user intent. TrainingLaunchSpec is the compiled process.
Product job status lives in TrainingRuntime, not in engine adapters.

统一 Training Engine 契约。

TrainingSpec 表示用户意图；TrainingLaunchSpec 表示编译后的进程。
Product 作业状态由 TrainingRuntime 管理，而不是由引擎适配器管理。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/__init__.py
# │ 中文：文件：training/core/src/cy_exec/training/contracts/__init__.py
# │ Module: training/core/src/cy_exec/training/contracts/__init__
# │ 模块：training/core/src/cy_exec/training/contracts/__init__
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责：规范 Yield 训练 runtime，拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from .adapter import EngineInspect, EngineValidation, TrainingEngineAdapter, require_engine_kind
from .checkpoint import CheckpointSpec
from .distributed import DistributedSpec
from .errors import TrainingError, TrainingErrorCode, TrainingIssue
from .events import TrainingEvent, TrainingEventKind, TrainingResult
from .artifacts import ArtifactCandidate, OutputDescriptor
from .attempt import KernelBinding, KernelOperationRef, TrainingAttempt, TrainingRun
from .workload import (
    StagedWorkload,
    WorkloadConfigRef,
    WorkloadConfigureSettings,
    assert_configure_is_not_training_spec,
)
from .launch import (
    FORBIDDEN_LAUNCH_ENV,
    MountSpec,
    OutputLayout,
    ResourceRequest,
    TrainingLaunchSpec,
    default_training_mounts,
    merge_executor_env,
)
from .spec import DatasetRef, HyperparamSpec, LoRASpec, ModelRef, QuantizationSpec, TrainingSpec
from .status import DistributedStrategy, EngineKind, LaunchKind, TrainingStatus
from ..environment import EnvironmentLock, EnvironmentSpec

__all__ = [
    "ArtifactCandidate",
    "CheckpointSpec",
    "DatasetRef",
    "DistributedSpec",
    "DistributedStrategy",
    "EngineInspect",
    "EngineKind",
    "EngineValidation",
    "EnvironmentLock",
    "EnvironmentSpec",
    "FORBIDDEN_LAUNCH_ENV",
    "HyperparamSpec",
    "KernelBinding",
    "KernelOperationRef",
    "LaunchKind",
    "LoRASpec",
    "ModelRef",
    "MountSpec",
    "OutputDescriptor",
    "OutputLayout",
    "QuantizationSpec",
    "ResourceRequest",
    "TrainingAttempt",
    "TrainingRun",
    "TrainingEngineAdapter",
    "TrainingError",
    "TrainingErrorCode",
    "TrainingEvent",
    "TrainingEventKind",
    "TrainingIssue",
    "TrainingLaunchSpec",
    "TrainingResult",
    "TrainingSpec",
    "TrainingStatus",
    "WorkloadConfigRef",
    "WorkloadConfigureSettings",
    "StagedWorkload",
    "assert_configure_is_not_training_spec",
    "default_training_mounts",
    "merge_executor_env",
    "require_engine_kind",
]
