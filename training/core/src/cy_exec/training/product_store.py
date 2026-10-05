"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.product_store                              │
│  Role: Durable draft/result metadata and idempotent import receipts.│
│  模块职责：持久化产品草稿与结果；运行状态继续由既有 Control Plane 保存。 │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, List
from uuid import UUID

from .logging import format_cyrene_log


def ensure_private_store_directory(path: Path) -> None:
    """Create or verify a service-owned directory for private Product state.

    中文：创建或核验由当前服务用户独占的 Product 私有状态目录。
    """

    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise PermissionError("YIELD_PRODUCT_STORE_PERMISSIONS: state directory must be a service-owned directory")
    os.chmod(path, 0o700)


class ProductStore:
    """Serialize only Yield resources; never store model or dataset content.

    只序列化 Yield 资源;绝不存储模型或数据集内容。
    """

    LOG_RETENTION_DAYS = 30

    def __init__(
        self,
        path: Path,
        *,
        log_retention_days: int = LOG_RETENTION_DAYS,
    ) -> None:
        path = Path(path)
        ensure_private_store_directory(path.parent)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(path, flags, 0o600)
            os.close(descriptor)
            metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise PermissionError("YIELD_PRODUCT_STORE_PERMISSIONS: database must be a service-owned regular file")
        os.chmod(path, 0o600)
        self.path = path
        self.log_retention_days = log_retention_days
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._lock = RLock()
        self._close_callbacks: list[Callable[[], None]] = []
        self._closed = False
        with self._connection:
            self._connection.executescript(
                "CREATE TABLE IF NOT EXISTS resources(kind TEXT, id TEXT, document TEXT, PRIMARY KEY(kind,id));"
                "CREATE TABLE IF NOT EXISTS receipts(key TEXT PRIMARY KEY, digest TEXT, id TEXT);"
                "CREATE TABLE IF NOT EXISTS workspace_draft_receipts("
                "organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL, key TEXT NOT NULL,"
                "digest TEXT NOT NULL, id TEXT NOT NULL,"
                "PRIMARY KEY(organization_id, workspace_id, key));"
                "CREATE TABLE IF NOT EXISTS workspace_resource_scopes("
                "kind TEXT NOT NULL, id TEXT NOT NULL, organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL,"
                "PRIMARY KEY(kind,id));"
                "CREATE INDEX IF NOT EXISTS ix_workspace_resource_scopes_scope"
                " ON workspace_resource_scopes(organization_id, workspace_id, kind);"
                "CREATE TABLE IF NOT EXISTS action_receipts("
                "key TEXT PRIMARY KEY, digest TEXT NOT NULL, document TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS training_events("
                "run_id TEXT NOT NULL, attempt_id TEXT NOT NULL, event_index INTEGER NOT NULL,"
                "sequence INTEGER NOT NULL, document TEXT NOT NULL,"
                "PRIMARY KEY(run_id, attempt_id, event_index));"
                "CREATE INDEX IF NOT EXISTS ix_training_events_run_sequence"
                " ON training_events(run_id, sequence);"
                "CREATE TABLE IF NOT EXISTS run_terminals("
                "run_id TEXT PRIMARY KEY, state TEXT NOT NULL, ended_at TEXT NOT NULL);"
                "CREATE INDEX IF NOT EXISTS ix_run_terminals_ended_at"
                " ON run_terminals(ended_at);"
                "CREATE TABLE IF NOT EXISTS training_diagnostics("
                "run_id TEXT NOT NULL, attempt_id TEXT NOT NULL, record_index INTEGER NOT NULL,"
                "sequence INTEGER NOT NULL, document TEXT NOT NULL,"
                "PRIMARY KEY(run_id, attempt_id, record_index));"
                "CREATE INDEX IF NOT EXISTS ix_training_diagnostics_run_sequence"
                " ON training_diagnostics(run_id, sequence);"
                "CREATE TABLE IF NOT EXISTS package_binding_operations("
                "request_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, package_id TEXT NOT NULL,"
                "installation_id TEXT NOT NULL, operation TEXT NOT NULL CHECK(operation='activate'),"
                "phase TEXT NOT NULL CHECK(phase IN ('INTENT','OUTCOME_PENDING_COMPLETE','PENDING_RECONCILE','UNKNOWN','COMPLETED')) ,"
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status_json TEXT, receipt_json TEXT, blocker TEXT);"
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_package_binding_one_pending_operation"
                " ON package_binding_operations(binding_id) WHERE phase <> 'COMPLETED';"
                "CREATE TABLE IF NOT EXISTS package_binding_owner_state("
                "binding_id TEXT PRIMARY KEY, package_id TEXT NOT NULL, installation_id TEXT, request_id TEXT,"
                "phase TEXT NOT NULL, runtime_state TEXT, runtime_generation INTEGER, failure_code TEXT,"
                "connection_ref TEXT, blocker TEXT, updated_at TEXT NOT NULL);"
            )
        self._secure_sqlite_files()

    def _secure_sqlite_files(self) -> None:
        """Keep the database and any SQLite sidecar files owner-only.

        中文：将数据库与可能存在的 SQLite 辅助文件限制为服务用户可读写。
        """

        for candidate in (
            self.path,
            Path(str(self.path) + "-wal"),
            Path(str(self.path) + "-shm"),
            Path(str(self.path) + "-journal"),
        ):
            try:
                metadata = candidate.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise PermissionError(
                    "YIELD_PRODUCT_STORE_PERMISSIONS: SQLite files must be service-owned regular files"
                )
            os.chmod(candidate, 0o600)

    @staticmethod
    def _binding_scope_matches(row: tuple[Any, ...], *, binding_id: str, package_id: str, installation_id: str) -> bool:
        return row[0] == binding_id and row[1] == package_id and row[2] == installation_id and row[3] == "activate"

    def begin_package_binding_operation(
        self,
        request_id: str,
        binding_id: str,
        package_id: str,
        installation_id: str,
    ) -> dict[str, Any] | None:
        """Durably reserve one exact activation intent before any Package Runtime call.

        中文：在调用 Package Runtime 前，先持久化唯一且精确的激活意图。
        """

        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self._connection.execute(
                    "SELECT binding_id, package_id, installation_id, operation, phase, blocker "
                    "FROM package_binding_operations WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if existing is not None:
                    if not self._binding_scope_matches(
                        existing, binding_id=binding_id, package_id=package_id, installation_id=installation_id
                    ):
                        raise ValueError("YIELD_PACKAGE_BINDING_IDEMPOTENCY_CONFLICT")
                    self._connection.commit()
                    return {
                        "request_id": request_id,
                        "binding_id": binding_id,
                        "package_id": package_id,
                        "installation_id": installation_id,
                        "operation": existing[3],
                        "phase": existing[4],
                        "blocker": existing[5],
                    }

                state = self._connection.execute(
                    "SELECT phase, installation_id FROM package_binding_owner_state WHERE binding_id=?",
                    (binding_id,),
                ).fetchone()
                if state is not None and state[0] == "ACTIVE":
                    if state[1] == installation_id:
                        self._connection.commit()
                        return {"phase": "ACTIVE", "installation_id": installation_id, "already_active": True}
                    raise ValueError("YIELD_PACKAGE_BINDING_ACTIVE_CONFLICT")

                pending = self._connection.execute(
                    "SELECT request_id, phase FROM package_binding_operations "
                    "WHERE binding_id=? AND phase <> 'COMPLETED' LIMIT 1",
                    (binding_id,),
                ).fetchone()
                if pending is not None:
                    raise ValueError("YIELD_PACKAGE_BINDING_OPERATION_PENDING")

                self._connection.execute(
                    "INSERT INTO package_binding_operations("
                    "request_id,binding_id,package_id,installation_id,operation,phase,created_at,updated_at,blocker) "
                    "VALUES(?,?,?,?,?,'INTENT',?,?,?)",
                    (
                        request_id,
                        binding_id,
                        package_id,
                        installation_id,
                        "activate",
                        now,
                        now,
                        "PACKAGE_BINDING_ACTIVATION_PENDING",
                    ),
                )
                self._write_package_binding_state(
                    binding_id=binding_id,
                    package_id=package_id,
                    installation_id=installation_id,
                    request_id=request_id,
                    phase="INTENT",
                    runtime_state=None,
                    runtime_generation=None,
                    failure_code=None,
                    connection_ref=None,
                    blocker="PACKAGE_BINDING_ACTIVATION_PENDING",
                    updated_at=now,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            self._secure_sqlite_files()
        return None

    def verify_package_binding_intent(self, request_id: str, scope: Any) -> None:
        """Check the SDK callback still refers to the already committed intent.

        中文：核验 SDK 回调使用的范围与先前持久化的 intent 完全一致。
        """

        with self._lock:
            row = self._connection.execute(
                "SELECT binding_id, package_id, installation_id, operation, phase "
                "FROM package_binding_operations WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if (
            row is None
            or not self._binding_scope_matches(
                row,
                binding_id=scope.binding_id,
                package_id=scope.package_id,
                installation_id=scope.installation_id,
            )
            or row[4] != "INTENT"
        ):
            raise ValueError("YIELD_PACKAGE_BINDING_INTENT_CONFLICT")

    def record_package_binding_outcome(
        self,
        request_id: str,
        binding_id: str,
        package_id: str,
        installation_id: str,
        status: dict[str, Any] | None,
        receipt: dict[str, Any],
        *,
        phase: str,
        blocker: str | None,
    ) -> None:
        """Atomically persist the observed runtime state and opaque broker receipt.

        中文：在同一 SQLite 事务内持久化运行状态和不透明 Broker 回执。
        """

        if phase not in {"OUTCOME_PENDING_COMPLETE", "PENDING_RECONCILE"}:
            raise ValueError("YIELD_PACKAGE_BINDING_PHASE_INVALID")
        now = datetime.now(UTC).isoformat()
        status_json = json.dumps(status, sort_keys=True, separators=(",", ":")) if status is not None else None
        receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT binding_id, package_id, installation_id, operation, phase, receipt_json "
                    "FROM package_binding_operations WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if (
                    row is None
                    or not self._binding_scope_matches(
                        row, binding_id=binding_id, package_id=package_id, installation_id=installation_id
                    )
                    or row[4] not in {"INTENT", "OUTCOME_PENDING_COMPLETE", "PENDING_RECONCILE"}
                    or (row[5] is not None and json.loads(row[5]) != receipt)
                ):
                    raise ValueError("YIELD_PACKAGE_BINDING_RECEIPT_CONFLICT")
                self._connection.execute(
                    "UPDATE package_binding_operations SET phase=?,updated_at=?,status_json=?,receipt_json=?,blocker=? "
                    "WHERE request_id=?",
                    (phase, now, status_json, receipt_json, blocker, request_id),
                )
                self._write_package_binding_state(
                    binding_id=binding_id,
                    package_id=package_id,
                    installation_id=installation_id,
                    request_id=request_id,
                    phase=phase,
                    runtime_state=status.get("state") if status else None,
                    runtime_generation=status.get("generation") if status else None,
                    failure_code=status.get("failure_code") if status else None,
                    connection_ref=status.get("connection_ref") if status else None,
                    blocker=blocker,
                    updated_at=now,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            self._secure_sqlite_files()

    def mark_package_binding_unknown(self, request_id: str, blocker: str) -> None:
        """Retain an intent without a receipt as non-replayable UNKNOWN state.

        中文：将缺少 receipt 的 intent 标为不可重放的 UNKNOWN 状态。
        """

        now = datetime.now(UTC).isoformat()
        state_values: tuple[Any, ...] | None = None
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT binding_id, package_id, installation_id, operation, phase, receipt_json "
                    "FROM package_binding_operations WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(request_id)
                if row[5] is not None:
                    self._connection.commit()
                    return
                if row[4] not in {"INTENT", "UNKNOWN"}:
                    self._connection.commit()
                    return
                self._connection.execute(
                    "UPDATE package_binding_operations SET phase='UNKNOWN',updated_at=?,blocker=? WHERE request_id=?",
                    (now, blocker, request_id),
                )
                state_values = (row[0], row[1], row[2])
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            self._secure_sqlite_files()
            if state_values is not None:
                self._connection.execute("BEGIN IMMEDIATE")
                try:
                    self._write_package_binding_state(
                        binding_id=state_values[0],
                        package_id=state_values[1],
                        installation_id=state_values[2],
                        request_id=request_id,
                        phase="UNKNOWN",
                        runtime_state=None,
                        runtime_generation=None,
                        failure_code=None,
                        connection_ref=None,
                        blocker=blocker,
                        updated_at=now,
                    )
                    self._connection.commit()
                except sqlite3.Error:
                    self._connection.rollback()
                    # The operation journal remains authoritative if its status projection
                    # cannot be updated during a local storage failure.
                    return
                self._secure_sqlite_files()

    def package_binding_operation_for_reconcile(self, request_id: str, binding_id: str) -> dict[str, Any] | None:
        """Load one private operation row; its receipt must never reach HTTP output.

        中文：读取内部恢复所需的操作行；其中 receipt 绝不能进入 HTTP 响应。
        """

        with self._lock:
            row = self._connection.execute(
                "SELECT request_id,binding_id,package_id,installation_id,operation,phase,status_json,receipt_json,blocker "
                "FROM package_binding_operations WHERE request_id=? AND binding_id=?",
                (request_id, binding_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "request_id": row[0],
            "binding_id": row[1],
            "package_id": row[2],
            "installation_id": row[3],
            "operation": row[4],
            "phase": row[5],
            "status": json.loads(row[6]) if row[6] else None,
            "receipt": json.loads(row[7]) if row[7] else None,
            "blocker": row[8],
        }

    def mark_package_binding_completed(self, request_id: str) -> None:
        """Mark a durably observed activation completed and erase its broker token.

        中文：在 SDK Complete 成功后标记激活完成，并清除数据库中的 Broker token。
        """

        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT binding_id,package_id,installation_id,phase,receipt_json,status_json "
                    "FROM package_binding_operations WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if row is None or row[3] not in {"OUTCOME_PENDING_COMPLETE", "COMPLETED"}:
                    raise ValueError("YIELD_PACKAGE_BINDING_OUTCOME_MISSING")
                status = json.loads(row[5]) if row[5] else None
                if not status or status.get("state") != "RUNNING" or not status.get("connection_ref"):
                    raise ValueError("YIELD_PACKAGE_BINDING_OUTCOME_INVALID")
                self._connection.execute(
                    "UPDATE package_binding_operations SET phase='COMPLETED',updated_at=?,receipt_json=NULL,blocker=NULL "
                    "WHERE request_id=?",
                    (now, request_id),
                )
                self._write_package_binding_state(
                    binding_id=row[0],
                    package_id=row[1],
                    installation_id=row[2],
                    request_id=request_id,
                    phase="ACTIVE",
                    runtime_state=status.get("state"),
                    runtime_generation=status.get("generation"),
                    failure_code=status.get("failure_code"),
                    connection_ref=status.get("connection_ref"),
                    blocker=None,
                    updated_at=now,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            self._secure_sqlite_files()

    def package_binding_status(self, binding_id: str) -> dict[str, Any]:
        """Return only the public-safe status projection for one binding.

        中文：仅返回绑定状态的安全投影，不返回连接引用或 Broker 回执。
        """

        with self._lock:
            row = self._connection.execute(
                "SELECT package_id,installation_id,request_id,phase,runtime_state,runtime_generation,blocker,updated_at "
                "FROM package_binding_owner_state WHERE binding_id=?",
                (binding_id,),
            ).fetchone()
            operation = self._connection.execute(
                "SELECT request_id,installation_id,phase,blocker FROM package_binding_operations "
                "WHERE binding_id=? ORDER BY updated_at DESC,created_at DESC LIMIT 1",
                (binding_id,),
            ).fetchone()
        if row is None:
            if operation is not None:
                return {
                    "bindingId": binding_id,
                    "packageId": "cyrene.training.llama-factory",
                    "phase": "ACTIVE" if operation[2] == "COMPLETED" else operation[2],
                    "requestId": operation[0],
                    "installationId": operation[1],
                    "runtimeState": None,
                    "runtimeGeneration": None,
                    "blocker": operation[3],
                    "updatedAt": None,
                }
            return {
                "bindingId": binding_id,
                "packageId": "cyrene.training.llama-factory",
                "phase": "UNBOUND",
                "requestId": None,
                "installationId": None,
                "runtimeState": None,
                "runtimeGeneration": None,
                "blocker": "PACKAGE_BINDING_NOT_INITIALIZED",
                "updatedAt": None,
            }
        phase = row[3]
        request_id = row[2]
        installation_id = row[1]
        blocker = row[6]
        if operation is not None:
            request_id = operation[0]
            installation_id = operation[1]
            phase = "ACTIVE" if operation[2] == "COMPLETED" else operation[2]
            if operation[2] != "COMPLETED":
                blocker = operation[3]
        return {
            "bindingId": binding_id,
            "packageId": row[0],
            "installationId": installation_id,
            "requestId": request_id,
            "phase": phase,
            "runtimeState": row[4],
            "runtimeGeneration": row[5],
            "blocker": blocker,
            "updatedAt": row[7],
        }

    def _write_package_binding_state(
        self,
        *,
        binding_id: str,
        package_id: str,
        installation_id: str | None,
        request_id: str | None,
        phase: str,
        runtime_state: str | None,
        runtime_generation: int | None,
        failure_code: str | None,
        connection_ref: str | None,
        blocker: str | None,
        updated_at: str,
    ) -> None:
        self._connection.execute(
            "INSERT INTO package_binding_owner_state("
            "binding_id,package_id,installation_id,request_id,phase,runtime_state,runtime_generation,"
            "failure_code,connection_ref,blocker,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(binding_id) DO UPDATE SET package_id=excluded.package_id,"
            "installation_id=excluded.installation_id,request_id=excluded.request_id,phase=excluded.phase,"
            "runtime_state=excluded.runtime_state,runtime_generation=excluded.runtime_generation,"
            "failure_code=excluded.failure_code,connection_ref=excluded.connection_ref,"
            "blocker=excluded.blocker,updated_at=excluded.updated_at",
            (
                binding_id,
                package_id,
                installation_id,
                request_id,
                phase,
                runtime_state,
                runtime_generation,
                failure_code,
                connection_ref,
                blocker,
                updated_at,
            ),
        )

    def get(self, kind: str, resource_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT document FROM resources WHERE kind=? AND id=?", (kind, resource_id)
            ).fetchone()
        if row is None:
            raise KeyError(resource_id)
        return json.loads(row[0])

    def list(self, kind: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT document FROM resources WHERE kind=? ORDER BY id", (kind,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_unscoped(self, kind: str) -> List[dict[str, Any]]:
        """List only legacy resources without trusted Workspace provenance."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT resource.document FROM resources AS resource "
                "LEFT JOIN workspace_resource_scopes AS scope "
                "ON scope.kind = resource.kind AND scope.id = resource.id "
                "WHERE resource.kind = ? AND scope.id IS NULL ORDER BY resource.id",
                (kind,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_for_workspace(self, kind: str, organization_id: str, workspace_id: str) -> List[dict[str, Any]]:
        """List resources whose immutable scope exactly matches the caller."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT resource.document FROM resources AS resource "
                "JOIN workspace_resource_scopes AS scope "
                "ON scope.kind = resource.kind AND scope.id = resource.id "
                "WHERE resource.kind = ? AND scope.organization_id = ? AND scope.workspace_id = ? "
                "ORDER BY resource.id",
                (kind, organization_id, workspace_id),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def workspace_resource_scope(self, kind: str, resource_id: str) -> tuple[str, str] | None:
        """Return trusted provenance, or None for legacy/unbound resources."""
        with self._lock:
            row = self._connection.execute(
                "SELECT organization_id, workspace_id FROM workspace_resource_scopes WHERE kind = ? AND id = ?",
                (kind, resource_id),
            ).fetchone()
        return (str(row[0]), str(row[1])) if row else None

    def save(self, kind: str, resource_id: str, document: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO resources VALUES(?,?,?)",
                (
                    kind,
                    resource_id,
                    json.dumps(document, sort_keys=True),
                ),
            )

    def create_draft(
        self,
        key: str,
        command: dict[str, Any],
        document: dict[str, Any],
        workspace_scope: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        """Commit resource and idempotency receipt in the same transaction.

        在同一事务中提交资源与幂等回执。
        """
        digest = hashlib.sha256(json.dumps(command, sort_keys=True).encode()).hexdigest()
        with self._lock, self._connection:
            if workspace_scope is None:
                row = self._connection.execute("SELECT digest,id FROM receipts WHERE key=?", (key,)).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT digest,id FROM workspace_draft_receipts "
                    "WHERE organization_id=? AND workspace_id=? AND key=?",
                    (workspace_scope[0], workspace_scope[1], key),
                ).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError("YIELD_IDEMPOTENCY_CONFLICT: key already identifies another import")
                if self.workspace_resource_scope("draft", row[1]) != workspace_scope:
                    raise ValueError("YIELD_WORKSPACE_SCOPE_CONFLICT")
                return self.get("draft", row[1])
            self._connection.execute(
                "INSERT INTO resources VALUES(?,?,?)", ("draft", document["id"], json.dumps(document))
            )
            if workspace_scope is not None:
                self._connection.execute(
                    "INSERT INTO workspace_draft_receipts(organization_id,workspace_id,key,digest,id) "
                    "VALUES (?,?,?,?,?)",
                    (workspace_scope[0], workspace_scope[1], key, digest, document["id"]),
                )
                self._connection.execute(
                    "INSERT INTO workspace_resource_scopes(kind,id,organization_id,workspace_id) "
                    "VALUES ('draft',?,?,?)",
                    (document["id"], workspace_scope[0], workspace_scope[1]),
                )
            else:
                self._connection.execute("INSERT INTO receipts VALUES(?,?,?)", (key, digest, document["id"]))
        return document

    def create_result(
        self,
        document: dict[str, Any],
        workspace_scope: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        """Keep the first immutable result when reconciliation and reads race.

        reconciliation 和读取发生竞争时,保留最早的不可变结果。
        """
        with self._lock, self._connection:
            inserted = self._connection.execute(
                "INSERT OR IGNORE INTO resources VALUES ('result', ?, ?)",
                (document["id"], json.dumps(document, sort_keys=True)),
            ).rowcount
            stored_scope = self.workspace_resource_scope("result", document["id"])
            if inserted and workspace_scope is not None:
                self._connection.execute(
                    "INSERT INTO workspace_resource_scopes(kind,id,organization_id,workspace_id) "
                    "VALUES ('result',?,?,?)",
                    (document["id"], workspace_scope[0], workspace_scope[1]),
                )
            elif stored_scope != workspace_scope:
                raise ValueError("YIELD_WORKSPACE_SCOPE_CONFLICT")
            training_run = document.get("trainingRun") or document.get("training_run", {})
            run_id = training_run.get("id") if isinstance(training_run, dict) else str(training_run).split("/")[-1]
            if run_id:
                ended_at_str = document.get("createdAt") or document.get("created_at")
                ended_at = datetime.fromisoformat(ended_at_str) if ended_at_str else None
                self.record_terminal_run(run_id, "COMPLETED", ended_at)
            return self.get("result", document["id"])

    def append_events(self, run_id: str, attempt_id: str, documents: List[dict[str, Any]]) -> List[dict[str, Any]]:
        """Append one attempt's new events with a monotonic per-run sequence.

        Persisted event count is the durable harvest offset, so re-reading a
        Kernel log after a controller restart cannot duplicate sequences.

        以已持久化条数作为采集偏移；控制服务重启后重读日志不会产生重复序号。
        """

        if not documents:
            return []
        appended: List[dict[str, Any]] = []
        with self._lock, self._connection:
            sequence = int(
                self._connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM training_events WHERE run_id=?", (run_id,)
                ).fetchone()[0]
            )
            event_index = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM training_events WHERE run_id=? AND attempt_id=?",
                    (run_id, attempt_id),
                ).fetchone()[0]
            )
            for offset, document in enumerate(documents):
                sequence += 1
                index = event_index + offset
                record = {**document, "sequence": sequence, "eventIndex": index}
                self._connection.execute(
                    "INSERT OR REPLACE INTO training_events(run_id, attempt_id, event_index, sequence, document)"
                    " VALUES(?,?,?,?,?)",
                    (run_id, attempt_id, index, sequence, json.dumps(record, sort_keys=True)),
                )
                appended.append(record)
        return appended

    def event_count(self, run_id: str, attempt_id: str) -> int:
        """Return how many events are already durable for one attempt.

        返回一个 attempt 已持久化的事件数量。
        """

        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) FROM training_events WHERE run_id=? AND attempt_id=?",
                (run_id, attempt_id),
            ).fetchone()
        return int(row[0])

    def append_diagnostics(self, run_id: str, attempt_id: str, documents: List[dict[str, Any]]) -> List[dict[str, Any]]:
        """Append one attempt's new diagnostic records with a per-run sequence.

        Mirrors append_events so both streams page the same way and a controller
        restart cannot duplicate sequences.

        与事件一致地按 Run 分配单调序号，重启后重读不会产生重复序号。
        """

        if not documents:
            return []
        appended: List[dict[str, Any]] = []
        with self._lock, self._connection:
            sequence = int(
                self._connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM training_diagnostics WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
            )
            record_index = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM training_diagnostics WHERE run_id=? AND attempt_id=?",
                    (run_id, attempt_id),
                ).fetchone()[0]
            )
            for offset, document in enumerate(documents):
                sequence += 1
                index = record_index + offset
                record = {**document, "sequence": sequence}
                self._connection.execute(
                    "INSERT OR REPLACE INTO training_diagnostics"
                    "(run_id, attempt_id, record_index, sequence, document) VALUES(?,?,?,?,?)",
                    (run_id, attempt_id, index, sequence, json.dumps(record, sort_keys=True)),
                )
                appended.append(record)
        return appended

    def diagnostics_count(self, run_id: str, attempt_id: str) -> int:
        """Return how many diagnostic records are already durable for one attempt.

        返回一个 attempt 已持久化的诊断记录数量。
        """

        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) FROM training_diagnostics WHERE run_id=? AND attempt_id=?",
                (run_id, attempt_id),
            ).fetchone()
        return int(row[0])

    def diagnostics_degraded(self, run_id: str) -> bool:
        """True when a persisted record shows the output budget was exhausted.

        当持久化记录表明输出字节上限已耗尽时返回 True。
        """

        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM training_diagnostics WHERE run_id=? AND document LIKE '%BUDGET_EXCEEDED%'",
                (run_id,),
            ).fetchone()
        return row is not None

    def purge_expired_diagnostics(self) -> int:
        """Drop persisted diagnostics for terminal runs past the retention window.

        删除超过保留期限的终态 run 持久化诊断记录。
        """

        cutoff = datetime.now(UTC) - timedelta(days=self.log_retention_days)
        purged = 0
        with self._lock, self._connection:
            for run_id in self._terminal_run_ids_before(cutoff):
                cursor = self._connection.execute("DELETE FROM training_diagnostics WHERE run_id=?", (run_id,))
                purged += int(cursor.rowcount or 0)
        return purged

    def list_diagnostics(self, run_id: str, after_sequence: int = 0, limit: int = 200) -> List[dict[str, Any]]:
        """Read persisted diagnostics in sequence order. | 按序号读取已持久化诊断。"""

        bounded = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._connection.execute(
                "SELECT document FROM training_diagnostics WHERE run_id=? AND sequence>? ORDER BY sequence ASC LIMIT ?",
                (run_id, int(after_sequence), bounded),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_events(self, run_id: str, after_sequence: int = 0, limit: int = 5000) -> List[dict[str, Any]]:
        """Read persisted events in sequence order. | 按序号读取已持久化事件。"""

        bounded = max(1, min(int(limit), 20000))
        with self._lock:
            rows = self._connection.execute(
                "SELECT document FROM training_events WHERE run_id=? AND sequence>? ORDER BY sequence ASC LIMIT ?",
                (run_id, int(after_sequence), bounded),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def recall_receipt(self, key: str, digest: str) -> dict[str, Any] | None:
        """Resolve one durable action receipt or reject conflicting reuse.

        解析一个持久化操作回执,或拒绝冲突的重复使用。
        """

        with self._lock:
            row = self._connection.execute(
                "SELECT digest, document FROM action_receipts WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        if row[0] != digest:
            raise ValueError("YIELD_IDEMPOTENCY_CONFLICT: key already identifies another action")
        return json.loads(row[1])

    def save_receipt(self, key: str, digest: str, document: dict[str, Any]) -> dict[str, Any]:
        """Persist an action receipt for later idempotent replay.

        持久化操作回执,以供后续幂等重放。
        """

        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO action_receipts(key, digest, document) VALUES(?,?,?)",
                (key, digest, json.dumps(document, sort_keys=True)),
            )
            row = self._connection.execute(
                "SELECT digest, document FROM action_receipts WHERE key=?", (key,)
            ).fetchone()
        if row[0] != digest:
            raise ValueError("YIELD_IDEMPOTENCY_CONFLICT: key already identifies another action")
        return json.loads(row[1])

    def record_terminal_run(self, run_id: UUID | str, state: str, ended_at: datetime | None = None) -> None:
        """Record a run transitioning to a terminal state (COMPLETED, FAILED, CANCELLED).

        The earliest observed timestamp wins: a run is read many times, and a
        later observation must not extend its retention window.
        """

        ts = (ended_at or datetime.now(UTC)).isoformat()
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT ended_at FROM run_terminals WHERE run_id=?", (str(run_id),)
            ).fetchone()
            if row is not None and str(row[0]) <= ts:
                self._connection.execute("UPDATE run_terminals SET state=? WHERE run_id=?", (state, str(run_id)))
                return
            self._connection.execute(
                "INSERT OR REPLACE INTO run_terminals(run_id, state, ended_at) VALUES(?,?,?)",
                (str(run_id), state, ts),
            )

    def _terminal_run_ids_before(self, cutoff: datetime) -> List[str]:
        terminal_ids: set[str] = set()
        cutoff_iso = cutoff.isoformat()
        with self._lock:
            rows = self._connection.execute(
                "SELECT run_id FROM run_terminals WHERE ended_at <= ?",
                (cutoff_iso,),
            ).fetchall()
            for row in rows:
                terminal_ids.add(row[0])

            results = self._connection.execute("SELECT document FROM resources WHERE kind='result'").fetchall()
            for (doc_text,) in results:
                doc = json.loads(doc_text)
                created_at_str = doc.get("createdAt") or doc.get("created_at")
                if created_at_str:
                    try:
                        doc_dt = datetime.fromisoformat(created_at_str)
                        if doc_dt <= cutoff:
                            run_ref = doc.get("trainingRun") or doc.get("training_run", {})
                            if isinstance(run_ref, dict):
                                run_id = run_ref.get("id") or (run_ref.get("uri", "").split("/")[-1])
                            else:
                                run_id = str(run_ref).split("/")[-1]
                            if run_id:
                                terminal_ids.add(str(run_id))
                    except (ValueError, TypeError) as exc:
                        sys.stderr.write(
                            format_cyrene_log(
                                level="WARN",
                                event_name="yield.training.terminal_run_parse_failed",
                                message="Failed to parse document timestamp or run reference",
                                attributes={"cause_type": type(exc).__name__},
                            )
                            + "\n"
                        )
        return sorted(terminal_ids)

    def add_close_callback(self, callback: Callable[[], None]) -> None:
        """Run a lifecycle cleanup before this store closes its database.

        If the store has already closed, run the callback immediately so the
        caller cannot leave a newly registered resource alive by mistake.

        中文:注册数据库关闭前的生命周期清理；若 store 已关闭则立即执行。
        """

        with self._lock:
            if not self._closed:
                self._close_callbacks.append(callback)
                return
        callback()

    def close(self) -> None:
        """Run registered cleanup outside the store lock, then close SQLite.

        Callback failures are surfaced after every cleanup is attempted and the
        database is closed. Repeated calls are harmless and never alter task
        activity records in the external maintenance broker.

        中文:先在锁外停止生命周期线程，再关闭 SQLite；关闭不代表任务完成。
        """

        with self._lock:
            if self._closed:
                return
            self._closed = True
            callbacks = tuple(self._close_callbacks)
            self._close_callbacks.clear()

        errors: list[Exception] = []
        for callback in callbacks:
            try:
                callback()
            except Exception as error:
                errors.append(error)

        with self._lock:
            self._connection.close()

        if errors:
            raise ExceptionGroup("Yield ProductStore close callback failures", errors)
