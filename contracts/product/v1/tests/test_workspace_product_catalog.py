"""
┌─────────────────────────────────────────────────────────────────────┐
│  📄 test_workspace_product_catalog.py                                │
│  Module: contracts.product.v1.tests.test_workspace_product_catalog   │
│  Role: Verify private Workspace v2 operation/schema bindings.        │
│  模块职责：核对私有 Workspace v2 操作目录及 schema 指针绑定。          │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml


CONTRACT_ROOT = Path(__file__).parents[1]
REPOSITORY_ROOT = CONTRACT_ROOT.parents[2]
CATALOG_PATH = REPOSITORY_ROOT / "contracts/product/v2/catalog.json"
PRIVATE_OPENAPI_PATH = CONTRACT_ROOT / "workspace-private.openapi.yaml"
EXPECTED_SCOPE_BINDINGS = [
    {"jsonPointer": "/organizationId", "matches": "ORGANIZATION_ID"},
    {"jsonPointer": "/workspaceId", "matches": "WORKSPACE_ID"},
    {"jsonPointer": "/trainingRunId", "matches": "RESOURCE_ID"},
]


def _resolve_pointer(document: object, pointer: str) -> object:
    """Resolve a local RFC 6901 pointer used by the operation catalog."""

    assert pointer.startswith("#/")
    value = document
    for fragment in pointer[2:].split("/"):
        key = fragment.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(key)]
        else:
            assert isinstance(value, dict)
            value = value[key]
    return value


def test_private_run_observation_operations_bind_exact_openapi_schemas() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    private_openapi = yaml.safe_load(PRIVATE_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {item["operationId"]: item for item in catalog["operations"]}
    expected = {
        "workspaceGetRun": ("get", None),
        "workspaceListRunEvents": (
            "post",
            "#/paths/~1internal~1workspace~1v1~1training-runs~1{run_id}~1events~1query/post/requestBody/content/application~1json/schema",
        ),
        "workspaceListRunAttempts": ("get", None),
    }

    for operation_id, (method, request_pointer) in expected.items():
        operation = operations[operation_id]
        assert operation["kind"] == "READ"
        assert operation["routeId"] == operation_id
        assert operation["openapiPath"] == "contracts/product/v1/workspace-private.openapi.yaml"
        assert operation["resourceId"]["required"] is True
        assert operation["resourceId"]["pathParameter"] == "run_id"
        assert operation["resourceId"]["pattern"] == (
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        )
        assert operation["scope"]["responseBindings"] == EXPECTED_SCOPE_BINDINGS + (
            [{"jsonPointer": "/id", "matches": "RESOURCE_ID"}] if operation_id == "workspaceGetRun" else []
        )
        response_pointer = operation["responseSchemaPointers"][0]
        response_schema = _resolve_pointer(private_openapi, response_pointer)
        assert isinstance(response_schema, dict)
        paths = private_openapi["paths"]
        matches = [
            (path, candidate_method, candidate)
            for path, item in paths.items()
            for candidate_method, candidate in item.items()
            if candidate.get("operationId") == operation_id
        ]
        assert len(matches) == 1
        path, actual_method, _ = matches[0]
        assert actual_method == method
        path_pointer = path.replace("~", "~0").replace("/", "~1")
        assert response_pointer == (f"#/paths/{path_pointer}/{method}/responses/200/content/application~1json/schema")
        if request_pointer is None:
            assert operation["requestSchemaPointer"] is None
        else:
            assert operation["requestSchemaPointer"] == request_pointer
            request_schema = _resolve_pointer(private_openapi, request_pointer)
            if "$ref" in request_schema:
                request_schema = _resolve_pointer(private_openapi, request_schema["$ref"])
            assert request_schema["additionalProperties"] is False
            assert request_schema["required"] == ["afterSequence", "limit"]
            assert request_schema["properties"]["afterSequence"]["minimum"] == 0
            assert request_schema["properties"]["limit"]["maximum"] == 100


def test_workspace_start_accepts_authority_idempotency_header() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    private_openapi = yaml.safe_load(PRIVATE_OPENAPI_PATH.read_text(encoding="utf-8"))
    start = next(item for item in catalog["operations"] if item["operationId"] == "workspaceStartRun")
    assert start["idempotency"] == {
        "required": False,
        "header": "Idempotency-Key",
        "minLength": 1,
        "maxLength": 200,
    }
    operation = private_openapi["paths"]["/internal/workspace/v1/training-drafts/{draft_id}/actions/start"]["post"]
    assert {"$ref": "#/components/parameters/IdempotencyKey"} in operation["parameters"]
