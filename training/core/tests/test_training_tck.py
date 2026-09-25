"""Training Engine TCK for the Plugins-owned adapter and Product status authority.

面向 Plugins 所有适配器与 Product 状态权威的 Training Engine TCK。
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_training_tck.py
# │ 中文：文件：training/core/tests/test_training_tck.py
# │ Module: training/core/tests/test_training_tck
# │ 模块：training/core/tests/test_training_tck
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │ 职责：Yield 核心测试模块，验证统一训练 runtime 与契约。
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import pytest
from cy_exec.training.contracts import FORBIDDEN_LAUNCH_ENV, EngineKind, TrainingStatus
from cy_exec.training.engines import get_engine
from cy_exec.training.runtime import TrainingRuntime
from training_tck_helpers import make_spec

ENGINES = [EngineKind.LLAMA_FACTORY]


@pytest.mark.parametrize("engine_kind", ENGINES)
def test_same_spec_compiles_for_each_engine(tmp_path, engine_kind):
    spec = make_spec(tmp_path, engine_kind, gpu_count=2)
    adapter = get_engine(engine_kind)
    validation = adapter.validate(spec)
    assert validation.ok, [issue.to_dict() for issue in validation.issues]
    launch = adapter.compile(spec)
    launch.assert_executor_agnostic()
    assert launch.engine == engine_kind
    assert launch.distributed.world_size == 2
    assert launch.distributed.nproc_per_node == 2
    assert "CUDA_VISIBLE_DEVICES" not in launch.env
    assert not FORBIDDEN_LAUNCH_ENV.intersection(launch.env)
    assert launch.argv
    assert launch.spec_artifact_path


def test_compiled_backend_is_plugins_owned_llama_factory(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)
    launch = get_engine(EngineKind.LLAMA_FACTORY).compile(spec)

    assert "llamafactory" in " ".join(launch.argv).lower()
    assert launch.engine is EngineKind.LLAMA_FACTORY


def test_adapters_do_not_own_product_job_status(tmp_path):
    for engine_kind in ENGINES:
        adapter = get_engine(engine_kind)
        assert not hasattr(adapter, "_jobs")
        assert not hasattr(adapter, "cancel_job")
        spec = make_spec(tmp_path, engine_kind)
        launch = adapter.compile(spec)
        result = adapter.collect_result(spec, launch, 0, TrainingStatus.COMPLETED)
        assert result.status == TrainingStatus.COMPLETED


def test_runtime_is_the_status_authority(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)
    spec.dataset.path = str(tmp_path / "does-not-exist.jsonl")
    runtime = TrainingRuntime()
    session = runtime.submit(spec)
    assert session.status == TrainingStatus.FAILED
    assert runtime.get(session.session_id) is session
    assert get_engine(spec.engine).__class__.__name__.endswith("Adapter")


def test_runtime_without_platform_execution_fails_closed(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)
    runtime = TrainingRuntime()

    session = runtime.submit(spec)

    assert session.status == TrainingStatus.FAILED
    assert session.error.startswith("YIELD_EXECUTION_NOT_CONFIGURED")
