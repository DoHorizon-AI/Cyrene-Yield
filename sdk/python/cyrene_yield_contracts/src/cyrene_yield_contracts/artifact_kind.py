"""Yield-owned artifact categories carried through generic Platform ArtifactRef.

由 Yield 拥有、通过通用 Platform ArtifactRef 携带的制品类别。
"""

from enum import StrEnum


class YieldArtifactKind(StrEnum):
    """Artifact categories whose meaning is owned by Yield. | 语义由 Yield 所有的 Artifact 类别。"""

    GENERIC = "generic"
    MODEL = "model"
    DATASET = "dataset"
    CHECKPOINT = "checkpoint"
    TRAINING_SPEC = "training_spec"
    METRICS = "metrics"
    REPORT = "report"


__all__ = ["YieldArtifactKind"]
