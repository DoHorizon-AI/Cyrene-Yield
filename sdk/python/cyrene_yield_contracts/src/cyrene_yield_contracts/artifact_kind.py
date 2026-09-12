"""Yield-owned artifact categories carried through generic Platform ArtifactRef."""

from enum import StrEnum


class YieldArtifactKind(StrEnum):
    """Artifact categories whose meaning is owned by Yield. | Yield 领域制品类别。"""

    GENERIC = "generic"
    MODEL = "model"
    DATASET = "dataset"
    CHECKPOINT = "checkpoint"
    TRAINING_SPEC = "training_spec"
    METRICS = "metrics"
    REPORT = "report"


__all__ = ["YieldArtifactKind"]
