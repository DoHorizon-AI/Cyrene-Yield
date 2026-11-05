"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.package_runtime_owner                      │
│  Role: Yield-owned, durable Package Runtime binding operations.      │
│  模块职责：持久化 Yield 对 Package Runtime 绑定的授权操作。              │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from typing import Any

from .product_store import ProductStore

PACKAGE_ID = "cyrene.training.llama-factory"
CAPABILITY_ID = "training.llama-factory.v1"
PRODUCT_SOURCE_ID = "cyrene-yield"
_IDENTITY_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{1,127}\Z", re.ASCII)
_DIGEST_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z", re.ASCII)
_RECEIPT_PROTOCOL = "cyrene.runtime-maintenance.binding-operations.v1"


class PackageBindingOwnerFailure(RuntimeError):
    """A fixed, non-sensitive response for an owner operation failure.

    中文：用于 owner 操作的固定安全错误，不包含远端文本或凭据。
    """

    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(code)


class PackageBindingOwner:
    """Enforce local bearer auth and durable Product ownership for one binding.

    中文：为单个绑定执行本机 bearer 鉴权和持久化 Product 所有权检查。
    """

    def __init__(self, store: ProductStore, *, binding_id: str | None, token_sha256: str | None) -> None:
        self._store = store
        self._binding_id = binding_id if isinstance(binding_id, str) and binding_id else None
        self._token_sha256 = token_sha256 if isinstance(token_sha256, str) and token_sha256 else None

    def authorize(self, authorization: str | None) -> None:
        """Fail closed when the local owner credential is absent or invalid.

        中文：owner 凭据缺失或配置无效时默认关闭。
        """

        if self._token_sha256 is None or not _DIGEST_PATTERN.fullmatch(self._token_sha256):
            raise PackageBindingOwnerFailure(503, "YIELD_PACKAGE_BINDING_OWNER_DISABLED")
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise PackageBindingOwnerFailure(401, "YIELD_PACKAGE_BINDING_OWNER_UNAUTHORIZED")
        token = authorization[7:]
        if not token or token != token.strip():
            raise PackageBindingOwnerFailure(401, "YIELD_PACKAGE_BINDING_OWNER_UNAUTHORIZED")
        try:
            token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        except UnicodeEncodeError:
            raise PackageBindingOwnerFailure(401, "YIELD_PACKAGE_BINDING_OWNER_UNAUTHORIZED") from None
        if not hmac.compare_digest(token_digest, self._token_sha256.lower()):
            raise PackageBindingOwnerFailure(401, "YIELD_PACKAGE_BINDING_OWNER_UNAUTHORIZED")

    def require_binding(self, requested_binding_id: str) -> str:
        """Accept only the exact valid binding installed in Product configuration.

        中文：仅接受 Product 配置中的精确有效绑定身份。
        """

        if not isinstance(requested_binding_id, str) or not _IDENTITY_PATTERN.fullmatch(requested_binding_id):
            raise PackageBindingOwnerFailure(422, "YIELD_PACKAGE_BINDING_ID_INVALID")
        if self._binding_id is None or not _IDENTITY_PATTERN.fullmatch(self._binding_id):
            raise PackageBindingOwnerFailure(503, "YIELD_PACKAGE_BINDING_OWNER_DISABLED")
        if requested_binding_id != self._binding_id:
            raise PackageBindingOwnerFailure(404, "YIELD_PACKAGE_BINDING_NOT_FOUND")
        return self._binding_id

    def status(self, binding_id: str) -> dict[str, Any]:
        """Return stored phase and blocker without exposing the endpoint or receipt.

        中文：返回已存阶段和阻塞原因，不暴露 endpoint 或 receipt。
        """

        binding_id = self.require_binding(binding_id)
        return self._store.package_binding_status(binding_id)

    def activate(self, binding_id: str, installation_id: str, request_id: str) -> dict[str, Any]:
        """Persist intent, validate the signed installation, and activate exactly once.

        中文：先持久化 intent，再核验已签名安装并仅执行一次激活。
        """

        binding_id = self.require_binding(binding_id)
        if not _IDENTITY_PATTERN.fullmatch(installation_id or ""):
            raise PackageBindingOwnerFailure(422, "YIELD_PACKAGE_INSTALLATION_ID_INVALID")
        _require_request_id(request_id)

        try:
            existing = self._store.begin_package_binding_operation(request_id, binding_id, PACKAGE_ID, installation_id)
        except ValueError as error:
            code = str(error).split(":", 1)[0]
            status_code = 409
            if code == "YIELD_PACKAGE_BINDING_ACTIVE_CONFLICT":
                code = "YIELD_PACKAGE_BINDING_ACTIVE_CONFLICT"
            elif code == "YIELD_PACKAGE_BINDING_IDEMPOTENCY_CONFLICT":
                code = "YIELD_PACKAGE_BINDING_IDEMPOTENCY_CONFLICT"
            else:
                code = "YIELD_PACKAGE_BINDING_OPERATION_PENDING"
            raise PackageBindingOwnerFailure(status_code, code) from None

        if existing is not None:
            if existing.get("already_active") or existing.get("phase") == "COMPLETED":
                return self._store.package_binding_status(binding_id)
            code = (
                "YIELD_PACKAGE_BINDING_UNKNOWN"
                if existing.get("phase") == "UNKNOWN"
                else "YIELD_PACKAGE_BINDING_OPERATION_PENDING"
            )
            raise PackageBindingOwnerFailure(409, code)

        try:
            client = self._package_runtime_client()
            installation = client.get_installation(installation_id)
            _validate_installation(installation, installation_id)

            def persist_intent(persisted_request_id: str, scope: Any) -> None:
                self._store.verify_package_binding_intent(persisted_request_id, scope)

            def persist(status: Mapping[str, Any], receipt: Any) -> None:
                receipt_value = _receipt_value(
                    receipt,
                    request_id=request_id,
                    binding_id=binding_id,
                    installation_id=installation_id,
                )
                safe_status, healthy, blocker = _status_outcome(status, binding_id, installation_id)
                phase = "OUTCOME_PENDING_COMPLETE" if healthy else "PENDING_RECONCILE"
                self._store.record_package_binding_outcome(
                    request_id,
                    binding_id,
                    PACKAGE_ID,
                    installation_id,
                    safe_status,
                    receipt_value,
                    phase=phase,
                    blocker=blocker,
                )
                if not healthy:
                    raise PackageBindingOwnerFailure(409, blocker or "YIELD_PACKAGE_BINDING_NOT_RUNNING")

            client.activate_and_persist(
                binding_id,
                installation_id,
                package_id=PACKAGE_ID,
                persist_intent=persist_intent,
                persist=persist,
                request_id=request_id,
            )
            self._store.mark_package_binding_completed(request_id)
            return self._store.package_binding_status(binding_id)
        except PackageBindingOwnerFailure:
            self._preserve_or_mark_unknown(request_id, binding_id)
            raise
        except Exception as error:
            pending = getattr(error, "pending_binding_operation", None)
            if pending is not None:
                try:
                    receipt_value = _receipt_value(
                        pending,
                        request_id=request_id,
                        binding_id=binding_id,
                        installation_id=installation_id,
                    )
                    self._store.record_package_binding_outcome(
                        request_id,
                        binding_id,
                        PACKAGE_ID,
                        installation_id,
                        None,
                        receipt_value,
                        phase="PENDING_RECONCILE",
                        blocker="PACKAGE_RUNTIME_RECONCILE_REQUIRED",
                    )
                except Exception:
                    self._preserve_or_mark_unknown(request_id, binding_id)
            else:
                self._preserve_or_mark_unknown(request_id, binding_id)
            operation = self._store.package_binding_operation_for_reconcile(request_id, binding_id)
            if operation and operation.get("receipt") is not None:
                raise PackageBindingOwnerFailure(409, "YIELD_PACKAGE_BINDING_RECONCILE_REQUIRED") from None
            raise PackageBindingOwnerFailure(409, "YIELD_PACKAGE_BINDING_UNKNOWN") from None

    def reconcile(self, binding_id: str, request_id: str) -> dict[str, Any]:
        """Read back an existing receipt and actual state; never reissue Activate.

        中文：核验已存 receipt 和实际状态；绝不重发 Activate。
        """

        binding_id = self.require_binding(binding_id)
        _require_request_id(request_id)
        operation = self._store.package_binding_operation_for_reconcile(request_id, binding_id)
        if operation is None:
            raise PackageBindingOwnerFailure(404, "YIELD_PACKAGE_BINDING_REQUEST_NOT_FOUND")
        if operation["phase"] == "COMPLETED":
            return self._store.package_binding_status(binding_id)
        if operation["phase"] == "UNKNOWN" or operation.get("receipt") is None:
            raise PackageBindingOwnerFailure(409, "YIELD_PACKAGE_BINDING_UNKNOWN")
        if operation["phase"] not in {"OUTCOME_PENDING_COMPLETE", "PENDING_RECONCILE"}:
            raise PackageBindingOwnerFailure(409, "YIELD_PACKAGE_BINDING_PHASE_CONFLICT")
        if operation["operation"] != "activate" or operation["package_id"] != PACKAGE_ID:
            raise PackageBindingOwnerFailure(409, "YIELD_PACKAGE_BINDING_SCOPE_CONFLICT")

        try:
            client = self._package_runtime_client()
            receipt = _restore_receipt(operation["receipt"])

            def persist_reconciled(
                status: Mapping[str, Any], installation: Mapping[str, Any], same_receipt: Any
            ) -> None:
                _validate_installation(installation, operation["installation_id"])
                receipt_value = _receipt_value(
                    same_receipt,
                    request_id=request_id,
                    binding_id=binding_id,
                    installation_id=operation["installation_id"],
                )
                if receipt_value != operation["receipt"]:
                    raise PackageBindingOwnerFailure(409, "YIELD_PACKAGE_BINDING_RECEIPT_CONFLICT")
                safe_status, healthy, blocker = _status_outcome(status, binding_id, operation["installation_id"])
                if not healthy:
                    raise PackageBindingOwnerFailure(409, blocker or "YIELD_PACKAGE_BINDING_NOT_RUNNING")
                self._store.record_package_binding_outcome(
                    request_id,
                    binding_id,
                    PACKAGE_ID,
                    operation["installation_id"],
                    safe_status,
                    receipt_value,
                    phase="OUTCOME_PENDING_COMPLETE",
                    blocker="PACKAGE_RUNTIME_COMPLETE_PENDING",
                )

            client.reconcile_binding_operation_and_persist(receipt, reconcile=persist_reconciled)

            self._store.mark_package_binding_completed(request_id)
            return self._store.package_binding_status(binding_id)
        except PackageBindingOwnerFailure:
            raise
        except Exception:
            raise PackageBindingOwnerFailure(409, "YIELD_PACKAGE_BINDING_RECONCILE_REQUIRED") from None

    def _package_runtime_client(self) -> Any:
        """Create the SDK client from this real Yield service process environment.

        中文：仅从真实 Yield 服务进程环境创建 SDK 客户端。
        """

        try:
            from cyrene_runtime_maintenance import PackageRuntimeClient

            client = PackageRuntimeClient.from_environment()
        except (ImportError, OSError, ValueError):
            raise PackageBindingOwnerFailure(503, "YIELD_PACKAGE_RUNTIME_UNAVAILABLE") from None
        if getattr(client, "source_id", None) != PRODUCT_SOURCE_ID:
            raise PackageBindingOwnerFailure(503, "YIELD_PACKAGE_RUNTIME_SOURCE_INVALID")
        return client

    def _preserve_or_mark_unknown(self, request_id: str, binding_id: str) -> None:
        operation = self._store.package_binding_operation_for_reconcile(request_id, binding_id)
        if operation is not None and operation.get("receipt") is None:
            self._store.mark_package_binding_unknown(request_id, "PACKAGE_RUNTIME_OUTCOME_UNKNOWN")


def _require_request_id(request_id: str) -> None:
    """Match the SDK's bounded stable request ID contract at the HTTP boundary.

    中文：在 HTTP 边界执行 SDK 的有界稳定请求 ID 约束。
    """

    if not isinstance(request_id, str) or not request_id or request_id != request_id.strip():
        raise PackageBindingOwnerFailure(422, "YIELD_PACKAGE_BINDING_REQUEST_ID_INVALID")
    try:
        encoded = request_id.encode("utf-8")
    except UnicodeEncodeError:
        raise PackageBindingOwnerFailure(422, "YIELD_PACKAGE_BINDING_REQUEST_ID_INVALID") from None
    if len(encoded) > 256 or any(ord(character) < 32 or ord(character) == 127 for character in request_id):
        raise PackageBindingOwnerFailure(422, "YIELD_PACKAGE_BINDING_REQUEST_ID_INVALID")


def _receipt_value(
    receipt: Any,
    *,
    request_id: str,
    binding_id: str,
    installation_id: str,
) -> dict[str, Any]:
    """Serialize a typed SDK receipt for private SQLite storage only.

    中文：仅供私有 SQLite 存储的 typed SDK receipt 序列化。
    """

    scope = getattr(receipt, "scope", None)
    expected = (
        getattr(receipt, "request_id", None) == request_id
        and getattr(receipt, "source_id", None) == PRODUCT_SOURCE_ID
        and getattr(receipt, "protocol_version", None) == _RECEIPT_PROTOCOL
        and getattr(receipt, "catalog_generation", None) is not None
        and type(getattr(receipt, "catalog_generation", None)) is int
        and getattr(receipt, "catalog_generation", 0) > 0
        and type(getattr(receipt, "gate_generation", None)) is int
        and getattr(receipt, "gate_generation", 0) > 0
        and isinstance(getattr(receipt, "operation_token", None), str)
        and bool(getattr(receipt, "operation_token", ""))
        and len(getattr(receipt, "operation_token", "")) <= 4096
        and not any(ord(character) < 32 for character in getattr(receipt, "operation_token", ""))
        and type(getattr(receipt, "already_in_flight", None)) is bool
        and type(getattr(receipt, "already_completed", None)) is bool
        and not getattr(receipt, "already_completed", False)
        and not (getattr(receipt, "already_in_flight", False) and getattr(receipt, "already_completed", False))
        and getattr(scope, "binding_id", None) == binding_id
        and getattr(scope, "package_id", None) == PACKAGE_ID
        and getattr(scope, "installation_id", None) == installation_id
        and getattr(scope, "operation", None) == "activate"
    )
    if not expected:
        raise PackageBindingOwnerFailure(409, "YIELD_PACKAGE_BINDING_RECEIPT_INVALID")
    value = {
        "request_id": receipt.request_id,
        "source_id": receipt.source_id,
        "protocol_version": receipt.protocol_version,
        "scope": {
            "binding_id": scope.binding_id,
            "package_id": scope.package_id,
            "installation_id": scope.installation_id,
            "operation": scope.operation,
        },
        "catalog_generation": receipt.catalog_generation,
        "gate_generation": receipt.gate_generation,
        "operation_token": receipt.operation_token,
        "already_in_flight": bool(receipt.already_in_flight),
        "already_completed": bool(receipt.already_completed),
    }
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _restore_receipt(value: dict[str, Any]) -> Any:
    """Rebuild the SDK receipt from a private database row without logging it.

    中文：从私有数据库记录恢复 SDK receipt，且不将其写入日志。
    """

    try:
        from cyrene_runtime_maintenance import BindingOperationReceipt, BindingOperationScope

        scope_value = value["scope"]
        scope = BindingOperationScope(
            binding_id=scope_value["binding_id"],
            package_id=scope_value["package_id"],
            installation_id=scope_value["installation_id"],
            operation=scope_value["operation"],
        )
        return BindingOperationReceipt(
            request_id=value["request_id"],
            source_id=value["source_id"],
            protocol_version=value["protocol_version"],
            catalog_generation=value["catalog_generation"],
            scope=scope,
            operation_token=value["operation_token"],
            gate_generation=value["gate_generation"],
            already_in_flight=value["already_in_flight"],
            already_completed=value["already_completed"],
        )
    except (ImportError, KeyError, TypeError, ValueError):
        raise PackageBindingOwnerFailure(409, "YIELD_PACKAGE_BINDING_RECEIPT_INVALID") from None


def _validate_installation(installation: Any, installation_id: str) -> None:
    """Require the exact installed package and advertised training capability.

    中文：要求安装身份精确匹配，且已安装 package 声明训练 capability。
    """

    if (
        not isinstance(installation, Mapping)
        or installation.get("installation_id") != installation_id
        or installation.get("package_id") != PACKAGE_ID
        or installation.get("state") != "INSTALLED"
        or not isinstance(installation.get("capabilities"), list)
        or CAPABILITY_ID not in installation["capabilities"]
    ):
        raise PackageBindingOwnerFailure(409, "YIELD_PACKAGE_INSTALLATION_NOT_READY")


def _status_outcome(status: Any, binding_id: str, installation_id: str) -> tuple[dict[str, Any] | None, bool, str]:
    """Validate RuntimeStatus and return a private, bounded snapshot plus readiness.

    中文：核验 RuntimeStatus，并返回有界私有快照与健康判断。
    """

    fields = {
        "binding_id",
        "installation_id",
        "generation",
        "state",
        "failure_code",
        "failure_message",
        "connection_ref",
    }
    if not isinstance(status, Mapping) or not fields.issubset(status):
        return None, False, "PACKAGE_RUNTIME_STATUS_INVALID"
    if status.get("binding_id") != binding_id or status.get("installation_id") != installation_id:
        return None, False, "PACKAGE_RUNTIME_SCOPE_MISMATCH"
    generation = status.get("generation")
    state = status.get("state")
    failure_code = status.get("failure_code")
    failure_message = status.get("failure_message")
    connection_ref = status.get("connection_ref")
    if (
        type(generation) is not int
        or generation <= 0
        or not isinstance(state, str)
        or state not in {"RUNNING", "STOPPED", "FAILED"}
        or (failure_code is not None and not _bounded_protocol_text(failure_code))
        or (failure_message is not None and not _bounded_protocol_text(failure_message))
        or (connection_ref is not None and not _valid_connection_ref(connection_ref))
    ):
        return None, False, "PACKAGE_RUNTIME_STATUS_INVALID"
    snapshot = {
        "binding_id": binding_id,
        "installation_id": installation_id,
        "generation": generation,
        "state": state,
        "failure_code": failure_code,
        "failure_message": failure_message,
        "connection_ref": connection_ref,
    }
    healthy = state == "RUNNING" and failure_code is None and failure_message is None and bool(connection_ref)
    return (
        snapshot,
        healthy,
        "PACKAGE_RUNTIME_BINDING_NOT_HEALTHY" if not healthy else "PACKAGE_RUNTIME_COMPLETE_PENDING",
    )


def _bounded_protocol_text(value: Any, *, max_length: int = 4096) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= max_length
        and not any(ord(character) < 32 or 0x7F <= ord(character) <= 0x9F for character in value)
    )


def _valid_connection_ref(value: Any) -> bool:
    """Match Yield's accepted opaque local endpoint size and whitespace rules.

    中文：按 Yield 接受的不透明本机 endpoint 长度和空白规则校验。
    """

    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return len(encoded) <= 2048 and not any(
        0 <= ord(character) < 32 or 0x7F <= ord(character) <= 0x9F for character in value
    )
