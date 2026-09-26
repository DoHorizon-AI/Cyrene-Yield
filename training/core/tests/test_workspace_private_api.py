"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: tests.test_workspace_private_api                            │
│  Role: Scoped private Yield routes and legacy read isolation.       │
│  模块职责：验证私有服务身份、Workspace 范围及旧路由读取隔离。             │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from uuid import UUID, uuid4

import httpx
import pytest
from cy_artifacts import LocalArtifactProvider
from cyrene_yield_contracts import YieldArtifactKind

from cy_exec.training.control_plane import TrainingControlPlane
from cy_exec.training.product_api import create_app
from cy_exec.training.product_store import ProductStore
from cy_exec.training.workspace_auth import WorkspaceScope, WorkspaceServiceAuthenticator
from test_product_lifecycle import AdapterFixtureExecutor, _base, _runtime


def _credential_map(*entries: tuple[str, str, str]) -> str:
    return json.dumps(
        {
            "version": 1,
            "credentials": [
                {
                    "tokenSha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
                    "organizationId": organization_id,
                    "workspaceId": workspace_id,
                }
                for token, organization_id, workspace_id in entries
            ],
        }
    )


def _draft_command(dataset, *, name: str = "Private input", workspace_id: str = "forged-body-scope"):
    dataset_id = str(uuid4())
    return {
        "name": name,
        "workspaceId": workspace_id,
        "datasetVersion": {
            "uri": f"cyrene://catalyst/dataset-versions/{dataset_id}",
            "id": dataset_id,
            "resourceVersion": 1,
            "artifact": dataset.to_dict(),
        },
    }


def test_workspace_auth_fails_closed_and_accepts_rotation_for_same_scope(tmp_path, capsys):
    token = "workspace-service-token-" + "a" * 16
    rotated = "workspace-service-token-" + "b" * 16
    other = "workspace-service-token-" + "c" * 16
    credential_map = _credential_map(
        (token, "org-one", "workspace-one"),
        (rotated, "org-one", "workspace-one"),
        (other, "org-two", "workspace-two"),
    )
    authenticator = WorkspaceServiceAuthenticator(credential_map)
    assert token not in repr(authenticator)

    missing = create_app(state_directory=tmp_path / "missing", artifact_root=tmp_path / "artifacts")
    configured = create_app(
        state_directory=tmp_path / "configured",
        artifact_root=tmp_path / "artifacts",
        workspace_credential_map_json=credential_map,
    )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=missing), base_url="http://test") as client:
            unavailable = await client.get("/internal/workspace/v1/training-drafts/00000000-0000-0000-0000-000000000001")
            assert unavailable.status_code == 503
            assert token not in unavailable.text

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=configured), base_url="http://test") as client:
            unauthorized = await client.get(
                "/internal/workspace/v1/training-drafts/00000000-0000-0000-0000-000000000001",
                headers={"Authorization": "Bearer " + "x" * 31},
            )
            assert unauthorized.status_code == 401
            assert token not in unauthorized.text

    asyncio.run(exercise())

    duplicate = _credential_map((token, "org-one", "workspace-one"), (token, "org-two", "workspace-two"))
    with pytest.raises(ValueError, match="YIELD_WORKSPACE_CREDENTIAL_MAP_INVALID"):
        WorkspaceServiceAuthenticator(duplicate)
    with pytest.raises(ValueError, match="YIELD_WORKSPACE_CREDENTIAL_MAP_INVALID"):
        WorkspaceServiceAuthenticator('{"version":1,"credentials":[')
    with pytest.raises(ValueError, match="YIELD_WORKSPACE_CREDENTIAL_MAP_INVALID"):
        WorkspaceServiceAuthenticator(_credential_map((token, "org\u0000one", "workspace-one")))
    captured = capsys.readouterr()
    for credential in (token, rotated, other):
        assert credential not in captured.out
        assert credential not in captured.err


def test_private_draft_and_scope_receipt_roll_back_as_one_transaction(tmp_path):
    store = ProductStore(tmp_path / "product.sqlite3")
    draft_id = str(uuid4())
    with store._connection:
        store._connection.execute(
            "CREATE TRIGGER reject_workspace_scope BEFORE INSERT ON workspace_resource_scopes "
            "BEGIN SELECT RAISE(ABORT, 'scope insert rejected'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="scope insert rejected"):
        store.create_draft(
            "same-private-key",
            {"intent": "training"},
            {"id": draft_id, "name": "atomic test"},
            workspace_scope=("org-one", "workspace-one"),
        )

    with pytest.raises(KeyError):
        store.get("draft", draft_id)
    assert store.workspace_resource_scope("draft", draft_id) is None
    assert store._connection.execute("SELECT COUNT(*) FROM workspace_draft_receipts").fetchone()[0] == 0
    store.close()


def test_private_draft_scope_is_server_assigned_and_legacy_reads_hide_it(tmp_path):
    provider = LocalArtifactProvider(tmp_path / "artifacts")
    dataset = provider.publish_bytes(b'{"instruction":"hello","output":"hi"}\n', kind=YieldArtifactKind.DATASET)
    base = _base(tmp_path, provider)
    token = "workspace-service-token-" + "a" * 16
    rotated = "workspace-service-token-" + "b" * 16
    other = "workspace-service-token-" + "c" * 16
    app = create_app(
        state_directory=tmp_path / "yield",
        artifact_root=tmp_path / "artifacts",
        workspace_credential_map_json=_credential_map(
            (token, "org-one", "workspace-one"),
            (rotated, "org-one", "workspace-one"),
            (other, "org-two", "workspace-two"),
        ),
    )
    private_headers = {"Authorization": "Bearer " + token, "Idempotency-Key": "draft-private"}

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            command = _draft_command(dataset)
            created = await client.post(
                "/internal/workspace/v1/training-drafts", json=command, headers=private_headers
            )
            assert created.status_code == 201, created.text
            draft = created.json()
            draft_id = draft["id"]
            assert draft["workspaceId"] == "workspace-one"
            assert app.state.yield_service.store.workspace_resource_scope("draft", draft_id) == (
                "org-one",
                "workspace-one",
            )

            replay = await client.post(
                "/internal/workspace/v1/training-drafts",
                json={**command, "workspaceId": "another-forged-scope"},
                headers=private_headers,
            )
            assert replay.status_code == 201 and replay.json()["id"] == draft_id

            imported = await client.post(
                "/internal/workspace/v1/training-drafts/actions/import-llama-factory",
                json={**_draft_command(dataset, name="Private YAML"), "yaml": "num_train_epochs: 2\n"},
                headers={"Authorization": "Bearer " + rotated, "Idempotency-Key": "yaml-private"},
            )
            assert imported.status_code == 201, imported.text
            assert imported.json()["workspaceId"] == "workspace-one"
            assert app.state.yield_service.store.workspace_resource_scope("draft", imported.json()["id"]) == (
                "org-one",
                "workspace-one",
            )

            private_get = await client.get(
                f"/internal/workspace/v1/training-drafts/{draft_id}",
                headers={"Authorization": "Bearer " + rotated},
            )
            assert private_get.status_code == 200
            wrong_scope = await client.get(
                f"/internal/workspace/v1/training-drafts/{draft_id}",
                headers={"Authorization": "Bearer " + other},
            )
            assert wrong_scope.status_code == 404
            wrong_scope_start = await client.post(
                f"/internal/workspace/v1/training-drafts/{draft_id}/actions/start",
                headers={"Authorization": "Bearer " + other},
            )
            assert wrong_scope_start.status_code == 404

            same_key_other_scope = await client.post(
                "/internal/workspace/v1/training-drafts",
                json=command,
                headers={"Authorization": "Bearer " + other, "Idempotency-Key": "draft-private"},
            )
            assert same_key_other_scope.status_code == 201
            assert same_key_other_scope.json()["id"] != draft_id
            assert app.state.yield_service.store.workspace_resource_scope(
                "draft", same_key_other_scope.json()["id"]
            ) == ("org-two", "workspace-two")

            legacy = await client.post(
                "/api/v1/training-drafts",
                json=_draft_command(dataset, name="Legacy"),
                headers={"Idempotency-Key": "draft-private"},
            )
            assert legacy.status_code == 201
            legacy_id = legacy.json()["id"]
            assert app.state.yield_service.store.workspace_resource_scope("draft", legacy_id) is None
            legacy_import = await client.post(
                "/api/v1/training-drafts/actions/import-llama-factory",
                json={**_draft_command(dataset, name="Legacy YAML"), "yaml": "num_train_epochs: 2\n"},
            )
            assert legacy_import.status_code == 201
            legacy_import_id = legacy_import.json()["id"]
            assert app.state.yield_service.store.workspace_resource_scope("draft", legacy_import_id) is None

            listed = await client.get("/api/v1/training-drafts")
            assert {item["id"] for item in listed.json()} == {legacy_id, legacy_import_id}
            for response in (
                await client.get(f"/api/v1/training-drafts/{draft_id}"),
                await client.get(f"/api/v1/training-drafts/{draft_id}/exports/llama-factory.yaml"),
                await client.patch(
                    f"/api/v1/training-drafts/{draft_id}",
                    json={"baseModel": base},
                ),
            ):
                assert response.status_code == 404, response.text

    asyncio.run(exercise())
    app.state.yield_service.store.close()


def test_scoped_run_and_associated_result_are_hidden_from_every_legacy_read(tmp_path):
    provider = LocalArtifactProvider(tmp_path / "artifacts")
    executor = AdapterFixtureExecutor()
    control = TrainingControlPlane(
        _runtime(provider, executor),
        tmp_path / "yield" / "runs.json",
        durable_tiny_attempt=True,
    )
    token = "workspace-service-token-" + "a" * 16
    other = "workspace-service-token-" + "c" * 16
    app = create_app(
        state_directory=tmp_path / "yield",
        artifact_root=tmp_path / "artifacts",
        control=control,
        workspace_credential_map_json=_credential_map(
            (token, "org-one", "workspace-one"), (other, "org-two", "workspace-two")
        ),
    )
    dataset = provider.publish_bytes(b'{"instruction":"hello","output":"hi"}\n', kind=YieldArtifactKind.DATASET)
    base = _base(tmp_path, provider)
    headers = {"Authorization": "Bearer " + token, "Idempotency-Key": "scoped-run"}

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/internal/workspace/v1/training-drafts", json=_draft_command(dataset), headers=headers
            )
            assert created.status_code == 201, created.text
            draft_id = created.json()["id"]
            prepared = await client.patch(
                f"/internal/workspace/v1/training-drafts/{draft_id}",
                headers=headers,
                json={"baseModel": base, "parameters": {"maxSteps": 1}},
            )
            assert prepared.status_code == 200, prepared.text
            started = await client.post(
                f"/internal/workspace/v1/training-drafts/{draft_id}/actions/start", headers=headers
            )
            assert started.status_code == 202, started.text
            run_id = started.json()["id"]
            for _ in range(14):
                app.state.yield_service.advance()

            private_read = await client.get(
                f"/internal/workspace/v1/training-drafts/{draft_id}", headers=headers
            )
            assert private_read.status_code == 200
            private_run = app.state.yield_service.get_run(
                UUID(run_id),
                workspace_scope=WorkspaceScope("org-one", "workspace-one"),
            )
            assert private_run.state == "COMPLETED"
            assert private_run.result is not None
            result_id = str(private_run.result.id)
            assert app.state.yield_service.store.workspace_resource_scope("result", result_id) == (
                "org-one",
                "workspace-one",
            )

            draft_list = await client.get("/api/v1/training-drafts")
            assert draft_id not in {item["id"] for item in draft_list.json()}
            run_list = await client.get("/api/v1/training-runs")
            assert run_id not in {item["id"] for item in run_list.json()["items"]}

            blocked_reads = [
                await client.get(f"/api/v1/training-drafts/{draft_id}"),
                await client.get(f"/api/v1/training-drafts/{draft_id}/exports/llama-factory.yaml"),
                await client.patch(f"/api/v1/training-drafts/{draft_id}", json={"baseModel": base}),
                await client.post(f"/api/v1/training-drafts/{draft_id}/actions/start"),
                await client.get(f"/api/v1/training-runs/{run_id}"),
                await client.post(f"/api/v1/training-runs/{run_id}/actions/preflight"),
                await client.get(f"/api/v1/training-runs/{run_id}/events"),
                await client.get(f"/api/v1/training-runs/{run_id}/events/stream"),
                await client.get(f"/api/v1/training-runs/{run_id}/diagnostics"),
                await client.get(f"/api/v1/training-runs/{run_id}/attempts"),
                await client.get(f"/api/v1/training-results/{result_id}"),
                await client.get(f"/api/v1/training-results/{result_id}/exports/llama-factory.yaml"),
                await client.post(f"/api/v1/training-results/{result_id}/actions/send-to-reactor"),
                await client.post(
                    f"/api/v1/training-results/{result_id}/actions/send-to-exchange",
                    json={"modelAlias": "private-model", "endpointUrl": "https://reactor.example/api/v1/endpoints/00000000-0000-0000-0000-000000000001"},
                ),
                await client.post(f"/api/v1/training-runs/{run_id}/actions/cancel"),
                await client.post(f"/api/v1/training-runs/{run_id}/actions/resume", json={}),
            ]
            assert [response.status_code for response in blocked_reads] == [404] * len(blocked_reads)

    asyncio.run(exercise())
    app.state.yield_service.store.close()
