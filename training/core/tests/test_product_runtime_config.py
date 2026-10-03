"""Canonical Platform and trainer runtime manifest consumption tests.

读取规范 Platform 与 trainer runtime manifest 的测试。
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from cy_exec.training.product_cli import _runtime_from_manifests


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def test_runtime_manifests_replace_individual_topology_paths(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    installations = tmp_path / "installations"
    artifacts.mkdir()
    installations.mkdir()
    key = tmp_path / "installer.key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    trainer = tmp_path / "trainer-python"
    trainer.write_text("#!/bin/sh\n")
    trainer.chmod(0o700)
    kernel_socket = tmp_path / "kernel.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(kernel_socket))
    platform_manifest = tmp_path / "platform.json"
    trainer_manifest = tmp_path / "trainer.json"
    _write(
        platform_manifest,
        {
            "schemaVersion": 1,
            "profile": "CYRENE_PLATFORM_RUNTIME_V1_LOCAL_GPU",
            "runtimeMode": "NATIVE_LINUX_PROFILE",
            "status": "READY",
            "artifactRoot": str(artifacts),
            "installationsRoot": str(installations),
            "signingKeyFile": str(key),
            "kernel": {"socket": str(kernel_socket)},
            "components": {"kernel": {"status": "READY"}},
            "host": {"gpuRuntime": "NATIVE_LINUX_CUDA", "hardIsolation": True},
        },
    )
    _write(
        trainer_manifest,
        {
            "schemaVersion": 1,
            "profile": "CYRENE_YIELD_TRAINER_V1_CUDA128",
            "status": "READY",
            "python": str(trainer),
        },
    )
    try:
        artifact_root, configuration = _runtime_from_manifests(
            state_directory=tmp_path / "state",
            runtime_config=platform_manifest,
            trainer_runtime_config=trainer_manifest,
        )
    finally:
        listener.close()

    assert artifact_root == artifacts
    assert configuration.socket == kernel_socket
    assert configuration.python == trainer
    assert not configuration.allow_wsl_shared_device


def test_runtime_manifest_fails_closed_when_kernel_is_down(tmp_path: Path) -> None:
    platform_manifest = tmp_path / "platform.json"
    trainer_manifest = tmp_path / "trainer.json"
    _write(
        platform_manifest,
        {
            "schemaVersion": 1,
            "profile": "CYRENE_PLATFORM_RUNTIME_V1_LOCAL_GPU",
            "status": "READY",
            "components": {"kernel": {"status": "DOWN"}},
        },
    )
    _write(
        trainer_manifest,
        {
            "schemaVersion": 1,
            "profile": "CYRENE_YIELD_TRAINER_V1_CUDA128",
            "status": "READY",
        },
    )

    with pytest.raises(ValueError, match="RUNTIME_COMPONENT_UNAVAILABLE"):
        _runtime_from_manifests(
            state_directory=tmp_path / "state",
            runtime_config=platform_manifest,
            trainer_runtime_config=trainer_manifest,
        )
