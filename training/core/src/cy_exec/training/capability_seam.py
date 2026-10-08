"""Yield-owned seam around the retained local training runtime.

围绕保留的本地训练 runtime 建立的 Yield 所有接缝。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import TrainingSpec
from .runtime import TrainingRuntime, TrainingSession

YIELD_TRAINING_RUNTIME_CAPABILITY = "cyrene.yield.training-runtime.v1"
YIELD_TRAINING_RUNTIME_INTERFACE_VERSION = "1"


@dataclass(frozen=True)
class TrainingRuntimeRequirement:
    capability: str = YIELD_TRAINING_RUNTIME_CAPABILITY
    interface_version: str = YIELD_TRAINING_RUNTIME_INTERFACE_VERSION
    execution_modes: tuple[str, ...] = ("WORKER",)


YIELD_TRAINING_RUNTIME_REQUIREMENT = TrainingRuntimeRequirement()


class TrainingRuntimePort(Protocol):
    """Yield application port; cancellation requires confirmed execution cleanup.

    Yield 应用端口;只有在确认执行清理后才能完成取消。
    """

    def submit(self, spec: TrainingSpec) -> TrainingSession: ...

    def poll(self, session_id: str) -> TrainingSession: ...

    def cancel(self, session_id: str) -> TrainingSession: ...


class TrainingRuntimeResolver(Protocol):
    """Resolve one Product-owned runtime or a direct owner-scoped Plugin adapter.

    解析一个 Product 所有的 runtime,或一个直接的 owner-scoped Plugin 适配器。
    """

    def resolve(self, requirement: TrainingRuntimeRequirement) -> TrainingRuntimePort: ...


class YieldTrainingRuntimeAdapter:
    """Product application adapter around Yield's lifecycle runtime.

    围绕 Yield 生命周期 runtime 的 Product 应用适配器。
    """

    def __init__(self, runtime: TrainingRuntime) -> None:
        self._runtime = runtime

    def submit(self, spec: TrainingSpec) -> TrainingSession:
        return self._runtime.submit(spec)

    def poll(self, session_id: str) -> TrainingSession:
        return self._runtime.poll(session_id)

    def cancel(self, session_id: str) -> TrainingSession:
        return self._runtime.cancel(session_id)


class YieldTrainingRuntimeResolver:
    """Resolve the Product-owned lifecycle runtime without a Platform data-plane hop.

    解析 Product 所有的生命周期 runtime,不经过 Platform data plane。
    """

    def __init__(self, runtime: TrainingRuntime) -> None:
        self._adapter = YieldTrainingRuntimeAdapter(runtime)

    def resolve(self, requirement: TrainingRuntimeRequirement) -> TrainingRuntimePort:
        if requirement != YIELD_TRAINING_RUNTIME_REQUIREMENT:
            raise ValueError(f"Unsupported training runtime requirement: {requirement}")
        return self._adapter


__all__ = [
    "YieldTrainingRuntimeAdapter",
    "YieldTrainingRuntimeResolver",
    "TrainingRuntimePort",
    "TrainingRuntimeRequirement",
    "TrainingRuntimeResolver",
    "YIELD_TRAINING_RUNTIME_CAPABILITY",
    "YIELD_TRAINING_RUNTIME_INTERFACE_VERSION",
    "YIELD_TRAINING_RUNTIME_REQUIREMENT",
]
