"""Training hyperparameter checks shared by both engines.

两个引擎共用的训练超参数检查。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/validation/params.py
# │ 中文：文件：training/core/src/cy_exec/training/validation/params.py
# │ Module: training/core/src/cy_exec/training/validation/params
# │ 模块：training/core/src/cy_exec/training/validation/params
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责：规范 Yield 训练 runtime，拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from typing import List

from ..contracts.errors import TrainingIssue
from ..contracts.spec import TrainingSpec


def validate_training_params(spec: TrainingSpec) -> List[TrainingIssue]:
    issues: List[TrainingIssue] = []
    if not spec.output_dir or not str(spec.output_dir).strip():
        issues.append(
            TrainingIssue(code="output_dir_missing", message="output_dir is required", field="output_dir")
        )

    hp = spec.hyperparams
    if hp.num_train_epochs <= 0:
        issues.append(
            TrainingIssue(
                code="invalid_epochs",
                message="num_train_epochs must be > 0",
                field="hyperparams.num_train_epochs",
            )
        )
    if hp.per_device_batch_size <= 0:
        issues.append(
            TrainingIssue(
                code="invalid_batch_size",
                message="per_device_batch_size must be > 0",
                field="hyperparams.per_device_batch_size",
            )
        )
    if hp.gradient_accumulation_steps <= 0:
        issues.append(
            TrainingIssue(
                code="invalid_grad_accum",
                message="gradient_accumulation_steps must be > 0",
                field="hyperparams.gradient_accumulation_steps",
            )
        )
    if hp.learning_rate <= 0:
        issues.append(
            TrainingIssue(
                code="invalid_learning_rate",
                message="learning_rate must be > 0",
                field="hyperparams.learning_rate",
            )
        )
    if hp.max_seq_length <= 0:
        issues.append(
            TrainingIssue(
                code="invalid_max_seq_length",
                message="max_seq_length must be > 0",
                field="hyperparams.max_seq_length",
            )
        )

    if spec.finetuning_type == "lora" and spec.lora.enabled:
        if spec.lora.r <= 0:
            issues.append(
                TrainingIssue(code="invalid_lora_r", message="lora.r must be > 0", field="lora.r")
            )
        if spec.lora.lora_alpha <= 0:
            issues.append(
                TrainingIssue(
                    code="invalid_lora_alpha",
                    message="lora.lora_alpha must be > 0",
                    field="lora.lora_alpha",
                )
            )
        if spec.lora.lora_dropout < 0 or spec.lora.lora_dropout >= 1:
            issues.append(
                TrainingIssue(
                    code="invalid_lora_dropout",
                    message="lora.lora_dropout must be in [0, 1)",
                    field="lora.lora_dropout",
                )
            )

    if spec.checkpoint.save_steps <= 0:
        issues.append(
            TrainingIssue(
                code="invalid_save_steps",
                message="checkpoint.save_steps must be > 0",
                field="checkpoint.save_steps",
            )
        )
    if spec.checkpoint.save_total_limit < 1:
        issues.append(
            TrainingIssue(
                code="invalid_save_total_limit",
                message="checkpoint.save_total_limit must be >= 1",
                field="checkpoint.save_total_limit",
            )
        )
    return issues
