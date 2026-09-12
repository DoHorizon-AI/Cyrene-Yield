"""CyreneKernelExecutor TCK: develop Kernel identity mapping, TEST ONLY in-process port."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_cyrene_kernel_executor.py
# │ Module: training/core/tests/test_cyrene_kernel_executor
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from cy_exec.training.contracts import (
    CheckpointSpec,
    DistributedSpec,
    EngineKind,
    FORBIDDEN_LAUNCH_ENV,
    TrainingLaunchSpec,
    TrainingStatus,
)
from cy_exec.training.contracts.launch import ResourceRequest
from cy_exec.training.engines import get_engine
from cy_exec.training.executors import CyreneKernelExecutor, KernelHostUnsupported, LocalProcessExecutor
from cy_exec.training.executors.kernel_commands import (
    DEFAULT_TRAINING_WORKER_EXECUTION_REF,
    assert_no_legacy_agent_contract,
    assert_start_worker_has_no_launch_argv,
)
from cy_exec.training.executors.kernel_events import (
    KERNEL_EVENT_KINDS,
    KernelLifecycleKind,
    TRAINING_TELEMETRY_KEYS,
    assert_not_kernel_event,
)
from cy_exec.training.executors.kernel_mapping import acquire_lease_command, start_worker_command
from cy_exec.training.executors.kernel_uds import UnixKernelAuthorityPort
from cy_exec.training.runtime import TrainingRuntime
from training_tck_helpers import make_spec

CHILD_TREE = """
import os
import subprocess
import sys
import time

child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
)
print(f"PARENT {os.getpid()}", flush=True)
print(f"CHILD {child.pid}", flush=True)
print('{"loss": 0.42, "step": 1, "epoch": 0}', flush=True)
time.sleep(60)
"""


def _kernel_executor() -> CyreneKernelExecutor:
    return CyreneKernelExecutor(test_inprocess=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil
    except ImportError:
        if os.name == "nt":
            import subprocess

            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in (result.stdout or "")
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    try:
        process = psutil.Process(pid)
        return process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False


def _launch(tmp_path: Path, *, gpu_count: int = 2, argv=None, sleep: bool = True) -> TrainingLaunchSpec:
    script = tmp_path / "job.py"
    if argv is None:
        if sleep:
            script.write_text(CHILD_TREE, encoding="utf-8")
            argv = [sys.executable, str(script)]
        else:
            argv = [sys.executable, "-c", "print('ok')"]
    return TrainingLaunchSpec(
        engine=EngineKind.LLAMA_FACTORY,
        argv=list(argv),
        work_dir=str(tmp_path),
        distributed=DistributedSpec.for_gpu_count(gpu_count),
        checkpoint=CheckpointSpec(output_dir=str(tmp_path / "ckpts")),
        resources=ResourceRequest(
            gpu_count=gpu_count,
            world_size=gpu_count,
            nnodes=1,
            nproc_per_node=gpu_count,
        ),
    )


def test_same_launch_spec_runs_on_both_executors(tmp_path):
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY, gpu_count=2)
    launch = get_engine(spec.engine).compile(spec)
    launch.assert_executor_agnostic()
    assert "CUDA_VISIBLE_DEVICES" not in launch.env
    assert not FORBIDDEN_LAUNCH_ENV.intersection(launch.env)
    assert launch.mounts
    assert launch.output_layout.model == "model"

    quick = TrainingLaunchSpec(
        engine=launch.engine,
        argv=[sys.executable, "-c", "print('executor-ok')"],
        work_dir=launch.work_dir,
        distributed=launch.distributed,
        checkpoint=launch.checkpoint,
        env=dict(launch.env),
        resources=launch.resources,
        mounts=list(launch.mounts),
        output_layout=launch.output_layout,
        spec_artifact_path=launch.spec_artifact_path,
    )
    local = LocalProcessExecutor()
    kernel = _kernel_executor()
    local_handle = local.start(quick)
    assert local.wait(local_handle, timeout=10) == 0
    kernel_handle = kernel.start(quick)
    assert kernel.wait(kernel_handle, timeout=20) == 0
    assert kernel_handle.extra.get("worker_id")
    assert kernel_handle.extra.get("start_operation_id") or kernel_handle.extra.get("operation_id")
    assert kernel_handle.extra.get("lease_id")
    assert kernel_handle.extra.get("fence_token") == 1
    assert kernel_handle.extra.get("resource_ids") == ["GPU-UUID-0", "GPU-UUID-1"]
    assert kernel_handle.extra.get("principal_id")
    assert kernel_handle.extra.get("execution_ref") == DEFAULT_TRAINING_WORKER_EXECUTION_REF
    kinds = {item.get("kind") for item in kernel_handle.extra.get("operations") or []}
    assert "worker.start" in kinds
    assert "worker.configure" in kinds
    assert "worker.invoke" in kinds
    settings = kernel_handle.extra.get("plugin_configure") or {}
    assert "workload_config_ref" in settings
    assert "control_plane_path" not in settings
    assert "CUDA_VISIBLE_DEVICES" not in settings


def test_one_lease_holds_n_resource_identities(tmp_path):
    launch = _launch(tmp_path, gpu_count=3, sleep=False)
    executor = _kernel_executor()
    handle = executor.start(launch)
    assert executor.wait(handle, timeout=10) == 0
    assert handle.extra["lease_id"]
    assert handle.extra["resource_ids"] == ["GPU-UUID-0", "GPU-UUID-1", "GPU-UUID-2"]
    acquire = executor.port.last_commands[0]
    assert acquire["rpc"] == "AcquireLease"
    assert acquire["query"]["count"] == 3
    start = next(item for item in executor.port.last_commands if item.get("rpc") == "StartWorker")
    assert_start_worker_has_no_launch_argv(start)
    assert "argv" not in start
    assert start["worker"]["lease"]["id"] == handle.extra["lease_id"]
    assert any(item.get("payload") == "Configure" for item in executor.port.last_commands)
    assert any(item.get("payload") == "Invoke" for item in executor.port.last_commands)


def test_kernel_does_not_generate_cuda_visibility(tmp_path):
    launch = _launch(tmp_path, gpu_count=2)
    assert "CUDA_VISIBLE_DEVICES" not in launch.env
    executor = _kernel_executor()
    handle = executor.start(launch)
    try:
        assigned = handle.extra.get("assigned_env") or {}
        assert "CUDA_VISIBLE_DEVICES" not in assigned
        assert "NVIDIA_VISIBLE_DEVICES" not in assigned
        kinds = {event.kind for event in executor.port.lifecycle_events()}
        assert KernelLifecycleKind.WORKER_STARTED in kinds
    finally:
        executor.cancel(handle, timeout=20)


def test_nnodes_greater_than_one_is_rejected(tmp_path):
    launch = _launch(tmp_path, gpu_count=1, sleep=False)
    launch.resources.nnodes = 2
    executor = _kernel_executor()
    with pytest.raises(ValueError, match="1 node"):
        executor.start(launch)


def test_kernel_cancel_kills_tree_then_releases_leases(tmp_path):
    launch = _launch(tmp_path, gpu_count=2)
    executor = _kernel_executor()
    handle = executor.start(launch)
    child_pid = None
    deadline = time.time() + 10
    while time.time() < deadline:
        for line in executor.read_new_output(handle):
            if line.startswith("CHILD "):
                child_pid = int(line.split()[1])
        if child_pid:
            break
        time.sleep(0.1)
    assert child_pid is not None
    assert _pid_alive(handle.pid)
    assert not executor.port.leases_released(handle)

    outcome = executor.cancel(handle, timeout=20)
    assert outcome.stopped, outcome.message
    assert outcome.cleanup_confirmed
    assert outcome.leases_released
    time.sleep(0.3)
    assert not _pid_alive(handle.pid)
    assert not _pid_alive(child_pid)
    assert executor.port.leases_released(handle)
    kinds = {event.kind.value for event in executor.port.lifecycle_events()}
    assert "Cancelled" in kinds
    assert "LeaseReleased" in kinds
    rpcs = {item.get("rpc") for item in executor.port.last_commands}
    assert "CancelOperation" in rpcs
    assert "StopWorker" in rpcs


def test_worker_lost_maps_to_attempt_not_run_success(tmp_path):
    launch = _launch(tmp_path, gpu_count=1)
    executor = _kernel_executor()

    class FakeAdapter:
        kind = EngineKind.LLAMA_FACTORY

        def validate(self, spec):
            from cy_exec.training.contracts import EngineValidation

            return EngineValidation(ok=True)

        def compile(self, spec):
            return launch

        def parse_event(self, line):
            from cy_exec.training.contracts import TrainingEvent, TrainingEventKind

            if "loss" in line:
                return TrainingEvent(kind=TrainingEventKind.PROGRESS, message=line, loss=0.42)
            return None

        def collect_result(self, spec, compiled, exit_code, status):
            from cy_exec.training.contracts import TrainingResult

            return TrainingResult(status=status, output_dir=spec.output_dir)

        def inspect(self):
            raise AssertionError("unused")

    from cy_exec.training import engines as engines_mod
    from cy_exec.training.contracts import DatasetRef, ModelRef, TrainingSpec

    original = engines_mod._ADAPTERS[EngineKind.LLAMA_FACTORY]
    engines_mod._ADAPTERS[EngineKind.LLAMA_FACTORY] = FakeAdapter()
    try:
        spec = TrainingSpec(
            engine=EngineKind.LLAMA_FACTORY,
            model=ModelRef(path="org/tiny-test-model"),
            dataset=DatasetRef(path=str(tmp_path / "unused.jsonl")),
            output_dir=str(tmp_path / "out"),
        )
        Path(spec.output_dir).mkdir(parents=True, exist_ok=True)
        runtime = TrainingRuntime(executor=executor)
        session = runtime.submit(spec)
        assert session.status == TrainingStatus.RUNNING
        assert session.current_attempt is not None
        assert session.handle is not None
        binding = session.current_attempt.binding
        assert binding.lease_id
        assert binding.resource_ids == ["GPU-UUID-0"]
        assert binding.fence_token == 1
        executor.port.mark_worker_lost(session.handle)
        polled = runtime.poll(session.session_id)
        assert polled.current_attempt.status == TrainingStatus.LOST
        assert polled.status == TrainingStatus.AWAITING_RETRY
        assert polled.status != TrainingStatus.COMPLETED
        assert not executor.port.leases_released(session.handle)
        executor.cancel(session.handle, timeout=20)
        retried = runtime.retry(session.session_id)
        assert retried.status == TrainingStatus.RUNNING
        assert retried.current_attempt.ordinal == 2
        runtime.cancel(session.session_id, timeout=20)
    finally:
        engines_mod._ADAPTERS[EngineKind.LLAMA_FACTORY] = original


def test_training_telemetry_does_not_enter_kernel_events(tmp_path):
    with pytest.raises(ValueError, match="telemetry"):
        assert_not_kernel_event({"loss": 0.1, "step": 3})
    launch = _launch(tmp_path, gpu_count=1)
    executor = _kernel_executor()
    handle = executor.start(launch)
    try:
        deadline = time.time() + 10
        saw_loss = False
        while time.time() < deadline:
            lines = executor.read_new_output(handle)
            if any("loss" in line for line in lines):
                saw_loss = True
                break
            time.sleep(0.1)
        assert saw_loss
        for event in executor.port.lifecycle_events():
            overlap = TRAINING_TELEMETRY_KEYS.intersection(event.payload)
            assert not overlap, event.to_dict()
            assert event.kind.value in KERNEL_EVENT_KINDS
        assert executor.port.output_channel().lines
    finally:
        executor.cancel(handle, timeout=20)


def test_output_descriptor_contract(tmp_path):
    launch = _launch(tmp_path, gpu_count=1, sleep=False)
    executor = _kernel_executor()
    handle = executor.start(launch)
    assert executor.wait(handle, timeout=10) == 0
    outputs = executor.collect_outputs(launch)
    normalized = outputs["model_dir"].replace("\\", "/")
    assert normalized.endswith("output/model")
    assert Path(outputs["manifest_path"]).is_file()
    assert Path(outputs["metrics_path"]).is_file()
    assert outputs["artifacts"]


def test_production_executor_does_not_default_to_inprocess():
    if os.name == "nt" or sys.platform.startswith("win"):
        with pytest.raises(KernelHostUnsupported, match="Unix-only"):
            CyreneKernelExecutor()
    else:
        with pytest.raises(Exception, match="CYRENE_KERNEL_AUTHORITY_SOCKET|Unix-only"):
            CyreneKernelExecutor()


def test_typed_start_worker_rejects_argv_and_legacy_markers():
    from cy_exec.training.executors.kernel_mapping import AllocationSet

    allocation = AllocationSet(
        node_id="n1",
        lease_id="lease/1",
        fence_token=9,
        resource_ids=["GPU-UUID-A", "GPU-UUID-C"],
        lease_generation=2,
    )
    command = start_worker_command(
        worker_id="worker/1",
        principal_id="principal/1",
        allocation=allocation,
        execution_ref=DEFAULT_TRAINING_WORKER_EXECUTION_REF,
    ).to_dict()
    assert_start_worker_has_no_launch_argv(command)
    acquire = acquire_lease_command(
        ResourceRequest(gpu_count=2, nnodes=1),
        holder_id="worker/1",
    ).to_dict()
    assert acquire["query"]["count"] == 2
    with pytest.raises(ValueError, match="legacy"):
        assert_no_legacy_agent_contract({"rpc": "ExecuteCommandStream"})


def test_unix_port_cancel_without_confirmation_is_not_cancelled():
    if os.name == "nt" or sys.platform.startswith("win"):
        with pytest.raises(KernelHostUnsupported):
            UnixKernelAuthorityPort()
        return
    os.environ["CYRENE_KERNEL_AUTHORITY_SOCKET"] = "/tmp/cyrene-kernel-not-verified.sock"
    try:
        port = UnixKernelAuthorityPort()
        from cy_exec.training.executors.base import ProcessHandle

        outcome = port.cancel(
            ProcessHandle(pid=-1, argv=[], work_dir=".", extra={"worker_id": "w", "lease_id": "l"}),
            timeout=1,
        )
        assert not outcome.stopped
        assert not outcome.cleanup_confirmed
        assert not outcome.leases_released
    finally:
        os.environ.pop("CYRENE_KERNEL_AUTHORITY_SOCKET", None)
