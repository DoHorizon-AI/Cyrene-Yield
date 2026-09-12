"""
┌─────────────────────────────────────────────────────────────────────┐
│ Module: Kernel training adapter contract tests                     │
│ Role: Verify existing RPC encoding, signed launch and cleanup gates.│
│ 模块职责：验证 RPC 契约、安装签名与回收门禁；不启动训练器或 GPU。        │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from google.protobuf import json_format, message_factory

from cy_exec.training.contracts import TrainingLaunchSpec, EngineKind, DistributedSpec, CheckpointSpec
from cy_exec.training.executors.kernel_rpc import KernelClient
from cy_exec.training.executors.kernel_training import KernelTrainingConfiguration, KernelTrainingExecutor
from cy_exec.training.executors.plugin_control import WorkloadControlError


class ContractKernel:
    """Validate requests using the shipped Platform descriptor, then return fixture replies."""

    def __init__(self, path):
        self.encoder = KernelClient(path / "unused.sock")
        self.calls = []
        self.released = True
        self.fail_start = False
        self.shared = False

    def capabilities(self):
        return {
            "node": {"nodeId": "unit-node", "nodeEpoch": "7"},
            "inventoryGeneration": "12",
            "resources": [
                {
                    "identity": {"id": "unit-gpu", "generation": "1"},
                    "capabilities": [{"id": "vendor.nvidia.cuda", "revision": "1"}],
                    "capacity": {
                        "memory.total": {"value": str(24 * 1024**3), "unit": "byte"},
                        "memory.allocatable": {"value": str(20 * 1024**3), "unit": "byte"},
                    },
                    "attributes": {"device.binding": "wsl-shared-soft" if self.shared else "nvidia-cgroup"},
                }
            ],
        }

    def authority(self, method, payload):
        descriptor = self.encoder.pool.FindServiceByName("cyrene.core.v1.KernelAuthorityService")
        kind = message_factory.GetMessageClass(descriptor.methods_by_name[method].input_type)
        json_format.ParseDict(payload, kind())
        self.calls.append((method, payload))
        if method == "AcquireLease":
            return {"identity": {"id": "unit-lease", "generation": "1"}, "fenceToken": "42"}
        if method == "StartWorker":
            if self.fail_start:
                raise ValueError("fixture start failure")
            return {"identity": {"id": "unit-start", "generation": "1"}}
        if method == "ReleaseLease":
            return {"state": "LEASE_STATE_RELEASED" if self.released else "LEASE_STATE_ACTIVE"}
        raise AssertionError(method)

    def close(self):
        self.encoder.close()


def configured(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "signing-key"
    path.write_bytes(key.private_bytes_raw())
    path.chmod(0o600)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0],
            0,
            stdout=json.dumps(
                {
                    "llamafactory": "unit-fixture",
                    "torch": "unit-fixture",
                    "transformers": "unit-fixture",
                    "peft": "unit-fixture",
                    "grpcio": "unit-fixture",
                    "protobuf": "unit-fixture",
                }
            ),
        ),
    )
    kernel = ContractKernel(tmp_path)
    config = KernelTrainingConfiguration(
        socket=tmp_path / "kernel.sock",
        installations=tmp_path / "installations",
        state_directory=tmp_path / "state",
        python=Path(sys.executable),
        signing_key_file=path,
    )
    executor = KernelTrainingExecutor(config, client=kernel)
    root = tmp_path / "output"
    root.mkdir()
    launch = TrainingLaunchSpec(
        engine=EngineKind.LLAMA_FACTORY,
        argv=[sys.executable, "-m", "llamafactory.cli", "train", str(root / "config.yaml")],
        work_dir=str(root),
        cwd=str(root),
        distributed=DistributedSpec(),
        checkpoint=CheckpointSpec(),
    )
    return executor, kernel, key, launch


def test_signed_launch_uses_existing_kernel_rpc_and_confirms_cleanup(tmp_path, monkeypatch):
    executor, kernel, key, launch = configured(tmp_path, monkeypatch)
    try:
        facts = executor.hardware_facts()
        assert facts.inventory_generation == 12
        assert facts.precision_support("fp32") is True
        assert facts.precision_support("bf16") is False
        handle = executor.start(launch)
        assert [method for method, _ in kernel.calls] == ["AcquireLease", "StartWorker"]
        installed = tmp_path / "installations" / handle.extra["worker_id"]
        key.public_key().verify(
            (installed / "installation.sig").read_bytes(), (installed / "installation-manifest.json").read_bytes()
        )
        receipt = json.loads((installed / "worker.json").read_text())
        assert receipt["launch"]["argv"] == launch.argv
        assert handle.extra["node_id"] == "unit-node"
        assert executor.recover()[0][0].to_dict() == launch.to_dict()
        (installed / "completion.json").write_text(json.dumps({"worker": receipt["worker"], "exitCode": 0}))
        kernel.released = False
        with pytest.raises(ValueError, match="YIELD_CLEANUP_UNCONFIRMED"):
            executor.poll(handle)
        kernel.released = True
        assert executor.poll(handle) == 0
        assert executor.cancel(handle).cleanup_confirmed
    finally:
        executor.close()


def test_start_failure_retains_receipt_and_requires_cleanup(tmp_path, monkeypatch):
    executor, kernel, _key, launch = configured(tmp_path, monkeypatch)
    kernel.fail_start = True
    try:
        with pytest.raises(WorkloadControlError) as caught:
            executor.start(launch)
        assert caught.value.cleanup_attempted and not caught.value.lost
        assert kernel.calls[-1][0] == "ReleaseLease"
        receipt = next((tmp_path / "state" / "execution-receipts").glob("*.json"))
        assert json.loads(receipt.read_text())["released"] is True
    finally:
        executor.close()


def test_shared_wsl_device_needs_explicit_operator_admission(tmp_path, monkeypatch):
    executor, kernel, _key, launch = configured(tmp_path, monkeypatch)
    kernel.shared = True
    try:
        with pytest.raises(WorkloadControlError, match="YIELD_KERNEL_ADMISSION_FAILED") as caught:
            executor.start(launch)
        assert not caught.value.lost and not caught.value.cleanup_attempted
        assert kernel.calls == []
    finally:
        executor.close()
