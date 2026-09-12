"""CyreneKernelExecutor.

Maps TrainingLaunchSpec onto origin/develop KernelAuthority typed commands.
Engine adapters never call Kernel. Device visibility is NVIDIA adapter-owned.

Production default is UnixKernelAuthorityPort (fail-closed on Windows).
InProcessKernelPort is TEST ONLY and must be requested explicitly.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/cyrene_kernel.py
# │ Module: training/core/src/cy_exec/training/executors/cyrene_kernel
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

from ..checkpoint import compute_checkpoint_digest
from ..contracts.artifacts import ArtifactCandidate, layout_paths
from ..contracts.launch import TrainingLaunchSpec
from ..contracts.workload import (
    TRAINING_SPEC_SCHEMA,
    WorkloadConfigureSettings,
    assert_configure_is_not_training_spec,
)
from .base import CancelOutcome, ProcessHandle
from .kernel_mapping import require_single_node
from .kernel_port import KernelControlPort
from .kernel_uds import UnixKernelAuthorityPort
from .plugin_control import PluginInvoke, WorkloadControlError, configure_from_workload
from .workload_stager import MinimalWorkloadStager


# ════════════════════════════════════════════════════════════════════════
# 🔧 CLASS: CyreneKernelExecutor
#
#   Delegates production training execution to the canonical Platform kernel
#   contract while preserving Yield's attempt and artifact semantics.
#
#   将生产训练执行委托给标准 Platform 内核契约，同时保持 Yield 的尝试与制品语义。
#
# ════════════════════════════════════════════════════════════════════════
class CyreneKernelExecutor:
    """Training executor backed by a Kernel control port.

    Production path: typed AcquireLease → StartWorker → StopWorker/CancelOperation.
    TEST ONLY path: InProcessKernelPort (local process tree, one-lease projection).
    """

    def __init__(
        self,
        port: KernelControlPort | None = None,
        *,
        test_inprocess: bool = False,
    ) -> None:
        if port is not None:
            self._port = port
        elif test_inprocess:
            from .inprocess_kernel import InProcessKernelPort

            self._port = InProcessKernelPort()
        else:
            self._port = UnixKernelAuthorityPort()
        self._stager = MinimalWorkloadStager()

    @property
    def port(self) -> KernelControlPort:
        return self._port

    def start(self, launch: TrainingLaunchSpec) -> ProcessHandle:
        launch.assert_executor_agnostic()
        require_single_node(launch.resources)
        leaked = {
            "CUDA_VISIBLE_DEVICES",
            "NVIDIA_VISIBLE_DEVICES",
        }.intersection(launch.env)
        if leaked:
            raise ValueError(f"TrainingLaunchSpec must not carry device visibility: {sorted(leaked)}")
        self._prepare_output_dirs(launch)
        allocation = self._port.allocate(launch.resources)
        handle = None
        try:
            handle = self._port.start_operation(launch, allocation, {})
            handle.extra.setdefault("assigned_env", {})
            handle.extra.setdefault("allocation_node_id", allocation.node_id)
            handle.extra.setdefault("lease_id", allocation.lease_id)
            handle.extra.setdefault("fence_token", allocation.fence_token)
            handle.extra.setdefault("resource_ids", list(allocation.resource_ids))
            self._port.wait_ready(handle)
            staged = self._stage_workload(launch)
            attempt_id = str(launch.extra.get("attempt_id") or f"attempt/{allocation.lease_id}")
            settings = WorkloadConfigureSettings(
                workload_config_ref=staged.config_ref,
                worker_config_path=staged.worker_visible_path,
                output_root=launch.work_dir,
                attempt_id=attempt_id,
                execution_id=str(handle.extra.get("worker_id") or attempt_id),
            )
            configure = configure_from_workload(
                settings,
                request_id=f"configure/{attempt_id}",
                generation=int(handle.extra.get("lease_generation") or allocation.lease_generation),
                fence_token=int(handle.extra.get("fence_token") or allocation.fence_token),
            )
            assert_configure_is_not_training_spec(configure.settings)
            if staged.control_plane_path in configure.settings.values():
                raise ValueError("control_plane_path must not enter Configure.settings")
            self._port.configure(handle, configure)
            invoke_id = self._port.invoke(
                handle,
                PluginInvoke(
                    request_id=f"invoke/{attempt_id}",
                    generation=int(handle.extra.get("lease_generation") or allocation.lease_generation),
                    fence_token=int(handle.extra.get("fence_token") or allocation.fence_token),
                ),
            )
            handle.extra["workload_config_ref"] = staged.config_ref.to_dict()
            handle.extra["worker_visible_path"] = staged.worker_visible_path
            handle.extra["invoke_request_id"] = invoke_id
            handle.extra["invoke_started"] = True
            handle.extra["plugin_configure"] = dict(configure.settings)
            return handle
        except Exception as exc:
            if handle is not None:
                self._port.cancel(handle, timeout=15.0)
            if isinstance(exc, WorkloadControlError):
                raise
            raise WorkloadControlError(str(exc), cleanup_attempted=handle is not None) from exc

    def _stage_workload(self, launch: TrainingLaunchSpec):
        attempt_id = str((launch.extra or {}).get("attempt_id") or "default").replace(":", "-")
        staging_dir = str(Path(launch.work_dir) / ".workload-stage" / attempt_id)
        inprocess = self._port.__class__.__name__ == "InProcessKernelPort"
        if inprocess:
            payload = json.dumps(launch.to_dict(), sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            return self._stager.stage_bytes(
                payload,
                staging_dir=staging_dir,
                schema="cyrene.training.launch-spec",
            )
        product_spec = (launch.extra or {}).get("product_spec")
        if (
            not inprocess
            and isinstance(product_spec, dict)
            and "model" in product_spec
            and "dataset" in product_spec
        ):
            from ..contracts.spec import TrainingSpec

            return self._stager.stage_spec(
                TrainingSpec.from_dict(product_spec),
                staging_dir=staging_dir,
            )
        if launch.spec_artifact_path and Path(launch.spec_artifact_path).is_file():
            schema = TRAINING_SPEC_SCHEMA
            text = Path(launch.spec_artifact_path).read_text(encoding="utf-8")
            try:
                doc = json.loads(text)
            except json.JSONDecodeError:
                doc = {}
            if not (isinstance(doc, dict) and "model" in doc and "dataset" in doc):
                schema = "cyrene.training.launch-spec"
            return self._stager.stage_path(
                launch.spec_artifact_path,
                staging_dir=staging_dir,
                schema=schema,
            )
        payload = json.dumps(launch.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self._stager.stage_bytes(
            payload,
            staging_dir=staging_dir,
            schema="cyrene.training.launch-spec",
        )

    def poll(self, handle: ProcessHandle) -> Optional[int]:
        return self._port.poll(handle)

    def wait(self, handle: ProcessHandle, timeout: Optional[float] = None) -> Optional[int]:
        import time

        deadline = None if timeout is None else time.time() + timeout
        while True:
            code = self.poll(handle)
            if code is not None:
                return code
            if deadline is not None and time.time() >= deadline:
                return None
            time.sleep(0.1)

    def cancel(self, handle: ProcessHandle, timeout: float = 15.0) -> CancelOutcome:
        extra = handle.extra or {}
        if extra.get("invoke_started"):
            from .plugin_control import PluginCancel, PLUGIN_INVOKE_CANCEL_SUPPORTED

            receipt = self._port.plugin_cancel(
                handle,
                PluginCancel(
                    target_request_id=str(extra.get("invoke_request_id") or extra.get("start_operation_id") or ""),
                    generation=int(extra.get("lease_generation") or 0),
                    fence_token=int(extra.get("fence_token") or 0),
                ),
            )
            handle.extra["plugin_cancel_receipt"] = bool(receipt)
            handle.extra["plugin_cancel_supported"] = PLUGIN_INVOKE_CANCEL_SUPPORTED
        return self._port.cancel(handle, timeout=timeout)

    def read_new_output(self, handle: ProcessHandle) -> Sequence[str]:
        lines = list(self._port.read_output(handle))
        for name in ("engine.stdout.log", "metrics.jsonl"):
            path = Path(handle.work_dir) / name
            if not path.is_file():
                continue
            key = f"_tail_{name}"
            offset = int(handle.extra.get(key) or 0)
            data = path.read_text(encoding="utf-8")
            if len(data) > offset:
                chunk = data[offset:]
                handle.extra[key] = offset + len(chunk)
                new_lines = [item for item in chunk.splitlines() if item]
                lines.extend(new_lines)
                self._port.output_channel().extend(new_lines)
        return lines

    def collect_outputs(self, launch: TrainingLaunchSpec) -> dict:
        descriptor = layout_paths(launch.work_dir, launch.output_layout)
        Path(descriptor.output_root).mkdir(parents=True, exist_ok=True)
        Path(descriptor.model_dir).mkdir(parents=True, exist_ok=True)
        Path(descriptor.checkpoint_dir).mkdir(parents=True, exist_ok=True)
        artifacts = []
        for path, kind in (
            (descriptor.model_dir, "model"),
            (descriptor.checkpoint_dir, "checkpoint"),
            (launch.checkpoint.output_dir, "checkpoint"),
        ):
            digest, size = compute_checkpoint_digest(path)
            if digest or Path(path).exists():
                artifacts.append(
                    ArtifactCandidate(path=path, kind=kind, digest=digest, size_bytes=size)
                )
        descriptor.artifacts = artifacts
        manifest = {
            "engine": launch.engine.value,
            "argv": list(launch.argv),
            "distributed": launch.distributed.to_dict(),
            "resources": launch.resources.to_dict(),
            "outputs": descriptor.to_dict(),
            "spec_artifact_path": launch.spec_artifact_path,
            "execution_ref": (launch.extra or {}).get("execution_ref"),
        }
        Path(descriptor.manifest_path).write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )
        if not Path(descriptor.metrics_path).exists():
            Path(descriptor.metrics_path).write_text("{}", encoding="utf-8")
        return descriptor.to_dict()

    def _prepare_output_dirs(self, launch: TrainingLaunchSpec) -> None:
        descriptor = layout_paths(launch.work_dir, launch.output_layout)
        Path(descriptor.output_root).mkdir(parents=True, exist_ok=True)
        Path(descriptor.model_dir).mkdir(parents=True, exist_ok=True)
        Path(descriptor.checkpoint_dir).mkdir(parents=True, exist_ok=True)
