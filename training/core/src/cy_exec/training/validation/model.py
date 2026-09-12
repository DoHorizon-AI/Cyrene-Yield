"""Local model directory checks shared by both engines."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/validation/model.py
# │ Module: training/core/src/cy_exec/training/validation/model
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from pathlib import Path
from typing import List

from ..contracts.errors import TrainingIssue
from .files import looks_like_local_path

_CONFIG_NAMES = ("config.json", "adapter_config.json")
_WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt")
_WEIGHT_INDEX_NAMES = ("model.safetensors.index.json", "pytorch_model.bin.index.json")


def validate_model_path(path: str, field: str = "model.path") -> List[TrainingIssue]:
    if not path or not str(path).strip():
        return [TrainingIssue(code="model_path_missing", message="Model path is required", field=field)]

    if not looks_like_local_path(path):
        return []

    target = Path(path)
    if not target.exists():
        return [
            TrainingIssue(
                code="model_missing",
                message=f"Local model path does not exist: {path}",
                field=field,
            )
        ]
    if target.is_file():
        if target.stat().st_size <= 0:
            return [TrainingIssue(code="empty_file", message=f"Model file is empty: {path}", field=field)]
        return []
    if not target.is_dir():
        return [TrainingIssue(code="model_invalid", message=f"Model path is invalid: {path}", field=field)]

    has_config = any((target / name).is_file() for name in _CONFIG_NAMES)
    has_weight = any(target.glob(f"*{suffix}") for suffix in _WEIGHT_SUFFIXES) or any(
        (target / name).is_file() for name in _WEIGHT_INDEX_NAMES
    )
    if not has_config:
        return [
            TrainingIssue(
                code="model_config_missing",
                message=f"Model directory is missing config.json: {path}",
                field=field,
            )
        ]
    if not has_weight:
        return [
            TrainingIssue(
                code="model_weights_missing",
                message=f"Model directory has no weight files: {path}",
                field=field,
            )
        ]
    return []
