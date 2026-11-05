"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.executors.kernel_training                  │
│  Role: Adapt compiled training to existing Kernel Lease/Worker RPCs.│
│  模块职责：调用既有 Kernel 启动、续租与回收；不实现第二套资源权威。        │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import grpc
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cyrene_preflight import AcceleratorFacts, HardwareFacts
from pydantic import BaseModel, ConfigDict, Field

from ..contracts import TrainingLaunchSpec
from .base import CancelOutcome, ExecutionControlError, ProcessHandle
from .kernel_rpc import KernelClient, context


class KernelTrainingConfiguration(BaseModel):
    """Operator configuration, never accepted as a Product handoff payload.

    运营方配置,不接受为 Product 交接 payload。
    """

    model_config = ConfigDict(extra="forbid")
    socket: Path
    installations: Path
    state_directory: Path
    python: Path
    signing_key_file: Path
    trainer_runtime_manifest: Path | None = None
    minimum_memory_bytes: int = Field(default=1024**3, gt=0)
    allow_wsl_shared_device: bool = False


@dataclass(frozen=True)
class KernelExecutionReadiness:
    """Typed projection of host capabilities needed before training submission.

    提交训练前所需 Kernel 主机能力的类型化投影；不证明具体设备绑定可执行。
    """

    hardware_facts: HardwareFacts
    system_adapter_available: bool
    hard_gpu_isolation_available: bool
    trainer_runtime_available: bool

    def block_reasons(self, *, minimum_memory_bytes: int) -> list[str]:
        """Return stable reasons this Kernel host cannot execute the v1 GPU profile.

        返回此 Kernel 主机无法执行 v1 GPU 配置的稳定原因。
        """

        reasons = []
        if not self.system_adapter_available:
            reasons.append("SYSTEM_ADAPTER_UNAVAILABLE")
        if not any(
            accelerator.kind == "gpu"
            and accelerator.vendor == "nvidia"
            and accelerator.allocatable_memory_bytes >= minimum_memory_bytes
            for accelerator in self.hardware_facts.accelerators
        ):
            reasons.append("GPU_UNAVAILABLE")
        if not self.hard_gpu_isolation_available:
            reasons.append("GPU_ISOLATION_UNAVAILABLE")
        if not self.trainer_runtime_available:
            reasons.append("TRAINER_RUNTIME_UNAVAILABLE")
        return reasons


def _document(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


_TRAINER_RUNTIME_PROFILE = "CYRENE_YIELD_TRAINER_V1_CUDA128"
_TRAINER_RUNTIME_PACKAGES = (
    "grpcio",
    "packaging",
    "protobuf",
    "torch",
    "torchaudio",
    "torchvision",
    "transformers",
    "peft",
    "llamafactory",
)
_TRAINER_RUNTIME_IMPORT_CHECK = """\
import importlib, importlib.metadata, json, os, sys
data = json.loads(sys.stdin.read())
expected_python = data['python']
if not os.path.samefile(sys.executable, expected_python):
    raise SystemExit('python path differs from trainer manifest')
expected_prefix = os.path.dirname(os.path.dirname(os.path.abspath(expected_python)))
if os.path.realpath(sys.prefix) != os.path.realpath(expected_prefix):
    raise SystemExit('python environment differs from trainer manifest')
for name, expected in data['packages'].items():
    if importlib.metadata.version(name) != expected:
        raise SystemExit('package version differs from trainer manifest: ' + name)
for module in ('grpc', 'google.protobuf', 'packaging', 'torch', 'torchaudio', 'torchvision',
               'transformers', 'peft', 'llamafactory.cli'):
    importlib.import_module(module)
if not callable(importlib.import_module('llamafactory.cli').main):
    raise SystemExit('LLaMA-Factory CLI entrypoint is unavailable')
"""


class KernelTrainingExecutor:
    """Kernel owns process trees and leases; files are private execution receipts.

    Kernel 拥有进程树与租约;文件是私有执行回执。
    """

    def __init__(self, configuration: KernelTrainingConfiguration, *, client: Any = None) -> None:
        self.configuration = configuration
        self.kernel = client or KernelClient(configuration.socket)
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._receipts = configuration.state_directory / "execution-receipts"
        self._receipts.mkdir(parents=True, exist_ok=True)
        self._trainer_probe_lock = threading.Lock()
        self._trainer_probe_expires_at = 0.0
        self._trainer_probe_result = False
        self._renewal = threading.Thread(target=self._renew, daemon=True)
        self._renewal.start()

    def _save(self, receipt: dict[str, Any]) -> None:
        path = self._receipts / (receipt["worker"]["id"] + ".json")
        pending = path.with_suffix(".pending")
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_document(receipt))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)

    def trainer_runtime_available(self, *, force: bool = False) -> bool:
        """Check that the private trainer manifest and its executable environment still agree.

        检查私有 trainer manifest 及其可执行环境当前仍一致。
        """

        manifest_path = self.configuration.trainer_runtime_manifest
        if manifest_path is None:
            return False
        now = time.monotonic()
        if not force and now < self._trainer_probe_expires_at:
            return self._trainer_probe_result
        with self._trainer_probe_lock:
            now = time.monotonic()
            if not force and now < self._trainer_probe_expires_at:
                return self._trainer_probe_result
            self._trainer_probe_result = self._probe_trainer_runtime(manifest_path)
            self._trainer_probe_expires_at = time.monotonic() + 30.0
            return self._trainer_probe_result

    def _probe_trainer_runtime(self, manifest_path: Path) -> bool:
        """Run a bounded import and distribution check using the manifest interpreter.

        使用 manifest 指定的解释器执行有时限的导入与 distribution 检查。
        """

        try:
            metadata = manifest_path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.getuid()
            ):
                return False
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("schemaVersion") != 1
                or manifest.get("profile") != _TRAINER_RUNTIME_PROFILE
                or manifest.get("status") != "READY"
            ):
                return False
            manifest_python = manifest.get("python")
            if not isinstance(manifest_python, str) or not Path(manifest_python).is_absolute():
                return False
            python = self.configuration.python
            if not python.is_file() or not os.access(python, os.X_OK):
                return False
            if Path(manifest_python).resolve(strict=True) != python.resolve(strict=True):
                return False
            packages = manifest.get("packages")
            if not isinstance(packages, dict) or any(
                not isinstance(packages.get(name), str) for name in _TRAINER_RUNTIME_PACKAGES
            ):
                return False
            expected = {
                "python": manifest_python,
                "packages": {name: packages[name] for name in _TRAINER_RUNTIME_PACKAGES},
            }
            result = subprocess.run(
                [str(python), "-I", "-c", _TRAINER_RUNTIME_IMPORT_CHECK],
                input=_document(expected).decode("utf-8"),
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
            )
            return result.returncode == 0
        except (OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
            return False

    def execution_readiness(self, *, trainer_runtime_available: bool | None = None) -> KernelExecutionReadiness:
        """Read one Kernel snapshot for training hardware and isolation readiness.

        从同一个 Kernel 快照读取训练硬件和隔离就绪事实。
        """

        if trainer_runtime_available is None:
            trainer_runtime_available = self.trainer_runtime_available()
        facts = self.kernel.capabilities()
        # ── Phase 1: Validate the existing Kernel capability facts ──────
        # 第一阶段：校验现有 Kernel 能力事实。
        feature_flags = facts.get("featureFlags", [])
        if not isinstance(feature_flags, list) or any(not isinstance(item, str) for item in feature_flags):
            raise ValueError("YIELD_KERNEL_CAPABILITIES_INVALID: feature flags must be strings")

        # ── Phase 2: Project inventory into the typed preflight contract ─
        # 第二阶段：将 inventory 投影到类型化 preflight 契约。
        accelerators = []
        for resource in facts.get("resources", []):
            capabilities = {item["id"] for item in resource.get("capabilities", [])}
            if "vendor.nvidia.cuda" not in capabilities:
                continue
            capacity = resource.get("capacity", {})
            total = capacity.get("memory.total", {})
            available = capacity.get("memory.allocatable", {})
            if total.get("unit") != "byte" or available.get("unit") != "byte":
                raise ValueError("YIELD_INVENTORY_INCOMPLETE: canonical memory quantities are required")
            accelerators.append(
                AcceleratorFacts(
                    device_id=resource["identity"]["id"],
                    kind="gpu",
                    vendor="nvidia",
                    total_memory_bytes=int(total["value"]),
                    allocatable_memory_bytes=int(available["value"]),
                    device_family=resource.get("attributes", {}).get("family"),
                    # FP32 is a baseline of the provider's CUDA capability. No claim
                    # FP32 是提供方 CUDA 能力的基线。此处不声称支持
                    # is made about optional BF16/FP16/quantized execution support.
                    # 可选的 BF16/FP16/量化执行。
                    features=("fp32",),
                )
            )
        hardware_facts = HardwareFacts.from_node_resource_inventory(
            node_id=facts["node"]["nodeId"],
            inventory_generation=int(facts["inventoryGeneration"]),
            accelerators=accelerators,
            accelerator_runtime="cuda",
            architecture=platform.machine().lower(),
        )
        flags = set(feature_flags)
        has_shared_device_binding = any(
            resource.get("attributes", {}).get("device.binding") == "wsl-shared-soft"
            for resource in facts.get("resources", [])
        )
        # This positive flag is only a host-level prerequisite. It does not
        # prove that a particular lease binding can be admitted; Kernel still
        # performs binding-aware admission and attaches isolation to the target
        # cgroup when it starts the worker.
        # 此正向标志只是主机级前提，不证明具体租约绑定可获准；Kernel 仍会在启动
        # worker 时执行绑定感知准入，并在目标 cgroup 上实际挂载隔离。
        return KernelExecutionReadiness(
            hardware_facts=hardware_facts,
            system_adapter_available="adapter.linux-system.cgroup-v2" in flags,
            hard_gpu_isolation_available="sandbox.device-bpf-capable" in flags and not has_shared_device_binding,
            trainer_runtime_available=trainer_runtime_available,
        )

    def hardware_facts(self) -> HardwareFacts:
        """Project the Kernel's NVIDIA CUDA inventory into the preflight contract.

        将 Kernel 的 NVIDIA CUDA 清单映射到 preflight 契约。
        """

        return self.execution_readiness().hardware_facts

    def recover(self) -> list[tuple[TrainingLaunchSpec, ProcessHandle]]:
        """Restore existing receipt handles without acquiring another lease.

        恢复现有回执句柄,不再获取新的租约。
        """
        recovered = []
        with self._lock:
            for path in self._receipts.glob("*.json"):
                receipt = json.loads(path.read_bytes())
                if receipt.get("operation") and receipt.get("lease"):
                    recovered.append((TrainingLaunchSpec(**receipt["launch"]), self._handle(receipt)))
        return recovered

    def _receipt(self, handle: ProcessHandle) -> dict[str, Any]:
        path = self._receipts / (str(handle.extra["worker_id"]) + ".json")
        return json.loads(path.read_bytes())

    def start(self, launch: TrainingLaunchSpec) -> ProcessHandle:
        """Acquire and start through Kernel; never spawn a training subprocess here.

        通过 Kernel 获取租约并启动;不得在此启动训练子进程。
        """
        try:
            facts = self._admit(launch)
        except (grpc.RpcError, OSError, ValueError) as exc:
            # Admission and inventory failures happen before any lease is acquired.
            raise ExecutionControlError(
                "YIELD_KERNEL_ADMISSION_FAILED: check the selected host and trainer profile",
                cleanup_attempted=False,
                lost=False,
            ) from exc
        return self._start(launch, facts)

    def _admit(self, launch: TrainingLaunchSpec) -> dict[str, Any]:
        if not self.trainer_runtime_available(force=True):
            raise ValueError("TRAINER_RUNTIME_UNAVAILABLE")
        self._bind_trainer_interpreter(launch)
        launch.assert_executor_agnostic()
        if launch.distributed.world_size != 1 or launch.distributed.gpu_count != 1:
            raise ValueError("YIELD_PROFILE_UNSUPPORTED: V1 supports one NVIDIA GPU")
        if not launch.argv or not all(isinstance(item, str) and item for item in launch.argv):
            raise ValueError("YIELD_PROFILE_UNSUPPORTED: Plugin returned an invalid launch")
        if {"CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"}.intersection(launch.env):
            raise ValueError("YIELD_DEVICE_AUTHORITY: Kernel owns device visibility")
        facts = self.kernel.capabilities()
        if (
            any(
                item.get("attributes", {}).get("device.binding") == "wsl-shared-soft"
                for item in facts.get("resources", [])
            )
            and not self.configuration.allow_wsl_shared_device
        ):
            raise ValueError("YIELD_HOST_UNSUPPORTED: shared WSL binding needs operator admission")
        return facts

    def _bind_trainer_interpreter(self, launch: TrainingLaunchSpec) -> None:
        """Bind the official LLaMA-Factory CLI to the manifest-owned interpreter.

        将官方 LLaMA-Factory CLI 绑定到 manifest 指定的解释器。
        """

        if launch.engine.value != "llamafactory":
            return
        argv = list(launch.argv)
        if argv and argv[0] == "llamafactory-cli":
            command = argv[1:]
        elif len(argv) >= 4 and argv[1:3] == ["-m", "llamafactory.cli"]:
            command = argv[3:]
        else:
            raise ValueError("YIELD_TRAINER_LAUNCHER_INVALID: expected the official LLaMA-Factory CLI")
        if not command or command[0] != "train":
            raise ValueError("YIELD_TRAINER_LAUNCHER_INVALID: expected the official train command")

        python = str(self.configuration.python)
        launch.argv = [python, "-I", "-m", "llamafactory.cli", *command]
        launch.env.pop("CYRENE_LLAMA_FACTORY_ENTRYPOINT", None)
        launch.env["CYRENE_LLAMA_FACTORY_PYTHON"] = python

    def _start(self, launch: TrainingLaunchSpec, facts: dict[str, Any]) -> ProcessHandle:
        worker: dict[str, Any] = {"id": "yield-" + str(uuid4()), "generation": 1}
        receipt: dict[str, Any] = {
            "worker": worker,
            "node": facts["node"],
            "launch": launch.to_dict(),
            "lease": None,
            "released": False,
            "createdAt": time.time(),
        }
        with self._lock:
            self._save(receipt)
            try:
                receipt["lease"] = self.kernel.authority(
                    "AcquireLease",
                    {
                        "context": context("acquire:" + worker["id"]),
                        "holder": worker,
                        "query": {
                            "resourceClass": "accelerator",
                            "count": 1,
                            "requiredCapabilities": [{"id": "vendor.nvidia.cuda", "minimumRevision": 1}],
                            "minimumCapacity": {
                                "memory.allocatable": {
                                    "value": str(self.configuration.minimum_memory_bytes),
                                    "unit": "byte",
                                }
                            },
                        },
                        "ttl": "120s",
                    },
                )
                self._save(receipt)
                receipt["installationRef"] = self._install(receipt)
                self._save(receipt)
                receipt["operation"] = self.kernel.authority(
                    "StartWorker",
                    {
                        "context": context("start:" + worker["id"]),
                        "worker": {
                            "identity": worker,
                            "provider": {"id": "yield.training", "generation": 1},
                            "lease": receipt["lease"]["identity"],
                            "state": "WORKER_STATE_REGISTERED",
                            "executionRef": receipt["installationRef"],
                        },
                    },
                )
                self._save(receipt)
            except (grpc.RpcError, OSError, ValueError, subprocess.SubprocessError) as exc:
                released = False
                if receipt["lease"] is not None:
                    try:
                        self._release(receipt)
                        released = True
                    except (grpc.RpcError, OSError, ValueError):
                        pass  # diagnostic-allow: Release failure is propagated as LOST.
                raise ExecutionControlError(
                    "YIELD_KERNEL_START_FAILED: inspect the execution host diagnostics",
                    cleanup_attempted=receipt["lease"] is not None,
                    lost=not released,
                ) from exc
        return self._handle(receipt)

    def _handle(self, receipt: dict[str, Any]) -> ProcessHandle:
        launch = receipt["launch"]
        return ProcessHandle(
            pid=0,
            argv=launch["argv"],
            work_dir=launch["work_dir"],
            extra={
                "worker_id": receipt["worker"]["id"],
                "node_id": receipt["node"]["nodeId"],
                "lease_id": receipt["lease"]["identity"].get("id", ""),
                "fence_token": receipt["lease"]["fenceToken"],
                "resource_ids": [item["id"] for item in receipt["lease"].get("resources", [])],
                "start_operation_id": receipt["operation"].get("identity", {}).get("id", ""),
                "execution_ref": receipt.get("installationRef", ""),
            },
        )

    def _install(self, receipt: dict[str, Any]) -> str:
        configuration = self.configuration
        if configuration.signing_key_file.stat().st_mode & 0o077:
            raise ValueError("YIELD_INSTALLER_KEY_PERMISSIONS: expected mode 0600")
        key = Ed25519PrivateKey.from_private_bytes(configuration.signing_key_file.read_bytes())
        inventory = subprocess.run(
            [
                str(configuration.python),
                "-c",
                "import importlib.metadata as m,json; print(json.dumps({n:m.version(n) for n in "
                "('torch','transformers','peft','grpcio','protobuf')}))",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        versions = json.loads(inventory.stdout)
        configuration.installations.mkdir(parents=True, exist_ok=True)
        name = receipt["worker"]["id"]
        with tempfile.TemporaryDirectory(dir=configuration.installations, prefix=".install-") as temporary:
            stage = Path(temporary)
            for member in ("kernel_rpc.py", "kernel.desc", "training_worker.py"):
                shutil.copyfile(Path(__file__).with_name(member), stage / member)
            (stage / "worker.json").write_bytes(_document(receipt))
            os.chmod(stage / "worker.json", 0o600)
            (stage / "launch").write_text(
                "#!" + str(configuration.python) + "\nfrom training_worker import main\nmain()\n"
            )
            os.chmod(stage / "launch", 0o700)
            sbom = _document({"runtimePackages": versions, "profile": "yield-training-v1"})
            provenance = _document({"worker": receipt["worker"], "launchDigest": _digest(_document(receipt["launch"]))})
            (stage / "sbom.json").write_bytes(sbom)
            (stage / "provenance.json").write_bytes(provenance)
            files = {p.name: _digest(p.read_bytes()) for p in stage.iterdir()}
            manifest = _document({"installation": name, "files": files})
            signature = key.sign(manifest)
            key.public_key().verify(signature, manifest)
            if any(_digest((stage / member).read_bytes()) != expected for member, expected in files.items()):
                raise ValueError("YIELD_INSTALLATION_CHANGED: content differs from signed manifest")
            (stage / "installation-manifest.json").write_bytes(manifest)
            (stage / "installation.sig").write_bytes(signature)
            (stage / "launch.json").write_bytes(
                _document(
                    {
                        "record_version": 1,
                        "installation_name": name,
                        "manifest_digest": _digest(manifest),
                        "artifact_digest": _digest(manifest),
                        "verified_signature_identity": "local-ed25519:" + key.public_key().public_bytes_raw().hex(),
                        "signature_policy_name": "operator-pinned-local-ed25519-v1",
                        "sbom_digest": _digest(sbom),
                        "provenance_digest": _digest(provenance),
                        "executable": "launch",
                        "args": [],
                        "environment": {},
                    }
                )
            )
            os.rename(stage, configuration.installations / name)
        return name + "@" + _digest(manifest)

    def _release(self, receipt: dict[str, Any]) -> None:
        if receipt["released"]:
            return
        lease = receipt["lease"]
        result = self.kernel.authority(
            "ReleaseLease",
            {
                "context": context("release:" + receipt["worker"]["id"]),
                "lease": lease["identity"],
                "fenceToken": lease["fenceToken"],
            },
        )
        if result.get("state") not in {"LEASE_STATE_RELEASED", "LEASE_STATE_EXPIRED", "LEASE_STATE_REVOKED"}:
            raise ValueError("YIELD_CLEANUP_UNCONFIRMED: Kernel resources remain reserved")
        receipt.update(released=True, releaseReceipt=result)
        self._save(receipt)

    def poll(self, handle: ProcessHandle) -> int | None:
        """A trainer exit plus confirmed Kernel cleanup precedes terminal success.

        只有 trainer 退出且 Kernel 确认清理后,状态才能进入终态成功。
        """
        with self._lock:
            receipt = self._receipt(handle)
            root = self.configuration.installations / receipt["worker"]["id"]
            completion = root / "completion.json"
            if completion.exists():
                result = json.loads(completion.read_bytes())
                if result.get("worker") != receipt["worker"] or type(result.get("exitCode")) is not int:
                    raise ValueError("YIELD_COMPLETION_INVALID: execution identity differs")
                self._release(receipt)
                return result["exitCode"]
            heartbeat = root / "heartbeat"
            last_seen = heartbeat.stat().st_mtime if heartbeat.exists() else receipt["createdAt"]
            if time.time() - last_seen > 60 or receipt.get("renewalFailed"):
                self._release(receipt)
                return 1
            return None

    def cancel(self, handle: ProcessHandle, timeout: float = 15.0) -> CancelOutcome:
        with self._lock:
            try:
                self._release(self._receipt(handle))
                return CancelOutcome(stopped=True, cleanup_confirmed=True, leases_released=True)
            except (grpc.RpcError, ValueError) as exc:
                return CancelOutcome(stopped=False, message="YIELD_CLEANUP_UNCONFIRMED: " + type(exc).__name__)

    def read_new_output(self, handle: ProcessHandle) -> list[str]:
        path = self.configuration.installations / str(handle.extra["worker_id"]) / "runtime.log"
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            stream.seek(handle.extra.get("logOffset", 0))
            lines = stream.readlines(256 * 1024)
            handle.extra["logOffset"] = stream.tell()
            return [line.rstrip("\n") for line in lines]

    def read_new_diagnostics(self, handle: ProcessHandle) -> list[dict[str, Any]]:
        """Return the new NDJSON diagnostic records the worker wrote.

        Only complete lines are consumed: a half-written tail stays buffered so
        the next poll picks it up instead of dropping the record.

        只消费完整行，半行留在下次采集，避免截断记录。
        """

        path = (
            self.configuration.installations
            / str(handle.extra.get("worker_id", ""))
            / "diagnostics.ndjson"
        )
        if not path.exists():
            return []
        offset = int(handle.extra.get("diagnosticsOffset", 0))
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            stream.seek(offset)
            chunk = stream.read(1024 * 1024)
        boundary = chunk.rfind("\n")
        if boundary == -1:
            return []
        handle.extra["diagnosticsOffset"] = offset + boundary + 1
        records: list[dict[str, Any]] = []
        for line in chunk[: boundary + 1].splitlines():
            try:
                document = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(document, dict):
                records.append(document)
        return records

    def diagnostics_degraded(self, handle: ProcessHandle) -> bool:
        """True when the worker could not keep every diagnostic line.

        当 worker 未能保留每一条诊断行时返回 True。
        """

        marker = (
            self.configuration.installations
            / str(handle.extra.get("worker_id", ""))
            / "diagnostics.degraded"
        )
        return marker.exists()

    def wait(self, handle: ProcessHandle, timeout: float | None = None) -> int | None:
        deadline = None if timeout is None else time.monotonic() + timeout
        while deadline is None or time.monotonic() < deadline:
            result = self.poll(handle)
            if result is not None:
                return result
            self._stopping.wait(0.2)
        return None

    def _renew(self) -> None:
        while not self._stopping.wait(25):
            with self._lock:
                for path in self._receipts.glob("*.json"):
                    receipt = json.loads(path.read_bytes())
                    if receipt["released"] or receipt["lease"] is None or not receipt.get("operation"):
                        # An uncertain start without an operation receipt must expire
                        # 对于没有 operation 回执的不确定启动,必须在 Kernel TTL 到期后
                        # under Kernel TTL rather than retaining an orphan indefinitely.
                        # 失效,不得无限期保留孤儿执行。
                        continue
                    lease = receipt["lease"]
                    try:
                        receipt["lease"] = self.kernel.authority(
                            "RenewLease",
                            {
                                "context": context("renew:" + str(uuid4())),
                                "lease": lease["identity"],
                                "fenceToken": lease["fenceToken"],
                                "ttl": "120s",
                            },
                        )
                    except grpc.RpcError:
                        receipt["renewalFailed"] = True
                    self._save(receipt)

    def close(self) -> None:
        """Stop renewing; Kernel TTL remains the execution authority.

        停止续租;Kernel TTL 仍是执行权威。
        """
        self._stopping.set()
        self._renewal.join(timeout=20)
        self.kernel.close()
