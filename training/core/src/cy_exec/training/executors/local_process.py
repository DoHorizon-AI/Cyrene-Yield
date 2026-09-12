"""Local process executor for Windows development and tests.

Starts TrainingLaunchSpec.argv as a real process tree and only reports
cancel success after the tree is gone. Device assignment is applied here
(if the caller provides it), never stored on the product contract.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/local_process.py
# │ Module: training/core/src/cy_exec/training/executors/local_process
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, IO, List, Mapping, Optional, Sequence

from ..contracts import TrainingLaunchSpec, merge_executor_env
from .base import CancelOutcome, ProcessHandle


# ════════════════════════════════════════════════════════════════════════
# 🔧 CLASS: LocalProcessExecutor
#
#   Starts, monitors, cancels, and collects events from a locally controlled
#   training process tree.
#
#   启动、监控、取消本地受控训练进程树，并收集其事件。
#
# ════════════════════════════════════════════════════════════════════════
class LocalProcessExecutor:
    """Local development / Windows executor.

    Consumes the same TrainingLaunchSpec as CyreneKernelExecutor. Device
    assignment is applied here (if the caller provides it), never stored
    on the product contract.
    """

    def __init__(
        self,
        *,
        assigned_env: Mapping[str, str] | None = None,
        kill_timeout_seconds: float = 15.0,
    ) -> None:
        self._assigned_env = dict(assigned_env or {})
        self._kill_timeout_seconds = kill_timeout_seconds
        self._procs: Dict[int, subprocess.Popen] = {}
        self._stdout: Dict[int, IO[str]] = {}
        self._offsets: Dict[int, int] = {}

    def start(
        self,
        launch: TrainingLaunchSpec,
        assigned_env: Mapping[str, str] | None = None,
    ) -> ProcessHandle:
        launch.assert_executor_agnostic()
        work_dir = Path(launch.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = launch.stdout_path or str(work_dir / "executor.stdout.log")
        stderr_path = launch.stderr_path or str(work_dir / "executor.stderr.log")
        stdout = open(stdout_path, "a+", encoding="utf-8")
        env = os.environ.copy()
        env.update(merge_executor_env(launch.env, {**self._assigned_env, **dict(assigned_env or {})}))
        env["PYTHONUNBUFFERED"] = "1"
        kwargs = {
            "args": list(launch.argv),
            "cwd": launch.cwd or launch.work_dir,
            "env": env,
            "stdout": stdout,
            "stderr": subprocess.STDOUT,
            "text": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(**kwargs)
        self._procs[proc.pid] = proc
        self._stdout[proc.pid] = stdout
        self._offsets[proc.pid] = 0
        return ProcessHandle(
            pid=proc.pid,
            argv=list(launch.argv),
            work_dir=launch.work_dir,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    def poll(self, handle: ProcessHandle) -> Optional[int]:
        proc = self._procs.get(handle.pid)
        if proc is None:
            return None
        code = proc.poll()
        if code is not None:
            self._close_stdout(handle.pid)
        return code

    def wait(self, handle: ProcessHandle, timeout: Optional[float] = None) -> Optional[int]:
        proc = self._procs.get(handle.pid)
        if proc is None:
            return None
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        self._close_stdout(handle.pid)
        return code

    def cancel(self, handle: ProcessHandle, timeout: float = 15.0) -> CancelOutcome:
        proc = self._procs.get(handle.pid)
        descendants = _descendant_pids(handle.pid)
        if proc is None:
            if not _pid_is_running(handle.pid) and not descendants:
                return CancelOutcome(
                    stopped=True,
                    remaining_pids=(),
                    message="process already gone",
                    cleanup_confirmed=True,
                )
            killed = _kill_tree(handle.pid, descendants)
            remaining = _wait_tree_gone(handle.pid, timeout, descendants)
            if remaining:
                return CancelOutcome(
                    stopped=False,
                    remaining_pids=remaining,
                    message="process tree still alive after cancel",
                )
            return CancelOutcome(
                stopped=True,
                remaining_pids=(),
                message=killed,
                cleanup_confirmed=True,
            )

        if proc.poll() is not None:
            self._close_stdout(handle.pid)
            leftover = [pid for pid in descendants if _pid_is_running(pid)]
            if leftover:
                _kill_tree(handle.pid, leftover)
                leftover = _wait_tree_gone(handle.pid, timeout, leftover)
                if leftover:
                    return CancelOutcome(
                        stopped=False,
                        remaining_pids=leftover,
                        message="child processes still alive after parent exit",
                    )
            return CancelOutcome(
                stopped=True,
                remaining_pids=(),
                message="process already exited",
                cleanup_confirmed=True,
            )

        _kill_tree(handle.pid, descendants)
        try:
            proc.wait(timeout=min(2.0, max(0.1, timeout)))
        except subprocess.TimeoutExpired:
            pass
        remaining = _wait_tree_gone(handle.pid, timeout, descendants)
        if remaining:
            return CancelOutcome(
                stopped=False,
                remaining_pids=remaining,
                message="unable to stop process tree",
            )
        try:
            proc.wait(timeout=1)
        except Exception:
            pass
        self._close_stdout(handle.pid)
        return CancelOutcome(
            stopped=True,
            remaining_pids=(),
            message="process tree stopped",
            cleanup_confirmed=True,
        )

    def read_new_output(self, handle: ProcessHandle) -> Sequence[str]:
        path = handle.stdout_path
        if not path or not Path(path).exists():
            return []
        offset = self._offsets.get(handle.pid, 0)
        data = Path(path).read_text(encoding="utf-8", errors="replace")
        if len(data) < offset:
            offset = 0
        chunk = data[offset:]
        self._offsets[handle.pid] = len(data)
        if not chunk:
            return []
        return chunk.splitlines()

    def _close_stdout(self, pid: int) -> None:
        handle = self._stdout.pop(pid, None)
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil
    except ImportError:
        if os.name == "nt":
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


def _descendant_pids(pid: int) -> List[int]:
    try:
        import psutil

        process = psutil.Process(pid)
        return [child.pid for child in process.children(recursive=True)]
    except Exception:
        return []


def _kill_tree(pid: int, known_descendants: Sequence[int] = ()) -> str:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return "taskkill /T /F"
    targets = {pid, *known_descendants}
    process_groups = set()
    for candidate in targets:
        try:
            process_groups.add(os.getpgid(candidate))
        except OSError:
            continue
    process_groups.discard(os.getpgrp())

    for process_group in process_groups:
        try:
            os.killpg(process_group, signal.SIGTERM)
        except OSError:
            pass
    for candidate in targets:
        try:
            os.kill(candidate, signal.SIGTERM)
        except OSError:
            pass
    time.sleep(0.5)

    for process_group in process_groups:
        try:
            os.killpg(process_group, signal.SIGKILL)
        except OSError:
            pass
    for candidate in targets:
        try:
            os.kill(candidate, signal.SIGKILL)
        except OSError:
            pass
    return "posix signal process group"


def _wait_tree_gone(
    pid: int,
    timeout: float,
    known_descendants: Sequence[int] = (),
) -> List[int]:
    deadline = time.monotonic() + max(0.1, timeout)
    tracked = {pid, *known_descendants}
    remaining: List[int] = []
    while time.monotonic() < deadline:
        tracked.update(_descendant_pids(pid))
        remaining = [candidate for candidate in tracked if _pid_is_running(candidate)]
        if not remaining:
            return []
        time.sleep(0.1)
    return remaining
