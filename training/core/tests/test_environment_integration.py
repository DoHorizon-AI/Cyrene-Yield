# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_environment_integration.py
# │ 中文：文件：training/core/tests/test_environment_integration.py
# │ Module: training/core/tests/test_environment_integration
# │ 模块：training/core/tests/test_environment_integration
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │ 职责：Yield 核心测试模块，验证统一训练 runtime 与契约。
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import ast
import sys
from pathlib import Path

from cy_exec.training.contracts import EngineKind, TrainingStatus
from cy_exec.training.environment import EnvironmentCandidate, EnvironmentSpec
from cy_exec.training.executors.base import ProcessHandle
from cy_exec.training.runtime import TrainingRuntime
from training_tck_helpers import make_spec


class CompletedExecutor:
    def start(self, launch):
        return ProcessHandle(pid=1, argv=list(launch.argv), work_dir=launch.work_dir)

    def poll(self, _handle):
        return None

    def read_new_output(self, _handle):
        return []


def test_training_resolves_and_records_environment_lock(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    spec = make_spec(job_dir, EngineKind.LLAMA_FACTORY)
    spec.environment = EnvironmentSpec(
        runtime_profile="local",
        python_version_constraint=">=3.11",
        engine=EngineKind.LLAMA_FACTORY.value,
    )
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    candidate = EnvironmentCandidate(
        candidate_id="local-known",
        runtime_profile="local",
        python_version=python_version,
        engine=EngineKind.LLAMA_FACTORY.value,
        resolution_provenance="test-local-catalog",
    )
    runtime = TrainingRuntime(CompletedExecutor(), environment_catalog=[candidate])

    session = runtime.submit(spec)

    assert session.status is TrainingStatus.RUNNING
    assert session.launch is not None
    assert session.launch.environment_lock is not None
    lock = session.launch.environment_lock
    assert lock.is_resolved
    assert session.current_attempt is not None
    assert session.current_attempt.launch.environment_lock is lock
    assert session.current_attempt.to_dict()["environment_lock_digest"] == lock.environment_digest
    assert session.launch.to_dict()["environment_lock"]["environment_digest"] == lock.environment_digest


def test_engine_adapters_do_not_own_environment_resolution():
    engines_root = Path(__file__).resolve().parents[1] / "src" / "cy_exec" / "training" / "engines"
    for source in engines_root.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("cy_exec.training.environment") for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in {"cy_exec.training.environment", "cy_exec.training.environment.resolver"}
