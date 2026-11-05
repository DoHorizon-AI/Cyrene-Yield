from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, cast
from uuid import uuid4

import pytest
from cy_artifacts import LocalArtifactProvider
from cyrene_yield_contracts import MODEL_VERSION_SCHEMA_VERSION, ModelVersion

from cy_exec.training.control_plane import TrainingControlPlane
from cy_exec.training.model_registry import (
    DirectPluginModelRegistry,
    ModelRegistration,
    ModelRegistryUnavailable,
)
from cy_exec.training.product_models import ArtifactRef, ResourceRef, TrainingResultResource
from cy_exec.training.product_service import YieldService
from cy_exec.training.product_store import ProductStore


def _artifact(character: str) -> dict[str, Any]:
    digest = "sha256:" + character * 64
    return {
        "uri": "artifact://sha256/" + character * 64,
        "digest": digest,
        "size_bytes": 1,
        "kind": "model",
        "manifest_digest": digest,
    }


def _model_version() -> dict[str, Any]:
    return ModelVersion.create(
        {
            "schemaVersion": MODEL_VERSION_SCHEMA_VERSION,
            "composition": "BASE_PLUS_LORA",
            "baseModel": {
                "artifact": _artifact("a"),
                "source": {"repository": "example/base", "revision": "c" * 40},
            },
            "adapterArtifact": _artifact("b"),
            "tokenizer": {"mode": "INHERIT"},
            "chatTemplate": {"mode": "INHERIT"},
            "lineage": {"trainingRun": "cyrene://yield/training-runs/example"},
        }
    ).to_dict()


class _Client:
    def __init__(self, response: dict[str, Any], *, response_type: str | None = None) -> None:
        self.response = response
        self.response_type = response_type or "type.cyrene.io/model.registry.v1.register.response"
        self.calls: list[dict[str, Any]] = []

    def invoke(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            type_url=self.response_type,
            value=json.dumps(self.response).encode("utf-8"),
        )


def test_direct_registry_sends_typed_immutable_descriptor() -> None:
    model_version = _model_version()
    client = _Client(
        {
            "model_version_id": model_version["id"],
            "resource_uri": "cyrene://registry/model-versions/example",
            "resource_version": 1,
            "created": True,
        }
    )

    registration = DirectPluginModelRegistry(client).register(
        model_version,
        source_ref="cyrene://yield/training-results/example",
    )

    assert registration.model_version_id == model_version["id"]
    assert registration.created is True
    call = client.calls[0]
    assert call["capability"] == "model.registry.v1"
    assert call["interface_version"] == "1"
    assert call["method"] == "register"
    assert call["request"].type_url == "type.cyrene.io/model.registry.v1.register.request"
    payload = json.loads(call["request"].value)
    assert payload == {
        "model_version": model_version,
        "source_ref": "cyrene://yield/training-results/example",
    }


@pytest.mark.parametrize(
    "response",
    [
        {"model_version_id": "model-version://sha256/" + "0" * 64, "resource_uri": "x:y", "resource_version": 1, "created": True},
        {"model_version_id": None, "resource_uri": "not a uri", "resource_version": 0, "created": "yes"},
    ],
)
def test_direct_registry_rejects_untrusted_acknowledgements(response: dict[str, Any]) -> None:
    with pytest.raises(ModelRegistryUnavailable):
        DirectPluginModelRegistry(_Client(response)).register(
            _model_version(),
            source_ref="cyrene://yield/training-results/example",
        )


class _Registry:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], str]] = []

    def register(self, model_version: Mapping[str, Any], *, source_ref: str) -> ModelRegistration:
        document = dict(model_version)
        self.calls.append((document, source_ref))
        return ModelRegistration(
            model_version_id=document["id"],
            resource_uri="cyrene://registry/model-versions/example",
            resource_version=1,
            created=len(self.calls) == 1,
        )


def _result(model_version: dict[str, Any]) -> TrainingResultResource:
    result_id = uuid4()
    run_id = uuid4()
    dataset_id = uuid4()
    return TrainingResultResource(
        id=result_id,
        resource_ref=ResourceRef(
            uri=f"cyrene://yield/training-results/{result_id}",
            id=result_id,
            resource_version=1,
        ),
        training_run=ResourceRef(
            uri=f"cyrene://yield/training-runs/{run_id}",
            id=run_id,
            resource_version=1,
        ),
        dataset_version=ResourceRef(
            uri=f"cyrene://catalyst/dataset-versions/{dataset_id}",
            id=dataset_id,
            resource_version=1,
        ),
        adapter_artifact=ArtifactRef.model_validate(_artifact("b")),
        checkpoint_artifacts=[],
        model_version=model_version,
        created_at=datetime.now(UTC),
    )


def _service(path: Path, registry: _Registry) -> YieldService:
    return YieldService(
        store=ProductStore(path / "product.sqlite3"),
        control=cast(TrainingControlPlane, object()),
        artifacts=LocalArtifactProvider(path / "artifacts"),
        state_directory=path,
        binding_id="test",
        model_registry=registry,
    )


def test_registry_receipt_is_durable_and_idempotent(tmp_path: Path) -> None:
    registry = _Registry()
    result = _result(_model_version())
    first = _service(tmp_path, registry)
    first._register_model_version(result)
    first._register_model_version(result)
    first.store.close()
    first._http.close()

    restarted = _service(tmp_path, registry)
    restarted._register_model_version(result)
    restarted.store.close()
    restarted._http.close()

    assert len(registry.calls) == 1
    assert registry.calls[0][1] == result.resource_ref.uri
