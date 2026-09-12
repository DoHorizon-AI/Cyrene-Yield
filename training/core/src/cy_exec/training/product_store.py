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
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any


class ProductStore:
    """Serialize only Yield resources; never store model or dataset content."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._lock = RLock()
        with self._connection:
            self._connection.executescript(
                "CREATE TABLE IF NOT EXISTS resources(kind TEXT, id TEXT, document TEXT, PRIMARY KEY(kind,id));"
                "CREATE TABLE IF NOT EXISTS receipts(key TEXT PRIMARY KEY, digest TEXT, id TEXT);"
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

    def create_draft(self, key: str, command: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
        """Commit resource and idempotency receipt in the same transaction."""
        digest = hashlib.sha256(json.dumps(command, sort_keys=True).encode()).hexdigest()
        with self._lock, self._connection:
            row = self._connection.execute("SELECT digest,id FROM receipts WHERE key=?", (key,)).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError("YIELD_IDEMPOTENCY_CONFLICT: key already identifies another import")
                return self.get("draft", row[1])
            self._connection.execute(
                "INSERT INTO resources VALUES(?,?,?)", ("draft", document["id"], json.dumps(document))
            )
            self._connection.execute("INSERT INTO receipts VALUES(?,?,?)", (key, digest, document["id"]))
        return document

    def create_result(self, document: dict[str, Any]) -> dict[str, Any]:
        """Keep the first immutable result when reconciliation and reads race."""
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO resources VALUES ('result', ?, ?)",
                (document["id"], json.dumps(document, sort_keys=True)),
            )
            return self.get("result", document["id"])

    def close(self) -> None:
        self._connection.close()
