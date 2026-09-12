"""Checkpoint helpers shared by both engines."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/checkpoint/__init__.py
# │ Module: training/core/src/cy_exec/training/checkpoint/__init__
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from .checkpoint_manager import CheckpointInfo, CheckpointManager
from .digest import compute_checkpoint_digest, find_checkpoint_weights_file

__all__ = [
    "CheckpointInfo",
    "CheckpointManager",
    "compute_checkpoint_digest",
    "find_checkpoint_weights_file",
]
