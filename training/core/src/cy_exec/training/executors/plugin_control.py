"""Product-private control envelopes for Yield's training worker.

These Product-private messages are sent directly to the training worker. They
do not project a Platform or public Plugin protocol and never travel through
KernelAuthorityService. They coordinate only the Product-owned worker process.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/executors/plugin_control.py
# │ Module: training/core/src/cy_exec/training/executors/plugin_control
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ..contracts.workload import WorkloadConfigureSettings, assert_configure_is_not_training_spec

# Worker SDK implements Cancel → CancelAck (receipt only). Kernel authority
# still requires StopWorker + physical cleanup before Product CANCELLED.
PLUGIN_INVOKE_CANCEL_SUPPORTED = True

GENERIC_WORKER_EXTENSION_POINT = "cyrene.worker"
GENERIC_WORKER_RUN_METHOD = "run"


class PluginEnvelopeUndeliverable(RuntimeError):
    """Product has no direct training worker or Plugin connection."""


class WorkloadControlError(RuntimeError):
    def __init__(self, message: str, *, lost: bool = False, cleanup_attempted: bool = False) -> None:
        super().__init__(message)
        self.lost = lost
        self.cleanup_attempted = cleanup_attempted


@dataclass(frozen=True)
class PluginConfigure:
    settings: Dict[str, str]
    request_id: str = ""
    generation: int = 0
    fence_token: int = 0

    def to_dict(self) -> Dict[str, Any]:
        assert_configure_is_not_training_spec(self.settings)
        return {
            "payload": "Configure",
            "settings": dict(self.settings),
            "request_id": self.request_id,
            "generation": self.generation,
            "fence_token": self.fence_token,
        }


@dataclass(frozen=True)
class PluginInvoke:
    extension_point: str = GENERIC_WORKER_EXTENSION_POINT
    method: str = GENERIC_WORKER_RUN_METHOD
    request_id: str = ""
    generation: int = 0
    fence_token: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "payload": "Invoke",
            "extension_point": self.extension_point,
            "method": self.method,
            "request_id": self.request_id,
            "generation": self.generation,
            "fence_token": self.fence_token,
        }


@dataclass(frozen=True)
class PluginCancel:
    target_request_id: str
    reason: str = "product-cancel"
    request_id: str = ""
    generation: int = 0
    fence_token: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "payload": "Cancel",
            "target_request_id": self.target_request_id,
            "reason": self.reason,
            "request_id": self.request_id,
            "generation": self.generation,
            "fence_token": self.fence_token,
            "ack_is_receipt_only": True,
        }


def configure_from_workload(
    settings: WorkloadConfigureSettings,
    *,
    request_id: str = "",
    generation: int = 0,
    fence_token: int = 0,
) -> PluginConfigure:
    payload = settings.to_settings_map()
    assert_configure_is_not_training_spec(payload)
    return PluginConfigure(
        settings=payload,
        request_id=request_id,
        generation=generation,
        fence_token=fence_token,
    )
