"""Tests for the authenticated, durable Yield Package Runtime owner API.

验证 Yield Package Runtime owner API 的鉴权和持久化边界。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cy_exec.training.product_api import create_app
from cy_exec.training.package_runtime_owner import CAPABILITY_ID, PACKAGE_ID
from cy_exec.training import product_cli

_TOKEN = "yield-local-owner-secret-test-only"
_BINDING_ID = "yield.llama-factory.primary"
_INSTALLATION_ID = "installation-from-signed-receipt"
_REQUEST_ID = "owner-activation-request-0001"
_SOURCE_ID = "cyrene-yield"
_OPERATION_TOKEN = "private-broker-operation-token"
_CONNECTION_REF = "unix:///run/cyrene/plugins/llama-factory.sock"


@dataclass(frozen=True)
class _Scope:
    binding_id: str
    package_id: str
    installation_id: str
    operation: str


@dataclass(frozen=True, repr=False)
class _Receipt:
    request_id: str
    source_id: str
    protocol_version: str
    catalog_generation: int
    scope: _Scope
    operation_token: str
    gate_generation: int
    already_in_flight: bool
    already_completed: bool

    def __repr__(self) -> str:
        return "BindingOperationReceipt(<redacted>)"


class _RuntimeError(RuntimeError):
    def __init__(self, *, pending: _Receipt | None = None) -> None:
        self.pending_binding_operation = pending
        self.request_id = _REQUEST_ID
        super().__init__("Package Runtime request failed")


class _FakeRuntimeClient:
    source_id = _SOURCE_ID

    def __init__(self, store: Any, behavior: str = "success") -> None:
        self.store = store
        self.behavior = behavior
        self.events: list[str] = []
        self.activate_calls = 0
        self.receipt = self._receipt(already_in_flight=behavior == "pending")

    @staticmethod
    def _receipt(*, already_in_flight: bool) -> _Receipt:
        return _Receipt(
            request_id=_REQUEST_ID,
            source_id=_SOURCE_ID,
            protocol_version="cyrene.runtime-maintenance.binding-operations.v1",
            catalog_generation=7,
            scope=_Scope(_BINDING_ID, PACKAGE_ID, _INSTALLATION_ID, "activate"),
            operation_token=_OPERATION_TOKEN,
            gate_generation=11,
            already_in_flight=already_in_flight,
            already_completed=False,
        )

    @staticmethod
    def _status() -> dict[str, Any]:
        return {
            "binding_id": _BINDING_ID,
            "installation_id": _INSTALLATION_ID,
            "generation": 3,
            "state": "RUNNING",
            "failure_code": None,
            "failure_message": None,
            "connection_ref": _CONNECTION_REF,
        }

    @staticmethod
    def _installation() -> dict[str, Any]:
        return {
            "installation_id": _INSTALLATION_ID,
            "package_id": PACKAGE_ID,
            "capabilities": [CAPABILITY_ID],
            "state": "INSTALLED",
        }

    @classmethod
    def from_environment(cls) -> _FakeRuntimeClient:
        raise AssertionError("test factory must be installed on the SDK module")

    def get_installation(self, installation_id: str) -> dict[str, Any]:
        self.events.append("get_installation")
        row = self.store._connection.execute(
            "SELECT phase FROM package_binding_operations WHERE request_id=?", (_REQUEST_ID,)
        ).fetchone()
        if self.activate_calls == 0:
            assert row is not None and row[0] == "INTENT"
        assert installation_id == _INSTALLATION_ID
        return self._installation()

    def activate_and_persist(
        self,
        binding_id: str,
        installation_id: str,
        *,
        package_id: str,
        persist_intent: Any,
        persist: Any,
        request_id: str,
    ) -> dict[str, Any]:
        self.activate_calls += 1
        persist_intent(
            request_id,
            _Scope(binding_id, package_id, installation_id, "activate"),
        )
        self.events.append("activate")
        if self.behavior == "no_receipt":
            raise _RuntimeError()
        if self.behavior == "pending":
            raise _RuntimeError(pending=self.receipt)
        if self.behavior == "partial_receipt":
            raise _RuntimeError(pending=self.receipt)
        persist(self._status(), self.receipt)
        row = self.store._connection.execute(
            "SELECT phase,status_json,receipt_json FROM package_binding_operations WHERE request_id=?",
            (_REQUEST_ID,),
        ).fetchone()
        assert row[0] == "OUTCOME_PENDING_COMPLETE"
        assert row[1] is not None and row[2] is not None
        self.events.append("durable-outcome")
        if self.behavior == "complete_failed":
            raise _RuntimeError()
        self.events.append("complete")
        return self._status()

    def reconcile_binding_operation_and_persist(self, receipt: _Receipt, *, reconcile: Any) -> None:
        self.events.append("reconcile")
        self.events.extend(("authority", "runtime_status", "get_installation"))
        reconcile(self._status(), self._installation(), receipt)
        self.events.append("complete")

    def runtime_status(self, binding_id: str) -> dict[str, Any]:
        self.events.append("runtime_status")
        assert binding_id == _BINDING_ID
        return self._status()

    def complete_binding_operation(self, receipt: _Receipt) -> dict[str, Any]:
        self.events.append("complete")
        assert receipt.request_id == _REQUEST_ID
        return {"completed": True}


def _app(tmp_path, monkeypatch, *, enabled: bool = True):
    monkeypatch.setenv("CYRENE_LLAMA_FACTORY_PACKAGE_BINDING_ID", _BINDING_ID)
    if enabled:
        monkeypatch.setenv("YIELD_RUNTIME_OWNER_TOKEN_SHA256", hashlib.sha256(_TOKEN.encode()).hexdigest())
    else:
        monkeypatch.delenv("YIELD_RUNTIME_OWNER_TOKEN_SHA256", raising=False)
    return create_app(state_directory=tmp_path / "yield", artifact_root=tmp_path / "artifacts")


def _install_fake_sdk(monkeypatch, store, *, behavior: str = "success") -> _FakeRuntimeClient:
    fake = _FakeRuntimeClient(store, behavior)
    module = ModuleType("cyrene_runtime_maintenance")

    class PackageRuntimeClient:
        @classmethod
        def from_environment(cls) -> _FakeRuntimeClient:
            return fake

    module.PackageRuntimeClient = PackageRuntimeClient  # type: ignore[attr-defined]
    module.BindingOperationReceipt = _Receipt  # type: ignore[attr-defined]
    module.BindingOperationScope = _Scope  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cyrene_runtime_maintenance", module)
    return fake


def _headers(*, token: str = _TOKEN, request_id: str = _REQUEST_ID) -> dict[str, str]:
    return {"Authorization": "Bearer " + token, "Idempotency-Key": request_id}


def test_owner_api_is_default_deny_and_authenticates_every_route(tmp_path, monkeypatch) -> None:
    disabled = _app(tmp_path / "disabled", monkeypatch, enabled=False)
    with TestClient(disabled) as client:
        for response in (
            client.get(f"/api/v1/runtime-bindings/{_BINDING_ID}/status", headers=_headers()),
            client.post(
                f"/api/v1/runtime-bindings/{_BINDING_ID}/actions/activate",
                headers=_headers(),
                json={"installationId": _INSTALLATION_ID},
            ),
            client.post(
                f"/api/v1/runtime-bindings/{_BINDING_ID}/actions/reconcile",
                headers=_headers(),
            ),
        ):
            assert response.status_code == 503
            assert "YIELD_PACKAGE_BINDING_OWNER_DISABLED" in response.text

    configured = _app(tmp_path / "configured", monkeypatch)
    with TestClient(configured) as client:
        missing = client.get(f"/api/v1/runtime-bindings/{_BINDING_ID}/status")
        response = client.get(
            f"/api/v1/runtime-bindings/{_BINDING_ID}/status",
            headers=_headers(token="wrong-token"),
        )
        assert missing.status_code == 401
        assert response.status_code == 401
        assert _TOKEN not in response.text


def test_binding_scope_and_request_shape_are_server_owned(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        mismatch = client.get("/api/v1/runtime-bindings/yield.llama-factory.other/status", headers=_headers())
        invalid = client.get("/api/v1/runtime-bindings/Bad Binding/status", headers=_headers())
        assert mismatch.status_code == 404
        assert invalid.status_code == 422

        store = app.state.yield_service.store
        runtime = _install_fake_sdk(monkeypatch, store)
        response = client.post(
            f"/api/v1/runtime-bindings/{_BINDING_ID}/actions/activate",
            headers=_headers(),
            json={"installationId": _INSTALLATION_ID, "source_token": "must-not-be-accepted"},
        )
        assert response.status_code == 422
        assert runtime.activate_calls == 0
        assert store._connection.execute("SELECT COUNT(*) FROM package_binding_operations").fetchone()[0] == 0


def test_activation_commits_intent_then_status_and_receipt_before_complete(tmp_path, monkeypatch, capsys) -> None:
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        store = app.state.yield_service.store
        runtime = _install_fake_sdk(monkeypatch, store)
        response = client.post(
            f"/api/v1/runtime-bindings/{_BINDING_ID}/actions/activate",
            headers=_headers(),
            json={"installationId": _INSTALLATION_ID},
        )
        assert response.status_code == 200, response.text
        assert runtime.events == ["get_installation", "activate", "durable-outcome", "complete"]
        payload = response.json()
        assert payload["phase"] == "ACTIVE"
        assert payload["requestId"] == _REQUEST_ID
        for forbidden in (_CONNECTION_REF, _OPERATION_TOKEN, _TOKEN):
            assert forbidden not in response.text
        operation = store._connection.execute(
            "SELECT phase,receipt_json,status_json FROM package_binding_operations WHERE request_id=?",
            (_REQUEST_ID,),
        ).fetchone()
        assert operation == ("COMPLETED", None, operation[2])
        assert operation[2] is not None
        assert _OPERATION_TOKEN not in capsys.readouterr().out
        assert _OPERATION_TOKEN not in capsys.readouterr().err


def test_unknown_intent_is_never_replayed_without_a_receipt(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        store = app.state.yield_service.store
        runtime = _install_fake_sdk(monkeypatch, store, behavior="no_receipt")
        endpoint = f"/api/v1/runtime-bindings/{_BINDING_ID}/actions/activate"
        first = client.post(endpoint, headers=_headers(), json={"installationId": _INSTALLATION_ID})
        second = client.post(endpoint, headers=_headers(), json={"installationId": _INSTALLATION_ID})
        new_request = client.post(
            endpoint,
            headers=_headers(request_id="new-recovery-attempt-must-not-replay"),
            json={"installationId": _INSTALLATION_ID},
        )
        status = client.get(f"/api/v1/runtime-bindings/{_BINDING_ID}/status", headers=_headers())
        reconcile = client.post(f"/api/v1/runtime-bindings/{_BINDING_ID}/actions/reconcile", headers=_headers())
        assert first.status_code == 409
        assert second.status_code == 409
        assert new_request.status_code == 409
        assert status.json()["phase"] == "UNKNOWN"
        assert reconcile.status_code == 409
        assert runtime.activate_calls == 1


def test_inflight_receipt_reconciles_without_reissuing_activate_or_leaking_secrets(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        store = app.state.yield_service.store
        runtime = _install_fake_sdk(monkeypatch, store, behavior="pending")
        endpoint = f"/api/v1/runtime-bindings/{_BINDING_ID}"
        started = client.post(
            endpoint + "/actions/activate",
            headers=_headers(),
            json={"installationId": _INSTALLATION_ID},
        )
        stored = store.package_binding_operation_for_reconcile(_REQUEST_ID, _BINDING_ID)
        pending_status = client.get(endpoint + "/status", headers=_headers())
        recovered = client.post(endpoint + "/actions/reconcile", headers=_headers())
        assert started.status_code == 409
        assert stored is not None and stored["receipt"]["already_in_flight"] is True
        assert stored["receipt"]["already_completed"] is False
        assert pending_status.json()["phase"] == "PENDING_RECONCILE"
        assert recovered.status_code == 200
        assert recovered.json()["phase"] == "ACTIVE"
        assert runtime.activate_calls == 1
        assert runtime.events == [
            "get_installation",
            "activate",
            "reconcile",
            "authority",
            "runtime_status",
            "get_installation",
            "complete",
        ]
        for response in (started, pending_status, recovered):
            assert _OPERATION_TOKEN not in response.text
            assert _CONNECTION_REF not in response.text


def test_partial_sdk_exception_preserves_fresh_receipt_flags_for_reconcile(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        store = app.state.yield_service.store
        runtime = _install_fake_sdk(monkeypatch, store, behavior="partial_receipt")
        endpoint = f"/api/v1/runtime-bindings/{_BINDING_ID}"
        started = client.post(
            endpoint + "/actions/activate",
            headers=_headers(),
            json={"installationId": _INSTALLATION_ID},
        )
        pending = store.package_binding_operation_for_reconcile(_REQUEST_ID, _BINDING_ID)
        recovered = client.post(endpoint + "/actions/reconcile", headers=_headers())
        assert started.status_code == 409
        assert pending is not None and pending["phase"] == "PENDING_RECONCILE"
        assert pending["receipt"]["already_in_flight"] is False
        assert pending["receipt"]["already_completed"] is False
        assert recovered.status_code == 200
        assert recovered.json()["phase"] == "ACTIVE"
        assert runtime.activate_calls == 1
        assert runtime.events == [
            "get_installation",
            "activate",
            "reconcile",
            "authority",
            "runtime_status",
            "get_installation",
            "complete",
        ]


def test_post_commit_failure_uses_saved_receipt_and_fresh_readback(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        store = app.state.yield_service.store
        runtime = _install_fake_sdk(monkeypatch, store, behavior="complete_failed")
        endpoint = f"/api/v1/runtime-bindings/{_BINDING_ID}"
        started = client.post(
            endpoint + "/actions/activate",
            headers=_headers(),
            json={"installationId": _INSTALLATION_ID},
        )
        pending = store.package_binding_operation_for_reconcile(_REQUEST_ID, _BINDING_ID)
        assert started.status_code == 409
        assert pending is not None and pending["phase"] == "OUTCOME_PENDING_COMPLETE"
        assert pending["receipt"]["operation_token"] == _OPERATION_TOKEN
        assert pending["receipt"]["already_in_flight"] is False
        assert pending["receipt"]["already_completed"] is False

        recovered = client.post(endpoint + "/actions/reconcile", headers=_headers())
        assert recovered.status_code == 200
        assert recovered.json()["phase"] == "ACTIVE"
        assert runtime.activate_calls == 1
        assert runtime.events == [
            "get_installation",
            "activate",
            "durable-outcome",
            "reconcile",
            "authority",
            "runtime_status",
            "get_installation",
            "complete",
        ]


def test_failed_outcome_transaction_rolls_back_receipt_and_marks_unknown(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        store = app.state.yield_service.store
        runtime = _install_fake_sdk(monkeypatch, store)
        store._connection.execute(
            "CREATE TRIGGER reject_binding_state BEFORE UPDATE ON package_binding_owner_state "
            "BEGIN SELECT RAISE(ABORT, 'injected local persistence failure'); END"
        )
        response = client.post(
            f"/api/v1/runtime-bindings/{_BINDING_ID}/actions/activate",
            headers=_headers(),
            json={"installationId": _INSTALLATION_ID},
        )
        status = client.get(f"/api/v1/runtime-bindings/{_BINDING_ID}/status", headers=_headers())
        operation = store.package_binding_operation_for_reconcile(_REQUEST_ID, _BINDING_ID)
        assert response.status_code == 409
        assert operation is not None and operation["phase"] == "UNKNOWN"
        assert operation["receipt"] is None
        assert status.json()["phase"] == "UNKNOWN"
        assert runtime.activate_calls == 1
        assert _OPERATION_TOKEN not in response.text


def test_same_request_id_with_different_scope_conflicts(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        store = app.state.yield_service.store
        _install_fake_sdk(monkeypatch, store)
        endpoint = f"/api/v1/runtime-bindings/{_BINDING_ID}/actions/activate"
        created = client.post(
            endpoint,
            headers=_headers(),
            json={"installationId": _INSTALLATION_ID},
        )
        conflict = client.post(
            endpoint,
            headers=_headers(),
            json={"installationId": "different-installed-package"},
        )
        assert created.status_code == 200
        assert conflict.status_code == 409
        assert "IDEMPOTENCY_CONFLICT" in conflict.text


def test_product_database_and_state_directory_are_owner_only(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch)
    store = app.state.yield_service.store
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store.path.stat().st_uid == os.getuid()
    store.close()


def test_cli_forwards_owner_token_only_to_fixed_loopback_http_api(monkeypatch, capsys) -> None:
    monkeypatch.setenv("OWNER_CLI_TOKEN", _TOKEN)
    requests: list[dict[str, Any]] = []

    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, str]:
            return {"phase": "ACTIVE", "requestId": _REQUEST_ID}

    class Client:
        def __init__(self, *, base_url: str, headers: dict[str, str], timeout: float) -> None:
            requests.append({"base_url": base_url, "headers": headers, "timeout": timeout})

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        @staticmethod
        def post(path: str, *, json: dict[str, Any] | None = None) -> Response:
            requests[-1]["path"] = path
            requests[-1]["json"] = json
            return Response()

        @staticmethod
        def get(path: str) -> Response:
            requests[-1]["path"] = path
            return Response()

    monkeypatch.setattr(product_cli.httpx, "Client", Client)
    result = product_cli._package_binding_command(
        ["activate", _BINDING_ID, _INSTALLATION_ID, "--token-env", "OWNER_CLI_TOKEN"]
    )
    output = capsys.readouterr()
    assert result == 0
    assert requests[0]["base_url"] == "http://127.0.0.1:8001"
    assert requests[0]["path"] == f"/api/v1/runtime-bindings/{_BINDING_ID}/actions/activate"
    assert requests[0]["headers"]["Authorization"] == "Bearer " + _TOKEN
    generated_id = requests[0]["headers"]["Idempotency-Key"]
    assert generated_id
    assert f"requestId: {generated_id}" in output.out
    assert requests[0]["json"] == {"installationId": _INSTALLATION_ID}
    assert _TOKEN not in output.out and _TOKEN not in output.err
