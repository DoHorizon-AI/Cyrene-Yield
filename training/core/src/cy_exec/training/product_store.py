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
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, List
from uuid import UUID

from .logging import format_cyrene_log


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
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.log_retention_days = log_retention_days
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
        """Commit resource and idempotency receipt in the same transaction.

        在同一事务中提交资源与幂等回执。
        """
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
        """Keep the first immutable result when reconciliation and reads race.

        reconciliation 和读取发生竞争时,保留最早的不可变结果。
        """
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO resources VALUES ('result', ?, ?)",
                (document["id"], json.dumps(document, sort_keys=True)),
            )
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

    def append_diagnostics(
        self, run_id: str, attempt_id: str, documents: List[dict[str, Any]]
    ) -> List[dict[str, Any]]:
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
                cursor = self._connection.execute(
                    "DELETE FROM training_diagnostics WHERE run_id=?", (run_id,)
                )
                purged += int(cursor.rowcount or 0)
        return purged

    def list_diagnostics(
        self, run_id: str, after_sequence: int = 0, limit: int = 200
    ) -> List[dict[str, Any]]:
        """Read persisted diagnostics in sequence order. | 按序号读取已持久化诊断。"""

        bounded = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._connection.execute(
                "SELECT document FROM training_diagnostics WHERE run_id=? AND sequence>?"
                " ORDER BY sequence ASC LIMIT ?",
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
                self._connection.execute(
                    "UPDATE run_terminals SET state=? WHERE run_id=?", (state, str(run_id))
                )
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

    def close(self) -> None:
        self._connection.close()
