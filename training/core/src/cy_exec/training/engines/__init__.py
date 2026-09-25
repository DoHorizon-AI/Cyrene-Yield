"""Training engine registry.

训练引擎注册表。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/engines/__init__.py
# │ 中文：文件：training/core/src/cy_exec/training/engines/__init__.py
# │ Module: training/core/src/cy_exec/training/engines/__init__
# │ 模块：training/core/src/cy_exec/training/engines/__init__
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责：规范 Yield 训练 runtime，拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

from typing import Dict

from ..contracts import EngineKind, TrainingEngineAdapter
from .llamafactory import LlamaFactoryEngineAdapter


_ADAPTERS: Dict[EngineKind, TrainingEngineAdapter] = {
    EngineKind.LLAMA_FACTORY: LlamaFactoryEngineAdapter(),
}


def get_engine(kind: EngineKind | str) -> TrainingEngineAdapter:
    engine = EngineKind(kind) if isinstance(kind, str) else kind
    try:
        return _ADAPTERS[engine]
    except KeyError as exc:
        raise KeyError(f"Unknown training engine: {engine}") from exc


def available_engines() -> Dict[str, TrainingEngineAdapter]:
    return {kind.value: adapter for kind, adapter in _ADAPTERS.items()}
