"""Compose Yield admission invariants with the Plugins-owned dataset verdict.

将 Yield 准入不变量与 Plugins 所有的数据集判定结果组合起来。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/validation/pipeline.py
# │ 中文:文件:training/core/src/cy_exec/training/validation/pipeline.py
# │ Module: training/core/src/cy_exec/training/validation/pipeline
# │ 模块:training/core/src/cy_exec/training/validation/pipeline
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责:规范 Yield 训练 runtime,拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..contracts.adapter import EngineValidation
from ..contracts.errors import TrainingIssue
from ..contracts.spec import TrainingSpec
from .dataset_plugin import DatasetValidationPort, dataset_validator_from_environment
from .files import looks_like_local_path, optional_file, validate_existing_file
from .model import validate_model_path
from .params import validate_training_params


def validate_training_spec(
    spec: TrainingSpec,
    *,
    require_local_model: bool = False,
    dataset_validator: Optional[DatasetValidationPort] = None,
) -> EngineValidation:
    issues: List[TrainingIssue] = []
    issues.extend(validate_training_params(spec))

    dataset_path = spec.dataset.path
    if not dataset_path:
        issues.append(
            TrainingIssue(
                code="dataset_path_missing",
                message="dataset.path is required",
                field="dataset.path",
            )
        )
    else:
        issues.extend(validate_existing_file(dataset_path, "dataset.path"))
        path = Path(dataset_path)
        if path.exists() and path.is_file():
            validator = dataset_validator or dataset_validator_from_environment()
            result = validator.validate(
                dataset_path,
                format_type=spec.dataset.format or "auto",
                schema=spec.dataset.schema,
            )
            if not result.is_valid:
                for error in result.errors:
                    issues.append(
                        TrainingIssue(
                            code="dataset_invalid",
                            message=error.message,
                            field=error.field or "dataset.path",
                            details={"row_index": error.row_index, "value": error.value},
                        )
                    )
        issues.extend(optional_file(spec.dataset.settings_path, "dataset.settings_path"))

    model_path = spec.model.path
    if require_local_model or looks_like_local_path(model_path):
        issues.extend(validate_model_path(model_path))

    resume = spec.checkpoint.resume_from
    if resume and resume != "auto":
        resume_path = Path(resume)
        if not resume_path.exists():
            issues.append(
                TrainingIssue(
                    code="checkpoint_missing",
                    message=f"Resume checkpoint does not exist: {resume}",
                    field="checkpoint.resume_from",
                )
            )

    return EngineValidation(ok=len(issues) == 0, issues=issues)
