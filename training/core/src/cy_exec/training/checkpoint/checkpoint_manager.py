"""Checkpoint save, discovery, validation, loading, and cleanup.

Canonical implementation lifted from Pro CheckpointManager, plus discovery
of HuggingFace / LLaMA-Factory checkpoint-* directories that have weights
but no Cyrene metadata file.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/checkpoint/checkpoint_manager.py
# │ Module: training/core/src/cy_exec/training/checkpoint/checkpoint_manager
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .digest import compute_checkpoint_digest, find_checkpoint_weights_file

LOGGER = logging.getLogger("cy_exec.training.checkpoint")


@dataclass
class CheckpointInfo:
    """Checkpoint metadata."""

    path: str
    step: int
    epoch: float
    loss: float
    timestamp: str
    is_valid: bool
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ════════════════════════════════════════════════════════════════════════
# 🔧 CLASS: CheckpointManager
#
#   Validates checkpoint contents, computes stable digests, and publishes
#   verified artifact references for completed training attempts.
#
#   校验检查点内容、计算稳定摘要，并为完成的训练尝试发布已验证制品引用。
#
# ════════════════════════════════════════════════════════════════════════
class CheckpointManager:
    """Manage checkpoint directories and their metadata files."""

    METADATA_FILE = "checkpoint_info.json"
    CHECKPOINT_PREFIX = "checkpoint-"

    def __init__(
        self,
        output_dir: str,
        max_checkpoints: int = 5,
        save_total_limit: int = 3,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.max_checkpoints = max_checkpoints
        self.save_total_limit = save_total_limit
        self.output_dir.mkdir(parents=True, exist_ok=True)
        LOGGER.info(
            "Checkpoint manager initialized: output_dir=%s, max_checkpoints=%d, "
            "save_total_limit=%d",
            output_dir,
            max_checkpoints,
            save_total_limit,
        )

    def save_checkpoint(
        self,
        trainer: Any,
        step: int,
        metrics: Dict[str, float],
        epoch: Optional[float] = None,
        auto_cleanup: bool = True,
    ) -> CheckpointInfo:
        if "loss" not in metrics:
            raise ValueError("metrics must contain a 'loss' key")

        checkpoint_dir = self.output_dir / f"{self.CHECKPOINT_PREFIX}{step}"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        try:
            if hasattr(trainer, "save_model"):
                trainer.save_model(str(checkpoint_dir))
            else:
                LOGGER.warning("Trainer has no save_model method; model save skipped")
        except Exception:
            LOGGER.exception("Model save failed")
            raise

        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        checkpoint_info = CheckpointInfo(
            path=str(checkpoint_dir),
            step=step,
            epoch=epoch or 0.0,
            loss=metrics.get("loss", float("inf")),
            timestamp=now,
            is_valid=True,
            metadata={"metrics": metrics, "created_at": now},
        )
        metadata_path = checkpoint_dir / self.METADATA_FILE
        metadata_path.write_text(
            json.dumps(checkpoint_info.to_dict(), indent=2),
            encoding="utf-8",
        )
        LOGGER.info(
            "Checkpoint saved: step=%d, loss=%s, path=%s",
            step,
            checkpoint_info.loss,
            checkpoint_dir,
        )
        if auto_cleanup:
            self.cleanup_old_checkpoints()
        return checkpoint_info

    def find_latest_checkpoint(self) -> Optional[CheckpointInfo]:
        checkpoints = self._list_checkpoints()
        if not checkpoints:
            LOGGER.info("No checkpoints found")
            return None
        latest = max(checkpoints, key=lambda checkpoint: checkpoint.step)
        LOGGER.info("Latest checkpoint: step=%d, path=%s", latest.step, latest.path)
        return latest

    def find_latest_training_dir(self) -> Optional[str]:
        """Latest checkpoint-* directory, with or without Cyrene metadata."""

        discovered = self.list_training_dirs()
        if not discovered:
            return None
        return discovered[0]

    def list_training_dirs(self) -> List[str]:
        if not self.output_dir.exists():
            return []
        entries = []
        for item in self.output_dir.iterdir():
            if not item.is_dir() or not item.name.startswith(self.CHECKPOINT_PREFIX):
                continue
            try:
                step = int(item.name.split("-", 1)[1])
            except (ValueError, IndexError):
                continue
            entries.append((step, str(item)))
        entries.sort(key=lambda item: item[0], reverse=True)
        return [path for _, path in entries]

    def validate_checkpoint(self, path: str) -> bool:
        checkpoint_path = Path(path)
        if not checkpoint_path.exists():
            LOGGER.warning("Checkpoint directory does not exist: %s", path)
            return False
        metadata_path = checkpoint_path / self.METADATA_FILE
        if not metadata_path.exists():
            LOGGER.warning("Checkpoint metadata does not exist: %s", metadata_path)
            return False
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            required_fields = ["path", "step", "epoch", "loss", "timestamp", "is_valid"]
            for required_field in required_fields:
                if required_field not in metadata:
                    LOGGER.warning("Checkpoint metadata missing field: %s", required_field)
                    return False
            LOGGER.info("Checkpoint validation passed: %s", path)
            return True
        except json.JSONDecodeError as exc:
            LOGGER.warning("Checkpoint metadata is invalid JSON: %s", exc)
            return False
        except Exception as exc:
            LOGGER.warning("Checkpoint validation failed: %s", exc)
            return False

    def validate_weights_or_metadata(self, path: str) -> bool:
        if self.validate_checkpoint(path):
            return True
        return find_checkpoint_weights_file(path) is not None

    def cleanup_old_checkpoints(self) -> List[str]:
        checkpoints = self._list_checkpoints()
        if len(checkpoints) <= self.save_total_limit:
            return []
        checkpoints.sort(key=lambda checkpoint: checkpoint.step)
        to_remove = checkpoints[: len(checkpoints) - self.save_total_limit]
        removed_paths: List[str] = []
        for checkpoint in to_remove:
            try:
                shutil.rmtree(checkpoint.path)
                removed_paths.append(checkpoint.path)
                LOGGER.info("Removed old checkpoint: %s", checkpoint.path)
            except Exception as exc:
                LOGGER.error("Failed to remove checkpoint %s: %s", checkpoint.path, exc)
        return removed_paths

    def _list_checkpoints(self) -> List[CheckpointInfo]:
        checkpoints: List[CheckpointInfo] = []
        if not self.output_dir.exists():
            return checkpoints
        for item in self.output_dir.iterdir():
            if not item.is_dir() or not item.name.startswith(self.CHECKPOINT_PREFIX):
                continue
            metadata_path = item / self.METADATA_FILE
            if not metadata_path.exists():
                LOGGER.debug("Skipping checkpoint without metadata: %s", item)
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                checkpoints.append(
                    CheckpointInfo(
                        path=metadata.get("path", str(item)),
                        step=metadata.get("step", 0),
                        epoch=metadata.get("epoch", 0.0),
                        loss=metadata.get("loss", float("inf")),
                        timestamp=metadata.get("timestamp", ""),
                        is_valid=metadata.get("is_valid", True),
                        metadata=metadata.get("metadata", {}),
                    )
                )
            except Exception as exc:
                LOGGER.debug("Unable to load checkpoint metadata %s: %s", item, exc)
        return checkpoints

    def load_checkpoint(self, path: str) -> Optional[Dict[str, Any]]:
        metadata_path = Path(path) / self.METADATA_FILE
        if not metadata_path.exists():
            LOGGER.warning("Checkpoint metadata does not exist: %s", metadata_path)
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            LOGGER.info("Checkpoint metadata loaded: %s", path)
            return metadata
        except Exception as exc:
            LOGGER.error("Failed to load checkpoint metadata: %s", exc)
            return None

    def collect_digest(self, path: Optional[str] = None) -> tuple[str, int, Optional[str]]:
        target = path or str(self.output_dir)
        digest, size = compute_checkpoint_digest(target)
        if digest:
            return digest, size, target
        latest = self.find_latest_training_dir()
        if latest:
            digest, size = compute_checkpoint_digest(latest)
            return digest, size, latest
        return "", 0, None


__all__ = ["CheckpointInfo", "CheckpointManager"]
