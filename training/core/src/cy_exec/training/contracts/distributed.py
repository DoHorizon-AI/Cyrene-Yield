"""Distributed topology requested by a training job.

This describes *how many* ranks and how they are grouped. It does not
assign physical GPUs. Device visibility (for example CUDA_VISIBLE_DEVICES)
belongs to the Executor / future Kernel, never this contract.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/distributed.py
# │ Module: training/core/src/cy_exec/training/contracts/distributed
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .status import DistributedStrategy


@dataclass
class DistributedSpec:
    """GPU topology and world size. No machine-level device assignment."""

    gpu_count: int = 1
    world_size: int = 1
    nnodes: int = 1
    nproc_per_node: int = 1
    node_rank: int = 0
    strategy: DistributedStrategy = DistributedStrategy.SINGLE
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.strategy, str):
            self.strategy = DistributedStrategy(self.strategy)
        if self.gpu_count < 1:
            raise ValueError("gpu_count must be >= 1")
        if self.nnodes < 1 or self.nproc_per_node < 1:
            raise ValueError("nnodes and nproc_per_node must be >= 1")
        expected = self.nnodes * self.nproc_per_node
        if self.world_size != expected:
            raise ValueError(
                f"world_size ({self.world_size}) must equal nnodes * nproc_per_node ({expected})"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gpu_count": self.gpu_count,
            "world_size": self.world_size,
            "nnodes": self.nnodes,
            "nproc_per_node": self.nproc_per_node,
            "node_rank": self.node_rank,
            "strategy": self.strategy.value,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DistributedSpec":
        if not data:
            return cls()
        payload = dict(data)
        payload.pop("cuda_visible_devices", None)
        payload.pop("CUDA_VISIBLE_DEVICES", None)
        return cls(**payload)

    @classmethod
    def single_process(cls) -> "DistributedSpec":
        return cls(gpu_count=1, world_size=1, nnodes=1, nproc_per_node=1)

    @classmethod
    def for_gpu_count(cls, gpu_count: int) -> "DistributedSpec":
        count = max(1, int(gpu_count))
        return cls(
            gpu_count=count,
            world_size=count,
            nnodes=1,
            nproc_per_node=count,
            strategy=DistributedStrategy.SINGLE if count == 1 else DistributedStrategy.DDP,
        )
