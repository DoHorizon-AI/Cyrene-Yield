"""Checkpoint policy expressed by the product contract.

由 Product 契约表达的 checkpoint 策略。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/checkpoint.py
# │ 中文：文件：training/core/src/cy_exec/training/contracts/checkpoint.py
# │ Module: training/core/src/cy_exec/training/contracts/checkpoint
# │ 模块：training/core/src/cy_exec/training/contracts/checkpoint
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责：规范 Yield 训练 runtime，拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class CheckpointSpec:
    """Where and how checkpoints should be kept. Not a job-status field.

    checkpoint 应保存的位置和方式。它不是作业状态字段。
    """

    output_dir: str = ""
    resume_from: Optional[str] = None
    save_steps: int = 100
    save_total_limit: int = 3
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "resume_from": self.resume_from,
            "save_steps": self.save_steps,
            "save_total_limit": self.save_total_limit,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CheckpointSpec":
        if not data:
            return cls()
        return cls(**data)
