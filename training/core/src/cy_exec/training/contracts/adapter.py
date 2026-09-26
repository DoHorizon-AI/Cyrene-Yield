"""TrainingEngineAdapter protocol.

Adapters inspect, validate, and compile. They must not own product job
state. launch/status/cancel may exist on legacy engines for compatibility
but are not part of this contract.

TrainingEngineAdapter 协议。

适配器负责检查、验证和编译,不得拥有 Product 作业状态。旧引擎可能为兼容性保留 launch/status/cancel,但这些方法不属于本契约。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/adapter.py
# │ 中文:文件:training/core/src/cy_exec/training/contracts/adapter.py
# │ Module: training/core/src/cy_exec/training/contracts/adapter
# │ 模块:training/core/src/cy_exec/training/contracts/adapter
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责:规范 Yield 训练 runtime,拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence

from .errors import TrainingIssue
from .events import TrainingEvent, TrainingResult
from .launch import TrainingLaunchSpec
from .spec import TrainingSpec
from .status import DistributedStrategy, EngineKind, TrainingStatus


@dataclass
class EngineInspect:
    engine: EngineKind
    available: bool
    version: Optional[str] = None
    supported_strategies: List[DistributedStrategy] = field(default_factory=list)
    supported_finetune_types: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine.value,
            "available": self.available,
            "version": self.version,
            "supported_strategies": [item.value for item in self.supported_strategies],
            "supported_finetune_types": list(self.supported_finetune_types),
            "notes": list(self.notes),
        }


@dataclass
class EngineValidation:
    ok: bool
    issues: List[TrainingIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class TrainingEngineAdapter(Protocol):
    """Compile a TrainingSpec into an executor-agnostic launch spec.

    将 TrainingSpec 编译为与执行器无关的 launch spec。
    """

    kind: EngineKind

    def inspect(self) -> EngineInspect:
        ...

    def validate(self, spec: TrainingSpec) -> EngineValidation:
        ...

    def compile(self, spec: TrainingSpec) -> TrainingLaunchSpec:
        ...

    def parse_event(self, line: str) -> Optional[TrainingEvent]:
        ...

    def collect_result(
        self,
        spec: TrainingSpec,
        launch: TrainingLaunchSpec,
        exit_code: Optional[int],
        status: TrainingStatus,
    ) -> TrainingResult:
        ...


def require_engine_kind(spec: TrainingSpec, expected: EngineKind) -> None:
    if spec.engine != expected:
        raise ValueError(
            f"Adapter {expected.value} received spec for engine {spec.engine.value}"
        )


def strategy_values(items: Sequence[DistributedStrategy]) -> List[str]:
    return [item.value for item in items]
