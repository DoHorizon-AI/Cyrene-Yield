"""Generic Cyrene training worker wrapper.

Kernel starts this process via execution_ref / LaunchPlan. It does not receive
TrainingLaunchSpec.argv from StartWorker. After Configure + Invoke it loads the
immutable WorkloadConfigRef document and dispatches EngineKind internally.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/worker/cli.py
# │ Module: training/core/src/cy_exec/training/worker/cli
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..contracts.spec import TrainingSpec
from ..contracts.workload import WorkloadConfigureSettings, assert_configure_is_not_training_spec
from ..executors.local_process import LocalProcessExecutor
from ..executors.workload_stager import verify_worker_config


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _wait_file(path: Path, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return path.read_text(encoding="utf-8")
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {path}")


def _fence_ok(generation: int, fence_token: int) -> bool:
    active_gen = int(os.environ.get("CYRENE_GENERATION") or "0")
    active_fence = int(os.environ.get("CYRENE_FENCE_TOKEN") or "0")
    if generation < active_gen or (generation == active_gen and fence_token < active_fence):
        return False
    return True


def _run_workload(document: Dict[str, Any], output_root: str) -> int:
    from ..engines import get_engine

    if "model" in document and "dataset" in document:
        spec = TrainingSpec.from_dict(document)
        launch = get_engine(spec.engine).compile(spec)
    elif "argv" in document:
        from ..contracts.launch import TrainingLaunchSpec
        from ..contracts.status import EngineKind
        from ..contracts.checkpoint import CheckpointSpec
        from ..contracts.distributed import DistributedSpec

        launch = TrainingLaunchSpec(
            engine=EngineKind(document.get("engine") or EngineKind.LLAMA_FACTORY.value),
            argv=list(document["argv"]),
            work_dir=document.get("work_dir") or output_root,
            distributed=DistributedSpec.from_dict(document["distributed"])
            if isinstance(document.get("distributed"), dict)
            else DistributedSpec(),
            checkpoint=CheckpointSpec.from_dict(document["checkpoint"])
            if isinstance(document.get("checkpoint"), dict)
            else CheckpointSpec(output_dir=str(Path(output_root) / "checkpoints")),
            env=dict(document.get("env") or {}),
        )
    else:
        raise ValueError("workload config is neither TrainingSpec nor a TEST ONLY launch document")
    launch.stdout_path = str(Path(output_root) / "engine.stdout.log")
    launch.stderr_path = str(Path(output_root) / "engine.stderr.log")
    executor = LocalProcessExecutor()
    handle = executor.start(launch)
    code = executor.wait(handle, timeout=None)
    metrics_dir = Path(output_root)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    metrics = metrics_dir / "metrics.jsonl"
    if not metrics.exists():
        metrics.write_text("", encoding="utf-8")
    return 0 if code is None else int(code)


def run_control_loop(control_dir: str, output_root: str, timeout: float = 3600.0) -> int:
    control = Path(control_dir)
    control.mkdir(parents=True, exist_ok=True)
    print("WORKER_READY", flush=True)
    _write(control / "ready", "WORKER_READY\n")

    raw = _wait_file(control / "configure.json", timeout)
    envelope = json.loads(raw)
    if envelope.get("payload") != "Configure":
        _write(control / "configure.err", "expected Configure envelope")
        return 2
    generation = int(envelope.get("generation") or 0)
    fence_token = int(envelope.get("fence_token") or 0)
    if not _fence_ok(generation, fence_token):
        _write(control / "configure.err", "FENCED_OUT")
        return 3
    settings = dict(envelope.get("settings") or {})
    try:
        assert_configure_is_not_training_spec(settings)
        parsed = WorkloadConfigureSettings.from_settings_map(settings)
        payload = verify_worker_config(parsed.worker_config_path, parsed.workload_config_ref)
    except Exception as exc:
        _write(control / "configure.err", str(exc))
        return 4
    _write(control / "configure.ack", "Configured")

    invoke_raw = _wait_file(control / "invoke.json", timeout)
    invoke = json.loads(invoke_raw)
    if invoke.get("payload") != "Invoke":
        _write(control / "invoke.err", "expected Invoke envelope")
        return 5
    if not _fence_ok(int(invoke.get("generation") or 0), int(invoke.get("fence_token") or 0)):
        _write(control / "invoke.err", "FENCED_OUT")
        return 3
    _write(control / "invoke.ack", invoke.get("request_id") or "run")
    document = json.loads(payload.decode("utf-8"))
    return _run_workload(document, parsed.output_root or output_root)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    control_dir = ""
    output_root = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--control-dir" and i + 1 < len(argv):
            control_dir = argv[i + 1]
            i += 2
            continue
        if argv[i] == "--output-root" and i + 1 < len(argv):
            output_root = argv[i + 1]
            i += 2
            continue
        i += 1
    if not control_dir or not output_root:
        print("usage: python -m cy_exec.training.worker --control-dir DIR --output-root DIR", file=sys.stderr)
        return 64
    try:
        return run_control_loop(control_dir, output_root)
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return 124
