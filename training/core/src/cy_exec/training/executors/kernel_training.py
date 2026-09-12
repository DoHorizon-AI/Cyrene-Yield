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
import subprocess
import tempfile
import threading
import time
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
    """Operator configuration, never accepted as a Product handoff payload."""

    model_config = ConfigDict(extra="forbid")
    socket: Path
    installations: Path
    state_directory: Path
    python: Path
    signing_key_file: Path
    minimum_memory_bytes: int = Field(default=1024**3, gt=0)
    allow_wsl_shared_device: bool = False


def _document(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


class KernelTrainingExecutor:
    """Kernel owns process trees and leases; files are private execution receipts."""

    def __init__(self, configuration: KernelTrainingConfiguration, *, client: Any = None) -> None:
        self.configuration = configuration
        self.kernel = client or KernelClient(configuration.socket)
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._receipts = configuration.state_directory / "execution-receipts"
        self._receipts.mkdir(parents=True, exist_ok=True)
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

    def hardware_facts(self) -> HardwareFacts:
        """Project the Kernel's NVIDIA CUDA inventory into the existing preflight contract."""
        facts = self.kernel.capabilities()
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
                    # is made about optional BF16/FP16/quantized execution support.
                    features=("fp32",),
                )
            )
        return HardwareFacts.from_node_resource_inventory(
            node_id=facts["node"]["nodeId"],
            inventory_generation=int(facts["inventoryGeneration"]),
            accelerators=accelerators,
            accelerator_runtime="cuda",
            architecture=platform.machine().lower(),
        )

    def recover(self) -> list[tuple[TrainingLaunchSpec, ProcessHandle]]:
        """Restore existing receipt handles without acquiring another lease."""
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
        """Acquire and start through Kernel; never spawn a training subprocess here."""
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
                        pass  # Propagated as LOST, never a successful cleanup receipt.
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
        """A trainer exit plus confirmed Kernel cleanup precedes terminal success."""
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
                        # under Kernel TTL rather than retaining an orphan indefinitely.
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
        """Stop renewing; Kernel TTL remains the execution authority."""
        self._stopping.set()
        self._renewal.join(timeout=20)
        self.kernel.close()
