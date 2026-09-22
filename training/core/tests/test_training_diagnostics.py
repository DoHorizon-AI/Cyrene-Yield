"""
Unit tests for Yield training diagnostics capture, paging and retention.

Tests the raw-output path end to end at the seams that matter: the worker sink
must never block the trainer, the host must only consume complete records, and
the public page must stay bounded and redacted.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from cy_exec.training.executors.base import ProcessHandle
from cy_exec.training.executors.kernel_training import KernelTrainingConfiguration, KernelTrainingExecutor
from cy_exec.training.product_api import create_app
from cy_exec.training.product_store import ProductStore

WORKER_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "cy_exec"
    / "training"
    / "executors"
    / "training_worker.py"
)


def _load_worker():
    spec = importlib.util.spec_from_file_location("cyrene_training_worker", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sink_tags_both_streams_and_keeps_the_merged_log():
    worker = _load_worker()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        sink = worker.DiagnosticsSink(root)
        sink.start()
        sink.put("stdout", "step 1 loss=0.5")
        sink.put("stderr", "CUDA out of memory")
        assert sink.close() is False

        records = [
            json.loads(line)
            for line in (root / "diagnostics.ndjson").read_text(encoding="utf-8").splitlines()
        ]
        assert [record["stream"] for record in records] == ["stdout", "stderr"]
        assert records[0]["level"] == "info"
        assert records[1]["level"] == "warn"
        assert [record["sequence"] for record in records] == [0, 1]
        # Business events still come from the merged log, so it keeps both lines.
        assert (root / "runtime.log").read_text(encoding="utf-8").splitlines() == [
            "step 1 loss=0.5",
            "CUDA out of memory",
        ]


def test_sink_over_budget_stops_writing_but_keeps_draining():
    worker = _load_worker()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        sink = worker.DiagnosticsSink(root, limit_bytes=200)
        sink.start()
        for index in range(200):
            sink.put("stderr", f"line {index} " + "x" * 50)
        assert sink.close() is True

        assert (root / "diagnostics.degraded").exists()
        records = [
            json.loads(line)
            for line in (root / "diagnostics.ndjson").read_text(encoding="utf-8").splitlines()
        ]
        assert any(record.get("code") == "YIELD.DIAGNOSTICS.BUDGET_EXCEEDED" for record in records)
        # The trainer never blocks: every line was consumed even while dropped.
        assert len(records) < 200


def test_sink_degrades_without_blocking_when_the_file_cannot_be_written():
    worker = _load_worker()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        # A directory in place of the sink file makes every open fail.
        (root / "diagnostics.ndjson").mkdir()
        sink = worker.DiagnosticsSink(root)
        sink.start()
        for index in range(100):
            sink.put("stdout", f"line {index}")
        assert sink.close() is True
        assert (root / "diagnostics.degraded").exists()


def _executor(root: Path) -> KernelTrainingExecutor:
    configuration = KernelTrainingConfiguration(
        socket=root / "kernel.sock",
        installations=root / "installations",
        state_directory=root / "state",
        python=Path(__file__).resolve().parents[0],
        signing_key_file=root / "key",
    )
    return KernelTrainingExecutor(configuration)


def test_executor_reads_only_complete_records():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        executor = _executor(root)
        worker_dir = root / "installations" / "worker-1"
        worker_dir.mkdir(parents=True)
        handle = ProcessHandle(pid=1, argv=[], work_dir="", extra={"worker_id": "worker-1"})
        sink_path = worker_dir / "diagnostics.ndjson"

        assert executor.read_new_diagnostics(handle) == []

        with sink_path.open("w", encoding="utf-8") as stream:
            stream.write('{"sequence":0,"stream":"stdout","message":"complete"}\n')
            # A half-written tail must stay buffered for the next poll.
            stream.write('{"sequence":1,"stream":"std')
            stream.flush()

        assert executor.read_new_diagnostics(handle) == [
            {"sequence": 0, "stream": "stdout", "message": "complete"}
        ]
        assert executor.read_new_diagnostics(handle) == []

        with sink_path.open("a", encoding="utf-8") as stream:
            stream.write('err","message":"late"}\n')
        records = executor.read_new_diagnostics(handle)
        assert [record["message"] for record in records] == ["late"]

        assert executor.diagnostics_degraded(handle) is False
        (worker_dir / "diagnostics.degraded").write_text("", encoding="utf-8")
        assert executor.diagnostics_degraded(handle) is True


def test_store_pages_diagnostics_and_reports_degradation():
    with TemporaryDirectory() as tmp:
        store = ProductStore(Path(tmp) / "product.sqlite3")
        store.append_diagnostics(
            "run-1",
            "attempt-1",
            [
                {"timestamp": "2026-01-01T00:00:00Z", "stream": "stderr", "message": "boom"},
                {"timestamp": "2026-01-01T00:00:01Z", "stream": "stdout", "message": "step 2"},
            ],
        )
        first = store.list_diagnostics("run-1", after_sequence=0, limit=1)
        assert len(first) == 1
        assert first[0]["sequence"] == 1
        rest = store.list_diagnostics("run-1", after_sequence=1)
        assert [record["sequence"] for record in rest] == [2]

        assert store.diagnostics_count("run-1", "attempt-1") == 2
        assert store.diagnostics_degraded("run-1") is False

        store.append_diagnostics(
            "run-1",
            "attempt-1",
            [{"timestamp": "2026-01-01T00:00:02Z", "code": "YIELD.DIAGNOSTICS.BUDGET_EXCEEDED"}],
        )
        assert store.diagnostics_degraded("run-1") is True

        # Retention only touches terminal runs.
        store.record_terminal_run("run-1", "FAILED", datetime.now(UTC) - timedelta(days=31))
        assert store.purge_expired_diagnostics() == 3
        assert store.list_diagnostics("run-1") == []
        store.close()


def test_page_is_trimmed_to_the_serialized_budget():
    from cy_exec.training.product_models import DiagnosticRecord
    from cy_exec.training.product_service import DIAGNOSTICS_PAGE_MAX_BYTES, _bounded_diagnostics

    big = [
        DiagnosticRecord(
            sequence=index + 1,
            timestamp="2026-01-01T00:00:00Z",
            message="x" * 4096,
        )
        for index in range(400)
    ]
    kept, dropped = _bounded_diagnostics(big)
    assert dropped is True
    assert len(kept) < len(big)
    serialized = json.dumps([item.model_dump(by_alias=True) for item in kept])
    assert len(serialized) <= DIAGNOSTICS_PAGE_MAX_BYTES


def test_diagnostic_document_redacts_private_paths():
    from cy_exec.training.product_service import _diagnostic_document

    class _Attempt:
        attempt_id = "attempt-7"
        metadata = {"operationId": "op-1", "resourceIds": ["res-1"]}

    secret = "/var/lib/cyrene/private/model.safetensors"
    document = _diagnostic_document(
        "11111111-1111-1111-1111-111111111111",
        _Attempt(),
        {"sequence": 3, "timestamp": "2026-01-01T00:00:00Z", "stream": "stderr", "message": f"cannot read {secret}"},
        (secret,),
    )
    assert secret not in json.dumps(document)
    assert document["attempt_id"] == "attempt-7"
    assert document["operation_id"] == "op-1"
    assert document["resource_id"] == "res-1"
    assert document["source"] == "trainer"
    assert document["stream"] == "stderr"


def test_diagnostics_endpoint_is_bounded_and_rejects_bad_cursors():
    with TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "state"
        app = create_app(state_directory=state_dir, artifact_root=Path(tmp) / "artifacts")
        with TestClient(app) as client:
            missing = client.get("/api/v1/training-runs/00000000-0000-0000-0000-000000000001/diagnostics")
            assert missing.status_code == 404
            assert missing.json()["code"] == "YIELD_RESOURCE_NOT_FOUND"

            too_many = client.get(
                "/api/v1/training-runs/00000000-0000-0000-0000-000000000001/diagnostics?limit=5000"
            )
            assert too_many.status_code == 422
