"""Shared helpers for Training Engine TCK tests."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/training_tck_helpers.py
# │ Module: training/core/tests/training_tck_helpers
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

import json
from pathlib import Path

from cy_exec.training.contracts import (
    DatasetRef,
    DistributedSpec,
    EngineKind,
    ModelRef,
    TrainingSpec,
)


def write_instruction_dataset(directory: Path, name: str = "train.jsonl") -> Path:
    path = directory / name
    rows = [
        {"instruction": "Say hi", "input": "", "output": "hello"},
        {"instruction": "Say bye", "input": "", "output": "goodbye"},
    ]
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return path


def make_spec(
    directory: Path,
    engine: EngineKind,
    *,
    gpu_count: int = 1,
    model_path: str = "org/tiny-test-model",
) -> TrainingSpec:
    dataset = write_instruction_dataset(directory)
    output_dir = directory / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return TrainingSpec(
        engine=engine,
        model=ModelRef(path=model_path, name="tiny-test-model"),
        dataset=DatasetRef(path=str(dataset), name="cyrene_custom", schema="instruction"),
        output_dir=str(output_dir),
        character_name="tck",
        distributed=DistributedSpec.for_gpu_count(gpu_count),
    )
