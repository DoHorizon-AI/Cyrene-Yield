"""Trainer runtime version and protocol probe regressions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).parents[1] / "probe.py"
SPEC = importlib.util.spec_from_file_location("cyrene_trainer_probe", MODULE)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def test_version_probe_rejects_missing_required_package(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_package: str) -> str:
        raise probe.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(probe.importlib.metadata, "version", missing)

    with pytest.raises(ValueError, match="TRAINER_PACKAGE_MISSING"):
        probe._versions()


def test_protocol_probe_requires_all_worker_services(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    location = root / "training/core/src/cy_exec/training/executors"
    location.mkdir(parents=True)
    (location / "kernel.desc").write_bytes(b"")
    (location / "kernel-descriptor.json").write_text("{}")
    (location / "training_worker.py").write_text("pass\n")

    with pytest.raises(ValueError, match="TRAINER_PROTOCOL_INCOMPATIBLE"):
        probe._protocol(root)
