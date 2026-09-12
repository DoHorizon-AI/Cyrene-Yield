"""Typed Kernel authority commands for origin/develop (cyrene.core.v1).

These models project KernelAuthorityService. They are not cy.llm.AgentService
and must never grow ExecuteCommandStream argv/env/payload fields.

Pinned generic control-plane base:

    Cyrene-Platform @ c59be6f2bd82489fbe933dadff84fc589e00afd9
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/kernel_commands.py
# │ Module: training/core/src/cy_exec/training/executors/kernel_commands
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

LEGACY_KERNEL_MARKERS = frozenset(
    {
        "AgentService",
        "ExecuteCommandStream",
        "cy.llm",
        "AgentCommandRequest",
        "command_type",
        "payload",
    }
)

# Opaque to Kernel Core. Format owned by FilesystemInstalledPluginResolver:
# installation-name@sha256:digest
DEFAULT_TRAINING_WORKER_EXECUTION_REF = "cyrene-training-worker@sha256:pending-install"


@dataclass(frozen=True)
class KernelIdentity:
    id: str
    generation: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "generation": self.generation}


@dataclass(frozen=True)
class ResourceQuery:
    resource_class: str = "accelerator"
    count: int = 1
    required_capabilities: List[str] = field(default_factory=lambda: ["accelerator.compute"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_class": self.resource_class,
            "count": self.count,
            "required_capabilities": list(self.required_capabilities),
        }


@dataclass(frozen=True)
class AcquireLeaseCommand:
    """AcquireLeaseRequest. One lease holds query.count resources."""

    holder: KernelIdentity
    query: ResourceQuery
    ttl_seconds: int = 3600

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rpc": "AcquireLease",
            "holder": self.holder.to_dict(),
            "query": self.query.to_dict(),
            "ttl_seconds": self.ttl_seconds,
        }


@dataclass(frozen=True)
class StartWorkerCommand:
    """StartWorkerRequest. Worker.execution_ref only; no argv/env."""

    worker_id: str
    principal_id: str
    lease_id: str
    lease_generation: int
    execution_ref: str
    state: str = "REGISTERED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rpc": "StartWorker",
            "worker": {
                "identity": {"id": self.worker_id, "generation": 0},
                "principal": {"id": self.principal_id, "generation": 0},
                "lease": {"id": self.lease_id, "generation": self.lease_generation},
                "state": self.state,
                "execution_ref": self.execution_ref,
            },
        }


@dataclass(frozen=True)
class StopWorkerCommand:
    worker_id: str
    lease_id: str
    fence_token: int
    grace_period_seconds: float = 15.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rpc": "StopWorker",
            "worker": {"id": self.worker_id, "generation": 0},
            "lease": {"id": self.lease_id, "generation": 0},
            "fence_token": self.fence_token,
            "grace_period_seconds": self.grace_period_seconds,
        }


@dataclass(frozen=True)
class CancelOperationCommand:
    operation_id: str
    operation_generation: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rpc": "CancelOperation",
            "operation": {
                "id": self.operation_id,
                "generation": self.operation_generation,
            },
        }


def assert_no_legacy_agent_contract(payload: Mapping[str, Any] | str) -> None:
    blob = payload if isinstance(payload, str) else str(payload)
    for marker in LEGACY_KERNEL_MARKERS:
        if marker in blob:
            raise ValueError(
                f"production Kernel mapping must not use legacy {marker}; "
                "canonical contract is origin/develop KernelAuthorityService"
            )


def assert_start_worker_has_no_launch_argv(command: Mapping[str, Any]) -> None:
    assert_no_legacy_agent_contract(command)
    worker = command.get("worker") or {}
    if "argv" in command or "argv" in worker:
        raise ValueError("StartWorker must not carry TrainingLaunchSpec.argv")
    if "env" in command or "env" in worker:
        raise ValueError("StartWorker must not carry process env / CUDA visibility")
    if not str(worker.get("execution_ref") or command.get("execution_ref") or "").strip():
        raise ValueError("StartWorker requires opaque execution_ref")


def plugin_configure_settings(
    *,
    spec_artifact_path: Optional[str],
    output_root: str,
) -> Dict[str, str]:
    """Map per-attempt workload onto the compatibility worker settings.

    Kernel StartWorker has no per-attempt business config field. Yield sends
    these settings directly to its worker after Platform returns lifecycle facts.
    """

    settings = {"output_root": output_root}
    if spec_artifact_path:
        settings["training_spec_path"] = spec_artifact_path
        settings["spec_artifact_path"] = spec_artifact_path
    return settings
