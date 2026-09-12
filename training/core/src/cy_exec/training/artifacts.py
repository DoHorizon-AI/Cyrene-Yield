"""Training consumer adapter for publishing output candidates."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/artifacts.py
# │ Module: training/core/src/cy_exec/training/artifacts
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from cy_artifacts import ArtifactKind, ArtifactProvider, ArtifactRef
from cyrene_yield_contracts import YieldArtifactKind
from .contracts.artifacts import ArtifactCandidate, layout_paths
from .contracts.launch import TrainingLaunchSpec


def output_candidates(launch: TrainingLaunchSpec) -> List[ArtifactCandidate]:
    descriptor = layout_paths(launch.work_dir, launch.output_layout)
    candidates: List[ArtifactCandidate] = []
    seen: set[str] = set()
    checkpoint_output = Path(launch.checkpoint.output_dir) if launch.checkpoint.output_dir else None
    checkpoint_paths = [Path(descriptor.checkpoint_dir)]
    if checkpoint_output is not None and not _same_path(checkpoint_output, Path(descriptor.output_root)):
        checkpoint_paths.append(checkpoint_output)
    paths_and_kinds = [
        (descriptor.model_dir, YieldArtifactKind.MODEL),
        (descriptor.metrics_path, YieldArtifactKind.METRICS),
        (descriptor.manifest_path, YieldArtifactKind.REPORT),
    ]
    paths_and_kinds[1:1] = [(str(path), YieldArtifactKind.CHECKPOINT) for path in checkpoint_paths]
    for path, kind in paths_and_kinds:
        path_text = str(path)
        if path_text in seen:
            continue
        seen.add(path_text)
        candidate_path = Path(path_text)
        if not _has_content(candidate_path):
            continue
        candidates.append(ArtifactCandidate(path=path_text, kind=kind.value))
    return candidates


def publish_candidate(
    candidate: ArtifactCandidate,
    provider: ArtifactProvider,
    *,
    producer: str = "cyrene-yield.training",
) -> ArtifactRef:
    ref = provider.publish(
        candidate.path,
        kind=ArtifactKind(candidate.kind),
        producer=producer,
    )
    candidate.digest = ref.digest
    candidate.size_bytes = ref.size_bytes
    candidate.artifact_ref = ref
    return ref


def publish_training_outputs(
    provider: ArtifactProvider,
    launch: TrainingLaunchSpec,
) -> Dict[str, ArtifactRef]:
    published: Dict[str, ArtifactRef] = {}
    for candidate in output_candidates(launch):
        ref = publish_candidate(candidate, provider)
        published[candidate.kind] = ref
    for checkpoint in sorted(Path(launch.work_dir).glob("checkpoint-*")):
        if checkpoint.is_dir() and not checkpoint.is_symlink():
            published[checkpoint.name] = provider.publish_portable_directory(
                checkpoint, kind=ArtifactKind(YieldArtifactKind.CHECKPOINT)
            )
    return published


def _has_content(path: Path) -> bool:
    if path.is_file():
        return True
    if not path.is_dir():
        return False
    return any(item.is_file() for item in path.rglob("*"))


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()


__all__ = ["output_candidates", "publish_candidate", "publish_training_outputs"]
