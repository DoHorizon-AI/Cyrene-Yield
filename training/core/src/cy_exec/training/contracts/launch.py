"""TrainingLaunchSpec: the process/container that should be started.

Compiled by a TrainingEngineAdapter. Consumed by any Executor
(LocalProcessExecutor today, CyreneKernelExecutor later). This type must
not import or mention a concrete executor.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/launch.py
# │ Module: training/core/src/cy_exec/training/contracts/launch
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from .checkpoint import CheckpointSpec
from .distributed import DistributedSpec
from .status import EngineKind, LaunchKind
from ..environment import EnvironmentLock

# Machine-level device assignment is an Executor/Kernel concern.
FORBIDDEN_LAUNCH_ENV = frozenset(
    {
        "CUDA_VISIBLE_DEVICES",
        "HIP_VISIBLE_DEVICES",
        "ROCR_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES",
    }
)


@dataclass
class ResourceRequest:
    """What the compiled job needs. Not a device binding."""

    gpu_count: int = 1
    world_size: int = 1
    nnodes: int = 1
    nproc_per_node: int = 1
    gpu_memory_gb: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gpu_count": self.gpu_count,
            "world_size": self.world_size,
            "nnodes": self.nnodes,
            "nproc_per_node": self.nproc_per_node,
            "gpu_memory_gb": self.gpu_memory_gb,
        }

    @classmethod
    def from_distributed(cls, distributed: DistributedSpec) -> "ResourceRequest":
        extra_mem = 0.0
        if distributed.extra:
            extra_mem = float(distributed.extra.get("gpu_memory_gb") or 0.0)
        return cls(
            gpu_count=distributed.gpu_count,
            world_size=distributed.world_size,
            nnodes=distributed.nnodes,
            nproc_per_node=distributed.nproc_per_node,
            gpu_memory_gb=extra_mem,
        )


@dataclass
class MountSpec:
    """Logical input/output mount. Paths stay product-side until Executor binds them."""

    source: str
    target: str
    kind: str = "bind"
    read_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "read_only": self.read_only,
        }


@dataclass
class OutputLayout:
    """Standard attempt output contract. Not an Artifact Plane."""

    root: str = "output"
    model: str = "model"
    checkpoints: str = "checkpoints"
    metrics: str = "metrics.json"
    manifest: str = "run-manifest.json"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "model": self.model,
            "checkpoints": self.checkpoints,
            "metrics": self.metrics,
            "manifest": self.manifest,
        }


@dataclass
class TrainingLaunchSpec:
    """Final launch description produced by compile()."""

    engine: EngineKind
    argv: List[str]
    work_dir: str
    distributed: DistributedSpec
    checkpoint: CheckpointSpec
    launch_kind: LaunchKind = LaunchKind.DIRECT
    cwd: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    resources: ResourceRequest = field(default_factory=ResourceRequest)
    mounts: List[MountSpec] = field(default_factory=list)
    output_layout: OutputLayout = field(default_factory=OutputLayout)
    environment_lock: Optional[EnvironmentLock] = None
    spec_artifact_path: Optional[str] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    timeout_seconds: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.engine, str):
            self.engine = EngineKind(self.engine)
        if isinstance(self.launch_kind, str):
            self.launch_kind = LaunchKind(self.launch_kind)
        if isinstance(self.distributed, dict):
            self.distributed = DistributedSpec.from_dict(self.distributed)
        if isinstance(self.checkpoint, dict):
            self.checkpoint = CheckpointSpec.from_dict(self.checkpoint)
        if isinstance(self.resources, dict):
            self.resources = ResourceRequest(**self.resources)
        if self.mounts and isinstance(self.mounts[0], dict):
            self.mounts = [MountSpec(**item) if isinstance(item, dict) else item for item in self.mounts]
        if isinstance(self.output_layout, dict):
            self.output_layout = OutputLayout(**self.output_layout)
        if isinstance(self.environment_lock, dict):
            self.environment_lock = EnvironmentLock.from_dict(self.environment_lock)
        leaked = FORBIDDEN_LAUNCH_ENV.intersection(self.env)
        if leaked:
            raise ValueError(
                "TrainingLaunchSpec.env must not contain machine-level device "
                f"assignment keys: {sorted(leaked)}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine.value,
            "argv": list(self.argv),
            "work_dir": self.work_dir,
            "distributed": self.distributed.to_dict(),
            "checkpoint": self.checkpoint.to_dict(),
            "launch_kind": self.launch_kind.value,
            "cwd": self.cwd,
            "env": dict(self.env),
            "resources": self.resources.to_dict(),
            "mounts": [item.to_dict() for item in self.mounts],
            "output_layout": self.output_layout.to_dict(),
            "environment_lock": (
                None if self.environment_lock is None else self.environment_lock.to_dict()
            ),
            "spec_artifact_path": self.spec_artifact_path,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "timeout_seconds": self.timeout_seconds,
            "extra": dict(self.extra),
        }

    def assert_executor_agnostic(self) -> None:
        """Guardrail: launch specs stay portable across executors."""
        blob = str(self.to_dict()).lower().replace("-", "").replace("_", "")
        if "localprocessexecutor" in blob or "cyrenekernelexecutor" in blob:
            raise ValueError("TrainingLaunchSpec must not name a concrete executor")


def default_training_mounts(dataset_path: str, output_dir: str) -> List[MountSpec]:
    """Logical input/output mounts. Executor binds them onto the node."""

    return [
        MountSpec(source=dataset_path, target="/input/dataset", kind="bind", read_only=True),
        MountSpec(source=output_dir, target="/output", kind="bind", read_only=False),
    ]


def merge_executor_env(
    launch_env: Mapping[str, str],
    assigned_env: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Executor-side merge. Device assignment may be added here, not in the contract."""

    merged = dict(launch_env)
    if assigned_env:
        merged.update(assigned_env)
    return merged
