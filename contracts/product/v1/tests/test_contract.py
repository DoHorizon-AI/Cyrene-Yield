"""
┌─────────────────────────────────────────────────────────────────────┐
│  📄 test_contract.py                                                │
│  Module: contracts.product.v1.tests.test_contract                   │
│  Role: Offline Training schema and boundary conformance checks.      │
│                                                                     │
│  模块职责：离线验证 Training 契约与权威边界。                              │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


CONTRACT_ROOT = Path(__file__).parents[1]
REPOSITORY_ROOT = CONTRACT_ROOT.parents[2]
PLATFORM_REVISION = "c59be6f2bd82489fbe933dadff84fc589e00afd9"


def _json(name: str) -> dict:
    return json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))


def _registry() -> Registry:
    artifact = _json("generated/platform/artifact-ref.schema.json")
    return Registry().with_resource(artifact["$id"], Resource.from_contents(artifact))


def test_all_json_schemas_are_draft_2020_12() -> None:
    for path in CONTRACT_ROOT.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_completed_training_run_example_has_artifact_lineage() -> None:
    schema = _json("training-run.schema.json")
    example = _json("examples/training-run.completed.json")
    Draft202012Validator(
        schema,
        registry=_registry(),
        format_checker=FormatChecker(),
    ).validate(example)
    output = example["outputArtifacts"][0]
    assert example["spec"]["modelArtifact"]["digest"] in output["derivedFromDigests"]
    assert example["spec"]["datasetVersion"]["artifact"]["digest"] in output["derivedFromDigests"]


def test_training_run_uses_exact_platform_artifact_ref_projection() -> None:
    generated = _json("generated/platform/artifact-ref.schema.json")
    training_run = _json("training-run.schema.json")
    provenance = _json("generated/platform/lifecycle-sources.json")
    digest = hashlib.sha256((CONTRACT_ROOT / "generated/platform/artifact-ref.schema.json").read_bytes()).hexdigest()
    assert training_run["$defs"]["artifactRef"] == generated
    assert provenance["revision"] == PLATFORM_REVISION
    assert provenance["sha256"] == {
        "contracts/schemas/manifests/artifact_ref.schema.json": digest,
        "contracts/product/v1/training-run.schema.json#/$defs/artifactRef": digest,
    }


def test_kernel_descriptor_matches_recorded_platform_projection() -> None:
    descriptor_root = REPOSITORY_ROOT / "training/core/src/cy_exec/training/executors"
    evidence = json.loads((descriptor_root / "kernel-descriptor.json").read_text(encoding="utf-8"))
    assert evidence["platformRevision"] == PLATFORM_REVISION
    assert evidence["descriptorSha256"] == hashlib.sha256((descriptor_root / "kernel.desc").read_bytes()).hexdigest()


def test_training_runtime_authority_is_owned_by_yield() -> None:
    schema = _json("training-run.schema.json")
    assert schema["properties"]["engineCapabilityType"] == {"const": "cyrene.yield.training-runtime.v1"}
    assert not (CONTRACT_ROOT / "training-engine-spi.schema.json").exists()
    assert "training.engine.adapter.v1" not in (CONTRACT_ROOT / "README.md").read_text()


def test_contract_branch_does_not_add_runtime_implementation() -> None:
    contract_files = {path.relative_to(CONTRACT_ROOT).as_posix() for path in CONTRACT_ROOT.rglob("*")}
    assert "training-execution-port.md" in contract_files
    assert not any(path.endswith("runtime.py") for path in contract_files)
