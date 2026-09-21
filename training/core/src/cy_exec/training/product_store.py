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
from typing import Any, List


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
                "CREATE TABLE IF NOT EXISTS action_receipts("
                "key TEXT PRIMARY KEY, digest TEXT NOT NULL, document TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS training_events("
                "run_id TEXT NOT NULL, attempt_id TEXT NOT NULL, event_index INTEGER NOT NULL,"
                "sequence INTEGER NOT NULL, document TEXT NOT NULL,"
                "PRIMARY KEY(run_id, attempt_id, event_index));"
                "CREATE INDEX IF NOT EXISTS ix_training_events_run_sequence"
                " ON training_events(run_id, sequence);"
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
        """Return how many events are already durable for one attempt."""

        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) FROM training_events WHERE run_id=? AND attempt_id=?",
                (run_id, attempt_id),
            ).fetchone()
        return int(row[0])

    def list_events(self, run_id: str, after_sequence: int = 0, limit: int = 5000) -> List[dict[str, Any]]:
        """Read persisted events in sequence order. | 按序号读取已持久化事件。"""

        bounded = max(1, min(int(limit), 20000))
        with self._lock:
            rows = self._connection.execute(
                "SELECT document FROM training_events WHERE run_id=? AND sequence>?"
                " ORDER BY sequence ASC LIMIT ?",
                (run_id, int(after_sequence), bounded),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def recall_receipt(self, key: str, digest: str) -> dict[str, Any] | None:
        """Resolve one durable action receipt or reject conflicting reuse."""

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
        """Persist an action receipt for later idempotent replay."""

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

    def close(self) -> None:
        self._connection.close()
