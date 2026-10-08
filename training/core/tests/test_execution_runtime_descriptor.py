"""
┌─────────────────────────────────────────────────────────────────────┐
│ Module: tests.test_execution_runtime_descriptor                     │
│ Role: Verify the Product-owned trainer runtime declaration.        │
│ 模块职责：验证 Product 所有的 trainer runtime 声明。                    │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
from pathlib import Path


def test_execution_runtime_descriptor_has_frozen_paths_and_profiles() -> None:
    repository = Path(__file__).resolve().parents[3]
    descriptor_path = repository / "execution-runtime.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))

    assert set(descriptor) == {
        "schema_version",
        "runtime_id",
        "source_root",
        "project_file",
        "lock_file",
        "bootstrap_script",
        "probe_script",
        "protocol_files",
        "profile",
        "platform_profile",
        "python_executable",
        "python_version",
        "uv_executable",
        "uv_version",
        "runtime_home_relative_path",
        "runtime_manifest_file",
        "runtime_arguments",
        "api_only_arguments",
    }
    assert descriptor["schema_version"] == 1
    assert descriptor["runtime_id"] == "yield-trainer"
    assert descriptor["source_root"] == "execution-runtime"
    assert descriptor["profile"] == "CYRENE_YIELD_TRAINER_V1_CUDA128"
    assert descriptor["platform_profile"] == "CYRENE_PLATFORM_RUNTIME_V1_LOCAL_GPU"
    assert descriptor["python_executable"] == "/opt/cyrene/python/3.12.14/bin/python3.12"
    assert descriptor["python_version"] == "3.12.14"
    assert descriptor["uv_executable"] == "/opt/cyrene/uv/0.12.21/uv"
    assert descriptor["uv_version"] == "0.12.21"
    assert descriptor["runtime_home_relative_path"] == "yield/trainer-runtime"
    assert descriptor["runtime_manifest_file"] == "runtime.json"
    assert descriptor["runtime_arguments"] == [
        "--runtime-config",
        "{platform_runtime_config}",
        "--trainer-runtime-config",
        "{trainer_runtime_config}",
    ]
    assert descriptor["api_only_arguments"] == ["--artifact-root", "{artifact_root}"]

    product_files = [
        descriptor["project_file"],
        descriptor["lock_file"],
        descriptor["bootstrap_script"],
        descriptor["probe_script"],
        *descriptor["protocol_files"],
    ]
    assert all((repository / relative_path).is_file() for relative_path in product_files)
    assert descriptor["protocol_files"] == sorted(set(descriptor["protocol_files"]))
    assert descriptor["protocol_files"] == [
        "training/core/src/cy_exec/training/executors/kernel-descriptor.json",
        "training/core/src/cy_exec/training/executors/kernel.desc",
        "training/core/src/cy_exec/training/executors/training_worker.py",
    ]
