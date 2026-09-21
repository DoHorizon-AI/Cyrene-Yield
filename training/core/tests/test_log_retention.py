"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: tests.test_log_retention                                   │
│  Role: Raw log 100 MiB limit and 30-day retention verification.      │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from cy_exec.training.product_store import ProductStore


def test_raw_log_size_limit_truncates_at_100mib(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "product.sqlite3")
    run_id = uuid4()

    log_path = store._log_path(run_id)
    with log_path.open("wb") as f:
        f.seek(ProductStore.LOG_SIZE_LIMIT_BYTES)
        f.write(b"\0")

    initial_size = log_path.stat().st_size
    assert initial_size >= ProductStore.LOG_SIZE_LIMIT_BYTES

    # Append lines past 100 MiB
    store.append_raw_log(run_id, "first line after limit")
    assert log_path.stat().st_size == initial_size

    # Verify a warning event was recorded
    events = store.list_events(str(run_id))
    assert len(events) == 1
    assert events[0]["kind"] == "warn"
    assert "Raw log limit reached (100 MiB)" in events[0]["message"]

    # Append another line; should not record a duplicate warning
    store.append_raw_log(run_id, "second line after limit")
    events_after = store.list_events(str(run_id))
    assert len(events_after) == 1

    # For a normal run under the limit, append succeeds
    normal_run_id = uuid4()
    store.append_raw_log(normal_run_id, "normal line 1")
    store.append_raw_log(normal_run_id, "normal line 2")
    normal_log = store._log_path(normal_run_id)
    assert normal_log.exists()
    assert normal_log.read_text(encoding="utf-8") == "normal line 1\nnormal line 2\n"

    store.close()


def test_purge_expired_logs_removes_only_terminal_runs(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "product.sqlite3")

    now = datetime.now(UTC)
    old_time = now - timedelta(days=35)
    recent_time = now - timedelta(days=5)

    # 1. Terminal run older than 30 days -> should be purged
    old_terminal_id = uuid4()
    store.append_raw_log(old_terminal_id, "old terminal log")
    store.record_terminal_run(old_terminal_id, "COMPLETED", ended_at=old_time)
    assert store._log_path(old_terminal_id).exists()

    # 2. Terminal run newer than 30 days (5 days old) -> should NOT be purged
    recent_terminal_id = uuid4()
    store.append_raw_log(recent_terminal_id, "recent terminal log")
    store.record_terminal_run(recent_terminal_id, "FAILED", ended_at=recent_time)
    assert store._log_path(recent_terminal_id).exists()

    # 3. Active run (non-terminal) created long ago -> should NOT be purged
    old_active_id = uuid4()
    store.append_raw_log(old_active_id, "active running log")
    assert store._log_path(old_active_id).exists()

    # Run purge
    purged_count = store.purge_expired_logs()
    assert purged_count == 1

    # Verify old terminal log file is deleted
    assert not store._log_path(old_terminal_id).exists()
    # Verify recent terminal log file still exists
    assert store._log_path(recent_terminal_id).exists()
    # Verify active run log file still exists
    assert store._log_path(old_active_id).exists()

    store.close()
