"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: tests.test_rc_product_surface                              │
│  Role: Regression coverage for RC Yield collection/event/YAML APIs.  │
│  模块职责：验证 RC Yield 的分页、事件持久化与 YAML 严格映射契约。        │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from cy_artifacts import LocalArtifactProvider
from cyrene_yield_contracts import YieldArtifactKind

from cy_exec.training.llama_factory_yaml import LlamaFactoryYamlError, parse_llama_factory_yaml
from cy_exec.training.product_api import create_app
from cy_exec.training.product_store import ProductStore
from cy_exec.training.control_plane import TrainingControlPlane
from test_product_lifecycle import AdapterFixtureExecutor, _base, _runtime


class _EventExecutor(AdapterFixtureExecutor):
    """Emit one structured trainer line per attempt for SSE replay coverage.

    为 SSE replay 覆盖范围输出每个 attempt 一条结构化 trainer 行。
    """

    def __init__(self) -> None:
        super().__init__()
        self._emitted: set[int] = set()

    def read_new_output(self, handle):
        handle_id = id(handle)
        if handle_id in self._emitted:
            return []
        self._emitted.add(handle_id)
        return ['{"loss":0.25,"step":1,"epoch":0.5}']


class _ResumeExecutor(AdapterFixtureExecutor):
    """Fail the first real attempt after publishing a usable checkpoint.

    在发布可用 checkpoint 后,让第一个真实 attempt 失败。
    """

    def start(self, launch):
        handle = super().start(launch)
        checkpoint = Path(handle.work_dir) / "checkpoint-1"
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "model.safetensors").write_bytes(b"checkpoint")
        return handle

    def poll(self, _handle):
        return 1 if len(self.launches) == 2 else 0


def test_llama_factory_yaml_rejects_unknown_and_out_of_range_fields():
    with pytest.raises(LlamaFactoryYamlError, match="YIELD_LLAMA_FACTORY_UNKNOWN_FIELD"):
        parse_llama_factory_yaml("unknown_field: true\n")
    with pytest.raises(LlamaFactoryYamlError, match="YIELD_LLAMA_FACTORY_INVALID_VALUE"):
        parse_llama_factory_yaml("num_train_epochs: 0\n")


def test_product_store_assigns_monotonic_event_sequences_and_replays_receipts(tmp_path: Path):
    store = ProductStore(tmp_path / "product.sqlite3")
    first = store.append_events("run-1", "attempt-1", [{"kind": "log", "timestamp": "now"}])
    second = store.append_events("run-1", "attempt-2", [{"kind": "progress", "timestamp": "later"}])

    assert [item["sequence"] for item in first + second] == [1, 2]
    assert [item["sequence"] for item in store.list_events("run-1")] == [1, 2]
    store.save_receipt("key-1", "digest-1", {"id": "route-1"})
    assert store.recall_receipt("key-1", "digest-1") == {"id": "route-1"}
    with pytest.raises(ValueError, match="YIELD_IDEMPOTENCY_CONFLICT"):
        store.recall_receipt("key-1", "digest-2")
    store.close()


def test_yaml_import_export_and_paginated_collection_surface(tmp_path: Path):
    provider = LocalArtifactProvider(tmp_path / "artifacts")
    dataset = provider.publish_bytes(b'{"instruction":"hello","output":"hi"}\n', kind=YieldArtifactKind.DATASET)
    dataset_id = uuid4()
    app = create_app(state_directory=tmp_path / "yield", artifact_root=tmp_path / "artifacts")

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            payload = {
                "name": "Imported YAML",
                "datasetVersion": {
                    "id": str(dataset_id),
                    "uri": f"cyrene://catalyst/dataset-versions/{dataset_id}",
                    "resourceVersion": 1,
                    "artifact": dataset.to_dict(),
                },
                "yaml": "model_name_or_path: example/base\nnum_train_epochs: 2\nlora_rank: 16\n",
            }
            imported = await client.post("/api/v1/training-drafts/actions/import-llama-factory", json=payload)
            assert imported.status_code == 201, imported.text
            draft_id = imported.json()["id"]
            assert imported.json()["importedParameters"]["parameters"]["epochs"] == 2.0

            exported = await client.get(f"/api/v1/training-drafts/{draft_id}/exports/llama-factory.yaml")
            assert exported.status_code == 200
            assert exported.headers["content-type"].startswith("application/x-yaml")
            assert "filename=\"training-draft-" in exported.headers["content-disposition"]
            assert "lora_rank: 16" in exported.text

            invalid = await client.post(
                "/api/v1/training-drafts/actions/import-llama-factory",
                json={**payload, "yaml": "not_admitted: true\n"},
            )
            assert invalid.status_code == 400
            assert invalid.json()["code"] == "YIELD_LLAMA_FACTORY_UNKNOWN_FIELD"

            page = await client.get("/api/v1/training-runs?limit=10&offset=0")
            assert page.status_code == 200
            assert page.json()["items"] == []

    asyncio.run(exercise())
    app.state.yield_service.store.close()


def test_run_collection_preflight_events_and_terminal_sse(tmp_path: Path):
    provider = LocalArtifactProvider(tmp_path / "artifacts")
    executor = _EventExecutor()
    control = TrainingControlPlane(
        _runtime(provider, executor),
        tmp_path / "yield" / "runs.json",
        durable_tiny_attempt=True,
    )
    endpoint_id = uuid4()
    deployment_id = uuid4()
    route_id = uuid4()
    source_endpoint_url = f"https://reactor.example/api/v1/endpoints/{endpoint_id}"
    model_version_id: str | None = None

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal model_version_id
        if request.url.host == "reactor.example" and request.url.path == f"/api/v1/endpoints/{endpoint_id}":
            return httpx.Response(
                200,
                json={
                    "id": str(endpoint_id),
                    "deploymentId": str(deployment_id),
                    "state": "READY",
                    "protocol": "openai.chat.v1",
                    "model": "trained-model",
                    "resourceVersion": 3,
                },
            )
        if request.url.host == "reactor.example" and request.url.path == f"/api/v1/deployments/{deployment_id}":
            assert model_version_id is not None
            return httpx.Response(
                200,
                json={
                    "id": str(deployment_id),
                    "modelArtifact": {"digest": "sha256:" + "b" * 64},
                    "modelVersion": {"id": model_version_id},
                },
            )
        if request.url.host == "exchange.example" and request.url.path == "/api/v1/gateway-route-drafts":
            body = request.content.decode()
            assert '"product":"reactor"' in body
            assert '"resourceVersion":3' in body
            return httpx.Response(201, json={"id": str(route_id)})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    http_client = httpx.Client(transport=httpx.MockTransport(respond))
    app = create_app(
        state_directory=tmp_path / "yield",
        artifact_root=tmp_path / "artifacts",
        control=control,
        reactor_url="https://reactor.example",
        exchange_url="https://exchange.example",
        exchange_endpoint_id=str(uuid4()),
        exchange_target_binding_id="binding-1",
        http_client=http_client,
    )
    dataset = provider.publish_bytes(b'{"instruction":"hello","output":"hi"}\n', kind=YieldArtifactKind.DATASET)
    base = _base(tmp_path, provider)

    async def exercise() -> None:
        nonlocal model_version_id
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            dataset_id = uuid4()
            draft = await client.post(
                "/api/v1/training-drafts",
                json={
                    "name": "Event surface",
                    "datasetVersion": {
                        "id": str(dataset_id),
                        "uri": f"cyrene://catalyst/dataset-versions/{dataset_id}",
                        "resourceVersion": 1,
                        "artifact": dataset.to_dict(),
                    },
                },
            )
            assert draft.status_code == 201, draft.text
            draft_id = draft.json()["id"]
            prepared = await client.patch(
                f"/api/v1/training-drafts/{draft_id}",
                json={"baseModel": base, "parameters": {"maxSteps": 1}},
            )
            assert prepared.status_code == 200, prepared.text
            started = await client.post(f"/api/v1/training-drafts/{draft_id}/actions/start")
            assert started.status_code == 202, started.text
            run_id = started.json()["id"]
            for _ in range(14):
                app.state.yield_service.advance()

            page = await client.get("/api/v1/training-runs?limit=1&offset=0")
            assert page.status_code == 200
            assert page.json()["total"] == 1
            assert page.json()["items"][0]["id"] == run_id

            preflight = await client.post(f"/api/v1/training-runs/{run_id}/actions/preflight")
            assert preflight.status_code == 200, preflight.text
            assert {item["id"] for item in preflight.json()["items"]} >= {"cuda-runtime", "disk-space"}

            events = await client.get(f"/api/v1/training-runs/{run_id}/events?after_sequence=0")
            assert events.status_code == 200
            assert events.json()["terminal"] is True
            assert len(events.json()["events"]) >= 2
            first_sequence = events.json()["events"][0]["sequence"]

            stream = await client.get(
                f"/api/v1/training-runs/{run_id}/events/stream",
                headers={"Last-Event-ID": str(first_sequence)},
            )
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            assert f"id: {first_sequence}\n" not in stream.text
            assert "event: done" in stream.text
            completed = await client.get(f"/api/v1/training-runs/{run_id}")
            result_id = UUID(completed.json()["result"]["id"])
            result = app.state.yield_service.get_result(result_id)
            model_version_id = result.model_version["id"]
            sent = await client.post(
                f"/api/v1/training-results/{result.id}/actions/send-to-exchange",
                headers={"Idempotency-Key": "exchange-once"},
                json={"modelAlias": "trained-model", "endpointUrl": source_endpoint_url},
            )
            assert sent.status_code == 201, sent.text
            assert sent.json()["routeId"] == str(route_id)

    asyncio.run(exercise())
    app.state.yield_service.store.close()
    http_client.close()


def test_resume_action_stages_checkpoint_and_keeps_the_same_run(tmp_path: Path):
    provider = LocalArtifactProvider(tmp_path / "artifacts")
    executor = _ResumeExecutor()
    control = TrainingControlPlane(
        _runtime(provider, executor),
        tmp_path / "yield" / "runs.json",
        durable_tiny_attempt=True,
    )
    app = create_app(state_directory=tmp_path / "yield", artifact_root=tmp_path / "artifacts", control=control)
    dataset = provider.publish_bytes(b'{"instruction":"hello","output":"hi"}\n', kind=YieldArtifactKind.DATASET)
    base = _base(tmp_path, provider)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            dataset_id = uuid4()
            draft = await client.post(
                "/api/v1/training-drafts",
                json={
                    "name": "Resume surface",
                    "datasetVersion": {
                        "id": str(dataset_id),
                        "uri": f"cyrene://catalyst/dataset-versions/{dataset_id}",
                        "resourceVersion": 1,
                        "artifact": dataset.to_dict(),
                    },
                },
            )
            draft_id = draft.json()["id"]
            await client.patch(
                f"/api/v1/training-drafts/{draft_id}",
                json={"baseModel": base, "parameters": {"maxSteps": 1}},
            )
            started = await client.post(f"/api/v1/training-drafts/{draft_id}/actions/start")
            run_id = started.json()["id"]
            for _ in range(14):
                app.state.yield_service.advance()
            failed = await client.get(f"/api/v1/training-runs/{run_id}")
            assert failed.json()["state"] == "FAILED"

            resumed = await client.post(
                f"/api/v1/training-runs/{run_id}/actions/resume",
                headers={"Idempotency-Key": "resume-once"},
                json={},
            )
            assert resumed.status_code == 202, resumed.text
            assert resumed.json()["id"] == run_id
            assert resumed.json()["attemptCount"] == 2
            assert executor.launches[-1].extra["product_spec"]["checkpoint"]["resume_from"]

            app.state.yield_service.advance()
            app.state.yield_service.advance()
            completed = await client.get(f"/api/v1/training-runs/{run_id}")
            assert completed.json()["state"] == "COMPLETED"

    asyncio.run(exercise())
    app.state.yield_service.store.close()


def test_event_snapshot_replays_after_runtime_restart(tmp_path: Path):
    provider = LocalArtifactProvider(tmp_path / "artifacts")
    executor = _EventExecutor()
    runtime = _runtime(provider, executor)
    control = TrainingControlPlane(
        runtime,
        tmp_path / "yield" / "runs.json",
        durable_tiny_attempt=True,
    )
    app = create_app(state_directory=tmp_path / "yield", artifact_root=tmp_path / "artifacts", control=control)
    dataset = provider.publish_bytes(b'{"instruction":"hello","output":"hi"}\n', kind=YieldArtifactKind.DATASET)
    base = _base(tmp_path, provider)

    async def start_run() -> str:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            dataset_id = uuid4()
            draft = await client.post(
                "/api/v1/training-drafts",
                json={
                    "name": "Restart events",
                    "datasetVersion": {
                        "id": str(dataset_id),
                        "uri": f"cyrene://catalyst/dataset-versions/{dataset_id}",
                        "resourceVersion": 1,
                        "artifact": dataset.to_dict(),
                    },
                },
            )
            draft_id = draft.json()["id"]
            await client.patch(
                f"/api/v1/training-drafts/{draft_id}",
                json={"baseModel": base, "parameters": {"maxSteps": 1}},
            )
            started = await client.post(f"/api/v1/training-drafts/{draft_id}/actions/start")
            return started.json()["id"]

    run_id = asyncio.run(start_run())
    for _ in range(4):
        control.reconcile_once("run-" + run_id)
    app.state.yield_service.store.close()

    restarted_control = TrainingControlPlane(
        _runtime(provider, executor),
        tmp_path / "yield" / "runs.json",
        durable_tiny_attempt=True,
    )
    restarted = create_app(
        state_directory=tmp_path / "yield",
        artifact_root=tmp_path / "artifacts",
        control=restarted_control,
    )
    page = restarted.state.yield_service.events(UUID(run_id))
    assert len(page.events) >= 1
    restarted.state.yield_service.store.close()
