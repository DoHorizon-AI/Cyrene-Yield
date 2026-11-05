"""Yield-owned training invariants and Plugins-owned dataset-validation adapter.

Yield retains request and training-admission invariants. Reusable dataset parsing,
schema validation, and quality inspection belong to ``tool.dataset.validator.v1``.

Yield 所有的训练不变量与 Plugins 所有的数据集校验适配器。

Yield 保留请求与训练准入不变量。可复用的数据集解析、schema 校验和质量检查属于 tool.dataset.validator.v1。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/validation/__init__.py
# │ 中文:文件:training/core/src/cy_exec/training/validation/__init__.py
# │ Module: training/core/src/cy_exec/training/validation/__init__
# │ 模块:training/core/src/cy_exec/training/validation/__init__
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责:规范 Yield 训练 runtime,拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from .dataset_plugin import (
    DatasetValidationPort,
    DatasetValidationUnavailable,
    DirectPluginDatasetValidator,
    UnavailableDatasetValidator,
    ValidationError,
    ValidationResult,
    dataset_validator_from_environment,
)
from .files import looks_like_local_path, validate_existing_dir, validate_existing_file
from .model import validate_model_path
from .params import validate_training_params
from .pipeline import validate_training_spec

__all__ = [
    "DatasetValidationPort",
    "DatasetValidationUnavailable",
    "DirectPluginDatasetValidator",
    "UnavailableDatasetValidator",
    "ValidationError",
    "ValidationResult",
    "dataset_validator_from_environment",
    "looks_like_local_path",
    "validate_existing_dir",
    "validate_existing_file",
    "validate_model_path",
    "validate_training_params",
    "validate_training_spec",
]
