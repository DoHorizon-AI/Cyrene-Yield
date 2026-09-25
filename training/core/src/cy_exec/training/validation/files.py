"""Local file existence and integrity checks shared by both engines.

两个引擎共用的本地文件存在性与完整性检查。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/validation/files.py
# │ 中文:文件:training/core/src/cy_exec/training/validation/files.py
# │ Module: training/core/src/cy_exec/training/validation/files
# │ 模块:training/core/src/cy_exec/training/validation/files
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责:规范 Yield 训练 runtime,拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..contracts.errors import TrainingIssue


def path_exists(path: str) -> bool:
    return Path(path).exists()


def validate_existing_file(path: str, field: str) -> List[TrainingIssue]:
    target = Path(path)
    if not target.exists():
        return [TrainingIssue(code="file_missing", message=f"File does not exist: {path}", field=field)]
    if not target.is_file():
        return [TrainingIssue(code="not_a_file", message=f"Path is not a file: {path}", field=field)]
    if target.stat().st_size <= 0:
        return [TrainingIssue(code="empty_file", message=f"File is empty: {path}", field=field)]
    return []


def validate_existing_dir(path: str, field: str) -> List[TrainingIssue]:
    target = Path(path)
    if not target.exists():
        return [TrainingIssue(code="dir_missing", message=f"Directory does not exist: {path}", field=field)]
    if not target.is_dir():
        return [TrainingIssue(code="not_a_directory", message=f"Path is not a directory: {path}", field=field)]
    return []


def looks_like_local_path(path: str) -> bool:
    if not path:
        return False
    candidate = Path(path)
    if candidate.exists():
        return True
    if path.startswith(("http://", "https://", "hf://", "s3://")):
        return False
    if "/" in path and not candidate.is_absolute() and not path.startswith((".", "/", "\\")):
        # HuggingFace hub id like org/name
        # HuggingFace Hub ID,例如 org/name。
        if candidate.suffix == "" and path.count("/") == 1:
            return False
    return True


def optional_file(path: Optional[str], field: str) -> List[TrainingIssue]:
    if not path:
        return []
    return validate_existing_file(path, field)
