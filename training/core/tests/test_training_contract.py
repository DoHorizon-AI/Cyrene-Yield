"""Contract tests for the unified Training Engine layer.

统一 Training Engine 层的契约测试。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_training_contract.py
# │ 中文：文件：training/core/tests/test_training_contract.py
# │ Module: training/core/tests/test_training_contract
# │ 模块：training/core/tests/test_training_contract
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │ 职责：Yield 核心测试模块，验证统一训练 runtime 与契约。
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import pytest

from cy_exec.training.contracts import (
    DistributedSpec,
    EngineKind,
    FORBIDDEN_LAUNCH_ENV,
    TrainingLaunchSpec,
    TrainingSpec,
)
from cy_exec.training.contracts.checkpoint import CheckpointSpec
from cy_exec.training.contracts.launch import ResourceRequest
from cy_exec.training.validation import validate_training_spec
from training_tck_helpers import make_spec


def test_training_spec_roundtrip(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY, gpu_count=2)
    restored = TrainingSpec.from_dict(spec.to_dict())
    assert restored.engine == EngineKind.LLAMA_FACTORY
    assert restored.distributed.world_size == 2
    assert restored.distributed.nproc_per_node == 2


def test_launch_spec_rejects_cuda_visible_devices(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)
    with pytest.raises(ValueError, match="CUDA_VISIBLE_DEVICES"):
        TrainingLaunchSpec(
            engine=spec.engine,
            argv=["python", "-c", "pass"],
            work_dir=spec.output_dir,
            distributed=spec.distributed,
            checkpoint=spec.checkpoint,
            env={"CUDA_VISIBLE_DEVICES": "0"},
            resources=ResourceRequest.from_distributed(spec.distributed),
        )


def test_forbidden_launch_env_is_explicit():
    assert "CUDA_VISIBLE_DEVICES" in FORBIDDEN_LAUNCH_ENV


def test_shared_dataset_validation_is_the_authority(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)
    spec.dataset.path = str(tmp_path / "missing.jsonl")
    result = validate_training_spec(spec)

    assert result.ok is False
    assert result.issues[0].code == "file_missing"


def test_invalid_hyperparams_are_rejected(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)
    spec.hyperparams.learning_rate = 0
    result = validate_training_spec(spec)
    assert result.ok is False
    assert any(issue.code == "invalid_learning_rate" for issue in result.issues)


def test_dataset_content_validation(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{}\n", encoding="utf-8")
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)
    spec.dataset.path = str(bad)
    spec.dataset.schema = "instruction"
    result = validate_training_spec(spec)
    assert result.ok is False
    assert any(issue.code == "dataset_invalid" for issue in result.issues)


def test_distributed_spec_requires_consistent_world_size():
    with pytest.raises(ValueError, match="world_size"):
        DistributedSpec(gpu_count=2, world_size=3, nnodes=1, nproc_per_node=2)
