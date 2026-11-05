"""
┌─────────────────────────────────────────────────────────────────────┐
│  📄 test_runtime_activity.py                                        │
│  Module: tests.test_runtime_activity                                │
│  Role: Verify managed activity startup and ProductStore cleanup.     │
│                                                                      │
│  模块职责：验证托管活动失败关闭与 Store 生命周期清理。                    │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import sqlite3
import sys
import threading
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cy_exec.training import product_service
from cy_exec.training.product_api import create_app
from cy_exec.training.product_store import ProductStore
from cy_exec.training.runtime_activity import (
    RuntimeActivityConfigurationError,
    start_activity_source,
)


_ACTIVITY_ENVIRONMENT = (
    "CYRENE_RUNTIME_ACTIVITY_SOURCE_ID",
    "CYRENE_RUNTIME_ACTIVITY_SOURCE_TOKEN_FILE",
    "CYRENE_RUNTIME_ACTIVITY_CATALOG_GENERATION",
    "CYRENE_RUNTIME_MAINTENANCE_SOCKET",
)


class _ThreadLifecycle:
    """Small lifecycle stand-in that exposes whether close joins its worker."""

    def __init__(self, store: ProductStore) -> None:
        self.store = store
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._stop.wait, daemon=True)
        self.thread.start()

    def close(self) -> None:
        """Stop the worker and verify ProductStore is still available."""

        self._stop.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError("activity thread did not stop")
        self.store.list("draft")


def test_product_store_close_callback_runs_outside_lock_before_sqlite_close(
    tmp_path: Path,
) -> None:
    """A cleanup can join another thread that briefly reads the open store."""

    store = ProductStore(tmp_path / "product.sqlite3")
    callbacks: list[str] = []

    def cleanup() -> None:
        completed = threading.Event()

        def read_store() -> None:
            store.list("draft")
            completed.set()

        reader = threading.Thread(target=read_store)
        reader.start()
        reader.join(timeout=1)
        assert completed.is_set()
        assert not reader.is_alive()
        callbacks.append("closed")

    store.add_close_callback(cleanup)
    store.close()
    store.close()

    assert callbacks == ["closed"]
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        store.list("draft")


def test_product_store_closes_database_and_surfaces_callback_failures(tmp_path: Path) -> None:
    """Cleanup errors remain visible while a repeated close stays harmless."""

    store = ProductStore(tmp_path / "product.sqlite3")

    def fail_cleanup() -> None:
        raise RuntimeError("activity cleanup failed")

    store.add_close_callback(fail_cleanup)
    with pytest.raises(ExceptionGroup, match="close callback failures"):
        store.close()

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        store.list("draft")
    store.close()


def test_yield_asgi_shutdown_joins_managed_activity_workers(tmp_path: Path, monkeypatch) -> None:
    """Multiple ASGI app lifetimes close their Product activity worker."""

    lifecycles: list[_ThreadLifecycle] = []

    def start_fake_activity(source_id: str, loader: Any) -> _ThreadLifecycle:
        assert source_id == "cyrene-yield"
        assert list(loader()) == []
        service = loader.__self__
        lifecycle = _ThreadLifecycle(service.store)
        lifecycles.append(lifecycle)
        return lifecycle

    monkeypatch.setattr(product_service, "start_activity_source", start_fake_activity)

    for index in range(2):
        app = create_app(
            state_directory=tmp_path / f"yield-{index}",
            artifact_root=tmp_path / "artifacts",
        )
        lifecycle = app.state.yield_service.activity
        with TestClient(app):
            assert lifecycle.thread.is_alive()
        assert not lifecycle.thread.is_alive()

    assert len(lifecycles) == 2


def test_runtime_socket_environment_marks_process_managed(tmp_path: Path, monkeypatch) -> None:
    """An injected socket path activates managed mode and startup is fail-closed."""

    for name in _ACTIVITY_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("cy_exec.training.runtime_activity._TOKEN_FILE", str(tmp_path / "missing-token"))
    monkeypatch.setattr("cy_exec.training.runtime_activity._SOCKET_PATH", str(tmp_path / "default.sock"))
    token_path = tmp_path / "source-token"
    token_path.write_text("unit-test-source-token", encoding="utf-8")
    monkeypatch.setenv("CYRENE_RUNTIME_ACTIVITY_SOURCE_ID", "cyrene-yield")
    monkeypatch.setenv("CYRENE_RUNTIME_ACTIVITY_SOURCE_TOKEN_FILE", str(token_path))
    monkeypatch.setenv("CYRENE_RUNTIME_ACTIVITY_CATALOG_GENERATION", "7")
    monkeypatch.setenv("CYRENE_RUNTIME_MAINTENANCE_SOCKET", str(tmp_path / "broker.sock"))
    monkeypatch.setitem(sys.modules, "cyrene_runtime_maintenance", None)

    with pytest.raises(RuntimeActivityConfigurationError, match="requires the installed"):
        start_activity_source("cyrene-yield", lambda: [])


def test_runtime_activity_startup_failure_does_not_return_unmanaged(tmp_path: Path, monkeypatch) -> None:
    """The installer socket reaches the SDK, and reconcile failure blocks startup."""

    token_path = tmp_path / "source-token"
    token_path.write_text("unit-test-source-token", encoding="utf-8")
    socket_path = tmp_path / "broker.sock"
    for name in _ACTIVITY_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CYRENE_RUNTIME_ACTIVITY_SOURCE_ID", "cyrene-yield")
    monkeypatch.setenv("CYRENE_RUNTIME_ACTIVITY_SOURCE_TOKEN_FILE", str(token_path))
    monkeypatch.setenv("CYRENE_RUNTIME_ACTIVITY_CATALOG_GENERATION", "7")
    monkeypatch.setenv("CYRENE_RUNTIME_MAINTENANCE_SOCKET", str(socket_path))
    sdk_arguments: dict[str, object] = {}

    class FakeClient:
        @classmethod
        def from_source_secret(
            cls,
            source_id: str,
            source_token_path: str,
            *,
            catalog_generation: int,
            socket_path: str,
        ) -> object:
            sdk_arguments.update(
                source_id=source_id,
                token_path=source_token_path,
                catalog_generation=catalog_generation,
                socket_path=socket_path,
            )
            return object()

    class FailingLifecycle:
        def __init__(self, _client: object) -> None:
            pass

        def start(self, loader: Any) -> None:
            assert list(loader()) == []
            raise RuntimeError("startup reconcile failed")

    sdk = types.ModuleType("cyrene_runtime_maintenance")
    sdk.RuntimeMaintenanceClient = FakeClient
    sdk.ActivitySourceLifecycle = FailingLifecycle
    monkeypatch.setitem(sys.modules, "cyrene_runtime_maintenance", sdk)

    with pytest.raises(RuntimeError, match="startup reconcile failed"):
        start_activity_source("cyrene-yield", lambda: [])

    assert sdk_arguments == {
        "source_id": "cyrene-yield",
        "token_path": str(token_path),
        "catalog_generation": 7,
        "socket_path": str(socket_path),
    }
