"""Yield adapter for the Plugins-owned LLaMA Factory capability.

Yield 针对 Plugins 所有的 LLaMA Factory 能力的适配器。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from ...checkpoint import CheckpointManager
from ...contracts import (
    EngineInspect,
    EngineKind,
    EngineValidation,
    TrainingEvent,
    TrainingEventKind,
    TrainingLaunchSpec,
    TrainingResult,
    TrainingSpec,
    TrainingStatus,
    require_engine_kind,
)
from ...validation import validate_training_spec

LOGGER = logging.getLogger("cy_exec.training.engines.llamafactory")
CAPABILITY_ID = "training.llama-factory.v1"
INTERFACE_VERSION = "1"
PACKAGE_RUNTIME_BINDING_ENV = "CYRENE_LLAMA_FACTORY_PACKAGE_BINDING_ID"
PACKAGE_RUNTIME_PACKAGE_ID = "cyrene.training.llama-factory"
EXPECTED_ACTIVITY_SOURCE_ID = "cyrene-yield"


class LlamaFactoryPackageRuntimeError(RuntimeError):
    """A fail-closed Package Runtime status or owner-policy rejection.

    中文：Package Runtime 状态或 owner 授权校验失败时拒绝连接。
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class LlamaFactoryPluginConnection:
    """Small Product-side connector for one resolved DirectPlugin endpoint.

    面向一个已解析 DirectPlugin 端点的小型 Product 连接器。
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_environment(cls) -> "LlamaFactoryPluginConnection":
        if PACKAGE_RUNTIME_BINDING_ENV in os.environ:
            binding_id = os.environ[PACKAGE_RUNTIME_BINDING_ENV]
            if not _is_package_runtime_identity(binding_id):
                raise LlamaFactoryPackageRuntimeError(
                    "YIELD_PACKAGE_RUNTIME_BINDING_INVALID",
                    f"{PACKAGE_RUNTIME_BINDING_ENV} must be a valid Platform BindingId",
                )
            connection_ref = cls._connection_ref_from_package_runtime(binding_id)
        else:
            connection_ref = os.environ.get("CYRENE_LLAMA_FACTORY_CONNECTION_REF", "").strip()
            if not connection_ref:
                raise RuntimeError(
                    "YIELD_PLUGIN_UNAVAILABLE: set CYRENE_LLAMA_FACTORY_CONNECTION_REF "
                    "to the resolved training.llama-factory.v1 endpoint"
                )
        try:
            from cyrene_plugin_runtime import DirectPluginClient
        except ImportError as exc:
            raise RuntimeError("YIELD_PLUGIN_RUNTIME_MISSING: install the Plugins direct runtime SDK") from exc
        return cls(DirectPluginClient.for_local_connection_ref(connection_ref))

    @staticmethod
    def _connection_ref_from_package_runtime(binding_id: str) -> str:
        """Resolve one healthy, exact package binding through read-only SDK calls.

        Package Runtime owns activation. Yield only verifies the existing binding
        and uses its opaque endpoint; it never starts or stops the package.
        中文：Yield 只读核验既有绑定，不负责启动或停止 package。
        """
        try:
            from cyrene_runtime_maintenance import PackageRuntimeClient, PackageRuntimeError
        except ImportError as exc:
            raise LlamaFactoryPackageRuntimeError(
                "YIELD_PACKAGE_RUNTIME_SDK_MISSING",
                "install the verified cyrene-runtime-maintenance SDK wheel",
            ) from exc

        try:
            client = PackageRuntimeClient.from_environment()
        except (PackageRuntimeError, ValueError) as exc:
            raise LlamaFactoryPackageRuntimeError(
                "YIELD_PACKAGE_RUNTIME_OWNER_CONFIG_INVALID",
                "Product source credentials or Package Runtime settings are unavailable",
            ) from exc

        if getattr(client, "source_id", None) != EXPECTED_ACTIVITY_SOURCE_ID:
            raise LlamaFactoryPackageRuntimeError(
                "YIELD_PACKAGE_RUNTIME_SOURCE_INVALID",
                "Package Runtime must use the installed cyrene-yield activity source",
            )

        try:
            status = client.runtime_status(binding_id)
        except PackageRuntimeError as exc:
            raise LlamaFactoryPackageRuntimeError(
                "YIELD_PACKAGE_RUNTIME_REJECTED",
                f"Package Runtime rejected the owner status request ({exc.code})",
            ) from exc

        connection_ref, installation_id = _validate_package_runtime_status(status, binding_id)
        try:
            installation = client.get_installation(installation_id)
        except PackageRuntimeError as exc:
            raise LlamaFactoryPackageRuntimeError(
                "YIELD_PACKAGE_RUNTIME_REJECTED",
                f"Package Runtime rejected the owner installation read ({exc.code})",
            ) from exc
        _validate_llama_factory_installation(installation, installation_id)
        return connection_ref

    def invoke(self, method: str, request: dict[str, Any]) -> dict[str, Any]:
        """Invoke one typed JSON method and decode only capability-owned bytes.

        调用一个有类型的 JSON 方法,只解码该能力所有的字节。
        """
        request_type_url = f"type.cyrene.io/{CAPABILITY_ID}.{method}.request"
        response = self._client.invoke(
            capability=CAPABILITY_ID,
            interface_version=INTERFACE_VERSION,
            method=method,
            request=self._payload(request_type_url, request),
        )
        return json.loads(response.value.decode("utf-8"))

    @staticmethod
    def _payload(type_url: str, request: dict[str, Any]) -> Any:
        from cyrene_plugin_runtime import DirectPayload

        return DirectPayload(type_url=type_url, value=json.dumps(request).encode("utf-8"))


class LlamaFactoryEngineAdapter:
    """Adapt Yield contracts to the Plugins-owned LLaMA Factory endpoint.

    将 Yield 契约适配到 Plugins 所有的 LLaMA Factory 端点。
    """

    kind = EngineKind.LLAMA_FACTORY

    def __init__(self, connection: LlamaFactoryPluginConnection | Any | None = None) -> None:
        self._connection = connection

    def _resolved_connection(self) -> Any:
        if self._connection is None:
            self._connection = LlamaFactoryPluginConnection.from_environment()
        return self._connection

    def inspect(self) -> EngineInspect:
        notes = [
            "Plugins-owned LLaMA Factory implementation via DirectPluginRuntime.",
            "Yield owns Product lifecycle and attempt state.",
        ]
        try:
            result = self._resolved_connection().invoke("inspect", {})
        except RuntimeError as exc:
            notes.append(str(exc))
            return EngineInspect(
                engine=self.kind,
                available=False,
                supported_strategies=[],
                supported_finetune_types=[],
                notes=notes,
            )
        from ...contracts.status import DistributedStrategy

        return EngineInspect(
            engine=self.kind,
            available=bool(result.get("available")),
            version=result.get("version"),
            supported_strategies=[
                DistributedStrategy(value)
                for value in result.get("supported_strategies", [])
                if value in {item.value for item in DistributedStrategy}
            ],
            supported_finetune_types=list(result.get("supported_finetune_types", [])),
            notes=notes + list(result.get("notes", [])),
        )

    def validate(self, spec: TrainingSpec) -> EngineValidation:
        require_engine_kind(spec, self.kind)
        return validate_training_spec(spec)

    def compile(self, spec: TrainingSpec) -> TrainingLaunchSpec:
        require_engine_kind(spec, self.kind)
        validation = self.validate(spec)
        if not validation.ok:
            messages = "; ".join(issue.message for issue in validation.issues)
            raise ValueError(f"LLaMA-Factory spec is invalid: {messages}")
        result = self._resolved_connection().invoke("compile", {"spec": spec.to_dict()})
        launch = result.get("launch")
        if not isinstance(launch, dict):
            raise ValueError("YIELD_PLUGIN_PROTOCOL_INVALID: compile response has no launch")
        return TrainingLaunchSpec(**launch)

    def parse_event(self, line: str) -> TrainingEvent | None:
        text = line.strip()
        if not text:
            return None
        try:
            result = self._resolved_connection().invoke("parse_event", {"line": text})
        except LlamaFactoryPackageRuntimeError:
            raise
        except RuntimeError:
            return TrainingEvent(kind=TrainingEventKind.LOG, message=text, raw=text)
        if not result:
            return None
        kind = TrainingEventKind(result.get("kind", "log"))
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        return TrainingEvent(
            kind=kind,
            message=str(result.get("message") or text),
            step=_as_int(payload.get("current_steps") or payload.get("step") or result.get("step")),
            loss=_as_float(payload.get("loss") or result.get("loss")),
            learning_rate=_as_float(payload.get("learning_rate") or result.get("learning_rate")),
            raw=str(result.get("raw") or text),
            payload=payload,
        )

    def collect_result(
        self,
        spec: TrainingSpec,
        launch: TrainingLaunchSpec,
        exit_code: int | None,
        status: TrainingStatus,
    ) -> TrainingResult:
        manager = CheckpointManager(spec.output_dir, save_total_limit=spec.checkpoint.save_total_limit)
        digest, size, path = manager.collect_digest(spec.output_dir)
        if not digest:
            digest, size, path = manager.collect_digest()
        message = "training finished"
        if status == TrainingStatus.CANCELLED:
            message = "training cancelled"
        elif status == TrainingStatus.LOST:
            message = "training process could not be confirmed stopped"
        elif status == TrainingStatus.FAILED:
            message = f"training failed with exit code {exit_code}"
        return TrainingResult(
            status=status,
            output_dir=spec.output_dir,
            checkpoint_path=path,
            checkpoint_digest=digest,
            checkpoint_size_bytes=size,
            exit_code=exit_code,
            message=message,
        )


def _as_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None  # diagnostic-allow: Invalid optional integer is represented as absent.


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None  # diagnostic-allow: Invalid optional float is represented as absent.


def _validate_package_runtime_status(status: Any, binding_id: str) -> tuple[str, str]:
    """Accept only the exact active binding and its live opaque endpoint.

    The Rust RuntimeStatus contract serializes ``RuntimeState::Running`` as
    ``RUNNING`` and carries the durable InstallationId with each binding.
    中文：只接受目标绑定正在运行、无失败且带真实连接引用的状态。
    """
    required_fields = {
        "binding_id",
        "installation_id",
        "generation",
        "state",
        "failure_code",
        "failure_message",
        "connection_ref",
    }
    if not isinstance(status, dict) or not required_fields.issubset(status):
        raise LlamaFactoryPackageRuntimeError(
            "YIELD_PACKAGE_RUNTIME_STATUS_INVALID",
            "Package Runtime returned an incomplete binding status",
        )
    if status["binding_id"] != binding_id:
        raise LlamaFactoryPackageRuntimeError(
            "YIELD_PACKAGE_RUNTIME_BINDING_MISMATCH",
            "Package Runtime returned a different binding identity",
        )
    generation = status["generation"]
    if type(generation) is not int or generation <= 0:
        raise LlamaFactoryPackageRuntimeError(
            "YIELD_PACKAGE_RUNTIME_STATUS_INVALID",
            "Package Runtime returned an invalid runtime generation",
        )
    if status["state"] != "RUNNING" or status["failure_code"] is not None or status["failure_message"] is not None:
        raise LlamaFactoryPackageRuntimeError(
            "YIELD_PACKAGE_RUNTIME_UNHEALTHY",
            "the configured LLaMA-Factory package binding is not healthy and running",
        )

    installation_id = status["installation_id"]
    connection_ref = status["connection_ref"]
    if not _is_package_runtime_identity(installation_id):
        raise LlamaFactoryPackageRuntimeError(
            "YIELD_PACKAGE_RUNTIME_STATUS_INVALID",
            "Package Runtime returned an invalid installation identity",
        )
    if not _is_package_runtime_connection_ref(connection_ref):
        raise LlamaFactoryPackageRuntimeError(
            "YIELD_PACKAGE_RUNTIME_ENDPOINT_INVALID",
            "Package Runtime did not return a valid opaque service endpoint",
        )
    return connection_ref, installation_id


def _is_package_runtime_connection_ref(value: Any) -> bool:
    """Mirror the Platform supervisor's opaque endpoint input limits.

    中文：校验连接引用符合 Platform supervisor 的长度、空白和控制字符约束。
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


def _is_package_runtime_identity(value: Any) -> bool:
    """Mirror the Platform identity syntax before making a second SDK request.

    中文：在请求安装记录前使用 Platform 相同的 package identity 字符规则。
    """
    if not isinstance(value, str):
        return False
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return (
        2 <= len(encoded) <= 128
        and (48 <= encoded[0] <= 57 or 97 <= encoded[0] <= 122)
        and all(48 <= byte <= 57 or 97 <= byte <= 122 or byte in (ord("."), ord("_"), ord("-")) for byte in encoded)
    )


def _validate_llama_factory_installation(installation: Any, installation_id: str) -> None:
    """Bind the active receipt to the verified LLaMA-Factory package record.

    中文：将活动回执绑定到确切安装记录，并核对 package 与 capability 身份。
    """
    required_fields = {"installation_id", "package_id", "capabilities", "state"}
    if not isinstance(installation, dict) or not required_fields.issubset(installation):
        raise LlamaFactoryPackageRuntimeError(
            "YIELD_PACKAGE_RUNTIME_INSTALLATION_INVALID",
            "Package Runtime returned an incomplete installation record",
        )
    if installation["installation_id"] != installation_id:
        raise LlamaFactoryPackageRuntimeError(
            "YIELD_PACKAGE_RUNTIME_INSTALLATION_MISMATCH",
            "Package Runtime returned a different installation identity",
        )
    if installation["package_id"] != PACKAGE_RUNTIME_PACKAGE_ID:
        raise LlamaFactoryPackageRuntimeError(
            "YIELD_PACKAGE_RUNTIME_PACKAGE_MISMATCH",
            "the active binding does not reference the approved LLaMA-Factory package",
        )
    if installation["state"] != "INSTALLED" or installation["capabilities"] != [CAPABILITY_ID]:
        raise LlamaFactoryPackageRuntimeError(
            "YIELD_PACKAGE_RUNTIME_CAPABILITY_MISMATCH",
            "the installed package does not expose the approved LLaMA-Factory capability",
        )
