"""Verify Yield reads a healthy, owner-authorized LLaMA-Factory binding.

验证 Yield 只读核验受 owner 授权且健康运行的 LLaMA-Factory package binding。
"""

from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from cy_exec.training.engines.llamafactory.adapter import (
    CAPABILITY_ID,
    PACKAGE_RUNTIME_BINDING_ENV,
    PACKAGE_RUNTIME_PACKAGE_ID,
    LlamaFactoryEngineAdapter,
    LlamaFactoryPackageRuntimeError,
    LlamaFactoryPluginConnection,
)

_INSTALLATION_ID = "installation-from-signed-receipt"
_CONNECTION_REF = "unix:///run/cyrene/plugins/llama-factory.sock"
_BINDING_ID = "yield.llama-factory.primary"
_OTHER_VALID_BINDING_ID = "yield.llama-factory.acceptance-2"


class _FakePackageRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str = "owner policy rejected the request") -> None:
        self.code = code
        super().__init__(message)


class _FakePackageRuntimeClient:
    def __init__(self, status: Any, installation: Any, *, source_id: str = "cyrene-yield") -> None:
        self.source_id = source_id
        self.status = status
        self.installation = installation
        self.calls: list[tuple[str, str]] = []

    def runtime_status(self, binding_id: str) -> Any:
        self.calls.append(("runtime_status", binding_id))
        if isinstance(self.status, Exception):
            raise self.status
        return self.status

    def get_installation(self, installation_id: str) -> Any:
        self.calls.append(("get_installation", installation_id))
        if isinstance(self.installation, Exception):
            raise self.installation
        return self.installation


def _healthy_status(*, binding_id: str = _BINDING_ID, **updates: Any) -> dict[str, Any]:
    return {
        "binding_id": binding_id,
        "installation_id": _INSTALLATION_ID,
        "generation": 3,
        "state": "RUNNING",
        "failure_code": None,
        "failure_message": None,
        "connection_ref": _CONNECTION_REF,
        **updates,
    }


def _installed_record(**updates: Any) -> dict[str, Any]:
    return {
        "installation_id": _INSTALLATION_ID,
        "package_id": PACKAGE_RUNTIME_PACKAGE_ID,
        "capabilities": [CAPABILITY_ID],
        "state": "INSTALLED",
        **updates,
    }


def _install_package_runtime(monkeypatch: pytest.MonkeyPatch, client: _FakePackageRuntimeClient) -> None:
    module = ModuleType("cyrene_runtime_maintenance")

    class FakePackageRuntimeClientFactory:
        @classmethod
        def from_environment(cls) -> _FakePackageRuntimeClient:
            return client

    module.PackageRuntimeClient = FakePackageRuntimeClientFactory  # type: ignore[attr-defined]
    module.PackageRuntimeError = _FakePackageRuntimeError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cyrene_runtime_maintenance", module)


def _install_direct_plugin_runtime(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    module = ModuleType("cyrene_plugin_runtime")
    clients: list[Any] = []

    class DirectPayload:
        def __init__(self, *, type_url: str, value: bytes) -> None:
            self.type_url = type_url
            self.value = value

    class DirectPluginClient:
        def __init__(self, connection_ref: str) -> None:
            self.connection_ref = connection_ref
            self.calls: list[dict[str, Any]] = []

        @classmethod
        def for_local_connection_ref(cls, connection_ref: str) -> DirectPluginClient:
            client = cls(connection_ref)
            clients.append(client)
            return client

        def invoke(self, **request: Any) -> Any:
            self.calls.append(request)
            return SimpleNamespace(value=json.dumps({"available": True}).encode("utf-8"))

    module.DirectPayload = DirectPayload  # type: ignore[attr-defined]
    module.DirectPluginClient = DirectPluginClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cyrene_plugin_runtime", module)
    return clients


def _enable_package_mode(
    monkeypatch: pytest.MonkeyPatch,
    binding_id: str = _BINDING_ID,
) -> None:
    monkeypatch.setenv(PACKAGE_RUNTIME_BINDING_ENV, binding_id)
    monkeypatch.setenv("CYRENE_RUNTIME_ACTIVITY_SOURCE_ID", "cyrene-yield")
    monkeypatch.setenv("CYRENE_LLAMA_FACTORY_CONNECTION_REF", "unix:///stale/legacy.sock")


def test_package_mode_uses_only_the_healthy_receipt_ref_and_existing_direct_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_package_mode(monkeypatch, binding_id=_OTHER_VALID_BINDING_ID)
    package_client = _FakePackageRuntimeClient(
        _healthy_status(binding_id=_OTHER_VALID_BINDING_ID),
        _installed_record(),
    )
    _install_package_runtime(monkeypatch, package_client)
    direct_clients = _install_direct_plugin_runtime(monkeypatch)

    connection = LlamaFactoryPluginConnection.from_environment()
    response = connection.invoke("inspect", {})

    assert response == {"available": True}
    assert package_client.calls == [
        ("runtime_status", _OTHER_VALID_BINDING_ID),
        ("get_installation", _INSTALLATION_ID),
    ]
    assert len(direct_clients) == 1
    assert direct_clients[0].connection_ref == _CONNECTION_REF
    assert direct_clients[0].calls[0]["capability"] == CAPABILITY_ID
    assert direct_clients[0].calls[0]["interface_version"] == "1"


@pytest.mark.parametrize(
    ("status_updates", "error_code"),
    [
        ({"binding_id": "another-binding"}, "YIELD_PACKAGE_RUNTIME_BINDING_MISMATCH"),
        ({"generation": True}, "YIELD_PACKAGE_RUNTIME_STATUS_INVALID"),
        ({"generation": 0}, "YIELD_PACKAGE_RUNTIME_STATUS_INVALID"),
        ({"state": "STOPPED"}, "YIELD_PACKAGE_RUNTIME_UNHEALTHY"),
        ({"state": "ACTIVE"}, "YIELD_PACKAGE_RUNTIME_UNHEALTHY"),
        ({"failure_code": "WORKER_FAILED"}, "YIELD_PACKAGE_RUNTIME_UNHEALTHY"),
        ({"installation_id": "INVALID_INSTALLATION_ID"}, "YIELD_PACKAGE_RUNTIME_STATUS_INVALID"),
        ({"connection_ref": None}, "YIELD_PACKAGE_RUNTIME_ENDPOINT_INVALID"),
        ({"connection_ref": " unix:///invalid.sock"}, "YIELD_PACKAGE_RUNTIME_ENDPOINT_INVALID"),
        ({"connection_ref": "unix:///invalid.sock\u0085"}, "YIELD_PACKAGE_RUNTIME_ENDPOINT_INVALID"),
        ({"connection_ref": "x" * 2049}, "YIELD_PACKAGE_RUNTIME_ENDPOINT_INVALID"),
    ],
)
def test_package_mode_rejects_invalid_or_unhealthy_runtime_status(
    monkeypatch: pytest.MonkeyPatch,
    status_updates: dict[str, Any],
    error_code: str,
) -> None:
    _enable_package_mode(monkeypatch)
    package_client = _FakePackageRuntimeClient(_healthy_status(**status_updates), _installed_record())
    _install_package_runtime(monkeypatch, package_client)
    direct_clients = _install_direct_plugin_runtime(monkeypatch)

    with pytest.raises(LlamaFactoryPackageRuntimeError) as error:
        LlamaFactoryPluginConnection.from_environment()

    assert error.value.code == error_code
    assert direct_clients == []
    assert [operation for operation, _ in package_client.calls] == ["runtime_status"]


@pytest.mark.parametrize(
    ("installation_updates", "error_code"),
    [
        ({"installation_id": "different-installation"}, "YIELD_PACKAGE_RUNTIME_INSTALLATION_MISMATCH"),
        ({"package_id": "another.package"}, "YIELD_PACKAGE_RUNTIME_PACKAGE_MISMATCH"),
        ({"capabilities": []}, "YIELD_PACKAGE_RUNTIME_CAPABILITY_MISMATCH"),
        ({"capabilities": [CAPABILITY_ID, "another.capability"]}, "YIELD_PACKAGE_RUNTIME_CAPABILITY_MISMATCH"),
        ({"state": "VERIFYING"}, "YIELD_PACKAGE_RUNTIME_CAPABILITY_MISMATCH"),
    ],
)
def test_package_mode_rejects_mismatched_installation_identity(
    monkeypatch: pytest.MonkeyPatch,
    installation_updates: dict[str, Any],
    error_code: str,
) -> None:
    _enable_package_mode(monkeypatch)
    package_client = _FakePackageRuntimeClient(
        _healthy_status(),
        _installed_record(**installation_updates),
    )
    _install_package_runtime(monkeypatch, package_client)
    direct_clients = _install_direct_plugin_runtime(monkeypatch)

    with pytest.raises(LlamaFactoryPackageRuntimeError) as error:
        LlamaFactoryPluginConnection.from_environment()

    assert error.value.code == error_code
    assert direct_clients == []


def test_package_mode_preserves_owner_policy_rejection_and_does_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_package_mode(monkeypatch)
    denied = _FakePackageRuntimeError("BINDING_NOT_AUTHORIZED")
    package_client = _FakePackageRuntimeClient(denied, _installed_record())
    _install_package_runtime(monkeypatch, package_client)
    direct_clients = _install_direct_plugin_runtime(monkeypatch)

    with pytest.raises(LlamaFactoryPackageRuntimeError, match="BINDING_NOT_AUTHORIZED") as error:
        LlamaFactoryPluginConnection.from_environment()

    assert error.value.code == "YIELD_PACKAGE_RUNTIME_REJECTED"
    assert direct_clients == []
    assert package_client.calls == [("runtime_status", _BINDING_ID)]


def test_package_mode_rejects_a_different_activity_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_package_mode(monkeypatch)
    package_client = _FakePackageRuntimeClient(
        _healthy_status(),
        _installed_record(),
        source_id="another-product",
    )
    _install_package_runtime(monkeypatch, package_client)
    direct_clients = _install_direct_plugin_runtime(monkeypatch)

    with pytest.raises(LlamaFactoryPackageRuntimeError) as error:
        LlamaFactoryPluginConnection.from_environment()

    assert error.value.code == "YIELD_PACKAGE_RUNTIME_SOURCE_INVALID"
    assert package_client.calls == []
    assert direct_clients == []


def test_package_mode_preserves_owner_policy_rejection_on_installation_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_package_mode(monkeypatch)
    denied = _FakePackageRuntimeError("INSTALLATION_NOT_AUTHORIZED")
    package_client = _FakePackageRuntimeClient(_healthy_status(), denied)
    _install_package_runtime(monkeypatch, package_client)
    direct_clients = _install_direct_plugin_runtime(monkeypatch)

    with pytest.raises(LlamaFactoryPackageRuntimeError, match="INSTALLATION_NOT_AUTHORIZED") as error:
        LlamaFactoryPluginConnection.from_environment()

    assert error.value.code == "YIELD_PACKAGE_RUNTIME_REJECTED"
    assert direct_clients == []
    assert package_client.calls == [
        ("runtime_status", _BINDING_ID),
        ("get_installation", _INSTALLATION_ID),
    ]


@pytest.mark.parametrize(
    "invalid_binding_id",
    ["", "x", "Yield.llama-factory", "yield/llama-factory", "yield\nllama-factory", "a" * 129],
)
def test_package_mode_rejects_invalid_binding_id_even_if_legacy_ref_exists(
    monkeypatch: pytest.MonkeyPatch,
    invalid_binding_id: str,
) -> None:
    monkeypatch.setenv(PACKAGE_RUNTIME_BINDING_ENV, invalid_binding_id)
    monkeypatch.setenv("CYRENE_LLAMA_FACTORY_CONNECTION_REF", _CONNECTION_REF)
    direct_clients = _install_direct_plugin_runtime(monkeypatch)

    with pytest.raises(LlamaFactoryPackageRuntimeError) as error:
        LlamaFactoryPluginConnection.from_environment()

    assert error.value.code == "YIELD_PACKAGE_RUNTIME_BINDING_INVALID"
    assert direct_clients == []


def test_package_mode_is_unavailable_when_sdk_wheel_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_package_mode(monkeypatch)
    monkeypatch.setitem(sys.modules, "cyrene_runtime_maintenance", None)

    with pytest.raises(LlamaFactoryPackageRuntimeError) as error:
        LlamaFactoryPluginConnection.from_environment()

    assert error.value.code == "YIELD_PACKAGE_RUNTIME_SDK_MISSING"


def test_package_runtime_failure_is_not_hidden_as_a_log_event(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_package_mode(monkeypatch)
    package_client = _FakePackageRuntimeClient(
        _healthy_status(state="STOPPED"),
        _installed_record(),
    )
    _install_package_runtime(monkeypatch, package_client)
    _install_direct_plugin_runtime(monkeypatch)

    adapter = LlamaFactoryEngineAdapter()
    with pytest.raises(LlamaFactoryPackageRuntimeError) as error:
        adapter.parse_event("trainer output")

    assert error.value.code == "YIELD_PACKAGE_RUNTIME_UNHEALTHY"


def test_legacy_owner_ref_path_remains_available_without_package_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PACKAGE_RUNTIME_BINDING_ENV, raising=False)
    monkeypatch.setenv("CYRENE_LLAMA_FACTORY_CONNECTION_REF", _CONNECTION_REF)
    monkeypatch.setitem(sys.modules, "cyrene_runtime_maintenance", None)
    direct_clients = _install_direct_plugin_runtime(monkeypatch)

    connection = LlamaFactoryPluginConnection.from_environment()

    assert len(direct_clients) == 1
    assert direct_clients[0].connection_ref == _CONNECTION_REF
    assert connection._client is direct_clients[0]


def test_inspect_reports_package_owner_rejection_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_package_mode(monkeypatch)
    package_client = _FakePackageRuntimeClient(
        _FakePackageRuntimeError("BINDING_NOT_AUTHORIZED"),
        _installed_record(),
    )
    _install_package_runtime(monkeypatch, package_client)
    _install_direct_plugin_runtime(monkeypatch)

    info = LlamaFactoryEngineAdapter().inspect()

    assert info.available is False
    assert any("YIELD_PACKAGE_RUNTIME_REJECTED" in note for note in info.notes)
