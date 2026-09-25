"""Property tests for the canonical CheckpointManager.

Migrated from the retired Pro package (``cy_exec_pro.training.checkpoint``).
The Pro module was a thin re-export of this core authority, so the invariants
below now guard the single checkpoint contract directly.

规范 CheckpointManager 的属性测试。

从已退役的 Pro package（cy_exec_pro.training.checkpoint）迁移而来。Pro 模块只是对此 core 权威实现的轻量 re-export，因此以下不变量现在直接保护唯一的 checkpoint 契约。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_checkpoint_manager_pbt.py
# │ 中文：文件：training/core/tests/test_checkpoint_manager_pbt.py
# │ Module: training/core/tests/test_checkpoint_manager_pbt
# │ 模块：training/core/tests/test_checkpoint_manager_pbt
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │ 职责：Yield 核心测试模块，验证统一训练 runtime 与契约。
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘


import tempfile
from unittest.mock import Mock

import pytest
from hypothesis import given, settings, strategies as st

from cy_exec.training.checkpoint.checkpoint_manager import (
    CheckpointInfo,
    CheckpointManager,
)


def make_trainer():
    trainer = Mock()
    trainer.save_model = Mock()
    return trainer


@given(
    step=st.integers(min_value=1, max_value=10000),
    loss=st.floats(0, 100, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=25, deadline=None)
def test_save_find_and_validate_checkpoint(step, loss):
    with tempfile.TemporaryDirectory() as directory:
        manager = CheckpointManager(directory)
        info = manager.save_checkpoint(
            make_trainer(),
            step=step,
            metrics={"loss": loss},
            epoch=2.0,
            auto_cleanup=False,
        )
        latest = manager.find_latest_checkpoint()

        assert isinstance(info, CheckpointInfo)
        assert latest is not None
        assert latest.step == step
        assert latest.loss == loss
        assert manager.validate_checkpoint(info.path)


@given(steps=st.lists(st.integers(1, 10000), min_size=2, max_size=8, unique=True))
@settings(max_examples=20, deadline=None)
def test_latest_checkpoint_has_highest_step(steps):
    with tempfile.TemporaryDirectory() as directory:
        manager = CheckpointManager(directory)
        trainer = make_trainer()
        for step in steps:
            manager.save_checkpoint(trainer, step, {"loss": 1.0}, auto_cleanup=False)
        latest = manager.find_latest_checkpoint()

    assert latest is not None
    assert latest.step == max(steps)


def test_cleanup_and_load_metadata():
    with tempfile.TemporaryDirectory() as directory:
        manager = CheckpointManager(directory, save_total_limit=2)
        trainer = make_trainer()
        for step in (1, 2, 3):
            manager.save_checkpoint(trainer, step, {"loss": 0.5}, auto_cleanup=True)
        checkpoints = manager._list_checkpoints()
        assert len(checkpoints) == 2
        assert manager.load_checkpoint(checkpoints[0].path)["step"] in (2, 3)


def test_checkpoint_requires_loss_and_missing_path_is_invalid(tmp_path):
    manager = CheckpointManager(str(tmp_path))
    with pytest.raises(ValueError):
        manager.save_checkpoint(make_trainer(), 1, {"eval_loss": 0.5})
    assert manager.find_latest_checkpoint() is None
    assert not manager.validate_checkpoint(str(tmp_path / "missing"))
