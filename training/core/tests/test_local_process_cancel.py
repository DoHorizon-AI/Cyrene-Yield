"""Cancel must stop the real process tree, not only flip a status field."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_local_process_cancel.py
# │ Module: training/core/tests/test_local_process_cancel
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
    TrainingLaunchSpec,
    TrainingStatus,
)
from cy_exec.training.contracts.launch import ResourceRequest
from cy_exec.training.executors import LocalProcessExecutor
from cy_exec.training.runtime import TrainingRuntime

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
time.sleep(60)
"""


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


def test_local_process_cancel_kills_child_tree(tmp_path):
    script = tmp_path / "child_tree.py"
    script.write_text(CHILD_TREE, encoding="utf-8")
    launch = TrainingLaunchSpec(
        engine=EngineKind.LLAMA_FACTORY,
        argv=[sys.executable, str(script)],
        work_dir=str(tmp_path),
        distributed=DistributedSpec.single_process(),
        checkpoint=CheckpointSpec(output_dir=str(tmp_path)),
        resources=ResourceRequest(gpu_count=1, world_size=1, nnodes=1, nproc_per_node=1),
    )
    executor = LocalProcessExecutor()
    handle = executor.start(launch)
    child_pid = None
    deadline = time.time() + 10
    while time.time() < deadline:
        lines = executor.read_new_output(handle)
        for line in lines:
            if line.startswith("CHILD "):
                child_pid = int(line.split()[1])
        if child_pid:
            break
        time.sleep(0.1)
    assert child_pid is not None, "child pid was not reported"
    assert _pid_alive(handle.pid)
    assert _pid_alive(child_pid)

    outcome = executor.cancel(handle, timeout=20)
    assert outcome.stopped, outcome.message
    time.sleep(0.3)
    assert not _pid_alive(handle.pid), f"parent {handle.pid} still alive"
    assert not _pid_alive(child_pid), f"child {child_pid} still alive"
    assert executor.poll(handle) is not None


def test_runtime_cancel_requires_process_exit(tmp_path):
    script = tmp_path / "sleeper.py"
    script.write_text("import time; time.sleep(60)\n", encoding="utf-8")

    class FakeAdapter:
        kind = EngineKind.LLAMA_FACTORY

        def inspect(self):
            raise AssertionError("inspect unused")

        def validate(self, spec):
            from cy_exec.training.contracts import EngineValidation

            return EngineValidation(ok=True)

        def compile(self, spec):
            return TrainingLaunchSpec(
                engine=spec.engine,
                argv=[sys.executable, str(script)],
                work_dir=spec.output_dir,
                distributed=spec.distributed,
                checkpoint=spec.checkpoint,
                resources=ResourceRequest.from_distributed(spec.distributed),
            )

        def parse_event(self, line):
            return None

        def collect_result(self, spec, launch, exit_code, status):
            from cy_exec.training.contracts import TrainingResult

            return TrainingResult(status=status, output_dir=spec.output_dir, exit_code=exit_code)

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
        runtime = TrainingRuntime(executor=LocalProcessExecutor())
        session = runtime.submit(spec)
        assert session.status == TrainingStatus.RUNNING
        assert session.handle is not None
        pid = session.handle.pid
        assert _pid_alive(pid)
        cancelled = runtime.cancel(session.session_id, timeout=20)
        assert cancelled.status == TrainingStatus.CANCELLED
        time.sleep(0.3)
        assert not _pid_alive(pid)
    finally:
        engines_mod._ADAPTERS[EngineKind.LLAMA_FACTORY] = original


def test_runtime_lost_when_cancel_cannot_stop(tmp_path):
    from cy_exec.training.contracts import DatasetRef, ModelRef, TrainingSpec, EngineValidation, TrainingResult
    from cy_exec.training.executors.base import CancelOutcome, ProcessHandle

    class StuckExecutor:
        def start(self, launch):
            return ProcessHandle(pid=999999, argv=launch.argv, work_dir=launch.work_dir)

        def poll(self, handle):
            return None

        def wait(self, handle, timeout=None):
            return None

        def cancel(self, handle, timeout=15.0):
            return CancelOutcome(stopped=False, remaining_pids=(handle.pid,), message="still running")

        def read_new_output(self, handle):
            return []

    class FakeAdapter:
        kind = EngineKind.LLAMA_FACTORY

        def validate(self, spec):
            return EngineValidation(ok=True)

        def compile(self, spec):
            return TrainingLaunchSpec(
                engine=spec.engine,
                argv=[sys.executable, "-c", "pass"],
                work_dir=spec.output_dir,
                distributed=spec.distributed,
                checkpoint=spec.checkpoint,
                resources=ResourceRequest.from_distributed(spec.distributed),
            )

        def parse_event(self, line):
            return None

        def collect_result(self, spec, launch, exit_code, status):
            return TrainingResult(status=status, output_dir=spec.output_dir)

        def inspect(self):
            raise AssertionError("unused")

    from cy_exec.training import engines as engines_mod

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
        runtime = TrainingRuntime(executor=StuckExecutor())
        session = runtime.submit(spec)
        lost = runtime.cancel(session.session_id)
        assert lost.status == TrainingStatus.AWAITING_RETRY
        assert lost.current_attempt is not None
        assert lost.current_attempt.status == TrainingStatus.LOST
        assert lost.result is not None
        assert lost.result.status == TrainingStatus.LOST
    finally:
        engines_mod._ADAPTERS[EngineKind.LLAMA_FACTORY] = original
