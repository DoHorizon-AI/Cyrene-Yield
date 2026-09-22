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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# One attempt may keep at most 100 MiB of raw trainer output. Beyond that the
# sink keeps draining so the trainer never blocks on a full pipe, and says so
# through a single budget record plus the degraded marker.
DIAGNOSTICS_LIMIT_BYTES = 100 * 1024 * 1024
DIAGNOSTICS_FILE_NAME = "diagnostics.ndjson"
DEGRADED_FILE_NAME = "diagnostics.degraded"
RUNTIME_LOG_FILE_NAME = "runtime.log"
MAX_LINE_CHARS = 4096


class DiagnosticsSink:
    """Write both trainer streams as NDJSON from one writer thread.

    stdout and stderr are drained concurrently because a trainer that fills one
    pipe while the reader sits on the other deadlocks. Records are serialised by
    a single writer so interleaving never corrupts a line.
    """

    def __init__(self, root: Path, *, limit_bytes: int = DIAGNOSTICS_LIMIT_BYTES) -> None:
        self._path = root / DIAGNOSTICS_FILE_NAME
        self._degraded_path = root / DEGRADED_FILE_NAME
        # The host still harvests business events from the merged runtime log,
        # so raw lines keep going there alongside the tagged NDJSON copy.
        self._runtime_log_path = root / RUNTIME_LOG_FILE_NAME
        self._limit_bytes = limit_bytes
        self._pending: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._written_bytes = 0
        self._sequence = 0
        self._budget_noticed = False
        self._failed = False
        self._thread = threading.Thread(target=self._drain, daemon=True)

    @property
    def degraded(self) -> bool:
        return self._failed or self._degraded_path.exists()

    def start(self) -> None:
        self._thread.start()

    def put(self, stream: str, text: str) -> None:
        self._pending.put((stream, text))

    def close(self, timeout: float = 10.0) -> bool:
        """Stop the writer and report whether diagnostics are degraded."""

        self._pending.put(None)
        self._thread.join(timeout)
        return self.degraded

    def _mark_degraded(self) -> None:
        try:
            self._degraded_path.write_text("", encoding="utf-8")
        except OSError:
            pass

    def _record(self, stream: str, text: str) -> str:
        trimmed = text[:MAX_LINE_CHARS]
        record = {
            "sequence": self._sequence,
            "timestamp": datetime.now(UTC).isoformat(),
            "stream": stream,
            "level": "warn" if stream == "stderr" else "info",
            "truncated": len(text) > MAX_LINE_CHARS,
            "message": trimmed,
        }
        self._sequence += 1
        return json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"

    def _drain(self) -> None:
        try:
            handle = self._path.open("a", encoding="utf-8")
            runtime_log = self._runtime_log_path.open("a", encoding="utf-8")
        except OSError:
            self._failed = True
            self._mark_degraded()
            self._consume_without_writing()
            return
        with handle, runtime_log:
            while True:
                item = self._pending.get()
                if item is None:
                    return
                stream, text = item
                if self._written_bytes >= self._limit_bytes:
                    if not self._budget_noticed:
                        self._budget_noticed = True
                        self._failed = True
                        self._mark_degraded()
                        try:
                            handle.write(
                                json.dumps(
                                    {
                                        "sequence": self._sequence,
                                        "timestamp": datetime.now(UTC).isoformat(),
                                        "stream": "combined",
                                        "level": "warn",
                                        "code": "YIELD.DIAGNOSTICS.BUDGET_EXCEEDED",
                                        "truncated": True,
                                        "message": (
                                            f"Diagnostics budget reached ({self._limit_bytes} bytes);"
                                            " further output is discarded."
                                        ),
                                    },
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                                + "\n"
                            )
                            handle.flush()
                        except OSError:
                            pass
                    continue
                line = self._record(stream, text)
                try:
                    handle.write(line)
                    handle.flush()
                    runtime_log.write(text + "\n")
                    runtime_log.flush()
                except OSError:
                    self._failed = True
                    self._mark_degraded()
                    continue
                self._written_bytes += len(line.encode("utf-8"))

    def _consume_without_writing(self) -> None:
        while True:
            if self._pending.get() is None:
                return


def _pump(pipe: Any, stream: str, sink: DiagnosticsSink) -> None:
    """Forward one pipe line by line; never let a full pipe stall the trainer."""

    try:
        for line in pipe:
            sink.put(stream, line.rstrip("\n"))
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except (OSError, ValueError):
            pass


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
    sink = DiagnosticsSink(root)
    sink.start()
    try:
        # stdout and stderr are piped separately and drained by two threads: a
        # trainer that fills one pipe while the reader sits on the other blocks.
        process = subprocess.Popen(  # noqa: S603 - the signed launch intent
            argv,
            cwd=working_directory,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            bufsize=1,
        )
        readers = [
            threading.Thread(target=_pump, args=(process.stdout, "stdout", sink), daemon=True),
            threading.Thread(target=_pump, args=(process.stderr, "stderr", sink), daemon=True),
        ]
        for reader in readers:
            reader.start()
        try:
            code = process.wait()
        finally:
            for reader in readers:
                reader.join(timeout=5)
        # Drain whatever the trainer wrote on its way out before reporting a
        # degraded state, otherwise the last root-cause lines are lost.
        sink.close()
        if code:
            raise subprocess.CalledProcessError(code, argv)
    finally:
        # The sink is closed here too so a launch that never started still
        # stops its writer instead of leaving a daemon thread behind.
        sink.close(timeout=1.0)
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
