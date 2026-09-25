"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: tests.test_product_lifecycle                               │
│  Role: Targeted Product handoff and portable result regressions.    │
│  模块职责：产品草稿、产物身份与失败语义测试；不是 CUDA 验收。              │
└─────────────────────────────────────────────────────────────────────┘
"""

import asyncio
import json
import platform
import struct
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from cy_artifacts import LocalArtifactProvider
from cyrene_yield_contracts import ModelVersion, YieldArtifactKind
from cy_exec.training.control_plane import TrainingControlPlane
from cy_exec.training.executors.base import CancelOutcome, ProcessHandle
from cy_exec.training.product_api import create_app
from cy_exec.training.product_results import compose_result, publish_adapter
from cy_exec.training.runtime import TrainingRuntime
from cyrene_preflight import AcceleratorFacts, HardwareFacts


class AdapterFixtureExecutor:
    """Unit fixture only: no training or GPU evidence is claimed by these bytes.

    仅用于单元测试的 fixture；这些字节不代表训练或 GPU 验收证据。
    """

    def __init__(self, *, broken=False):
        self.launches = []
        self.broken = broken
        self.running = False

    def start(self, launch):
        self.launches.append(launch)
        output = Path(launch.work_dir)
        output.mkdir(parents=True, exist_ok=True)
        spec = launch.extra["product_spec"]
        (output / "adapter_config.json").write_text(
            json.dumps(
                {
                    "peft_type": "LORA",
                    "task_type": "CAUSAL_LM",
                    "base_model_name_or_path": spec["model"]["path"],
                    "revision": None,
                }
            )
        )
        if not self.broken:
            _weights(output / "adapter_model.safetensors")
        return ProcessHandle(pid=1, argv=launch.argv, work_dir=launch.work_dir)

    def poll(self, handle):
        return None if self.running else 0

    def read_new_output(self, handle):
        return []

    def cancel(self, handle, timeout=15):
        self.running = False
        return CancelOutcome(stopped=True, cleanup_confirmed=True, leases_released=True)


def _runtime(provider, executor):
    return TrainingRuntime(
        executor=executor,
        artifact_provider=provider,
        hardware_facts=HardwareFacts.from_node_resource_inventory(
            node_id="unit-node",
            inventory_generation=1,
            accelerator_runtime="cuda",
            architecture=platform.machine().lower(),
            accelerators=[
                AcceleratorFacts(
                    device_id="unit-gpu",
                    kind="gpu",
                    vendor="nvidia",
                    total_memory_bytes=24 * 1024**3,
                    allocatable_memory_bytes=24 * 1024**3,
                    features=("fp32",),
                )
            ],
        ),
    )


def _weights(path: Path) -> None:
    header = json.dumps({"layer.lora_A.weight": {"dtype": "F32", "shape": [1, 1], "data_offsets": [0, 4]}}).encode()
    path.write_bytes(struct.pack("<Q", len(header)) + header + b"\0" * 4)


def _base(tmp_path: Path, provider: LocalArtifactProvider) -> dict:
    stage = tmp_path / "base"
    stage.mkdir()
    (stage / "config.json").write_text('{"model_type":"llama"}')
    _weights(stage / "model.safetensors")
    return {
        "artifact": provider.publish_portable_directory(stage, kind=YieldArtifactKind.MODEL).to_dict(),
        "source": {"repository": "example/text-base", "revision": "a" * 40},
    }


def test_draft_import_is_idempotent_prepared_and_never_starts_training(tmp_path):
    provider = LocalArtifactProvider(tmp_path / "artifacts")
    dataset = provider.publish_bytes(b'{"instruction":"Hi","input":"","output":"Hello"}\n', kind=YieldArtifactKind.DATASET)
    base = _base(tmp_path, provider)
    dataset_id = str(uuid4())
    command = {
        "name": "Instruction dataset",
        "datasetVersion": {
            "id": dataset_id,
            "uri": "cyrene://catalyst/dataset-versions/" + dataset_id,
            "resourceVersion": 1,
            "artifact": dataset.to_dict(),
            "format": "ALPACA_JSONL",
        },
    }
    app = create_app(state_directory=tmp_path / "yield", artifact_root=tmp_path / "artifacts")

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/api/v1/training-drafts", json=command)
            assert first.status_code == 201, first.text
            draft = first.json()
            assert draft["state"] == "DRAFT" and "trainingRun" not in draft
            assert draft == (await client.post("/api/v1/training-drafts", json=command)).json()
            command["name"] = "Changed intent"
            assert (await client.post("/api/v1/training-drafts", json=command)).status_code == 409
            prepared = await client.patch("/api/v1/training-drafts/" + draft["id"], json={"baseModel": base})
            assert prepared.status_code == 200, prepared.text
            assert prepared.json()["state"] == "PREPARED"
            start = await client.post("/api/v1/training-drafts/" + draft["id"] + "/actions/start")
            assert start.status_code == 422
            assert start.json()["code"] == "YIELD_EXECUTION_NOT_CONFIGURED"
            assert not (tmp_path / "yield" / "training").exists()
            assert json.loads((tmp_path / "yield" / "runs.json").read_text())["runs"] == {}
        reopened = create_app(state_directory=tmp_path / "yield", artifact_root=tmp_path / "artifacts")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=reopened), base_url="http://test") as client:
            assert (await client.get("/api/v1/training-drafts/" + draft["id"])).json()["state"] == "PREPARED"

    asyncio.run(exercise())


def test_result_uses_portable_membership_and_canonical_model_identity(tmp_path):
    provider = LocalArtifactProvider(tmp_path / "artifacts")
    base = _base(tmp_path, provider)
    output = tmp_path / "output"
    output.mkdir()
    config = {
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "base_model_name_or_path": str(tmp_path / "base"),
        "revision": None,
        "r": 8,
        "lora_alpha": 16,
        "target_modules": ["q_proj"],
    }
    (output / "adapter_config.json").write_text(json.dumps(config))
    _weights(output / "adapter_model.safetensors")
    (output / "training_args.bin").write_bytes(b"private trainer output")
    ref = publish_adapter(provider, output, base_source=base["source"], staged_base=str(tmp_path / "base"))
    assert ref.manifest_digest == ref.digest
    stage = tmp_path / "readback"
    provider.stage(ref, stage)
    assert {item.name for item in stage.iterdir()} == {"adapter_config.json", "adapter_model.safetensors"}
    exported = json.loads((stage / "adapter_config.json").read_bytes())
    assert exported["base_model_name_or_path"] == base["source"]["repository"]
    assert exported["revision"] == base["source"]["revision"]
    assert exported["r"] == config["r"] and exported["target_modules"] == config["target_modules"]
    model = compose_result(
        run_ref="cyrene://yield/training-runs/" + str(uuid4()),
        dataset_ref="cyrene://catalyst/dataset-versions/" + str(uuid4()),
        base_model=base,
        adapter=ref,
        dataset_artifacts=[],
        tokenizer={"mode": "INHERIT"},
        chat_template={"mode": "INHERIT"},
    )
    assert ModelVersion.from_dict(model.to_dict()).id == model.id
    assert not {"r", "lora_alpha", "target_modules"}.intersection(model.to_dict())


@pytest.mark.parametrize("failure", ["missing", "truncated", "wrong-base", "symlink"])
def test_bad_adapter_never_publishes_a_model_result(tmp_path, failure):
    provider = LocalArtifactProvider(tmp_path / "artifacts")
    output = tmp_path / "output"
    output.mkdir()
    config = {"peft_type": "LORA", "task_type": "CAUSAL_LM", "base_model_name_or_path": "base"}
    if failure == "wrong-base":
        config["base_model_name_or_path"] = "other"
    (output / "adapter_config.json").write_text(json.dumps(config))
    weight = output / "adapter_model.safetensors"
    if failure != "missing":
        _weights(weight)
    if failure == "truncated":
        weight.write_bytes(weight.read_bytes()[:-1])
    if failure == "symlink":
        weight.rename(tmp_path / "weights")
        weight.symlink_to(tmp_path / "weights")
    with pytest.raises(ValueError, match="YIELD_ADAPTER_"):
        publish_adapter(
            provider, output, base_source={"repository": "example/base", "revision": "a" * 40}, staged_base="base"
        )


@pytest.mark.parametrize("broken", [False, True])
def test_explicit_product_run_publishes_only_valid_results_and_survives_readback(tmp_path, broken):
    provider = LocalArtifactProvider(tmp_path / "artifacts")
    executor = AdapterFixtureExecutor(broken=broken)
    runtime = _runtime(provider, executor)
    control = TrainingControlPlane(runtime, tmp_path / "yield" / "runs.json", durable_tiny_attempt=True)
    app = create_app(state_directory=tmp_path / "yield", artifact_root=tmp_path / "artifacts", control=control)
    dataset = provider.publish_bytes(b'{"instruction":"Hello","output":"Hi"}\n', kind=YieldArtifactKind.DATASET)
    base = _base(tmp_path, provider)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            dataset_id = str(uuid4())
            response = await client.post(
                "/api/v1/training-drafts",
                json={
                    "name": "Unit input",
                    "datasetVersion": {
                        "uri": f"cyrene://catalyst/dataset-versions/{dataset_id}",
                        "id": dataset_id,
                        "resourceVersion": 1,
                        "artifact": dataset.to_dict(),
                    },
                },
            )
            assert response.status_code == 201, response.text
            draft_id = response.json()["id"]
            prepared = await client.patch(
                f"/api/v1/training-drafts/{draft_id}", json={"baseModel": base, "parameters": {"maxSteps": 1}}
            )
            assert prepared.status_code == 200, prepared.text
            assert not executor.launches
            started = await client.post(f"/api/v1/training-drafts/{draft_id}/actions/start")
            assert started.status_code == 202, started.text
            run_id = started.json()["id"]
            replay = await client.post(f"/api/v1/training-drafts/{draft_id}/actions/start")
            assert replay.json()["id"] == run_id
            for _ in range(14):
                app.state.yield_service.advance()
            run = (await client.get(f"/api/v1/training-runs/{run_id}")).json()
            assert run["state"] == ("FAILED" if broken else "COMPLETED"), run
            _validate_public_run(run)
            if broken:
                assert "result" not in run
                return
            assert len(executor.launches) == 2
            assert executor.launches[0].extra["product_spec"]["extra"]["tiny_dry_run"] is True
            result = run["result"]
            assert result["modelVersion"]["lineage"]["trainingRun"] == run["resourceRef"]["uri"]
            assert result["modelVersion"]["lineage"]["datasetVersion"].endswith(dataset_id)
            public = json.dumps(run)
            assert str(tmp_path) not in public
            assert "adapter_config" not in result["modelVersion"]
            reopened = create_app(
                state_directory=tmp_path / "yield", artifact_root=tmp_path / "artifacts", control=control
            )
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=reopened), base_url="http://test") as again:
                assert (await again.get(f"/api/v1/training-results/{result['id']}")).json() == result

    asyncio.run(exercise())


def _validate_public_run(run):
    """Validate the actual HTTP response with only local canonical schema resources.

    仅使用本地规范 schema 资源验证实际 HTTP 响应。
    """
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource

    root = Path(__file__).resolve().parents[3] / "contracts/product/v1"
    registry = Registry()
    for path in root.rglob("*.schema.json"):
        document = json.loads(path.read_text())
        resource = Resource.from_contents(document)
        registry = registry.with_resource(path.as_uri(), resource)
        registry = registry.with_resource(
            "https://schemas.cyrene.dev/yield/product/v1/" + path.relative_to(root).as_posix(), resource
        )
        if "$id" in document:
            registry = registry.with_resource(document["$id"], resource)
    schema = json.loads((root / "training-run.schema.json").read_text())
    Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(run)


def test_optional_step_limit_does_not_override_trainer_default_with_null(tmp_path):
    from cy_exec.training.contracts import DatasetRef, EngineKind, ModelRef, TrainingSpec
    from cy_exec.training.engines import get_engine

    dataset = tmp_path / "instruction.jsonl"
    dataset.write_text('{"instruction":"q","output":"a"}\n')
    spec = TrainingSpec(
        engine=EngineKind.LLAMA_FACTORY,
        model=ModelRef(path="example/base"),
        dataset=DatasetRef(path=str(dataset), format="jsonl", schema="instruction"),
        output_dir=str(tmp_path / "result"),
        extra={"max_steps": None},
    )
    launch = get_engine(spec.engine).compile(spec)
    args = json.loads(Path(launch.spec_artifact_path).read_text())
    assert "max_steps" not in args and "max_samples" not in args
