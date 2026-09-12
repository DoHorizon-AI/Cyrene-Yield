"""Targeted Artifact Plane MVP tests."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_artifact_plane.py
# │ Module: training/core/tests/test_artifact_plane
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

import cy_artifacts as artifact_module
from cy_artifacts import (
    ArtifactIntegrityError,
    ArtifactKind,
    LocalArtifactProvider,
)
from cy_artifacts.local import LocalDirectoryFile, LocalDirectoryManifest
from cyrene_yield_contracts import YieldArtifactKind
from cy_exec.training.artifacts import publish_training_outputs
from cy_exec.training.contracts import EngineKind
from cy_exec.training.executors.workload_stager import MinimalWorkloadStager
from cy_exec.training.runtime import TrainingRuntime
from training_tck_helpers import make_spec


def test_same_file_content_is_idempotent_and_content_changes_identity(tmp_path):
    source = tmp_path / "payload.bin"
    source.write_bytes(b"same content")
    provider = LocalArtifactProvider(tmp_path / "store", chunk_size=3)

    first = provider.publish(source, kind=ArtifactKind.GENERIC)
    second = provider.publish(source, kind=ArtifactKind.GENERIC)
    assert first.uri == second.uri
    assert first.digest == second.digest
    assert provider.verify(first) is True

    source.write_bytes(b"changed content")
    changed = provider.publish(source, kind=ArtifactKind.GENERIC)
    assert changed.uri != first.uri
    assert changed.digest != first.digest


def test_digest_mismatch_is_fail_closed(tmp_path):
    source = tmp_path / "payload.bin"
    source.write_bytes(b"verified")
    provider = LocalArtifactProvider(tmp_path / "store")
    ref = provider.publish(source)
    resolved = provider.resolve(ref)
    resolved.location.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        provider.verify(ref)


def test_interrupted_directory_publish_has_no_committed_manifest(tmp_path, monkeypatch):
    source = tmp_path / "directory"
    source.mkdir()
    (source / "weights.bin").write_bytes(b"weights")
    provider = LocalArtifactProvider(tmp_path / "store")

    def interrupt(_manifest):
        raise RuntimeError("interrupted before manifest commit")

    monkeypatch.setattr(provider, "_commit_manifest", interrupt)
    with pytest.raises(RuntimeError, match="interrupted"):
        provider.publish(source, kind=YieldArtifactKind.MODEL)

    assert not list((provider.root / "manifests").rglob("*"))
    assert not list((provider.root / "tmp").iterdir())


def test_directory_manifest_resolve_and_stage_verifies_every_file(tmp_path):
    source = tmp_path / "model"
    (source / "nested").mkdir(parents=True)
    (source / "config.json").write_text('{"hidden": false}', encoding="utf-8")
    (source / "nested" / "weights.bin").write_bytes(b"weights")
    provider = LocalArtifactProvider(tmp_path / "store", chunk_size=2)

    ref = provider.publish(source, kind=YieldArtifactKind.MODEL, producer="test")
    resolved = provider.resolve(ref)
    assert ref.manifest_digest == ref.digest
    assert isinstance(resolved.manifest, LocalDirectoryManifest)
    assert [item.path for item in resolved.manifest.files] == ["config.json", "nested/weights.bin"]

    staged = provider.stage(ref, tmp_path / "worker" / "model")
    assert staged.verified_digest == ref.digest
    assert Path(staged.worker_visible_path, "config.json").read_text(encoding="utf-8") == '{"hidden": false}'
    assert Path(staged.local_path, "nested", "weights.bin").read_bytes() == b"weights"


def test_directory_identity_ignores_mtime_and_rejects_traversal(tmp_path):
    source = tmp_path / "model"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "weights.bin").write_bytes(b"weights")
    provider = LocalArtifactProvider(tmp_path / "store")

    first = provider.publish(source, kind=YieldArtifactKind.MODEL)
    os.utime(source / "nested" / "weights.bin", ns=(1_000_000_000, 1_000_000_000))
    second = provider.publish(source, kind=YieldArtifactKind.MODEL)

    assert first == second
    with pytest.raises(ValueError, match="relative"):
        LocalDirectoryFile(
            path="../escape.bin",
            digest="sha256:" + "0" * 64,
            size_bytes=0,
        )


def test_training_spec_publish_stage_and_worker_read(tmp_path):
    provider = LocalArtifactProvider(tmp_path / "store")
    (tmp_path / "job").mkdir()
    spec = make_spec(tmp_path / "job", EngineKind.LLAMA_FACTORY)
    staged = MinimalWorkloadStager(provider).stage_spec(
        spec,
        staging_dir=str(tmp_path / "stage"),
    )

    assert staged.config_ref.kind == YieldArtifactKind.TRAINING_SPEC.value
    assert Path(staged.worker_visible_path).name == "training-spec.json"
    assert Path(staged.worker_visible_path).parent.name == "config"
    assert staged.artifact_ref.uri.startswith("artifact://sha256/")
    assert staged.artifact_ref.uri not in staged.worker_visible_path
    assert Path(staged.worker_visible_path).read_text(encoding="utf-8") == json.dumps(
        spec.to_dict(), sort_keys=True, separators=(",", ":")
    )


def test_training_outputs_publish_to_artifact_refs(tmp_path):
    provider = LocalArtifactProvider(tmp_path / "store", chunk_size=3)
    (tmp_path / "job").mkdir()
    spec = make_spec(tmp_path / "job", EngineKind.LLAMA_FACTORY)
    output = Path(spec.output_dir)
    (output / "model").mkdir(parents=True, exist_ok=True)
    (output / "model" / "weights.bin").write_bytes(b"model")
    (output / "checkpoints").mkdir(parents=True, exist_ok=True)
    (output / "checkpoints" / "step.bin").write_bytes(b"checkpoint")
    (output / "metrics.json").write_text('{"loss": 0.1}', encoding="utf-8")
    (output / "run-manifest.json").write_text('{"run": "one"}', encoding="utf-8")
    from cy_exec.training.engines import get_engine

    launch = get_engine(EngineKind.LLAMA_FACTORY).compile(spec)

    assert launch.output_layout.root == ""
    published = publish_training_outputs(provider, launch)
    assert set(published) == {"model", "checkpoint", "metrics", "report"}
    assert all(ref.uri.startswith("artifact://sha256/") for ref in published.values())
    assert all(provider.verify(ref) for ref in published.values())


def test_runtime_publishes_outputs_without_kernel_upload(tmp_path):
    class CompletedExecutor:
        def start(self, launch):
            from cy_exec.training.executors.base import ProcessHandle

            return ProcessHandle(pid=1, argv=list(launch.argv), work_dir=launch.work_dir)

        def poll(self, _handle):
            return 0

        def read_new_output(self, _handle):
            return []

    provider = LocalArtifactProvider(tmp_path / "store")
    (tmp_path / "job").mkdir()
    spec = make_spec(tmp_path / "job", EngineKind.LLAMA_FACTORY)
    output = Path(spec.output_dir)
    (output / "model").mkdir(parents=True, exist_ok=True)
    (output / "model" / "weights.bin").write_bytes(b"model")

    runtime = TrainingRuntime(CompletedExecutor(), artifact_provider=provider)
    session = runtime.submit(spec)
    completed = runtime.poll(session.session_id)

    assert completed.result is not None
    assert completed.result.artifacts["model"].kind == YieldArtifactKind.MODEL


def test_artifact_core_does_not_import_training_modules():
    source_root = Path(artifact_module.__file__).parent
    for source in source_root.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("cy_exec.training") for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("cy_exec.training")
