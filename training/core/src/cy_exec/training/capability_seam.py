"""Yield-owned seam around the retained local training runtime."""

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
    """Yield application port; cancellation requires confirmed execution cleanup."""

    def submit(self, spec: TrainingSpec) -> TrainingSession: ...

    def poll(self, session_id: str) -> TrainingSession: ...

    def cancel(self, session_id: str) -> TrainingSession: ...


class TrainingRuntimeResolver(Protocol):
    """Resolve one Product-owned runtime or a direct owner-scoped Plugin adapter."""

    def resolve(self, requirement: TrainingRuntimeRequirement) -> TrainingRuntimePort: ...


class YieldTrainingRuntimeAdapter:
    """Product application adapter around Yield's lifecycle runtime."""

    def __init__(self, runtime: TrainingRuntime) -> None:
        self._runtime = runtime

    def submit(self, spec: TrainingSpec) -> TrainingSession:
        return self._runtime.submit(spec)

    def poll(self, session_id: str) -> TrainingSession:
        return self._runtime.poll(session_id)

    def cancel(self, session_id: str) -> TrainingSession:
        return self._runtime.cancel(session_id)


class YieldTrainingRuntimeResolver:
    """Resolve the Product-owned lifecycle runtime without a Platform data-plane hop."""

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
