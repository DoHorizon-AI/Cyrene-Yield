"""Stage 3B: generic workload config + shared training worker control."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_workload_control.py
# │ Module: training/core/tests/test_workload_control
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cy_exec.training.contracts import (
    EngineKind,
    TrainingStatus,
    WorkloadConfigRef,
    assert_configure_is_not_training_spec,
)
from cy_exec.training.contracts.workload import WorkloadConfigureSettings
from cy_exec.training.executors.plugin_control import (
    PLUGIN_INVOKE_CANCEL_SUPPORTED,
    PluginConfigure,
    configure_from_workload,
)
from cy_exec.training.executors.workload_stager import MinimalWorkloadStager
from cy_exec.training.worker.cli import _run_workload
from training_tck_helpers import make_spec


def test_configure_settings_are_not_training_spec(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)
    staged = MinimalWorkloadStager().stage_spec(spec, staging_dir=str(tmp_path / "stage"))
    settings = WorkloadConfigureSettings(
        workload_config_ref=staged.config_ref,
        worker_config_path=staged.worker_visible_path,
        output_root=str(tmp_path / "out"),
        attempt_id="a1",
        execution_id="e1",
    ).to_settings_map()
    assert_configure_is_not_training_spec(settings)
    assert "control_plane_path" not in settings
    assert staged.control_plane_path not in settings.values()
    assert settings["worker_config_path"] != staged.control_plane_path
    ref = WorkloadConfigRef.from_dict(json.loads(settings["workload_config_ref"]))
    assert ref.digest.startswith("sha256:")
    assert ref.uri.startswith("artifact://sha256/")
    assert staged.artifact_ref.uri == ref.uri
    with pytest.raises(ValueError, match="TrainingSpec"):
        assert_configure_is_not_training_spec({"model": "x", "workload_config_ref": "{}"})


def test_stager_separates_control_plane_and_worker_paths(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)
    staged = MinimalWorkloadStager().stage_spec(spec, staging_dir=str(tmp_path / "stage"))
    assert Path(staged.control_plane_path).is_file()
    assert Path(staged.worker_visible_path).is_file()
    assert staged.worker_visible_path != staged.control_plane_path
    assert staged.config_ref.schema == "cyrene.training.spec"


def test_plugins_owned_engine_dispatches_inside_worker(tmp_path, monkeypatch):
    seen = []

    class RecordingExecutor:
        def start(self, launch, assigned_env=None):
            seen.append(launch.engine)
            from cy_exec.training.executors.base import ProcessHandle

            return ProcessHandle(pid=1, argv=list(launch.argv), work_dir=launch.work_dir)

        def wait(self, handle, timeout=None):
            return 0

    monkeypatch.setattr("cy_exec.training.worker.cli.LocalProcessExecutor", lambda: RecordingExecutor())
    kind = EngineKind.LLAMA_FACTORY
    directory = tmp_path / kind.value
    directory.mkdir(parents=True, exist_ok=True)
    spec = make_spec(directory, kind)

    code = _run_workload(spec.to_dict(), str(tmp_path / kind.value / "out"))

    assert code == 0
    assert seen == [EngineKind.LLAMA_FACTORY]


def test_plugin_configure_envelope_carries_fence(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)
    staged = MinimalWorkloadStager().stage_spec(spec, staging_dir=str(tmp_path / "stage"))
    settings = WorkloadConfigureSettings(
        workload_config_ref=staged.config_ref,
        worker_config_path=staged.worker_visible_path,
        output_root=str(tmp_path),
        attempt_id="a1",
        execution_id="e1",
    )
    envelope = configure_from_workload(settings, request_id="cfg-1", generation=4, fence_token=9)
    assert envelope.to_dict()["payload"] == "Configure"
    assert envelope.generation == 4
    assert envelope.fence_token == 9
    assert PLUGIN_INVOKE_CANCEL_SUPPORTED is True
