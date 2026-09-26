"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: tests.test_log_retention                                   │
│  Role: Diagnostics retention for terminal runs (30-day window).      │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from cy_exec.training.product_store import ProductStore


def test_purge_removes_diagnostics_only_for_expired_terminal_runs(tmp_path: Path) -> None:
    """Retention follows terminal state and age, not which runs published a result."""

    store = ProductStore(tmp_path / "product.sqlite3")
    now = datetime.now(UTC)
    old_terminal = uuid4()
    recent_terminal = uuid4()
    active = uuid4()

    for run_id, message in (
        (old_terminal, "old failure output"),
        (recent_terminal, "recent failure output"),
        (active, "still running"),
    ):
        store.append_diagnostics(
            str(run_id),
            f"{run_id}:1",
            [{"timestamp": now.isoformat(), "message": message}],
        )

    store.record_terminal_run(old_terminal, "FAILED", now - timedelta(days=35))
    store.record_terminal_run(recent_terminal, "CANCELLED", now - timedelta(days=5))

    assert store.purge_expired_diagnostics() == 1
    assert store.list_diagnostics(str(old_terminal)) == []
    assert len(store.list_diagnostics(str(recent_terminal))) == 1
    # A run that never reached a terminal state keeps its output.
    assert len(store.list_diagnostics(str(active))) == 1
    store.close()


def test_every_terminal_state_is_retained(tmp_path: Path) -> None:
    """A failed or cancelled run is retained exactly like a completed one."""

    store = ProductStore(tmp_path / "product.sqlite3")
    now = datetime.now(UTC)
    old = now - timedelta(days=40)

    for state in ("COMPLETED", "FAILED", "CANCELLED"):
        run_id = uuid4()
        store.append_diagnostics(
            str(run_id),
            f"{run_id}:1",
            [{"timestamp": now.isoformat(), "message": f"{state} output"}],
        )
        store.record_terminal_run(run_id, state, old)

    assert store.purge_expired_diagnostics() == 3
    store.close()


def test_a_result_records_its_run_for_retention(tmp_path: Path) -> None:
    """A result published before the controller restarted still ages out."""

    store = ProductStore(tmp_path / "product.sqlite3")
    now = datetime.now(UTC)
    old_run = uuid4()
    store.append_diagnostics(
        str(old_run), f"{old_run}:1", [{"timestamp": now.isoformat(), "message": "old"}]
    )
    store.create_result(
        {
            "id": str(uuid4()),
            "createdAt": (now - timedelta(days=40)).isoformat(),
            "trainingRun": {"id": str(old_run)},
        }
    )

    assert store.purge_expired_diagnostics() == 1
    assert store.list_diagnostics(str(old_run)) == []
    store.close()


def test_reading_an_old_terminal_run_does_not_extend_retention(tmp_path: Path) -> None:
    """A later observation must not push the retention clock forward."""

    store = ProductStore(tmp_path / "product.sqlite3")
    run_id = uuid4()
    old = datetime.now(UTC) - timedelta(days=40)
    store.record_terminal_run(run_id, "FAILED", old)

    # The service observes the same terminal run again today.
    store.record_terminal_run(run_id, "FAILED")

    store.append_diagnostics(str(run_id), f"{run_id}:1", [{"message": "old"}])
    assert store.purge_expired_diagnostics() == 1
    store.close()
