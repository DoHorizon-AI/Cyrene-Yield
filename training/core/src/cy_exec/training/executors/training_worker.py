"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.executors.training_worker                  │
│  Role: Enter the selected trainer inside a Kernel-owned worker.     │
│  模块职责：在 Kernel 管理的 Worker 内运行训练器，维护既有控制通路。        │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import importlib
import json
import os
import queue
import signal
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def main() -> None:
    """Run the signed launch intent and record the trainer's actual completion."""
    # The signed installation stages this transport module beside the worker.
    rpc = importlib.import_module("kernel_rpc")

    root = Path(__file__).resolve().parent
    configuration = json.loads((root / "worker.json").read_bytes())
    launch = configuration["launch"]
    log = os.open(root / "runtime.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.dup2(log, 1)
    os.dup2(log, 2)
    os.close(log)
    client = rpc.KernelClient(Path(os.environ["CYRENE_WORKER_CONTROL_SOCKET"]), root / "kernel.desc")
    outgoing: queue.Queue[dict[str, Any] | None] = queue.Queue()
    identity = {
        "worker": configuration["worker"],
        "lease": configuration["lease"]["identity"],
        "fenceToken": configuration["lease"]["fenceToken"],
    }
    accepted = threading.Event()
    finished = threading.Event()

    def requests() -> Iterator[dict[str, Any]]:
        while True:
            value = outgoing.get()
            if value is None:
                return
            yield value

    def control() -> None:
        try:
            for response in client.worker_control(requests()):
                if "welcome" in response:
                    accepted.set()
                if "shutdown" in response:
                    os.kill(os.getpid(), signal.SIGTERM)
        finally:
            if not finished.is_set():
                os.kill(os.getpid(), signal.SIGTERM)

    def heartbeat() -> None:
        while not finished.wait(2):
            outgoing.put({"context": rpc.context("heartbeat"), "heartbeat": identity})
            (root / "heartbeat").touch()

    outgoing.put({"context": rpc.context("hello"), "hello": identity})
    threading.Thread(target=control, daemon=True).start()
    if not accepted.wait(10):
        raise RuntimeError("KERNEL_WORKER_CONTROL_UNAVAILABLE")
    threading.Thread(target=heartbeat, daemon=True).start()
    argv = launch.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError("YIELD_TRAINER_INVALID_LAUNCH: plugin returned no executable argv")
    # Device visibility stays exactly as assigned by Kernel's NVIDIA binding.
    # 输入基座已由 Artifact Plane 校验，训练期间不重新下载或执行远程模型代码。
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    working_directory = launch.get("cwd") or launch.get("work_dir")
    if not isinstance(working_directory, str) or not working_directory:
        raise ValueError("YIELD_TRAINER_INVALID_LAUNCH: plugin returned no working directory")
    environment = os.environ.copy()
    launch_environment = launch.get("env") or {}
    if not isinstance(launch_environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in launch_environment.items()
    ):
        raise ValueError("YIELD_TRAINER_INVALID_LAUNCH: plugin returned invalid environment")
    environment.update(launch_environment)
    code = 1
    try:
        code = subprocess.call(argv, cwd=working_directory, env=environment)
        if code:
            raise subprocess.CalledProcessError(code, argv)
    finally:
        pending = root / "completion.pending"
        with pending.open("w", encoding="utf-8") as stream:
            json.dump({"worker": identity["worker"], "exitCode": code}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, root / "completion.json")
        # The host confirms ReleaseLease before converting this into a result.
        finished.set()
        outgoing.put(None)
        client.close()


if __name__ == "__main__":
    main()
