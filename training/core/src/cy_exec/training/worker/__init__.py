"""Generic training worker process."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/worker/__init__.py
# │ Module: training/core/src/cy_exec/training/worker/__init__
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from .cli import main, run_control_loop

__all__ = ["main", "run_control_loop"]
