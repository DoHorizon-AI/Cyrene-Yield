"""Standalone Yield tests with exact Platform SDK and Plugin owner bindings."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

CORE_SRC = Path(__file__).resolve().parents[1] / "src"

platform_sdk = None
platform_root_env = os.environ.get("CYRENE_PLATFORM_WORKTREE")
if platform_root_env:
    sdk_dir = Path(platform_root_env).resolve() / "sdk" / "python"
    if not (sdk_dir / "cyrene_artifacts" / "src").is_dir():
        raise RuntimeError("CYRENE_PLATFORM_WORKTREE does not contain the Platform SDK")
    platform_sdk = sdk_dir

TEST_PYTHON_PATHS = [str(CORE_SRC)]
if platform_sdk is not None:
    TEST_PYTHON_PATHS.extend(
        [
            str(platform_sdk / "cyrene_artifacts" / "src"),
            str(platform_sdk / "cyrene_preflight" / "src"),
        ]
    )

for source in TEST_PYTHON_PATHS:
    if source not in sys.path:
        sys.path.insert(0, source)

# Child workers must resolve the same exact SDK snapshot as the test process.
inherited_python_path = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = os.pathsep.join([*(str(source) for source in TEST_PYTHON_PATHS), inherited_python_path])


class _LlamaFactoryContractFixture:
    """Offline launch-contract fixture; real training remains a Plugin acceptance lane."""

    def invoke(self, method: str, request: dict[str, Any]) -> dict[str, Any]:
        """Return deterministic contract payloads without implementing a trainer."""

        if method == "inspect":
            return {
                "engine": "llamafactory",
                "available": True,
                "version": "0.9.6.dev0-fixture",
                "supported_strategies": [
                    "single",
                    "ddp",
                    "fsdp",
                    "deepspeed",
                    "torchrun",
                ],
                "supported_finetune_types": ["lora", "full", "freeze", "oft"],
                "notes": ["offline contract fixture"],
            }
        if method == "parse_event":
            line = request["line"]
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and "loss" in payload:
                return {
                    "kind": "progress",
                    "message": line,
                    "payload": payload,
                    "raw": line,
                }
            return {"kind": "log", "message": line, "raw": line}
        if method == "compile":
            spec = request["spec"]
            output = Path(spec["output_dir"])
            output.mkdir(parents=True, exist_ok=True)
            extras = dict(spec.get("extra") or {})
            arguments = dict(extras.get("llamafactory_args") or {})
            if extras.get("max_steps") is not None:
                arguments["max_steps"] = extras["max_steps"]
            if extras.get("max_train_samples") is not None:
                arguments["max_samples"] = extras["max_train_samples"]
            artifact = output / "llamafactory_train.json"
            artifact.write_text(json.dumps(arguments), encoding="utf-8")
            distributed = spec["distributed"]
            return {
                "launch": {
                    "engine": "llamafactory",
                    "argv": [
                        sys.executable,
                        "-m",
                        "llamafactory.cli",
                        "train",
                        str(artifact),
                    ],
                    "work_dir": str(output),
                    "cwd": str(output),
                    "distributed": distributed,
                    "checkpoint": spec["checkpoint"],
                    "launch_kind": "direct",
                    "env": {},
                    "resources": {
                        "gpu_count": distributed["gpu_count"],
                        "world_size": distributed["world_size"],
                        "nnodes": distributed["nnodes"],
                        "nproc_per_node": distributed["nproc_per_node"],
                        "gpu_memory_gb": 0.0,
                    },
                    "mounts": [
                        {
                            "source": spec["dataset"]["path"],
                            "target": "/input/dataset",
                            "kind": "bind",
                            "read_only": True,
                        },
                        {
                            "source": str(output),
                            "target": "/output",
                            "kind": "bind",
                            "read_only": False,
                        },
                    ],
                    "output_layout": {"root": ""},
                    "spec_artifact_path": str(artifact),
                    "extra": {},
                }
            }
        raise AssertionError(f"Unexpected fixture method: {method}")


_PREFLIGHT_SERVERS: list[Any] = []


def pytest_configure() -> None:
    """Start the exact pinned Plugin implementations over real direct endpoints."""

    try:
        from compat_rules import CompatibilityRuleEvaluator
        from cyrene_plugin_runtime import serve
        from dataset_validator import DatasetValidatorPlugin
        from hf_model_analyzer import HfModelAnalyzer
    except ImportError as exc:  # pragma: no cover - dependency failure is explicit
        raise RuntimeError("Yield tests require the pinned Plugins runtime and preflight owner packages") from exc

    bindings = (
        (
            HfModelAnalyzer(),
            "model.analyzer.v1",
            "CYRENE_MODEL_ANALYZER_CONNECTION_REF",
        ),
        (
            CompatibilityRuleEvaluator(),
            "compatibility.evaluator.v1",
            "CYRENE_COMPATIBILITY_EVALUATOR_CONNECTION_REF",
        ),
        (
            DatasetValidatorPlugin(),
            "tool.dataset.validator.v1",
            "CYRENE_DATASET_VALIDATOR_CONNECTION_REF",
        ),
    )
    for plugin, capability, environment_name in bindings:
        server, connection_ref = serve(plugin, capability, "1", "127.0.0.1:0")
        _PREFLIGHT_SERVERS.append(server)
        os.environ[environment_name] = connection_ref

    from cy_exec.training.contracts import EngineKind
    from cy_exec.training.engines import _ADAPTERS
    from cy_exec.training.engines.llamafactory import LlamaFactoryEngineAdapter

    _ADAPTERS[EngineKind.LLAMA_FACTORY] = LlamaFactoryEngineAdapter(connection=_LlamaFactoryContractFixture())


def pytest_unconfigure() -> None:
    """Stop Plugin endpoints and remove their process-local connection refs."""

    for environment_name in (
        "CYRENE_MODEL_ANALYZER_CONNECTION_REF",
        "CYRENE_COMPATIBILITY_EVALUATOR_CONNECTION_REF",
        "CYRENE_DATASET_VALIDATOR_CONNECTION_REF",
    ):
        os.environ.pop(environment_name, None)
    for server in _PREFLIGHT_SERVERS:
        server.stop(grace=None).wait()
    _PREFLIGHT_SERVERS.clear()
