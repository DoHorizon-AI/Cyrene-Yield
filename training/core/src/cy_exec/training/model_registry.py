"""Typed adapter for the Plugins-owned ``model.registry.v1`` capability.

针对 Plugins 所有的 model.registry.v1 能力的有类型适配器。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from cyrene_yield_contracts import ModelVersion

MODEL_REGISTRY_CAPABILITY = "model.registry.v1"
MODEL_REGISTRY_INTERFACE_VERSION = "1"
_RESOURCE_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")


@dataclass(frozen=True, slots=True)
class ModelRegistration:
    """Validated registry acknowledgement for one immutable ModelVersion.

    针对一个不可变 ModelVersion 的已验证 registry 确认。
    """

    model_version_id: str
    resource_uri: str
    resource_version: int
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelVersionId": self.model_version_id,
            "resourceUri": self.resource_uri,
            "resourceVersion": self.resource_version,
            "created": self.created,
        }


class ModelRegistryPort(Protocol):
    """Yield application port; registry implementations remain Plugins-owned.

    Yield 应用端口；registry 实现仍由 Plugins 所有。
    """

    def register(
        self,
        model_version: Mapping[str, Any],
        *,
        source_ref: str,
    ) -> ModelRegistration:
        """Register an immutable descriptor without transferring Artifact bytes.

        注册不可变描述符，不转移 Artifact 字节。
        """


class DirectPluginModelRegistry:
    """Invoke ``model.registry.v1/register`` through one resolved endpoint.

    通过一个已解析端点调用 model.registry.v1/register。
    """

    def __init__(self, client: Any, *, deadline_seconds: float = 10.0) -> None:
        self._client = client
        self._deadline_seconds = deadline_seconds

    @classmethod
    def from_connection_ref(cls, connection_ref: str) -> DirectPluginModelRegistry:
        if not isinstance(connection_ref, str) or not connection_ref.strip():
            raise ModelRegistryUnavailable("connection_ref is not configured")
        try:
            from cyrene_plugin_runtime import DirectPluginClient

            client = DirectPluginClient.for_local_connection_ref(connection_ref.strip())
        except ImportError as exc:
            raise ModelRegistryUnavailable("cyrene-plugin-runtime is not installed") from exc
        except (TypeError, ValueError) as exc:
            raise ModelRegistryUnavailable(f"connection_ref is invalid: {exc}") from exc
        return cls(client)

    def register(
        self,
        model_version: Mapping[str, Any],
        *,
        source_ref: str,
    ) -> ModelRegistration:
        normalized = ModelVersion.from_dict(model_version).to_dict()
        if not isinstance(source_ref, str) or not _RESOURCE_URI.fullmatch(source_ref):
            raise ModelRegistryUnavailable("source_ref must be a non-empty opaque URI")
        request = {
            "model_version": normalized,
            "source_ref": source_ref,
        }
        try:
            from cyrene_plugin_runtime import DirectPayload, DirectPluginError

            response = self._client.invoke(
                capability=MODEL_REGISTRY_CAPABILITY,
                interface_version=MODEL_REGISTRY_INTERFACE_VERSION,
                method="register",
                request=DirectPayload(
                    type_url="type.cyrene.io/model.registry.v1.register.request",
                    value=json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                ),
                deadline_seconds=self._deadline_seconds,
            )
        except ImportError as exc:
            raise ModelRegistryUnavailable("cyrene-plugin-runtime is not installed") from exc
        except DirectPluginError as exc:
            raise ModelRegistryUnavailable(f"direct invocation failed: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise ModelRegistryUnavailable(f"direct invocation is invalid: {exc}") from exc
        if response.type_url != "type.cyrene.io/model.registry.v1.register.response":
            raise ModelRegistryUnavailable("Plugin returned an unexpected response type")
        try:
            payload = json.loads(response.value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelRegistryUnavailable("Plugin returned invalid UTF-8 JSON") from exc
        return _registration(payload, expected_model_version_id=normalized["id"])


class ModelRegistryUnavailable(RuntimeError):
    """The configured model registry could not produce a valid acknowledgement.

    已配置的 model registry 无法生成有效确认。
    """


def _registration(value: Any, *, expected_model_version_id: str) -> ModelRegistration:
    if not isinstance(value, dict):
        raise ModelRegistryUnavailable("Plugin response must be an object")
    model_version_id = value.get("model_version_id")
    resource_uri = value.get("resource_uri")
    resource_version = value.get("resource_version")
    created = value.get("created")
    if model_version_id != expected_model_version_id:
        raise ModelRegistryUnavailable("Plugin acknowledged a different ModelVersion")
    if not isinstance(resource_uri, str) or not _RESOURCE_URI.fullmatch(resource_uri):
        raise ModelRegistryUnavailable("Plugin response resource_uri must be an opaque URI")
    if isinstance(resource_version, bool) or not isinstance(resource_version, int) or resource_version < 1:
        raise ModelRegistryUnavailable("Plugin response resource_version must be a positive integer")
    if not isinstance(created, bool):
        raise ModelRegistryUnavailable("Plugin response created must be boolean")
    return ModelRegistration(
        model_version_id=model_version_id,
        resource_uri=resource_uri,
        resource_version=resource_version,
        created=created,
    )


__all__ = [
    "DirectPluginModelRegistry",
    "MODEL_REGISTRY_CAPABILITY",
    "MODEL_REGISTRY_INTERFACE_VERSION",
    "ModelRegistration",
    "ModelRegistryPort",
    "ModelRegistryUnavailable",
]
