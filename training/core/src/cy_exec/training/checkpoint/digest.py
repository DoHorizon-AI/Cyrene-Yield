"""Checkpoint weight digest owned by Yield's Product artifact boundary.

Never fabricates a digest: missing weights yield ("", 0).

Yield 的 Product 制品边界所拥有的 checkpoint 权重摘要。

绝不伪造摘要:缺少权重时返回 ("", 0)。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/checkpoint/digest.py
# │ 中文:文件:training/core/src/cy_exec/training/checkpoint/digest.py
# │ Module: training/core/src/cy_exec/training/checkpoint/digest
# │ 模块:training/core/src/cy_exec/training/checkpoint/digest
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │ 职责:规范 Yield 训练 runtime,拥有训练契约、attempt、执行器、引擎、checkpoint 与 preflight。
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple

_PREFERRED_WEIGHTS_FILE = "adapter_model.safetensors"
_WEIGHTS_SUFFIXES = (".safetensors", ".bin")
_DIGEST_CHUNK_SIZE = 1024 * 1024


def find_checkpoint_weights_file(checkpoint_dir: str | os.PathLike) -> Optional[Path]:
    path = Path(checkpoint_dir)
    if not path.is_dir():
        return None
    preferred = path / _PREFERRED_WEIGHTS_FILE
    if preferred.is_file():
        return preferred
    candidates = [entry for entry in path.iterdir() if entry.is_file() and entry.suffix in _WEIGHTS_SUFFIXES]
    if not candidates:
        return None
    return max(candidates, key=lambda entry: entry.stat().st_size)


def compute_checkpoint_digest(checkpoint_dir: str | os.PathLike) -> Tuple[str, int]:
    """Return ``("sha256:<hex>", size_bytes)`` for the primary weight file.

    返回主权重文件的 ("sha256:<hex>", size_bytes)。
    """

    path = Path(checkpoint_dir)
    if not path.is_dir():
        return "", 0
    weights_file = find_checkpoint_weights_file(path)
    if weights_file is None:
        return "", 0
    hasher = hashlib.sha256()
    size_bytes = 0
    with weights_file.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_DIGEST_CHUNK_SIZE), b""):
            hasher.update(chunk)
            size_bytes += len(chunk)
    return f"sha256:{hasher.hexdigest()}", size_bytes
