"""Typed training errors and validation issues.

有类型的训练错误与校验问题。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/errors.py
# │ 中文：文件：training/core/src/cy_exec/training/contracts/errors.py
# │ Module: training/core/src/cy_exec/training/contracts/errors
# │ 模块：training/core/src/cy_exec/training/contracts/errors
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责：规范 Yield 训练 runtime，拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field as data_field
from enum import Enum
from typing import Any, Dict, List, Optional


class TrainingErrorCode(str, Enum):
    INVALID_SPEC = "invalid_spec"
    VALIDATION_FAILED = "validation_failed"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    COMPILE_FAILED = "compile_failed"
    EXECUTION_FAILED = "execution_failed"
    CANCEL_FAILED = "cancel_failed"
    LOST = "lost"
    CHECKPOINT_INVALID = "checkpoint_invalid"


@dataclass
class TrainingIssue:
    """One validation or runtime issue.

    一项校验或 runtime 问题。
    """

    code: str
    message: str
    field: Optional[str] = None
    details: Dict[str, Any] = data_field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "details": dict(self.details),
        }


@dataclass
class TrainingError(Exception):
    """Structured failure used by adapters and the runtime.

    供适配器与 runtime 使用的结构化失败信息。
    """

    code: TrainingErrorCode
    message: str
    issues: List[TrainingIssue] = data_field(default_factory=list)
    details: Dict[str, Any] = data_field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "issues": [issue.to_dict() for issue in self.issues],
            "details": dict(self.details),
        }
